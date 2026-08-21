//! `PostgreSQL` 18 storage foundation for Loom Runtime persistence ports.
//!
//! This module owns concrete `SQLx`/`PostgreSQL` concerns. `PgStorage` deliberately
//! exposes no `PgPool` accessor: Runtime and higher Loom layers consume
//! Runtime-owned persistence traits rather than reaching through the adapter to
//! issue SQL directly. M2-T1 establishes connection, migration and health
//! behavior plus the M2-T2 `WorldStore` read path. M2-T3 adds the atomic
//! `CommitStore` path, and M2-T4 adds Durable Work claim/retry fencing in
//! private child modules.

mod commit;
mod work;

use std::{fmt::Display, str::FromStr};

use loom_core::{
    AssociationRole, Entity, EntityId, EventId, EventSeq, EventTypeId, FacetOwner, FacetTypeId,
    Relationship, RelationshipId, RelationshipParticipant, RelationshipTypeId, SchemaRevision,
    StateRevision, TimelineId, TimelineVersion, WorkHandlerId, WorkId, WorldEffect, WorldId,
    WorldInstant,
};
use loom_runtime::{
    BaseWorldSnapshot, CommittedEvent, LifecycleError, PersistenceFuture, PlatformTime,
    ProposedEvent, ReadError, TimelineSnapshot, WorkLease, WorkRecord, WorkStatus, WorldCreation,
    WorldLifecycleStore, WorldStore,
};
use serde_json::Value;
use sqlx::{PgPool, Row, postgres::PgPoolOptions};

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!();

/// Concrete `PostgreSQL` persistence adapter owned by `loom-storage`.
///
/// The contained `SQLx` pool is intentionally private. Application composition
/// code may construct this adapter and inject it into Runtime-owned persistence
/// ports, but Core/Protocol/API/Capability/Runtime code must never receive the
/// underlying pool or `SQLx` transaction types.
#[derive(Clone, Debug)]
pub struct PgStorage {
    pool: PgPool,
}

impl PgStorage {
    /// Connects to an existing `PostgreSQL` database without changing its schema.
    ///
    /// Migrations are explicit through [`Self::migrate`] so deployment/startup
    /// policy can decide when schema changes are allowed. This method owns only
    /// concrete adapter setup; it does not grant Runtime commit authority.
    ///
    /// # Errors
    ///
    /// Returns [`sqlx::Error`] when `SQLx` cannot establish the `PostgreSQL` pool.
    pub async fn connect(database_url: &str) -> Result<Self, sqlx::Error> {
        let pool = PgPoolOptions::new().connect(database_url).await?;
        Ok(Self { pool })
    }

    /// Applies the embedded, repository-versioned `SQLx` migrations.
    ///
    /// SQL migrations under `crates/loom-storage/migrations` are the readable
    /// database representation of the already-reviewed Loom persistence
    /// contract. Re-running this method is safe: `SQLx` records applied migration
    /// checksums and does not replay an unchanged migration.
    ///
    /// # Errors
    ///
    /// Returns [`sqlx::migrate::MigrateError`] if migration metadata is invalid,
    /// a migration checksum changed, or `PostgreSQL` rejects a migration.
    pub async fn migrate(&self) -> Result<(), sqlx::migrate::MigrateError> {
        MIGRATOR.run(&self.pool).await
    }

    /// Checks whether the configured `PostgreSQL` authority database is reachable.
    ///
    /// This is an operational adapter health check only. A successful result
    /// does not mean migrations are current and does not imply any World commit
    /// has been authorized.
    ///
    /// # Errors
    ///
    /// Returns [`sqlx::Error`] when the pool cannot execute a trivial query.
    pub async fn health(&self) -> Result<(), sqlx::Error> {
        let _: i32 = sqlx::query_scalar("SELECT 1").fetch_one(&self.pool).await?;
        Ok(())
    }

    /// Gracefully closes the `SQLx` pool owned by this adapter.
    pub async fn close(&self) {
        self.pool.close().await;
    }
}

impl PgStorage {
    async fn read_snapshot(&self, timeline_id: TimelineId) -> Result<TimelineSnapshot, ReadError> {
        let mut transaction = self.pool.begin().await.map_err(sql_read_error)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *transaction)
            .await
            .map_err(sql_read_error)?;

