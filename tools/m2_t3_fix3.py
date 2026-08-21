from pathlib import Path

path = Path("crates/loom-storage/src/postgres/commit.rs")
text = path.read_text()
text = text.replace(
    "//! PostgreSQL implementation of the Runtime-owned atomic CommitStore port.",
    "//! `PostgreSQL` implementation of the Runtime-owned atomic `CommitStore` port.",
    1,
)
path.write_text(text)
