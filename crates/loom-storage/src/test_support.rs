//! `PostgreSQL` fixtures for integration tests in dependent workspace crates.

use std::{
    path::Path,
    process::{self, Command},
    sync::atomic::{AtomicU64, Ordering},
};

use loom_core::{TimelineId, WorkId};
use loom_runtime::{PlatformTime, ReadError, WorkClaim, WorkError, WorkRecord, WorkStore};
use sqlx::{AssertSqlSafe, PgPool};
use url::Url;

use crate::PgStorage;

static NEXT_DATABASE: AtomicU64 = AtomicU64::new(1);

const DEFAULT_POSTGRES_CONTROL_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";

/// One isolated `PostgreSQL` database created for a live integration-test
/// fixture. SQL and database lifecycle remain owned by `loom-storage`; callers
/// receive only Loom storage-port operations and cleanup.
pub struct TestDatabase {
    control_pool: PgPool,
    database_name: String,
    database_url: String,
}

impl TestDatabase {
    /// Creates a unique empty database and applies the embedded Loom migrations.
    ///
    /// `LOOM_TEST_POSTGRES_URL` may override the repository-local control
    /// database. When it is unset or empty, the repository-managed
    /// `PostgreSQL` service is started on demand.
    ///
    /// # Panics
    ///
    /// Panics when the control database, isolated database, migrations or
    /// repository-managed `PostgreSQL` service cannot be prepared.
    pub async fn provision(label: &str) -> Self {
        let (control_url, uses_repository_default) = postgres_control_url();
        let control_pool = connect_control_database(&control_url, uses_repository_default).await;
        let database_name = unique_database_name(label);
        let create_sql = format!("CREATE DATABASE {}", quote_identifier(&database_name));
        sqlx::query(AssertSqlSafe(create_sql))
            .execute(&control_pool)
            .await
            .expect("PostgreSQL test role should create isolated databases");

        let database_url = child_database_url(&control_url, &database_name);
        let storage = PgStorage::connect(&database_url)
            .await
            .expect("isolated PostgreSQL test database should accept connections");
        if let Err(error) = storage.migrate().await {
            storage.close().await;
            drop_database(&control_pool, &database_name).await;
            panic!("migrations should apply to a fresh isolated database: {error}");
        }
        storage.close().await;

        Self {
            control_pool,
            database_name,
            database_url,
        }
    }

    /// Returns the isolated database URL for a Loom server configuration.
    #[must_use]
    pub fn database_url(&self) -> &str {
        &self.database_url
    }

    /// Claims one Work through the storage-owned Runtime Work port.
    ///
    /// This is test setup for an operational lease; it does not select a
    /// logical Work head or perform Scheduler execution.
    ///
    /// # Errors
    ///
    /// Returns the Runtime Work-port error when the claim cannot be
    /// established.
    pub async fn claim_work(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> Result<WorkClaim, WorkError> {
        let storage = self.connect_storage().await;
        let result = storage
            .claim(timeline_id, work_id, now, claimed_until)
            .await;
        storage.close().await;
        result
    }

    /// Records one technical Work retry through the storage-owned Runtime Work
    /// port, preserving the Work's logical identity and schedule position.
    ///
    /// # Errors
    ///
    /// Returns the Runtime Work-port error when the claim is stale, expired or
    /// otherwise cannot be retried.
    pub async fn retry_work(
        &self,
        claim: &WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> Result<WorkRecord, WorkError> {
        let storage = self.connect_storage().await;
        let result = storage.retry(claim, now, available_at, last_error).await;
        storage.close().await;
        result
    }

    /// Reads one Work's operational and logical state through the storage-owned
    /// Runtime Work port.
    ///
    /// # Errors
    ///
    /// Returns the Runtime read error when the Timeline cannot be read.
    pub async fn read_work(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
    ) -> Result<Option<WorkRecord>, ReadError> {
        let storage = self.connect_storage().await;
        let result = storage.work(timeline_id, work_id).await;
        storage.close().await;
        result
    }

    /// Drops the isolated database, force-closing any leaked test connections.
    pub async fn cleanup(self) {
        drop_database(&self.control_pool, &self.database_name).await;
        self.control_pool.close().await;
    }

    async fn connect_storage(&self) -> PgStorage {
        PgStorage::connect(&self.database_url)
            .await
            .expect("isolated PostgreSQL test database should accept connections")
    }
}

fn postgres_control_url() -> (String, bool) {
    match std::env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) if !url.trim().is_empty() => (url, false),
        _ => (DEFAULT_POSTGRES_CONTROL_URL.to_owned(), true),
    }
}

async fn connect_control_database(control_url: &str, uses_repository_default: bool) -> PgPool {
    match PgPool::connect(control_url).await {
        Ok(pool) => pool,
        Err(error) if uses_repository_default => {
            start_repository_postgres(&error);
            PgPool::connect(control_url).await.unwrap_or_else(|retry_error| {
                panic!(
                    "repository-managed PostgreSQL test service is still unreachable after startup: \
                     {retry_error}"
                )
            })
        }
        Err(error) => panic!(
            "PostgreSQL integration test control database from LOOM_TEST_POSTGRES_URL is unavailable: \
             {error}"
        ),
    }
}

fn start_repository_postgres(initial_error: &sqlx::Error) {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/postgres-test.sh");
    let status = Command::new("bash").arg(&script).arg("up").status();
    match status {
        Ok(status) if status.success() => {}
        Ok(status) => panic!(
            "default PostgreSQL control database was unreachable ({initial_error}); \
             `{}` exited with {status}",
            script.display()
        ),
        Err(error) => panic!(
            "default PostgreSQL control database was unreachable ({initial_error}); \
             failed to start `{}`: {error}",
            script.display()
        ),
    }
}

fn child_database_url(control_url: &str, database_name: &str) -> String {
    let mut url = Url::parse(control_url).expect("LOOM_TEST_POSTGRES_URL should be a valid URL");
    url.set_path(&format!("/{database_name}"));
    url.to_string()
}

fn unique_database_name(label: &str) -> String {
    let label = label
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .take(20)
        .collect::<String>()
        .to_ascii_lowercase();
    let counter = NEXT_DATABASE.fetch_add(1, Ordering::Relaxed);
    format!("loom_{label}_{}_{}", process::id(), counter)
}

fn quote_identifier(identifier: &str) -> String {
    debug_assert!(
        identifier
            .chars()
            .all(|character| character.is_ascii_lowercase()
                || character.is_ascii_digit()
                || character == '_')
    );
    format!("\"{identifier}\"")
}

async fn drop_database(control_pool: &PgPool, database_name: &str) {
    let drop_sql = format!(
        "DROP DATABASE IF EXISTS {} WITH (FORCE)",
        quote_identifier(database_name)
    );
    sqlx::query(AssertSqlSafe(drop_sql))
        .execute(control_pool)
        .await
        .expect("isolated PostgreSQL test database should be droppable");
}
