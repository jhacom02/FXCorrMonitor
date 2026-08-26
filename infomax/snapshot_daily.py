"""Infomax IMDP Snapshot daily ETL: B1 → refresh → read 16 cells → UPSERT."""

from __future__ import annotations

import logging
import math
import os
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from config.instruments import INSTRUMENT_BY_ID, INSTRUMENTS, instrument_to_row
from src.database import (
    finish_ingestion_log,
    init_db,
    start_ingestion_log,
    upsert_instruments,
    upsert_market_data,
)
from src.utils import ensure_parent_dir, resolve_path, utc_now_iso

logger = logging.getLogger(__name__)

MAPPING: list[tuple[str, str]] = [
    ("D3", "USDKRW"),
    ("E4", "DXY"),
    ("E5", "USDJPY"),
    ("E6", "USDCNH"),
    ("E7", "EURUSD"),
    ("D8", "KOSPI"),
    ("F8", "F_NET"),
    ("D9", "SPX"),
    ("D10", "NDX"),
    ("D11", "VIX"),
    ("D12", "WTI"),
    ("D13", "GOLD"),
    ("G14", "UST2Y"),
    ("G15", "UST10Y"),
    ("H16", "KTB3Y"),
    ("H17", "KTB10Y"),
]
DEFAULT_EXCEL = "data/raw/infomax_raw_snapshot.xlsx"
SHEET, DATE_CELL = "Sheet1", "B1"
USDKRW_CELL, USDKRW_FALLBACK_CELL = "D3", "E3"
USDKRW_FALLBACK_FORMULA = "=_xll.IMDP($B3,$C3,E$2,$B$1)"
LOOKBACK_DAYS, REFRESH_TIMEOUT, POLL_INTERVAL = 7, 30.0, 0.5
USDKRW_FALLBACK_WAIT = 15.0
XL_DONE, XL_AUTO = 0, -4105
ADDIN_RELOAD_PAUSE = 1.0
_INFOMAX_ADDIN_KEYWORDS = ("infomax", "인포맥스")
_EXCEL_CVERR_MIN = -2146826300
_EXCEL_CVERR_MAX = -2146826200


def lookback_dates(n: int = LOOKBACK_DAYS, *, today: date | None = None) -> list[date]:
    anchor = today or date.today()
    end = date.fromordinal(anchor.toordinal() - 1)
    return [date.fromordinal(end.toordinal() - (n - 1 - i)) for i in range(n)]


def _read_cell(ws: Any, cell: str) -> Any:
    rng = ws.Range(cell)
    for attr in ("Value2", "Value"):
        try:
            raw = getattr(rng, attr)
            if parse_number(raw) is not None:
                return raw
        except Exception:
            pass
    try:
        text = rng.Text
        if parse_number(text) is not None:
            return text
    except Exception:
        pass
    try:
        return rng.Value
    except Exception:
        return None


def parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        if not math.isfinite(num):
            return None
        if _EXCEL_CVERR_MIN <= num <= _EXCEL_CVERR_MAX:
            return None
        return num
    text = str(value).strip()
    if not text or text == "-" or any(
        t in text.upper() for t in ("#N/A", "#VALUE", "#REF", "#NAME", "#BUSY", "#GETTING", "#DIV")
    ):
        return None
    try:
        num = float(text.replace(",", ""))
    except ValueError:
        return None
    return num if math.isfinite(num) else None


def cells_to_rows(
    values: dict[str, Any], query_date: date, *, source_file: str, loaded_at: str
) -> tuple[list[dict[str, Any]], list[str]]:
    rows, skips = [], []
    obs = query_date.isoformat()
    for cell, asset in MAPPING:
        if asset not in INSTRUMENT_BY_ID:
            skips.append(f"{asset}: unknown")
            continue
        num = parse_number(values.get(cell))
        if num is None:
            skips.append(f"{asset}@{cell}: {values.get(cell)!r}")
            continue
        inst = INSTRUMENT_BY_ID[asset]
        rows.append(
            {
                "date": obs,
                "instrument_id": asset,
                "raw_value": float(num),
                "source_file": source_file,
                "source_sheet": SHEET,
                "source_column": inst.source_column,
                "loaded_at": loaded_at,
            }
        )
    return rows, skips


