"""Excel ingestion into SQLite for FXCorrMonitor."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from config.instruments import INSTRUMENTS, TARGET_ID, Instrument, instrument_to_row
from src.database import (
    finish_ingestion_log,
    init_db,
    start_ingestion_log,
    upsert_instruments,
    upsert_market_data,
)
from src.utils import date_to_iso, normalize_date, parse_numeric, resolve_path, utc_now_iso

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Fatal ingestion error (e.g. missing USDKRW)."""


def _sheet_names(path: Path) -> list[str]:
    xl = pd.ExcelFile(path, engine="openpyxl")
    return list(xl.sheet_names)


def read_instrument_sheet(
    excel_path: Path,
    instrument: Instrument,
    available_sheets: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    sheets = available_sheets if available_sheets is not None else _sheet_names(excel_path)

    if instrument.sheet_name not in sheets:
        msg = f"시트 없음: '{instrument.sheet_name}' ({instrument.instrument_id})"
        warnings.append(msg)
        logger.warning(msg)
        return pd.DataFrame(columns=["date", "raw_value", "parse_failures"]), warnings

    try:
        df = pd.read_excel(
            excel_path,
            sheet_name=instrument.sheet_name,
            header=2,
            engine="openpyxl",
        )
    except Exception as exc:
        msg = f"시트 읽기 실패: {instrument.sheet_name} ({instrument.instrument_id}): {exc}"
        warnings.append(msg)
        logger.warning(msg)
        return pd.DataFrame(columns=["date", "raw_value", "parse_failures"]), warnings

    df.columns = [str(c).strip() if c is not None else "" for c in df.columns]

    if "일자" not in df.columns:
        msg = f"열 '일자' 없음: {instrument.sheet_name} ({instrument.instrument_id})"
        warnings.append(msg)
        logger.warning(msg)
        return pd.DataFrame(columns=["date", "raw_value", "parse_failures"]), warnings

    if instrument.source_column not in df.columns:
        msg = (
            f"열 '{instrument.source_column}' 없음: "
            f"{instrument.sheet_name} ({instrument.instrument_id})"
        )
        warnings.append(msg)
        logger.warning(msg)
        return pd.DataFrame(columns=["date", "raw_value", "parse_failures"]), warnings

    work = df[["일자", instrument.source_column]].copy()
    dates: list[str | None] = []
    values: list[float | None] = []
    parse_failures = 0

    for _, row in work.iterrows():
        d = normalize_date(row["일자"])
        iso = date_to_iso(d) if d else None
        raw = row[instrument.source_column]
        num = parse_numeric(raw)
        if raw is not None and not (isinstance(raw, float) and pd.isna(raw)) and num is None:
            text = str(raw).strip()
            if text and text.lower() not in {"nan", "none"}:
                parse_failures += 1
        dates.append(iso)
        values.append(num)

    out = pd.DataFrame({"date": dates, "raw_value": values})
    out["parse_failures"] = 0
    if len(out):
        out.loc[0, "parse_failures"] = parse_failures

    out = out.dropna(subset=["date", "raw_value"])
    if out.empty:
        warnings.append(f"유효 데이터 없음: {instrument.instrument_id}")
        return pd.DataFrame(columns=["date", "raw_value", "parse_failures"]), warnings

    out = out.sort_values("date")
    out = out.drop_duplicates(subset=["date"], keep="last")
    out["parse_failures"] = parse_failures
    out = out.reset_index(drop=True)
    return out, warnings


def prepare_market_rows(
    cleaned: pd.DataFrame,
    instrument: Instrument,
    source_file: str,
    loaded_at: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, r in cleaned.iterrows():
        rows.append(
            {
                "date": r["date"],
                "instrument_id": instrument.instrument_id,
                "raw_value": float(r["raw_value"]),
                "source_file": source_file,
                "source_sheet": instrument.sheet_name,
                "source_column": instrument.source_column,
                "loaded_at": loaded_at,
            }
        )
    return rows


def ingest_excel(
    file_path: str | Path,
    db_path: str | Path | None = None,
    replace: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    from src.utils import setup_logging

    setup_logging(verbose)

    excel_path = resolve_path(file_path)
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel 파일이 없습니다: {excel_path}")

    db = resolve_path(db_path) if db_path else resolve_path("data/fx_dashboard.db")
    init_db(db, replace=replace)

    source_name = str(excel_path)
    ingestion_id = start_ingestion_log(source_name, db)
    loaded_at = utc_now_iso()
    warnings: list[str] = []
    missing_sheets: list[str] = []
    all_rows: list[dict[str, Any]] = []
    parse_failure_total = 0
    usdkrw_loaded = False

    try:
        available = _sheet_names(excel_path)
        logger.info("Excel sheets (%d): %s", len(available), available)

        instrument_rows = [
            instrument_to_row(inst, loaded_at) for inst in INSTRUMENTS
        ]
        upsert_instruments(instrument_rows, db)

        for inst in INSTRUMENTS:
            cleaned, w = read_instrument_sheet(excel_path, inst, available)
            warnings.extend(w)
            for msg in w:
                if "시트 없음" in msg:
                    missing_sheets.append(inst.sheet_name)

            if cleaned.empty:
                if inst.instrument_id == TARGET_ID:
                    raise IngestionError(
                        "USDKRW 시트가 없거나 유효 데이터가 없어 분석을 진행할 수 없습니다. "
                        f"시트명: '{inst.sheet_name}'"
                    )
                continue

            if "parse_failures" in cleaned.columns:
                parse_failure_total += int(cleaned["parse_failures"].iloc[0])

            rows = prepare_market_rows(cleaned, inst, source_name, loaded_at)
            all_rows.extend(rows)
            if inst.instrument_id == TARGET_ID:
                usdkrw_loaded = True
            logger.info(
                "Loaded %s: %d rows (%s ~ %s)",
                inst.instrument_id,
                len(rows),
                rows[0]["date"] if rows else "—",
                rows[-1]["date"] if rows else "—",
            )

        if not usdkrw_loaded:
            raise IngestionError("USDKRW 데이터가 적재되지 않았습니다.")

        inserted, updated = upsert_market_data(all_rows, db)
        finish_ingestion_log(
            ingestion_id,
            status="success",
            inserted_rows=inserted,
            updated_rows=updated,
            db_path=db,
        )

        result = {
            "status": "success",
            "db_path": str(db),
            "source_file": source_name,
            "inserted_rows": inserted,
            "updated_rows": updated,
            "total_rows": len(all_rows),
            "missing_sheets": sorted(set(missing_sheets)),
            "warnings": warnings,
            "parse_failures": parse_failure_total,
            "ingestion_id": ingestion_id,
        }
        logger.info(
            "Ingestion complete: inserted=%d updated=%d total=%d missing_sheets=%s",
            inserted,
            updated,
            len(all_rows),
            result["missing_sheets"],
        )
        return result

    except Exception as exc:
        finish_ingestion_log(
            ingestion_id,
            status="failed",
            error_message=str(exc),
            db_path=db,
        )
        logger.exception("Ingestion failed")
        raise
