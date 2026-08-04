"""Excel ingestion into SQLite for FXCorrMonitor."""

from __future__ import annotations

import logging
import re
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

_SHEET_SUFFIX_RE = re.compile(r"_\d+$")


class IngestionError(Exception):
    """Fatal ingestion error (e.g. missing USDKRW)."""


def _sheet_names(path: Path) -> list[str]:
    xl = pd.ExcelFile(path, engine="openpyxl")
    return list(xl.sheet_names)


def _normalize_sheet_name(name: str) -> str:
    return _SHEET_SUFFIX_RE.sub("", str(name).strip())


def _normalize_source_code(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return str(value).strip()
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return text or None


def _read_sheet_meta_code(excel_path: Path, sheet_name: str) -> str | None:
    meta = pd.read_excel(
        excel_path,
        sheet_name=sheet_name,
        header=None,
        nrows=1,
        engine="openpyxl",
    )
    if meta.empty or meta.shape[1] < 2:
        return None
    row = meta.iloc[0]
    for i, cell in enumerate(row.tolist()):
        if str(cell).strip() == "종목코드" and i + 1 < len(row):
            return _normalize_source_code(row.iloc[i + 1])
    if meta.shape[1] > 5:
        return _normalize_source_code(row.iloc[5])
    return None


def build_sheet_catalog(
    excel_path: Path,
    available_sheets: list[str] | None = None,
) -> tuple[list[dict[str, str | None]], list[str]]:
    warnings: list[str] = []
    sheets = available_sheets if available_sheets is not None else _sheet_names(excel_path)
    catalog: list[dict[str, str | None]] = []
    for actual in sheets:
        code = None
        try:
            code = _read_sheet_meta_code(excel_path, actual)
        except Exception as exc:
            msg = f"시트 메타 읽기 실패: {actual}: {exc}"
            warnings.append(msg)
            logger.warning(msg)
        catalog.append(
            {
                "actual": actual,
                "normalized": _normalize_sheet_name(actual),
                "code": code,
            }
        )

    by_code: dict[str, list[str]] = {}
    for entry in catalog:
        code = entry["code"]
        if not code:
            continue
        by_code.setdefault(code, []).append(str(entry["actual"]))
    for code, names in by_code.items():
        if len(names) > 1:
            msg = (
                f"동일 종목코드 '{code}'가 여러 시트에 있습니다: {names}. "
                "해당 코드로는 매칭하지 않습니다."
            )
            warnings.append(msg)
            logger.warning(msg)

    return catalog, warnings


def resolve_sheet_for_instrument(
    instrument: Instrument,
    catalog: list[dict[str, str | None]],
) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    by_code: dict[str, list[str]] = {}
    for entry in catalog:
        code = entry["code"]
        if not code:
            continue
        by_code.setdefault(str(code), []).append(str(entry["actual"]))

    want_code = _normalize_source_code(instrument.source_code)
    if want_code and want_code in by_code:
        matches = by_code[want_code]
        if len(matches) == 1:
            return matches[0], warnings
        warnings.append(
            f"종목코드 '{want_code}' 모호 ({instrument.instrument_id}): "
            f"시트 {matches} — 시트명 fallback 사용"
        )

    want_name = _normalize_sheet_name(instrument.sheet_name)
    name_hits = [
        str(e["actual"]) for e in catalog if e["normalized"] == want_name
    ]
    if len(name_hits) == 1:
        return name_hits[0], warnings
    if len(name_hits) > 1:
        msg = (
            f"정규화 시트명 '{want_name}'이 여러 개입니다 "
            f"({instrument.instrument_id}): {name_hits}"
        )
        warnings.append(msg)
        logger.warning(msg)
        return None, warnings

    msg = f"시트 없음: '{instrument.sheet_name}' ({instrument.instrument_id})"
    warnings.append(msg)
    logger.warning(msg)
    return None, warnings


def read_instrument_sheet(
    excel_path: Path,
    instrument: Instrument,
    available_sheets: list[str] | None = None,
    catalog: list[dict[str, str | None]] | None = None,
) -> tuple[pd.DataFrame, list[str], str | None]:
    warnings: list[str] = []
    sheets = available_sheets if available_sheets is not None else _sheet_names(excel_path)
    if catalog is None:
        catalog, cat_warn = build_sheet_catalog(excel_path, sheets)
        warnings.extend(cat_warn)

    actual_sheet, resolve_warn = resolve_sheet_for_instrument(instrument, catalog)
    warnings.extend(resolve_warn)
    if actual_sheet is None:
        return (
            pd.DataFrame(columns=["date", "raw_value", "parse_failures"]),
            warnings,
            None,
        )

    try:
        df = pd.read_excel(
            excel_path,
            sheet_name=actual_sheet,
            header=2,
            engine="openpyxl",
        )
    except Exception as exc:
        msg = f"시트 읽기 실패: {actual_sheet} ({instrument.instrument_id}): {exc}"
        warnings.append(msg)
        logger.warning(msg)
        return (
            pd.DataFrame(columns=["date", "raw_value", "parse_failures"]),
            warnings,
            None,
        )

    df.columns = [str(c).strip() if c is not None else "" for c in df.columns]

    if "일자" not in df.columns:
        msg = f"열 '일자' 없음: {actual_sheet} ({instrument.instrument_id})"
        warnings.append(msg)
        logger.warning(msg)
        return (
            pd.DataFrame(columns=["date", "raw_value", "parse_failures"]),
            warnings,
            None,
        )

    if instrument.source_column not in df.columns:
        msg = (
            f"열 '{instrument.source_column}' 없음: "
            f"{actual_sheet} ({instrument.instrument_id})"
        )
        warnings.append(msg)
        logger.warning(msg)
        return (
            pd.DataFrame(columns=["date", "raw_value", "parse_failures"]),
            warnings,
            None,
        )

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
        return (
            pd.DataFrame(columns=["date", "raw_value", "parse_failures"]),
            warnings,
            actual_sheet,
        )

    out = out.sort_values("date")
    out = out.drop_duplicates(subset=["date"], keep="last")
    out["parse_failures"] = parse_failures
    out = out.reset_index(drop=True)
    return out, warnings, actual_sheet


def prepare_market_rows(
    cleaned: pd.DataFrame,
    instrument: Instrument,
    source_file: str,
    loaded_at: str,
    source_sheet: str | None = None,
) -> list[dict[str, Any]]:
    sheet = source_sheet if source_sheet is not None else instrument.sheet_name
    rows: list[dict[str, Any]] = []
    for _, r in cleaned.iterrows():
        rows.append(
            {
                "date": r["date"],
                "instrument_id": instrument.instrument_id,
                "raw_value": float(r["raw_value"]),
                "source_file": source_file,
                "source_sheet": sheet,
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

        catalog, cat_warn = build_sheet_catalog(excel_path, available)
        warnings.extend(cat_warn)

        instrument_rows = [
            instrument_to_row(inst, loaded_at) for inst in INSTRUMENTS
        ]
        upsert_instruments(instrument_rows, db)

        for inst in INSTRUMENTS:
            cleaned, w, actual_sheet = read_instrument_sheet(
                excel_path, inst, available, catalog=catalog
            )
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

            rows = prepare_market_rows(
                cleaned, inst, source_name, loaded_at, source_sheet=actual_sheet
            )
            all_rows.extend(rows)
            if inst.instrument_id == TARGET_ID:
                usdkrw_loaded = True
            logger.info(
                "Loaded %s: %d rows from [%s] (%s ~ %s)",
                inst.instrument_id,
                len(rows),
                actual_sheet,
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