def _lock(path: Path):
    ensure_parent_dir(path)
    fh = open(path, "a+", encoding="utf-8")
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def _unlock(fh) -> None:
    if not fh:
        return
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    fh.close()


acquire_lock = _lock
release_lock = _unlock


def _is_infomax_addin(addin: Any) -> bool:
    try:
        label = f"{addin.Name} {addin.FullName}".lower()
        return any(keyword in label for keyword in _INFOMAX_ADDIN_KEYWORDS)
    except Exception:
        return False


def _enable_infomax_addins(app: Any) -> None:
    try:
        for index in range(1, app.AddIns.Count + 1):
            addin = app.AddIns.Item(index)
            if _is_infomax_addin(addin) and not addin.Installed:
                addin.Installed = True
                logger.info("Infomax add-in enabled: %s", addin.Name)
    except Exception as exc:
        logger.warning("Infomax add-in enable failed (continue): %s", exc)


def _reload_installed_addins(app: Any) -> None:
    reloaded = 0
    try:
        for index in range(1, app.AddIns.Count + 1):
            addin = app.AddIns.Item(index)
            if not addin.Installed:
                continue
            addin.Installed = False
            addin.Installed = True
            reloaded += 1
            logger.info("Add-in reloaded: %s", addin.Name)
    except Exception as exc:
        logger.warning("Add-in reload failed (continue): %s", exc)
        return
    if reloaded:
        logger.info("Add-in reload done (%d)", reloaded)
        time.sleep(ADDIN_RELOAD_PAUSE)
    else:
        logger.warning("No installed add-ins to reload")


def _wait_for_data_refresh(app: Any, wait_seconds: float) -> None:
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    while time.monotonic() < deadline:
        try:
            if int(app.CalculationState) == XL_DONE:
                break
        except Exception:
            break
        time.sleep(POLL_INTERVAL)
    try:
        app.CalculateUntilAsyncQueriesDone()
    except Exception:
        pass
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def _ensure_usdkrw_mid_formula(ws: Any) -> None:
    try:
        rng = ws.Range(USDKRW_FALLBACK_CELL)
        formula = str(rng.Formula or "").strip()
        if formula != USDKRW_FALLBACK_FORMULA:
            rng.Formula = USDKRW_FALLBACK_FORMULA
    except Exception:
        pass


def _refresh(excel, wb, ws, query_date: date) -> None:
    ws.Range(DATE_CELL).Value = datetime(query_date.year, query_date.month, query_date.day)
    _ensure_usdkrw_mid_formula(ws)
    try:
        excel.Calculation = XL_AUTO
    except Exception:
        pass

    _enable_infomax_addins(excel)
    _reload_installed_addins(excel)

    try:
        wb.RefreshAll()
        logger.info("RefreshAll")
    except Exception as exc:
        logger.warning("RefreshAll failed (continue): %s", exc)

    try:
        excel.CalculateFull()
        logger.info("CalculateFull")
    except Exception:
        try:
            excel.CalculateFullRebuild()
            logger.info("CalculateFullRebuild")
        except Exception as exc:
            logger.warning("Full calculate failed (continue): %s", exc)

    _wait_for_data_refresh(excel, min(5.0, REFRESH_TIMEOUT))


def _cell_busy(value: Any) -> bool:
    return isinstance(value, str) and (
        "BUSY" in value.upper() or "GETTING" in value.upper()
    )


def select_usdkrw_raw(primary: Any, fallback: Any) -> Any:
    if parse_number(fallback) is not None:
        return fallback
    if parse_number(primary) is not None:
        return primary
    return primary


