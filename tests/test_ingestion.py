"""Tests for Excel ingestion and SQLite UPSERT behavior."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.instruments import INSTRUMENTS, TARGET_ID
from src.database import init_db, load_market_data, upsert_market_data
from src.ingestion import IngestionError, ingest_excel, read_instrument_sheet
from src.utils import normalize_date, parse_numeric, utc_now_iso


def test_excel_serial_date_normalized():
    # Excel serial for 2020-01-02 is 43832 (origin 1899-12-30)
    d = normalize_date(43832)
    assert d == date(2020, 1, 2)


def test_datetime_date_normalized():
    assert normalize_date(datetime(2024, 5, 1, 15, 30)) == date(2024, 5, 1)
    assert normalize_date(pd.Timestamp("2024-05-01")) == date(2024, 5, 1)
    assert normalize_date("2024-05-01") == date(2024, 5, 1)


def test_parse_numeric_string():
    assert parse_numeric("1,234.5") == 1234.5
    assert parse_numeric("(100)") == -100.0
    assert parse_numeric(None) is None


def test_sqlite_upsert_no_duplicate(tmp_path: Path):
    db = tmp_path / "t.db"
    init_db(db)
    # Need instruments FK
    from src.database import upsert_instruments

    upsert_instruments(
        [
            {
                "instrument_id": "USDKRW",
                "display_name": "USDKRW",
                "category": "기준 환율",
                "source_sheet": "s",
                "source_code": "c",
                "source_column": "현재가",
                "data_type": "price",
                "transformation": "log_return",
                "alignment": "same_day",
                "active": 1,
                "note": None,
                "updated_at": utc_now_iso(),
            }
        ],
        db,
    )
    rows1 = [
        {
            "date": "2024-01-02",
            "instrument_id": "USDKRW",
            "raw_value": 1300.0,
            "source_file": "a.xlsx",
            "source_sheet": "s",
            "source_column": "현재가",
            "loaded_at": utc_now_iso(),
        }
    ]
    upsert_market_data(rows1, db)
    rows2 = [
        {
            "date": "2024-01-02",
            "instrument_id": "USDKRW",
            "raw_value": 1301.5,
            "source_file": "b.xlsx",
            "source_sheet": "s",
            "source_column": "현재가",
            "loaded_at": utc_now_iso(),
        }
    ]
    upsert_market_data(rows2, db)
    df = load_market_data(db, instrument_ids=["USDKRW"])
    assert len(df) == 1
    assert float(df.iloc[0]["raw_value"]) == 1301.5


def _write_minimal_excel(path: Path, include_usdkrw: bool = True) -> None:
    """Create a tiny Infomax-like workbook for one or two sheets."""
    from openpyxl import Workbook

    wb = Workbook()
    # USDKRW sheet
    if include_usdkrw:
        ws = wb.active
        ws.title = "서울외환(기업용) USDKRW 스팟"
        ws.append(["시작", datetime(2024, 1, 1), "종료", datetime(2024, 1, 10), "종목코드", "USDSP_SMBCC_EXT"])
        ws.append(["서울외환(기업용) USDKRW 스팟"])
        ws.append(["일자", "고가", "저가", "현재가", "전일대비"])
        ws.append([datetime(2024, 1, 2), 1300, 1290, 1295, 1])
        ws.append([datetime(2024, 1, 3), 1305, 1295, 1300, 5])
        ws.append([datetime(2024, 1, 3), 1306, 1296, 1302, 7])  # duplicate date -> last wins
    else:
        ws = wb.active
        ws.title = "Other"

    # DXY sheet
    ws2 = wb.create_sheet("달러인덱스 Dollars")
    ws2.append(["시작", datetime(2024, 1, 1), "종료", datetime(2024, 1, 10), "종목코드", "DOLLAR"])
    ws2.append(["달러인덱스 DOLLARS"])
    ws2.append(["일자", "KR_MID_Open", "KR_MID_Close", "KR_MID_Chg"])
    ws2.append([43832, 100, 101, 1])  # serial date 2020-01-02 — intentional different era ok for unit
    ws2.append([datetime(2024, 1, 2), 103, 104, 1])
    ws2.append([datetime(2024, 1, 3), 104, 105, 1])

    wb.save(path)


def test_ingest_requires_usdkrw(tmp_path: Path):
    xlsx = tmp_path / "no_usd.xlsx"
    _write_minimal_excel(xlsx, include_usdkrw=False)
    db = tmp_path / "t.db"
    with pytest.raises(IngestionError):
        ingest_excel(xlsx, db_path=db, replace=True)


def test_ingest_dedupes_dates_and_continues(tmp_path: Path):
    xlsx = tmp_path / "ok.xlsx"
    _write_minimal_excel(xlsx, include_usdkrw=True)
    db = tmp_path / "t.db"
    result = ingest_excel(xlsx, db_path=db, replace=True)
    assert result["status"] == "success"
    usd = load_market_data(db, instrument_ids=["USDKRW"])
    # duplicate 2024-01-03 kept last value 1302
    row = usd[usd["date"] == "2024-01-03"]
    assert len(row) == 1
    assert float(row.iloc[0]["raw_value"]) == 1302.0