        let timeline_row = sqlx::query(
            "SELECT world_id::text AS world_id, head_event_seq::text AS head_event_seq, \
                    state_revision::text AS state_revision, world_time \
             FROM loom_timeline WHERE timeline_id = $1::uuid",
        )
        .bind(timeline_id.to_string())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        let Some(timeline_row) = timeline_row else {
            let _ = transaction.rollback().await;
            return Err(ReadError::TimelineNotFound { timeline_id });
        };

        let world_id =
            parse_identity::<WorldId>(&row_string(&timeline_row, "world_id")?, "WorldId")?;
        let head_event_seq = EventSeq::new(parse_u64(
            &row_string(&timeline_row, "head_event_seq")?,
            "head_event_seq",
        )?);
        let state_revision = StateRevision::new(parse_u64(
            &row_string(&timeline_row, "state_revision")?,
            "state_revision",
        )?);
        let world_time = WorldInstant::new(row_i64(&timeline_row, "world_time")?);
        let mut base = BaseWorldSnapshot::new(
            world_id,
            timeline_id,
            TimelineVersion::new(head_event_seq, state_revision),
            world_time,
        );

        let entity_rows = sqlx::query(
            "SELECT entity_id::text AS entity_id FROM loom_entity \
             WHERE timeline_id = $1::uuid ORDER BY entity_id",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        for row in entity_rows {
            let entity_id =
                parse_identity::<EntityId>(&row_string(&row, "entity_id")?, "EntityId")?;
            base.insert_entity(Entity {
                id: entity_id,
                world_id,
            });
        }

        let relationship_rows = sqlx::query(
            "SELECT relationship_id::text AS relationship_id, relationship_type, active \
             FROM loom_relationship WHERE timeline_id = $1::uuid ORDER BY relationship_id",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        for row in relationship_rows {
            let relationship_id = parse_identity::<RelationshipId>(
                &row_string(&row, "relationship_id")?,
                "RelationshipId",
            )?;
            let relationship_type =
                RelationshipTypeId::from(row_string(&row, "relationship_type")?);
            let active: bool = row.try_get("active").map_err(sql_read_error)?;
            let participant_rows = sqlx::query(
                "SELECT entity_id::text AS entity_id, role \
                 FROM loom_relationship_participant \
                 WHERE timeline_id = $1::uuid AND relationship_id = $2::uuid \
                 ORDER BY participant_order",
            )
            .bind(timeline_id.to_string())
            .bind(relationship_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
            let mut participants = Vec::with_capacity(participant_rows.len());
            for participant in participant_rows {
                participants.push(RelationshipParticipant::new(
                    parse_identity::<EntityId>(
                        &row_string(&participant, "entity_id")?,
                        "EntityId",
                    )?,
                    AssociationRole::from(row_string(&participant, "role")?),
                ));
            }
            base.insert_relationship(
                Relationship::new(relationship_id, world_id, relationship_type, participants),
                active,
            );
        }

        let entity_facet_rows = sqlx::query(
            "SELECT entity_id::text AS owner_id, facet_type, schema_revision, value \
             FROM loom_entity_facet WHERE timeline_id = $1::uuid \
             ORDER BY entity_id, facet_type",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        for row in entity_facet_rows {
            base.insert_facet(
                FacetOwner::entity(parse_identity::<EntityId>(
                    &row_string(&row, "owner_id")?,
                    "EntityId",
                )?),
                FacetTypeId::from(row_string(&row, "facet_type")?),
                schema_revision(&row)?,
                row_json(&row, "value")?,
            );
        }

        let relationship_facet_rows = sqlx::query(
            "SELECT relationship_id::text AS owner_id, facet_type, schema_revision, value \
             FROM loom_relationship_facet WHERE timeline_id = $1::uuid \
             ORDER BY relationship_id, facet_type",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        for row in relationship_facet_rows {
            base.insert_facet(
                FacetOwner::relationship(parse_identity::<RelationshipId>(
                    &row_string(&row, "owner_id")?,
                    "RelationshipId",
                )?),
                FacetTypeId::from(row_string(&row, "facet_type")?),
                schema_revision(&row)?,
                row_json(&row, "value")?,
            );
        }

        let event_rows = sqlx::query(
            "SELECT event_id::text AS event_id, event_seq::text AS event_seq, event_type, \
                    schema_revision, occurred_at, payload, effects \
             FROM loom_event WHERE timeline_id = $1::uuid ORDER BY event_seq",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        let mut events = Vec::with_capacity(event_rows.len());
        for row in event_rows {
            let event_id = parse_identity::<EventId>(&row_string(&row, "event_id")?, "EventId")?;
            let effects_value = row_json(&row, "effects")?;
            let effects: Vec<WorldEffect> = serde_json::from_value(effects_value)
                .map_err(|error| corrupt(format!("invalid persisted Event effects: {error}")))?;
            let event_seq = EventSeq::new(parse_u64(&row_string(&row, "event_seq")?, "event_seq")?);
            let mut proposal = ProposedEvent::new(
                event_id,
                EventTypeId::from(row_string(&row, "event_type")?),
                schema_revision(&row)?,
                WorldInstant::new(row_i64(&row, "occurred_at")?),
                row_json(&row, "payload")?,
            );
            proposal.effects = effects;
            let mut event = CommittedEvent::from_proposed(timeline_id, event_seq, &proposal);

            let participant_rows = sqlx::query(
                "SELECT entity_id::text AS entity_id, role FROM loom_event_participant \
                 WHERE timeline_id = $1::uuid AND event_id = $2::uuid ORDER BY participant_order",
            )
            .bind(timeline_id.to_string())
            .bind(event_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
            for participant in participant_rows {
                event.push_participant(
                    parse_identity::<EntityId>(
                        &row_string(&participant, "entity_id")?,
                        "EntityId",
                    )?,
                    AssociationRole::from(row_string(&participant, "role")?),
                );
            }

            let relationship_rows = sqlx::query(
                "SELECT relationship_id::text AS relationship_id, role \
                 FROM loom_event_relationship_ref \
                 WHERE timeline_id = $1::uuid AND event_id = $2::uuid ORDER BY reference_order",
            )
            .bind(timeline_id.to_string())
            .bind(event_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
            for relationship in relationship_rows {
                event.push_relationship_ref(
                    parse_identity::<RelationshipId>(
                        &row_string(&relationship, "relationship_id")?,
                        "RelationshipId",
                    )?,
                    AssociationRole::from(row_string(&relationship, "role")?),
                );
            }

            let causal_rows = sqlx::query(
                "SELECT cause_event_id::text AS cause_event_id FROM loom_event_causal_link \
                 WHERE timeline_id = $1::uuid AND event_id = $2::uuid ORDER BY causal_order",
            )
            .bind(timeline_id.to_string())
            .bind(event_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
            for causal in causal_rows {
                event.push_causal_link(parse_identity::<EventId>(
                    &row_string(&causal, "cause_event_id")?,
                    "EventId",
                )?);
            }
            base.insert_event(event_id);
            events.push(event);
        }

        let work_rows = sqlx::query(
            "SELECT work_id::text AS work_id, handler, schema_revision, payload, due_world_time, \
                    causal_event_id::text AS causal_event_id, origin_work_id::text AS origin_work_id, \
                    status, attempt_count, claim_generation::text AS claim_generation, available_at, \
                    last_error, lease_claimed_until, lease_fence::text AS lease_fence \
             FROM loom_work WHERE timeline_id = $1::uuid ORDER BY work_id",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        let mut works = Vec::with_capacity(work_rows.len());
        for row in work_rows {
            let work_id = parse_identity::<WorkId>(&row_string(&row, "work_id")?, "WorkId")?;
            let lease_until: Option<i64> =
                row.try_get("lease_claimed_until").map_err(sql_read_error)?;
            let lease_fence: Option<String> = row.try_get("lease_fence").map_err(sql_read_error)?;
            let lease = match (lease_until, lease_fence) {
                (None, None) => None,
                (Some(until), Some(fence)) => Some(WorkLease::new(
                    PlatformTime::new(until),
                    parse_u64(&fence, "lease_fence")?,
                )),
                _ => return Err(corrupt("persisted Work lease columns disagree")),
            };
            let attempt_count = u32::try_from(row_i64(&row, "attempt_count")?)
                .map_err(|_| corrupt("attempt_count exceeds u32"))?;
            works.push(WorkRecord {
                id: work_id,
                timeline_id,
                handler: WorkHandlerId::from(row_string(&row, "handler")?),
                schema_revision: schema_revision(&row)?,
                payload: row_json(&row, "payload")?,
                due_world_time: row
                    .try_get::<Option<i64>, _>("due_world_time")
                    .map_err(sql_read_error)?
                    .map(WorldInstant::new),
                causal_event_id: optional_identity::<EventId>(&row, "causal_event_id", "EventId")?,
                origin_work_id: optional_identity::<WorkId>(&row, "origin_work_id", "WorkId")?,
                status: parse_work_status(&row_string(&row, "status")?)?,
                attempt_count,
                claim_generation: parse_u64(
                    &row_string(&row, "claim_generation")?,
                    "claim_generation",
                )?,
                available_at: PlatformTime::new(row_i64(&row, "available_at")?),
                last_error: row.try_get("last_error").map_err(sql_read_error)?,
                lease,
            });
        }

        transaction.commit().await.map_err(sql_read_error)?;
        Ok(TimelineSnapshot::new(base, events, works))
    }
}

impl WorldLifecycleStore for PgStorage {
    fn create_world(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: WorldInstant,
    ) -> PersistenceFuture<'_, Result<WorldCreation, LifecycleError>> {
        Box::pin(async move {
            let mut transaction = self.pool.begin().await.map_err(sql_lifecycle_error)?;

            if let Err(error) = sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
                .bind(world_id.to_string())
                .execute(&mut *transaction)
                .await
            {
                let _ = transaction.rollback().await;
                if is_unique_violation(&error) {
                    return Err(LifecycleError::WorldAlreadyExists { world_id });
                }
                return Err(sql_lifecycle_error(error));
            }

            if let Err(error) = sqlx::query(
                "INSERT INTO loom_timeline \
                 (timeline_id, world_id, head_event_seq, state_revision, world_time) \
                 VALUES ($1::uuid, $2::uuid, 0, 0, $3)",
            )
            .bind(timeline_id.to_string())
            .bind(world_id.to_string())
            .bind(initial_world_time.value())
            .execute(&mut *transaction)
            .await
            {
                let _ = transaction.rollback().await;
                if is_unique_violation(&error) {
                    return Err(LifecycleError::TimelineAlreadyExists { timeline_id });
                }
                return Err(sql_lifecycle_error(error));
            }

            transaction.commit().await.map_err(sql_lifecycle_error)?;
            Ok(WorldCreation::new(
                world_id,
                timeline_id,
                initial_world_time,
            ))
        })
    }
}

impl WorldStore for PgStorage {
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        Box::pin(async move { self.read_snapshot(timeline_id).await })
    }
}

fn sql_lifecycle_error(error: sqlx::Error) -> LifecycleError {
    LifecycleError::StorageUnavailable {
        message: format!("PostgreSQL lifecycle persistence failed: {error}"),
    }
}

fn is_unique_violation(error: &sqlx::Error) -> bool {
    error
        .as_database_error()
        .and_then(sqlx::error::DatabaseError::code)
        .is_some_and(|code| code == "23505")
}

fn corrupt(message: impl Into<String>) -> ReadError {
    ReadError::StorageUnavailable {
        message: message.into(),
    }
}

fn sql_read_error(error: sqlx::Error) -> ReadError {
    corrupt(format!("PostgreSQL authority read failed: {error}"))
}

fn parse_identity<T>(value: &str, label: &str) -> Result<T, ReadError>
where
    T: FromStr,
    T::Err: Display,
{
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid persisted {label}: {error}")))
}

fn parse_u64(value: &str, label: &str) -> Result<u64, ReadError> {
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid persisted {label}: {error}")))
}

fn row_string(row: &sqlx::postgres::PgRow, column: &str) -> Result<String, ReadError> {
    row.try_get(column).map_err(sql_read_error)
}

fn row_i64(row: &sqlx::postgres::PgRow, column: &str) -> Result<i64, ReadError> {
    row.try_get(column).map_err(sql_read_error)
}

fn row_json(row: &sqlx::postgres::PgRow, column: &str) -> Result<Value, ReadError> {
    row.try_get(column).map_err(sql_read_error)
}

fn schema_revision(row: &sqlx::postgres::PgRow) -> Result<SchemaRevision, ReadError> {
    let value = u32::try_from(row_i64(row, "schema_revision")?)
        .map_err(|_| corrupt("schema_revision exceeds u32"))?;
    Ok(SchemaRevision::new(value))
}

fn optional_identity<T>(
    row: &sqlx::postgres::PgRow,
    column: &str,
    label: &str,
) -> Result<Option<T>, ReadError>
where
    T: FromStr,
    T::Err: Display,
{
    row.try_get::<Option<String>, _>(column)
        .map_err(sql_read_error)?
        .map(|value| parse_identity(&value, label))
        .transpose()
}

fn parse_work_status(value: &str) -> Result<WorkStatus, ReadError> {
    match value {
        "pending" => Ok(WorkStatus::Pending),
        "completed" => Ok(WorkStatus::Completed),
        "cancelled" => Ok(WorkStatus::Cancelled),
        "dead" => Ok(WorkStatus::Dead),
        other => Err(corrupt(format!("invalid persisted Work status {other}"))),
    }
}

#[cfg(test)]
mod tests {
    use super::PgStorage;

    const WORLD_ID: &str = "00000000-0000-0000-0000-000000000101";
    const TIMELINE_ID: &str = "00000000-0000-0000-0000-000000000102";
    const ENTITY_ID: &str = "00000000-0000-0000-0000-000000000103";

    fn postgres_url() -> Option<String> {
        match std::env::var("LOOM_TEST_POSTGRES_URL") {
            Ok(url) => Some(url),
            Err(error) if std::env::var_os("LOOM_REQUIRE_POSTGRES_TESTS").is_some() => {
                panic!("LOOM_TEST_POSTGRES_URL is required for PostgreSQL tests: {error}")
            }
            Err(_) => None,
        }
    }

    fn database_error_code(error: &sqlx::Error) -> Option<String> {
        error
            .as_database_error()
            .and_then(sqlx::error::DatabaseError::code)
            .map(std::borrow::Cow::into_owned)
    }

    #[tokio::test]
    async fn postgres_18_schema_contract() {
        let Some(database_url) = postgres_url() else {
            return;
        };

        let storage = PgStorage::connect(&database_url)
            .await
            .expect("PostgreSQL test database should accept connections");

        let server_version: i32 =
            sqlx::query_scalar("SELECT current_setting('server_version_num')::integer")
                .fetch_one(&storage.pool)
                .await
                .expect("PostgreSQL should report its server version");
        assert!(
            (180_000..190_000).contains(&server_version),
            "schema gate must run against PostgreSQL 18, got server_version_num={server_version}"
        );

        storage
            .migrate()
            .await
            .expect("migrations should apply to an empty PostgreSQL 18 database");
        storage
            .migrate()
            .await
            .expect("re-running unchanged migrations should be deterministic");
        storage.health().await.expect("health query should succeed");

        let loom_table_count: i64 = sqlx::query_scalar(
            "SELECT count(*)::bigint \
             FROM information_schema.tables \
             WHERE table_schema = 'public' AND table_name LIKE 'loom_%'",
        )
        .fetch_one(&storage.pool)
        .await
        .expect("schema tables should be inspectable");
        assert_eq!(loom_table_count, 12);

        sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
            .bind(WORLD_ID)
            .execute(&storage.pool)
            .await
            .expect("test World should insert");
        sqlx::query(
            "INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)",
        )
        .bind(TIMELINE_ID)
        .bind(WORLD_ID)
        .execute(&storage.pool)
        .await
        .expect("test Timeline should insert");
        sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
            .bind(TIMELINE_ID)
            .bind(ENTITY_ID)
            .execute(&storage.pool)
            .await
            .expect("test Entity should insert");

        let duplicate_entity = sqlx::query(
            "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)",
        )
        .bind(TIMELINE_ID)
        .bind(ENTITY_ID)
        .execute(&storage.pool)
        .await
        .expect_err("duplicate Timeline-local Entity identity must be rejected");
        assert_eq!(
            database_error_code(&duplicate_entity).as_deref(),
            Some("23505")
        );

        let missing_facet_owner = sqlx::query(
            "INSERT INTO loom_entity_facet \
             (timeline_id, entity_id, facet_type, schema_revision, value) \
             VALUES ($1::uuid, $2::uuid, 'test.missing', 1, '{}'::jsonb)",
        )
        .bind(TIMELINE_ID)
        .bind("00000000-0000-0000-0000-000000000199")
        .execute(&storage.pool)
        .await
        .expect_err("Facet owner foreign key must be enforced");
        assert_eq!(
            database_error_code(&missing_facet_owner).as_deref(),
            Some("23503")
        );

        let invalid_u64_range = sqlx::query(
            "INSERT INTO loom_timeline \
             (timeline_id, world_id, head_event_seq) \
             VALUES ('00000000-0000-0000-0000-000000000198'::uuid, $1::uuid, -1)",
        )
        .bind(WORLD_ID)
        .execute(&storage.pool)
        .await
        .expect_err("negative EventSeq representation must be rejected");
        assert_eq!(
            database_error_code(&invalid_u64_range).as_deref(),
            Some("23514")
        );

        storage.close().await;
    }

    #[tokio::test]
    async fn postgres_18_read_snapshot_parity() {
        let Some(database_url) = postgres_url() else {
            return;
        };
        let storage = PgStorage::connect(&database_url)
            .await
            .expect("PostgreSQL test database should accept connections");
        storage
            .migrate()
            .await
            .expect("migrations should be current");

        let world_id = "00000000-0000-0000-0000-000000000201";
        let timeline_id = "00000000-0000-0000-0000-000000000202";
        let entity_a = "00000000-0000-0000-0000-000000000203";
        let entity_b = "00000000-0000-0000-0000-000000000204";
        let relationship_id = "00000000-0000-0000-0000-000000000205";
        let event_first = "00000000-0000-0000-0000-000000000299";
        let event_second = "00000000-0000-0000-0000-000000000210";
        let work_id = "00000000-0000-0000-0000-000000000211";

        sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid) ON CONFLICT DO NOTHING")
            .bind(world_id)
            .execute(&storage.pool)
            .await
            .expect("read fixture World should insert");
        sqlx::query(
            "INSERT INTO loom_timeline \
             (timeline_id, world_id, head_event_seq, state_revision, world_time) \
             VALUES ($1::uuid, $2::uuid, 2, 3, 42) ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(world_id)
        .execute(&storage.pool)
        .await
        .expect("read fixture Timeline should insert");
        for entity_id in [entity_a, entity_b] {
            sqlx::query(
                "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid) \
                 ON CONFLICT DO NOTHING",
            )
            .bind(timeline_id)
            .bind(entity_id)
            .execute(&storage.pool)
            .await
            .expect("read fixture Entity should insert");
        }
        sqlx::query(
            "INSERT INTO loom_relationship \
             (timeline_id, relationship_id, relationship_type, active) \
             VALUES ($1::uuid, $2::uuid, 'test.membership', FALSE) ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(relationship_id)
        .execute(&storage.pool)
        .await
        .expect("read fixture Relationship should insert");
        sqlx::query(
            "INSERT INTO loom_relationship_participant \
             (timeline_id, relationship_id, participant_order, entity_id, role) \
             VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'member') ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(relationship_id)
        .bind(entity_a)
        .execute(&storage.pool)
        .await
        .expect("Relationship participant should insert");
        sqlx::query(
            "INSERT INTO loom_entity_facet \
             (timeline_id, entity_id, facet_type, schema_revision, value) \
             VALUES ($1::uuid, $2::uuid, 'test.counter', 1, '{\"value\":7}'::jsonb) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(entity_a)
        .execute(&storage.pool)
        .await
        .expect("Entity Facet should insert");
        sqlx::query(
            "INSERT INTO loom_relationship_facet \
             (timeline_id, relationship_id, facet_type, schema_revision, value) \
             VALUES ($1::uuid, $2::uuid, 'test.relationship_state', 2, '{\"ended\":true}'::jsonb) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(relationship_id)
        .execute(&storage.pool)
        .await
        .expect("Relationship Facet should insert");

        // Insert EventSeq 2 first and give EventSeq 1 the lexicographically larger UUID.
        // A correct adapter must still return [1, 2].
        for (event_id, sequence, event_type, occurred_at) in [
            (event_second, 2_i64, "test.second", 42_i64),
            (event_first, 1_i64, "test.first", 40_i64),
        ] {
            sqlx::query(
                "INSERT INTO loom_event \
                 (timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects) \
                 VALUES ($1::uuid, $2::uuid, $3, $4, 1, $5, '{}'::jsonb, '[]'::jsonb) \
                 ON CONFLICT DO NOTHING",
            )
            .bind(timeline_id)
            .bind(event_id)
            .bind(sequence)
            .bind(event_type)
            .bind(occurred_at)
            .execute(&storage.pool)
            .await
            .expect("Event fixture should insert");
        }
        sqlx::query(
            "INSERT INTO loom_event_participant \
             (timeline_id, event_id, participant_order, entity_id, role) \
             VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'actor') ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(event_first)
        .bind(entity_a)
        .execute(&storage.pool)
        .await
        .expect("Event participant should insert");
        sqlx::query(
            "INSERT INTO loom_event_relationship_ref \
             (timeline_id, event_id, reference_order, relationship_id, role) \
             VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'subject') ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(event_first)
        .bind(relationship_id)
        .execute(&storage.pool)
        .await
        .expect("Event Relationship reference should insert");
        sqlx::query(
            "INSERT INTO loom_event_causal_link \
             (timeline_id, event_id, causal_order, cause_event_id) \
             VALUES ($1::uuid, $2::uuid, 0, $3::uuid) ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(event_second)
        .bind(event_first)
        .execute(&storage.pool)
        .await
        .expect("Event causal link should insert");
        sqlx::query(
            "INSERT INTO loom_work \
             (timeline_id, work_id, handler, schema_revision, payload, due_world_time, status, \
              attempt_count, claim_generation, available_at) \
             VALUES ($1::uuid, $2::uuid, 'test.handler', 1, '{}'::jsonb, 50, 'pending', 2, 4, 9) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(work_id)
        .execute(&storage.pool)
        .await
        .expect("Work fixture should insert");

        let timeline: loom_core::TimelineId = timeline_id.parse().expect("TimelineId should parse");
        let snapshot = loom_runtime::WorldStore::snapshot(&storage, timeline)
            .await
            .expect("PostgreSQL snapshot should reconstruct the fixture");
        assert_eq!(snapshot.version().head_event_seq.value(), 2);
        assert_eq!(snapshot.version().state_revision.value(), 3);
        assert_eq!(snapshot.world_time().value(), 42);
        assert_eq!(snapshot.events.len(), 2);
        assert_eq!(snapshot.events[0].event_seq.value(), 1);
        assert_eq!(snapshot.events[1].event_seq.value(), 2);
        assert_eq!(snapshot.events[0].id.to_string(), event_first);
        assert_eq!(snapshot.events[0].participants.len(), 1);
        assert_eq!(snapshot.events[0].relationship_refs.len(), 1);
        assert_eq!(
            snapshot.events[1].causal_links[0].event_id(),
            snapshot.events[0].id
        );
        assert_eq!(snapshot.works.len(), 1);
        assert_eq!(snapshot.works[0].attempt_count, 2);
        assert_eq!(snapshot.works[0].claim_generation, 4);
        assert_eq!(snapshot.works[0].available_at.value(), 9);

        let view = snapshot.world_view();
        let entity: loom_core::EntityId = entity_a.parse().expect("EntityId should parse");
        assert!(view.entity(entity).is_some());
        let relationship: loom_core::RelationshipId = relationship_id
            .parse()
            .expect("RelationshipId should parse");
        assert!(
            view.relationship(relationship).is_none(),
            "ended Relationship must not be active"
        );
        assert_eq!(
            view.facet(
                loom_core::FacetOwner::entity(entity),
                &loom_core::FacetTypeId::from("test.counter"),
            )
            .expect("Entity Facet should be reconstructed")
            .value(),
            &serde_json::json!({"value": 7}),
        );

        let missing: loom_core::TimelineId = "00000000-0000-0000-0000-000000000298"
            .parse()
            .expect("missing TimelineId should parse");
        assert!(matches!(
            loom_runtime::WorldStore::snapshot(&storage, missing).await,
            Err(loom_runtime::ReadError::TimelineNotFound { .. })
        ));
        storage.close().await;
    }
}