def _fetch_usdkrw(ws: Any, excel: Any) -> Any:
    primary = _read_cell(ws, USDKRW_CELL)
    fallback = _read_cell(ws, USDKRW_FALLBACK_CELL)
    chosen = select_usdkrw_raw(primary, fallback)
    if parse_number(chosen) is not None:
        logger.info("USDKRW via %s: %r", USDKRW_FALLBACK_CELL if parse_number(fallback) is not None else USDKRW_CELL, chosen)
        return chosen

    logger.warning("USDKRW@%s empty; trying KR_MID_Close via %s", USDKRW_CELL, USDKRW_FALLBACK_CELL)
    fallback_rng = ws.Range(USDKRW_FALLBACK_CELL)
    try:
        fallback_rng.Formula = USDKRW_FALLBACK_FORMULA
        try:
            excel.ActiveWorkbook.RefreshAll()
        except Exception:
            pass
        try:
            excel.CalculateFull()
        except Exception:
            pass
        _wait_for_data_refresh(excel, USDKRW_FALLBACK_WAIT)
        deadline = time.monotonic() + USDKRW_FALLBACK_WAIT
        while time.monotonic() < deadline:
            value = _read_cell(ws, USDKRW_FALLBACK_CELL)
            if parse_number(value) is not None:
                logger.info("USDKRW via %s: %r", USDKRW_FALLBACK_CELL, value)
                return value
            time.sleep(POLL_INTERVAL)
    except Exception:
        pass

    chosen = select_usdkrw_raw(
        _read_cell(ws, USDKRW_CELL), _read_cell(ws, USDKRW_FALLBACK_CELL)
    )
    if parse_number(chosen) is not None:
        logger.info("USDKRW via %s: %r", USDKRW_CELL, chosen)
    return chosen


def _wait_ready(excel, ws) -> bool:
    cells = [c for c, _ in MAPPING]
    deadline = time.monotonic() + REFRESH_TIMEOUT
    while time.monotonic() < deadline:
        try:
            state = int(excel.CalculationState)
        except Exception:
            state = XL_DONE
        if state == XL_DONE:
            vals = [_read_cell(ws, c) for c in cells]
            if any(parse_number(v) is not None for v in vals) and not any(
                _cell_busy(v) for v in vals if v is not None
            ):
                return True
        time.sleep(POLL_INTERVAL)
    return False


@contextmanager
def _excel_book(path: Path, visible: bool) -> Iterator[tuple[Any, Any, Any]]:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    excel = wb = None
    try:
        try:
            excel = win32com.client.DispatchEx("Excel.Application")
        except Exception:
            excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = visible
        excel.DisplayAlerts = False
        excel.EnableEvents = True
        _enable_infomax_addins(excel)
        _reload_installed_addins(excel)
        wb = excel.Workbooks.Open(str(path.resolve()))
        yield excel, wb, wb.Worksheets(SHEET)
    finally:
        try:
            if wb is not None:
                wb.Close(SaveChanges=False)
        except Exception:
            pass
        try:
            if excel is not None:
                excel.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def _fetch_day(excel, wb, ws, qd: date) -> dict[str, Any]:
    _refresh(excel, wb, ws, qd)
    if not _wait_ready(excel, ws):
        logger.warning("Timeout; retry %s", qd)
        _refresh(excel, wb, ws, qd)
        _wait_ready(excel, ws)
    values = {cell: _read_cell(ws, cell) for cell, _ in MAPPING}
    values[USDKRW_CELL] = _fetch_usdkrw(ws, excel)
    return values


def run_etl(
    *,
    dates: list[date],
    excel_path: Path,
    db_path: Path,
    dry_run: bool = False,
    visible: bool = False,
) -> int:
    if not excel_path.exists():
        logger.error("Excel missing: %s", excel_path)
        return 1

    dates = [d for d in dates if d.weekday() < 5]
    if not dates:
        logger.error("No weekday dates to process")
        return 1

    ingestion_id = None
    if not dry_run:
        init_db(db_path, replace=False)
        ts = utc_now_iso()
        upsert_instruments([instrument_to_row(i, ts) for i in INSTRUMENTS], db_path)
        ingestion_id = start_ingestion_log(str(excel_path), db_path)

    ok_days = inserted_sum = updated_sum = total = 0
    try:
        with _excel_book(excel_path, visible) as (excel, wb, ws):
            logger.info("Excel opened: %s", excel_path)
            for qd in dates:
                logger.info("Query date=%s", qd.isoformat())
                try:
                    values = _fetch_day(excel, wb, ws, qd)
                    rows, skips = cells_to_rows(
                        values, qd, source_file=str(excel_path), loaded_at=utc_now_iso()
                    )
                    for s in skips:
                        logger.info("skip: %s", s)
                    logger.info("%s: %d/%d loaded", qd.isoformat(), len(rows), len(MAPPING))
                    if not rows:
                        continue
                    if not any(r["instrument_id"] == "USDKRW" for r in rows):
                        logger.error("%s: USDKRW missing — day skipped", qd.isoformat())
                        continue
                    if dry_run:
                        for r in rows:
                            logger.info(
                                "dry-run %s %s=%s",
                                r["date"],
                                r["instrument_id"],
                                r["raw_value"],
                            )
                    else:
                        ins, upd = upsert_market_data(rows, db_path)
                        inserted_sum += ins
                        updated_sum += upd
                        total += ins + upd
                        logger.info("upserted inserted=%d updated=%d", ins, upd)
                    ok_days += 1
                except Exception as exc:
                    logger.exception("Day %s failed: %s", qd.isoformat(), exc)
    except ImportError:
        logger.error("pywin32 required: pip install pywin32")
        return 1
    finally:
        logger.info("Excel closed")

    if ingestion_id is not None:
        finish_ingestion_log(
            ingestion_id,
            status="success" if ok_days else "error",
            inserted_rows=inserted_sum,
            updated_rows=updated_sum,
            error_message=None if ok_days else "no successful days",
            db_path=db_path,
        )
    logger.info("Done upserted=%d days_ok=%d/%d", total, ok_days, len(dates))
    return 1 if ok_days == 0 else (2 if ok_days < len(dates) else 0)


