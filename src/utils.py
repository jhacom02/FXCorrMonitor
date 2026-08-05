"""Shared utilities for FXCorrMonitor."""

from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from pandas.errors import OutOfBoundsDatetime
except ImportError:
    OutOfBoundsDatetime = ValueError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "fx_dashboard.db"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        try:
            return value.date()
        except (ValueError, NotImplementedError, OverflowError):
            return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return None
        as_int = int(num)
        if as_int == num and 19000101 <= as_int <= 21001231:
            s = f"{as_int:08d}"
            try:
                return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
            except ValueError:
                pass
        try:
            ts = pd.to_datetime(num, unit="D", origin="1899-12-30")
            if pd.isna(ts):
                return None
            return ts.date()
        except (ValueError, OutOfBoundsDatetime, OverflowError, NotImplementedError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return None
        if text.isdigit() and len(text) == 8:
            packed = normalize_date(int(text))
            if packed is not None:
                return packed
        try:
            ts = pd.to_datetime(text)
            if pd.isna(ts):
                return None
            return ts.date()
        except (ValueError, TypeError, OutOfBoundsDatetime, NotImplementedError):
            return None
    return None


def date_to_iso(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        d = normalize_date(value)
        return d.isoformat() if d else None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    d = normalize_date(value)
    return d.isoformat() if d else None


def parse_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or text in {"-", "—", "N/A", "n/a"}:
            return None
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        try:
            num = float(text)
        except ValueError:
            cleaned = re.sub(r"[^\d.\-eE+]", "", text)
            if not cleaned or cleaned in {"-", ".", "-."}:
                return None
            try:
                num = float(cleaned)
            except ValueError:
                return None
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    return None


def sanitize_series(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan)
    return out


def format_fx(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value:,.2f}"


def format_yield(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value:.3f}"


def format_corr(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value:.2f}"


def format_pct(value: float | None, decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value * 100:.{decimals}f}%"


def format_bp(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value:.1f} bp"


def utc_now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def db_mtime_key(db_path: Path) -> float:
    if not db_path.exists():
        return 0.0
    return db_path.stat().st_mtime


LOOKBACK_PERIODS = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y"]
DEFAULT_LOOKBACK_PERIOD = "1Y"

_LOOKBACK_OFFSETS: dict[str, pd.DateOffset] = {
    "1M": pd.DateOffset(months=1),
    "3M": pd.DateOffset(months=3),
    "6M": pd.DateOffset(months=6),
    "1Y": pd.DateOffset(years=1),
    "2Y": pd.DateOffset(years=2),
    "3Y": pd.DateOffset(years=3),
    "5Y": pd.DateOffset(years=5),
    "10Y": pd.DateOffset(years=10),
}


def lookback_range(
    as_of: date | datetime | pd.Timestamp,
    period_key: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    end = pd.Timestamp(as_of).normalize()
    offset = _LOOKBACK_OFFSETS.get(period_key)
    if offset is None:
        offset = _LOOKBACK_OFFSETS[DEFAULT_LOOKBACK_PERIOD]
    start = (end - offset).normalize()
    return start, end


def format_lookback_period(
    period_key: str,
    as_of: date | datetime | pd.Timestamp | str | None,
) -> str:
    if as_of is None or (isinstance(as_of, float) and pd.isna(as_of)) or as_of == "":
        return period_key
    start, end = lookback_range(as_of, period_key)
    return f"{period_key} ({start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')})"
