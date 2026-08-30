//! Test-only PostgreSQL fixture support for cross-crate live tests.
//!
//! This module is enabled only by the `test-support` feature. It keeps
//! PostgreSQL control connections and database lifecycle operations inside the
//! storage adapter, while callers receive only an isolated database URL and
//! continue to exercise the application through its public surfaces.

use std::{
    path::Path,
    process::{self, Command},
    sync::atomic::{AtomicU64, Ordering},
};

use sqlx::{AssertSqlSafe, PgPool};
use url::Url;

use crate::PgStorage;

const DEFAULT_POSTGRES_CONTROL_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";
const SERVER_VERSION_SQL: &str = include_str!("../sql/health/server_version.sql");

static NEXT_DATABASE: AtomicU64 = AtomicU64::new(1);

/// An isolated `PostgreSQL` database for a cross-crate integration-test fixture.
///
/// The control connection and database lifecycle remain owned by
/// `loom-storage`. Callers can pass [`Self::database_url`] to a real server,
/// then explicitly call [`Self::cleanup`] after the test has finished.
#[derive(Debug)]
pub struct TestDatabase {
    control_pool: PgPool,
    database_name: String,
    database_url: String,
}

impl TestDatabase {
    /// Creates a unique database and applies the embedded Loom migrations.
    ///
    /// `LOOM_TEST_POSTGRES_URL` overrides the repository-local control
    /// database. When the override is absent, the repository-managed test
    /// service is started on demand if necessary. The configured role must be
    /// allowed to create and drop databases.
    pub async fn provision(label: &str) -> Self {
        let (control_url, uses_repository_default) = postgres_control_url();
        let control_pool = connect_control_database(&control_url, uses_repository_default).await;
        assert_postgres_18(&control_pool).await;

        let database_name = unique_database_name(label);
        let create_sql = format!("CREATE DATABASE {}", quote_identifier(&database_name));
        sqlx::query(AssertSqlSafe(create_sql))
            .execute(&control_pool)
            .await
            .expect("controlled PostgreSQL role should create an isolated test database");

        let database_url = child_database_url(&control_url, &database_name);
        let storage = PgStorage::connect(&database_url)
            .await
            .expect("isolated PostgreSQL test database should accept connections");
        if let Err(error) = storage.migrate().await {
            storage.close().await;
            drop_database(&control_pool, &database_name).await;
            panic!("isolated PostgreSQL test database migrations should succeed: {error}");
        }
        storage.close().await;

        Self {
            control_pool,
            database_name,
            database_url,
        }
    }

    /// Returns the URL of the isolated, migrated `PostgreSQL` database.
    #[must_use]
    pub fn database_url(&self) -> &str {
        &self.database_url
    }

    /// Drops the isolated database and closes the control connection.
    pub async fn cleanup(self) {
        drop_database(&self.control_pool, &self.database_name).await;
        self.control_pool.close().await;
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
                    "repository-managed PostgreSQL test service is still unreachable after startup: {retry_error}"
                )
            })
        }
        Err(error) => panic!(
            "PostgreSQL control database from LOOM_TEST_POSTGRES_URL is unavailable: {error}"
        ),
    }
}

fn start_repository_postgres(initial_error: &sqlx::Error) {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/postgres-test.sh");
    let status = Command::new("bash").arg(&script).arg("up").status();
    match status {
        Ok(status) if status.success() => {}
        Ok(status) => panic!(
            "default PostgreSQL control database was unreachable ({initial_error}); `{}` exited with {status}",
            script.display()
        ),
        Err(error) => panic!(
            "default PostgreSQL control database was unreachable ({initial_error}); failed to start `{}`: {error}",
            script.display()
        ),
    }
}

async fn assert_postgres_18(pool: &PgPool) {
    let server_version: i32 = sqlx::query_scalar(SERVER_VERSION_SQL)
        .fetch_one(pool)
        .await
        .expect("controlled PostgreSQL should report its server version");
    assert!(
        (180_000..190_000).contains(&server_version),
        "cross-crate live tests require controlled PostgreSQL 18, got server_version_num={server_version}"
    );
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
