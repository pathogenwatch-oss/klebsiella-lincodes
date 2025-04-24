import sqlite3
from pathlib import Path


def connect_db(db_file: str) -> sqlite3.Connection:
    return sqlite3.connect(db_file)


def initialise_db(file: str|Path) -> sqlite3.Connection:
    conn: sqlite3.Connection = sqlite3.connect(file)
    cursor: sqlite3.Cursor = conn.cursor()

    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=OFF")

    cursor.execute(
        "CREATE TABLE IF NOT EXISTS alleles(checksum TEXT, position INTEGER, code INTEGER)"
    )
    cursor.execute("DELETE FROM alleles")
    cursor.execute("DROP INDEX IF EXISTS idx_checksum")

    cursor.close()
    conn.commit()
    return conn


def finalise_db(db: sqlite3.Connection) -> None:
    cursor: sqlite3.Cursor = db.cursor()
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_checksum ON alleles(checksum, position)"
    )
    cursor.execute("VACUUM")
    cursor.execute("ANALYZE")
    cursor.execute("PRAGMA optimize")
    cursor.execute("PRAGMA query_only = ON")  # Set to read-only mode
    db.commit()
    cursor.close()


def lookup_st(cursor: sqlite3.Cursor, checksum: str, position: int) -> int | None:
    result: tuple[int] | None = next(
        cursor.execute(
            "SELECT code FROM alleles WHERE checksum =? AND position =?", (checksum, position)
        ),
        None,
    )
    return result[0] if result is not None else None
