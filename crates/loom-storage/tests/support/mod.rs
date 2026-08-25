use std::{
    path::Path,
    process::{self, Command},
    sync::atomic::{AtomicU64, Ordering},
};

use loom_storage::PgStorage;
use sqlx::{AssertSqlSafe, PgPool};
use url::Url;

static NEXT_DATABASE: AtomicU64 = AtomicU64::new(1);

const DEFAULT_POSTGRES_CONTROL_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";

/// One isolated `PostgreSQL` database created for an integration-test fixture.
///
/// `LOOM_TEST_POSTGRES_URL` may override the repository-local control database.
/// When it is unset or empty, tests use Loom's localhost-only default control
/// database and start the repository-managed `PostgreSQL` service on demand if it
/// is not already reachable. The configured role must be allowed to create/drop
/// databases. Each fixture creates a unique child database, applies Loom
/// migrations from scratch, and requires explicit async cleanup at the end.
pub struct TestDatabase {
    control_pool: PgPool,
    database_name: String,
    database_url: String,
}

impl TestDatabase {
    /// Creates a unique empty database and applies the embedded Loom migrations.
    ///
    /// `PostgreSQL` integration tests never self-skip. The repository-local
    /// service is started on demand when the default control URL is in use. An
    /// explicit unreachable `LOOM_TEST_POSTGRES_URL` fails the test directly.
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

    /// Opens Loom's concrete storage adapter against this isolated database.
    pub async fn storage(&self) -> PgStorage {
        PgStorage::connect(&self.database_url)
            .await
            .expect("isolated PostgreSQL storage connection should succeed")
    }

    /// Opens a direct `SQLx` pool for test fixture setup and schema assertions.
    pub async fn pool(&self) -> PgPool {
        PgPool::connect(&self.database_url)
            .await
            .expect("isolated PostgreSQL fixture pool should connect")
    }

    /// Drops the isolated database, force-closing any leaked test connections.
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
