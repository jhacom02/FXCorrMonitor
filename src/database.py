"""SQLite access layer for FXCorrMonitor."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Iterable

import pandas as pd

from src.utils import DEFAULT_DB_PATH, ensure_parent_dir, utc_now_iso

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_code TEXT,
    source_column TEXT NOT NULL,
    data_type TEXT NOT NULL,
    transformation TEXT NOT NULL,
    alignment TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_data (
    date TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    raw_value REAL NOT NULL,
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_column TEXT NOT NULL,
    loaded_at TEXT NOT NULL,
    PRIMARY KEY (date, instrument_id),
    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
);

CREATE TABLE IF NOT EXISTS ingestion_log (
    ingestion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    inserted_rows INTEGER DEFAULT 0,
    updated_rows INTEGER DEFAULT 0,
    error_message TEXT
);
"""


@contextmanager
def get_connection(db_path: str | Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    ensure_parent_dir(path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None, replace: bool = False) -> Path:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    ensure_parent_dir(path)
    if replace and path.exists():
        path.unlink()
        logger.info("Removed existing database: %s", path)
    with get_connection(path) as conn:
        conn.executescript(SCHEMA_SQL)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(instruments)").fetchall()]
        if "category" in cols:
            conn.execute("ALTER TABLE instruments DROP COLUMN category")
        if "note" in cols:
            conn.execute("ALTER TABLE instruments DROP COLUMN note")
    logger.info("Initialized database schema at %s", path)
    return path


def table_exists(db_path: str | Path | None, table_name: str) -> bool:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not path.exists():
        return False
    with get_connection(path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    return row is not None


def upsert_instruments(rows: Iterable[dict[str, Any]], db_path: str | Path | None = None) -> int:
    sql = """
    INSERT INTO instruments (
        instrument_id, display_name, source_sheet, source_code,
        source_column, data_type, transformation, alignment, active, updated_at
    ) VALUES (
        :instrument_id, :display_name, :source_sheet, :source_code,
        :source_column, :data_type, :transformation, :alignment, :active, :updated_at
    )
    ON CONFLICT(instrument_id) DO UPDATE SET
        display_name=excluded.display_name,
        source_sheet=excluded.source_sheet,
        source_code=excluded.source_code,
        source_column=excluded.source_column,
        data_type=excluded.data_type,
        transformation=excluded.transformation,
        alignment=excluded.alignment,
        active=excluded.active,
        updated_at=excluded.updated_at
    """
    rows_list = list(rows)
    if not rows_list:
        return 0
    with get_connection(db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(instruments)").fetchall()]
        if "category" in cols:
            conn.execute("ALTER TABLE instruments DROP COLUMN category")
        if "note" in cols:
            conn.execute("ALTER TABLE instruments DROP COLUMN note")
        conn.executemany(sql, rows_list)
    return len(rows_list)


def upsert_market_data(
    rows: Iterable[dict[str, Any]],
    db_path: str | Path | None = None,
) -> tuple[int, int]:
    rows_list = list(rows)
    if not rows_list:
        return 0, 0

    check_sql = "SELECT 1 FROM market_data WHERE date=? AND instrument_id=?"
    insert_sql = """
    INSERT INTO market_data (
        date, instrument_id, raw_value, source_file, source_sheet, source_column, loaded_at
    ) VALUES (
        :date, :instrument_id, :raw_value, :source_file, :source_sheet, :source_column, :loaded_at
    )
    ON CONFLICT(date, instrument_id) DO UPDATE SET
        raw_value=excluded.raw_value,
        source_file=excluded.source_file,
        source_sheet=excluded.source_sheet,
        source_column=excluded.source_column,
        loaded_at=excluded.loaded_at
    """
    inserted = 0
    updated = 0
    with get_connection(db_path) as conn:
        for row in rows_list:
            exists = conn.execute(check_sql, (row["date"], row["instrument_id"])).fetchone()
            if exists:
                updated += 1
            else:
                inserted += 1
            conn.execute(insert_sql, row)
    return inserted, updated


def start_ingestion_log(source_file: str, db_path: str | Path | None = None) -> int:
    started_at = utc_now_iso()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO ingestion_log (source_file, started_at, status)
            VALUES (?, ?, ?)
            """,
            (source_file, started_at, "running"),
        )
        return int(cur.lastrowid)


def finish_ingestion_log(
    ingestion_id: int,
    status: str,
    inserted_rows: int = 0,
    updated_rows: int = 0,
    error_message: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE ingestion_log
            SET completed_at=?, status=?, inserted_rows=?, updated_rows=?, error_message=?
            WHERE ingestion_id=?
            """,
            (utc_now_iso(), status, inserted_rows, updated_rows, error_message, ingestion_id),
        )


def load_instruments(db_path: str | Path | None = None, active_only: bool = True) -> pd.DataFrame:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not path.exists() or not table_exists(path, "instruments"):
        return pd.DataFrame()
    sql = "SELECT * FROM instruments"
    params: tuple[Any, ...] = ()
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY instrument_id"
    with get_connection(path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def load_market_data(
    db_path: str | Path | None = None,
    instrument_ids: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not path.exists() or not table_exists(path, "market_data"):
        return pd.DataFrame(
            columns=[
                "date",
                "instrument_id",
                "raw_value",
                "source_file",
                "source_sheet",
                "source_column",
                "loaded_at",
            ]
        )

    clauses: list[str] = []
    params: list[Any] = []
    if instrument_ids:
        placeholders = ",".join("?" for _ in instrument_ids)
        clauses.append(f"instrument_id IN ({placeholders})")
        params.extend(instrument_ids)
    if start_date:
        clauses.append("date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("date <= ?")
        params.append(end_date)

    sql = "SELECT date, instrument_id, raw_value, source_file, source_sheet, source_column, loaded_at FROM market_data"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY date, instrument_id"

    with get_connection(path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    return df


def get_latest_ingestion(db_path: str | Path | None = None) -> dict[str, Any] | None:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not path.exists() or not table_exists(path, "ingestion_log"):
        return None
    with get_connection(path) as conn:
        row = conn.execute(
            """
            SELECT * FROM ingestion_log
            ORDER BY ingestion_id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def get_db_status(db_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    status: dict[str, Any] = {
        "db_path": str(path),
        "db_exists": path.exists(),
        "market_data_exists": False,
        "latest_date": None,
        "usdkrw_latest_date": None,
        "usdkrw_latest_value": None,
        "row_count": 0,
        "last_ingestion": None,
    }
    if not path.exists():
        return status

    status["market_data_exists"] = table_exists(path, "market_data")
    if not status["market_data_exists"]:
        return status

    with get_connection(path) as conn:
        row_count = conn.execute("SELECT COUNT(*) AS n FROM market_data").fetchone()["n"]
        latest = conn.execute("SELECT MAX(date) AS d FROM market_data").fetchone()["d"]
        usd = conn.execute(
            """
            SELECT date, raw_value FROM market_data
            WHERE instrument_id='USDKRW'
            ORDER BY date DESC
            LIMIT 1
            """
        ).fetchone()
    status["row_count"] = int(row_count)
    status["latest_date"] = latest
    if usd:
        status["usdkrw_latest_date"] = usd["date"]
        status["usdkrw_latest_value"] = float(usd["raw_value"])
    status["last_ingestion"] = get_latest_ingestion(path)
    return status
