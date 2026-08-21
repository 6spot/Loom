from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"expected source block not found in {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1))


POSTGRES_URL_FN = '''fn postgres_url() -> Option<String> {
    match std::env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) => Some(url),
        Err(error) if std::env::var_os("LOOM_REQUIRE_POSTGRES_TESTS").is_some() => {
            panic!("LOOM_TEST_POSTGRES_URL is required for PostgreSQL tests: {error}")
        }
        Err(_) => None,
    }
}

'''

# Empty read parity test.
read = Path("crates/loom-storage/tests/postgres_read.rs")
text = read.read_text()
text = text.replace("use loom_core::TimelineId;", "mod support;\n\nuse loom_core::TimelineId;", 1)
text = text.replace("use loom_storage::PgStorage;\n", "use loom_storage::PgStorage;\nuse support::TestDatabase;\n", 1)
text = text.replace(POSTGRES_URL_FN, "", 1)
old = '''    let Some(database_url) = postgres_url() else {
        return;
    };

    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");
    storage
        .migrate()
        .await
        .expect("migrations should be current");

    let pool = sqlx::PgPool::connect(&database_url)
        .await
        .expect("test setup should connect independently");
'''
new = '''    let Some(database) = TestDatabase::provision("read-empty").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
'''
if old not in text:
    raise SystemExit("postgres_read setup block not found")
text = text.replace(old, new, 1)
text = text.replace(
    "    storage.close().await;\n}",
    "    storage.close().await;\n    database.cleanup().await;\n}",
    1,
)
read.write_text(text)

# Commit suite: each authority fixture gets a fresh migrated database.
commit = Path("crates/loom-storage/tests/postgres_commit.rs")
text = commit.read_text()
text = text.replace("use std::str::FromStr;", "mod support;\n\nuse std::str::FromStr;", 1)
text = text.replace("use sqlx::PgPool;\n", "use sqlx::PgPool;\nuse support::TestDatabase;\n", 1)
text = text.replace(POSTGRES_URL_FN, "", 1)
old = '''async fn authority(seed: u128) -> Option<(PgStorage, PgPool, WorldId, TimelineId)> {
    let database_url = postgres_url()?;
    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");
    storage
        .migrate()
        .await
        .expect("migrations should be current");
    let pool = PgPool::connect(&database_url)
        .await
        .expect("test setup should connect independently");
'''
new = '''async fn authority(
    seed: u128,
) -> Option<(TestDatabase, PgStorage, PgPool, WorldId, TimelineId)> {
    let database = TestDatabase::provision("commit").await?;
    let storage = database.storage().await;
    let pool = database.pool().await;
'''
if old not in text:
    raise SystemExit("postgres_commit authority block not found")
text = text.replace(old, new, 1)
text = text.replace(
    "    Some((storage, pool, world_id, timeline_id))\n}",
    "    Some((database, storage, pool, world_id, timeline_id))\n}",
    1,
)
text = text.replace(
    "let Some((storage, pool,",
    "let Some((database, storage, pool,",
)
text = text.replace(
    "    storage.close().await;\n}",
    "    storage.close().await;\n    database.cleanup().await;\n}",
)
if "postgres_url()" in text:
    raise SystemExit("postgres_commit still contains direct shared postgres_url use")
commit.write_text(text)

# Durable Work suite follows the same isolated authority fixture pattern.
work = Path("crates/loom-storage/tests/postgres_work.rs")
text = work.read_text()
text = text.replace("use std::str::FromStr;", "mod support;\n\nuse std::str::FromStr;", 1)
text = text.replace("use sqlx::PgPool;\n", "use sqlx::PgPool;\nuse support::TestDatabase;\n", 1)
text = text.replace(POSTGRES_URL_FN, "", 1)
old = '''async fn authority(seed: u128) -> Option<(PgStorage, PgPool, WorldId, TimelineId)> {
    let database_url = postgres_url()?;
    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");
    storage
        .migrate()
        .await
        .expect("migrations should be current");
    let pool = PgPool::connect(&database_url)
        .await
        .expect("test setup should connect independently");
'''
new = '''async fn authority(
    seed: u128,
) -> Option<(TestDatabase, PgStorage, PgPool, WorldId, TimelineId)> {
    let database = TestDatabase::provision("work").await?;
    let storage = database.storage().await;
    let pool = database.pool().await;
'''
if old not in text:
    raise SystemExit("postgres_work authority block not found")
text = text.replace(old, new, 1)
text = text.replace(
    "    Some((storage, pool, world_id, timeline_id))\n}",
    "    Some((database, storage, pool, world_id, timeline_id))\n}",
    1,
)
text = text.replace("let Some((storage, pool,", "let Some((database, storage, pool,")
text = text.replace(
    "    storage.close().await;\n}",
    "    storage.close().await;\n    database.cleanup().await;\n}",
)
if "postgres_url()" in text:
    raise SystemExit("postgres_work still contains direct shared postgres_url use")
work.write_text(text)

# Stale-completion regression test gets its own fresh database too.
stale = Path("crates/loom-storage/tests/postgres_work_stale_completion.rs")
text = stale.read_text()
text = text.replace("use std::str::FromStr;", "mod support;\n\nuse std::str::FromStr;", 1)
text = text.replace("use sqlx::PgPool;\n", "use sqlx::PgPool;\nuse support::TestDatabase;\n", 1)
text = text.replace(POSTGRES_URL_FN, "", 1)
old = '''    let Some(database_url) = postgres_url() else {
        return;
    };
    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");
    storage
        .migrate()
        .await
        .expect("migrations should be current");
    let pool = PgPool::connect(&database_url)
        .await
        .expect("test setup should connect independently");
'''
new = '''    let Some(database) = TestDatabase::provision("work-stale-completion").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
'''
if old not in text:
    raise SystemExit("postgres_work_stale_completion setup block not found")
text = text.replace(old, new, 1)
text = text.replace(
    "    storage.close().await;\n}",
    "    storage.close().await;\n    database.cleanup().await;\n}",
    1,
)
stale.write_text(text)
