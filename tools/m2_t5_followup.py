from pathlib import Path

path = Path("crates/loom-storage/tests/postgres_read.rs")
text = path.read_text()
path.write_text(text.replace("use loom_storage::PgStorage;\n", "", 1))
