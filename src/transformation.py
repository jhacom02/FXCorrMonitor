"""Data transformation and market alignment for FXCorrMonitor."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from config.instruments import (
    INSTRUMENT_BY_ID,
    TARGET_ID,
    Instrument,
    get_active_instruments,
)
from src.utils import sanitize_series

logger = logging.getLogger(__name__)


def compute_log_return(values: pd.Series) -> pd.Series:
    """ln(v_t / v_{t-1}); no forward fill. Inf → NaN."""
    v = sanitize_series(values)
    ratio = v / v.shift(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.log(ratio)
    return sanitize_series(out)


def compute_diff_bp(values: pd.Series) -> pd.Series:
    """(y_t - y_{t-1}) * 100 in basis points. No forward fill."""
    v = sanitize_series(values)
    out = (v - v.shift(1)) * 100.0
    return sanitize_series(out)


def compute_level(values: pd.Series) -> pd.Series:
    """Keep signed flow levels as-is."""
    return sanitize_series(values)


def transform_series(values: pd.Series, transformation: str) -> pd.Series:
    if transformation == "log_return":
        return compute_log_return(values)
    if transformation == "diff_bp":
        return compute_diff_bp(values)
    if transformation == "level":
        return compute_level(values)
    raise ValueError(f"Unknown transformation: {transformation}")


def pivot_raw_market_data(market_df: pd.DataFrame) -> pd.DataFrame:
    if market_df.empty:
        return pd.DataFrame()
    df = market_df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    wide = (
        df.pivot_table(index="date", columns="instrument_id", values="raw_value", aggfunc="last")
        .sort_index()
    )
    return wide


def apply_as_of_cutoff(
    raw_wide: pd.DataFrame,
    as_of_date: pd.Timestamp | None = None,
    *,
    run_date: date | None = None,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    if raw_wide.empty:
        raise ValueError("원자료가 비어 있습니다.")
    if TARGET_ID not in raw_wide.columns:
        raise ValueError("USD/KRW 데이터가 없습니다.")

    usd = sanitize_series(raw_wide[TARGET_ID]).dropna()
    if usd.empty:
        raise ValueError("USD/KRW 유효 관측치가 없습니다.")

    if as_of_date is None:
        today = pd.Timestamp(run_date or date.today()).normalize()
        prior = usd.index[usd.index < today]
        if len(prior) == 0:
            raise ValueError("실행일 이전의 USD/KRW 확정 종가가 없습니다.")
        as_of = prior.max()
    else:
        as_of = pd.Timestamp(as_of_date).normalize()

    clipped = raw_wide.loc[raw_wide.index <= as_of].copy()
    return clipped, pd.Timestamp(as_of).normalize()


def _shift_previous_us_close_onto_seoul(
    series: pd.Series,
    seoul_dates: pd.DatetimeIndex,
) -> pd.Series:
    us = sanitize_series(series).dropna().sort_index()
    if us.empty:
        return pd.Series(index=seoul_dates, dtype=float)

    left = pd.DataFrame({"date": pd.DatetimeIndex(seoul_dates)}).sort_values("date")
    right = us.rename("value").rename_axis("date").reset_index().sort_values("date")
    merged = pd.merge_asof(
        left,
        right,
        on="date",
        direction="backward",
        allow_exact_matches=False,
    )
    out = pd.Series(
        merged["value"].values,
        index=pd.DatetimeIndex(merged["date"]),
        name=series.name,
    )
    return out


def align_transformed(
    raw_wide: pd.DataFrame,
    instruments: list[Instrument] | None = None,
    as_of_date: pd.Timestamp | None = None,
) -> dict[str, Any]:
    instruments = instruments or get_active_instruments()
    clipped, as_of = apply_as_of_cutoff(raw_wide, as_of_date)

    if TARGET_ID not in clipped.columns:
        raise ValueError("USD/KRW 데이터가 없습니다.")

    own_transformed: dict[str, pd.Series] = {}
    meta: dict[str, dict[str, Any]] = {}

    for inst in instruments:
        iid = inst.instrument_id
        if iid not in clipped.columns:
            meta[iid] = {
                "display_name": inst.display_name,
                "available": False,
                "obs_count": 0,
                "missing_rate": np.nan,
            }
            continue

        raw = sanitize_series(clipped[iid])
        native = raw.dropna()
        transformed_native = transform_series(native, inst.transformation)
        transformed_full = transformed_native.reindex(clipped.index)
        own_transformed[iid] = transformed_full

        total_days = len(clipped.index)
        obs = int(native.notna().sum())
        meta[iid] = {
            "display_name": inst.display_name,
            "available": True,
            "obs_count": obs,
            "missing_rate": 1.0 - (obs / total_days) if total_days else np.nan,
            "transformation": inst.transformation,
            "alignment": inst.alignment,
            "first_date": native.index.min().date().isoformat() if len(native) else None,
            "last_date": native.index.max().date().isoformat() if len(native) else None,
        }

    seoul_dates = clipped.index[clipped[TARGET_ID].notna()]
    if seoul_dates.empty:
        raise ValueError("USD/KRW 유효 거래일이 없습니다.")

    aligned: dict[str, pd.Series] = {}

    target_t = own_transformed[TARGET_ID].reindex(seoul_dates)
    aligned[TARGET_ID] = target_t

    for inst in instruments:
        iid = inst.instrument_id
        if iid == TARGET_ID:
            continue
        if iid not in own_transformed:
            continue

        series = own_transformed[iid]

        if inst.alignment == "previous_us_close":
            native_t = series.dropna()
            aligned[iid] = _shift_previous_us_close_onto_seoul(native_t, seoul_dates)
        else:
            aligned[iid] = series.reindex(seoul_dates)

    transformed_wide = pd.DataFrame(aligned).sort_index()
    raw_aligned: dict[str, pd.Series] = {}
    for inst in instruments:
        iid = inst.instrument_id
        if iid not in clipped.columns:
            continue
        raw = sanitize_series(clipped[iid])
        if inst.alignment == "same_day" or iid == TARGET_ID:
            raw_aligned[iid] = raw.reindex(seoul_dates)
        else:
            native_raw = raw.dropna()
            raw_aligned[iid] = _shift_previous_us_close_onto_seoul(native_raw, seoul_dates)
    raw_aligned_wide = pd.DataFrame(raw_aligned).sort_index()

    return {
        "raw_wide": clipped,
        "raw_aligned_wide": raw_aligned_wide,
        "transformed_wide": transformed_wide,
        "analysis_as_of_date": as_of.date().isoformat(),
        "meta": meta,
        "seoul_dates": seoul_dates,
    }


def build_analysis_frame(
    market_df: pd.DataFrame,
    include_inactive: bool = False,
    as_of_date: pd.Timestamp | None = None,
) -> dict[str, Any]:
    instruments = get_active_instruments(include_inactive=include_inactive)
    ids = {i.instrument_id for i in instruments}
    if TARGET_ID not in ids:
        instruments = [INSTRUMENT_BY_ID[TARGET_ID]] + instruments

    raw_wide = pivot_raw_market_data(market_df)
    return align_transformed(
        raw_wide,
        instruments=instruments,
        as_of_date=as_of_date,
    )