def run_poc(excel_path: Path, date_a: date, date_b: date, *, visible: bool = True) -> int:
    sample = ["D3", "E4", "D8", "F8", "G14", "H16"]
    try:
        with _excel_book(excel_path, visible) as (excel, wb, ws):
            snaps = {}
            for qd in (date_a, date_b):
                _fetch_day(excel, wb, ws, qd)
                snaps[qd] = {c: _read_cell(ws, c) for c in sample}
                snaps[qd][USDKRW_CELL] = _fetch_usdkrw(ws, excel)
                print(f"\n=== {qd.isoformat()} ===")
                for c, v in snaps[qd].items():
                    print(f"  {c}: {v!r}")
            changed = any(snaps[date_a].get(c) != snaps[date_b].get(c) for c in sample)
            print(
                "\nOK: values changed."
                if changed
                else "\nWARN: no change — may need Infomax Refresh UI in _refresh()."
            )
            return 0 if changed else 2
    except ImportError:
        print("pywin32 required", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    from src.utils import DEFAULT_DB_PATH, PROJECT_ROOT, setup_logging

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    p = argparse.ArgumentParser(description="Infomax IMDP daily snapshot ETL")
    p.add_argument("--date")
    p.add_argument("--lookback", type=int, default=None)
    p.add_argument("--excel", default=None)
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--dry-run", "--no-db", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--visible", action="store_true")
    p.add_argument("--skip-lock", action="store_true")
    p.add_argument("--poc", action="store_true")
    p.add_argument("--date-a", default="2026-08-07")
    p.add_argument("--date-b", default="2026-08-06")
    args = p.parse_args(argv)

    setup_logging(args.verbose)
    log_dir = resolve_path(os.environ.get("INFOMAX_LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(
        log_dir / f"infomax_daily_{datetime.now():%Y%m%d}.log", encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)

    excel_path = resolve_path(args.excel or os.environ.get("INFOMAX_EXCEL_PATH", DEFAULT_EXCEL))
    if args.poc:
        return run_poc(
            excel_path,
            date.fromisoformat(args.date_a),
            date.fromisoformat(args.date_b),
            visible=True,
        )

    lock_fh = None
    if not args.skip_lock:
        lock_fh = acquire_lock(
            resolve_path(os.environ.get("INFOMAX_LOCK_PATH", "data/.infomax_daily.lock"))
        )
        if lock_fh is None:
            logger.error("ETL already running")
            return 1
    try:
        if args.date:
            dates = [date.fromisoformat(args.date)]
        else:
            n = args.lookback
            if n is None:
                n = int(os.environ.get("INFOMAX_LOOKBACK_DAYS", LOOKBACK_DAYS))
            dates = lookback_dates(n)
        visible = args.visible or os.environ.get("INFOMAX_EXCEL_VISIBLE", "").lower() in {
            "1",
            "true",
            "yes",
        }
        return run_etl(
            dates=dates,
            excel_path=excel_path,
            db_path=resolve_path(args.db),
            dry_run=args.dry_run,
            visible=visible,
        )
    finally:
        release_lock(lock_fh)


if __name__ == "__main__":
    raise SystemExit(main())
