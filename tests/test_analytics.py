"""Tests for rolling correlation and driver analytics."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics import (
    DRIVER_MIXED,
    DRIVER_NONE,
    assign_daily_drivers,
    calculate_rolling_correlations,
    compress_driver_regimes,
    compute_driver_scores,
    min_periods_for_window,
)


def test_min_periods_20_is_16():
    assert min_periods_for_window(20) == 16
    assert min_periods_for_window(60) == 48
    assert min_periods_for_window(120) == 96


def _synth_corr_frame(n: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    target = rng.normal(0, 0.01, size=n)
    # Strong co-mover
    a = 0.9 * target + rng.normal(0, 0.001, size=n)
    # Independent
    b = rng.normal(0, 0.01, size=n)
    return pd.DataFrame({"USDKRW": target, "DXY": a, "VIX": b}, index=idx)


def test_rolling_corr_in_range_and_min_periods():
    df = _synth_corr_frame(50)
    out = calculate_rolling_correlations(df, drivers=["DXY", "VIX"], window=20)
    assert out["rolling_correlation"].dropna().between(-1, 1).all()
    # First valid correlations require at least 16 pairwise obs
    dxy = out[out["instrument_id"] == "DXY"].sort_values("date")
    first_valid = dxy[dxy["rolling_correlation"].notna()].iloc[0]
    assert first_valid["observation_count"] >= 16


def test_driver_top_winner():
    # Construct scored panel where DXY clearly wins
    dates = pd.date_range("2024-06-01", periods=5, freq="B")
    rows = []
    for d in dates:
        rows.append(
            {
                "date": d,
                "instrument_id": "DXY",
                "display_name": "DXY",
                "category": "외환 환율",
                "rolling_correlation": 0.8,
                "abs_correlation": 0.8,
                "observation_count": 20,
            }
        )
        rows.append(
            {
                "date": d,
                "instrument_id": "VIX",
                "display_name": "VIX",
                "category": "변동성 지표",
                "rolling_correlation": 0.1,
                "abs_correlation": 0.1,
                "observation_count": 20,
            }
        )
    scored = compute_driver_scores(pd.DataFrame(rows))
    daily = assign_daily_drivers(scored)
    assert daily.iloc[-1]["driver_id"] == "DXY"


def test_mixed_regime_when_gap_small():
    dates = pd.date_range("2024-06-01", periods=5, freq="B")
    rows = []
    for d in dates:
        rows.append(
            {
                "date": d,
                "instrument_id": "DXY",
                "display_name": "DXY",
                "category": "외환 환율",
                "rolling_correlation": 0.55,
                "abs_correlation": 0.55,
                "observation_count": 20,
            }
        )
        rows.append(
            {
                "date": d,
                "instrument_id": "USDCNH",
                "display_name": "USDCNH",
                "category": "외환 환율",
                "rolling_correlation": 0.52,
                "abs_correlation": 0.52,
                "observation_count": 20,
            }
        )
    scored = compute_driver_scores(pd.DataFrame(rows))
    daily = assign_daily_drivers(scored)
    assert daily.iloc[-1]["driver_id"] == DRIVER_MIXED


def test_none_when_score_below_threshold():
    dates = pd.date_range("2024-06-01", periods=5, freq="B")
    rows = []
    for d in dates:
        rows.append(
            {
                "date": d,
                "instrument_id": "DXY",
                "display_name": "DXY",
                "category": "외환 환율",
                "rolling_correlation": 0.2,
                "abs_correlation": 0.2,
                "observation_count": 20,
            }
        )
        rows.append(
            {
                "date": d,
                "instrument_id": "VIX",
                "display_name": "VIX",
                "category": "변동성 지표",
                "rolling_correlation": 0.1,
                "abs_correlation": 0.1,
                "observation_count": 20,
            }
        )
    scored = compute_driver_scores(pd.DataFrame(rows))
    daily = assign_daily_drivers(scored)
    assert daily.iloc[-1]["driver_id"] == DRIVER_NONE


def test_compress_regimes():
    dates = pd.date_range("2024-06-01", periods=6, freq="B")
    daily = pd.DataFrame(
        {
            "date": dates,
            "driver_id": ["DXY", "DXY", "VIX", "DXY", "DXY", "DXY"],
            "driver_name": ["DXY"] * 6,
            "category": ["외환 환율"] * 6,
            "signed_correlation": [0.5] * 6,
            "abs_correlation": [0.5] * 6,
            "driver_score": [0.5] * 6,
        }
    )
    # Single-day VIX between DXY runs should be absorbed back to DXY
    regimes = compress_driver_regimes(daily)
    assert len(regimes) == 1
    assert regimes.iloc[0]["driver_id"] == "DXY"
    assert int(regimes.iloc[0]["trading_days"]) == 6


def test_reproducible_correlations():
    df = _synth_corr_frame(60)
    a = calculate_rolling_correlations(df, drivers=["DXY"], window=20)
    b = calculate_rolling_correlations(df, drivers=["DXY"], window=20)
    pd.testing.assert_frame_equal(a, b)
