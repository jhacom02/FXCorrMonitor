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

from config.thresholds import sig_abs
from src.analytics import (
    DRIVER_MIXED,
    DRIVER_NONE,
    DRIVER_NONE_NAME,
    assign_daily_drivers,
    calculate_rolling_correlations,
    compress_driver_regimes,
    latest_top_driver,
    min_periods_for_window,
    regime_label_on_date,
)


def test_min_periods_20_is_16():
    assert min_periods_for_window(20) == 16
    assert min_periods_for_window(60) == 48
    assert min_periods_for_window(120) == 96


def _synth_corr_frame(n: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    target = rng.normal(0, 0.01, size=n)
    a = 0.9 * target + rng.normal(0, 0.001, size=n)
    b = rng.normal(0, 0.01, size=n)
    return pd.DataFrame({"USDKRW": target, "DXY": a, "VIX": b}, index=idx)


def test_rolling_corr_in_range_and_min_periods():
    df = _synth_corr_frame(50)
    out = calculate_rolling_correlations(df, drivers=["DXY", "VIX"], window=20)
    assert out["rolling_correlation"].dropna().between(-1, 1).all()
    dxy = out[out["instrument_id"] == "DXY"].sort_values("date")
    first_valid = dxy[dxy["rolling_correlation"].notna()].iloc[0]
    assert first_valid["observation_count"] >= 16


def test_driver_top_winner():
    dates = pd.date_range("2024-06-01", periods=5, freq="B")
    rows = []
    for d in dates:
        rows.append(
            {
                "date": d,
                "instrument_id": "DXY",
                "display_name": "DXY",
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
                "rolling_correlation": 0.1,
                "abs_correlation": 0.1,
                "observation_count": 20,
            }
        )
    daily = assign_daily_drivers(pd.DataFrame(rows), min_score=sig_abs(20))
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
                "rolling_correlation": 0.52,
                "abs_correlation": 0.52,
                "observation_count": 20,
            }
        )
    daily = assign_daily_drivers(pd.DataFrame(rows), min_score=sig_abs(20))
    assert daily.iloc[-1]["driver_id"] == DRIVER_MIXED
    assert daily.iloc[-1]["driver_name"] == "혼합(DXY, USDCNH)"
    assert abs(float(daily.iloc[-1]["mix_abs_1"]) - 0.55) < 1e-9
    assert abs(float(daily.iloc[-1]["mix_abs_2"]) - 0.52) < 1e-9
    assert abs(float(daily.iloc[-1]["mix_signed_1"]) - 0.55) < 1e-9
    assert abs(float(daily.iloc[-1]["mix_signed_2"]) - 0.52) < 1e-9

    regimes = compress_driver_regimes(daily)
    assert len(regimes) == 1
    assert regimes.iloc[0]["driver_id"] == DRIVER_MIXED
    assert abs(float(regimes.iloc[0]["mix_avg_abs_1"]) - 0.55) < 1e-9
    assert abs(float(regimes.iloc[0]["mix_avg_abs_2"]) - 0.52) < 1e-9
    assert abs(float(regimes.iloc[0]["mix_avg_signed_1"]) - 0.55) < 1e-9
    as_of = dates[-1]
    assert regime_label_on_date(regimes, as_of) == "혼합(DXY, USDCNH)"


def test_none_when_abs_below_threshold():
    dates = pd.date_range("2024-06-01", periods=5, freq="B")
    rows = []
    for d in dates:
        rows.append(
            {
                "date": d,
                "instrument_id": "DXY",
                "display_name": "DXY",
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
                "rolling_correlation": 0.1,
                "abs_correlation": 0.1,
                "observation_count": 20,
            }
        )
    daily = assign_daily_drivers(pd.DataFrame(rows), min_score=sig_abs(20))
    assert daily.iloc[-1]["driver_id"] == DRIVER_NONE
    assert daily.iloc[-1]["driver_name"] == DRIVER_NONE_NAME


def test_latest_top_driver_no_mixed():
    dates = pd.date_range("2024-06-01", periods=2, freq="B")
    rows = []
    for d in dates:
        rows.append(
            {
                "date": d,
                "instrument_id": "DXY",
                "display_name": "DXY",
                "rolling_correlation": 0.55,
                "abs_correlation": 0.55,
            }
        )
        rows.append(
            {
                "date": d,
                "instrument_id": "USDCNH",
                "display_name": "USDCNH",
                "rolling_correlation": 0.52,
                "abs_correlation": 0.52,
            }
        )
    top = latest_top_driver(pd.DataFrame(rows), sig_abs(20))
    assert top["driver_id"] == "DXY"
    assert top["driver_name"] == "DXY"
    assert abs(top["signed_correlation"] - 0.55) < 1e-9

    low = latest_top_driver(pd.DataFrame(rows), 0.60)
    assert low["driver_id"] == DRIVER_NONE


def test_compress_regimes():
    dates = pd.date_range("2024-06-01", periods=6, freq="B")
    daily = pd.DataFrame(
        {
            "date": dates,
            "driver_id": ["DXY", "DXY", "VIX", "DXY", "DXY", "DXY"],
            "driver_name": ["DXY"] * 6,
            "signed_correlation": [0.5] * 6,
            "abs_correlation": [0.5] * 6,
        }
    )
    regimes = compress_driver_regimes(daily)
    assert len(regimes) == 1
    assert regimes.iloc[0]["driver_id"] == "DXY"
    assert int(regimes.iloc[0]["trading_days"]) == 6


def test_compress_absorbs_one_day_into_prev_not_mixed():
    dates = pd.date_range("2024-06-01", periods=5, freq="B")
    daily = pd.DataFrame(
        {
            "date": dates,
            "driver_id": ["DXY", "DXY", "VIX", "USDCNH", "USDCNH"],
            "driver_name": ["DXY", "DXY", "VIX", "USDCNH", "USDCNH"],
            "signed_correlation": [0.5] * 5,
            "abs_correlation": [0.5] * 5,
        }
    )
    regimes = compress_driver_regimes(daily)
    assert DRIVER_MIXED not in set(regimes["driver_id"])
    by_id = {r["driver_id"]: int(r["trading_days"]) for _, r in regimes.iterrows()}
    assert by_id == {"DXY": 3, "USDCNH": 2}


def test_compress_absorbs_leading_one_day_into_next():
    dates = pd.date_range("2024-06-01", periods=3, freq="B")
    daily = pd.DataFrame(
        {
            "date": dates,
            "driver_id": ["VIX", "DXY", "DXY"],
            "driver_name": ["VIX", "DXY", "DXY"],
            "signed_correlation": [0.4, 0.5, 0.5],
            "abs_correlation": [0.4, 0.5, 0.5],
        }
    )
    regimes = compress_driver_regimes(daily)
    assert len(regimes) == 1
    assert regimes.iloc[0]["driver_id"] == "DXY"
    assert int(regimes.iloc[0]["trading_days"]) == 3


def test_reproducible_correlations():
    df = _synth_corr_frame(60)
    a = calculate_rolling_correlations(df, drivers=["DXY"], window=20)
    b = calculate_rolling_correlations(df, drivers=["DXY"], window=20)
    pd.testing.assert_frame_equal(a, b)


def test_lookback_range_1y():
    from src.utils import lookback_range

    start, end = lookback_range("2024-06-15", "1Y")
    assert end == pd.Timestamp("2024-06-15")
    assert start == pd.Timestamp("2023-06-15")


def test_lookback_range_1m():
    from src.utils import lookback_range

    start, end = lookback_range("2024-03-31", "1M")
    assert end == pd.Timestamp("2024-03-31")
    assert start == pd.Timestamp("2024-02-29")


def test_regimes_for_window_smoke():
    from src.analytics import regimes_for_window

    df = _synth_corr_frame(80)
    regimes = regimes_for_window(df, ["DXY", "VIX"], window=20)
    assert "average_signed_correlation" in regimes.columns
    assert "min_signed_correlation" in regimes.columns


def test_classify_driver_status_cases():
    from src.analytics import classify_driver_status

    assert classify_driver_status(0.2, 0.1, 0.1) == "—"
    assert classify_driver_status(0.5, 0.1, 0.1) == "신규"
    assert classify_driver_status(0.5, -0.4, 0.3) == "전환"
    assert classify_driver_status(0.5, 0.45, -0.4) == "전환"
    assert classify_driver_status(0.6, 0.4, 0.35) == "강화"
    assert classify_driver_status(0.5, 0.65, 0.55) == "약화"
    assert classify_driver_status(0.5, 0.48, 0.45) == "지속"
    assert classify_driver_status(0.5, -0.1, 0.0) == "신규"
    assert classify_driver_status(0.55, -0.35, 0.2) == "전환"


def test_regime_label_on_date_none_is_dash():
    dates = pd.date_range("2024-06-01", periods=3, freq="B")
    daily = pd.DataFrame(
        {
            "date": dates,
            "driver_id": [DRIVER_NONE] * 3,
            "driver_name": [DRIVER_NONE_NAME] * 3,
            "signed_correlation": [np.nan] * 3,
            "abs_correlation": [np.nan] * 3,
        }
    )
    regimes = compress_driver_regimes(daily)
    assert regime_label_on_date(regimes, dates[-1]) == "—"


def test_sig_abs_and_display_floor():
    from config.thresholds import DISPLAY_MIN_ABS_DEFAULT, display_floor, sig_abs

    assert sig_abs(20) == 0.44
    assert sig_abs(60) == 0.25
    assert sig_abs(120) == 0.18
    assert display_floor(20, DISPLAY_MIN_ABS_DEFAULT) == sig_abs(20)
    assert display_floor(60, DISPLAY_MIN_ABS_DEFAULT) == DISPLAY_MIN_ABS_DEFAULT
    assert display_floor(120, 0.10) == sig_abs(120)


def test_robust_z_excludes_current_and_needs_252():
    from config.thresholds import MAD_NORMAL_SCALE, ROBUST_Z_WINDOW
    from src.analytics import _robust_z_series

    n = ROBUST_Z_WINDOW + 5
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    base = np.full(n, 0.001)
    # mild dispersion so MAD > 0
    base[::2] = -0.001
    s = pd.Series(base, index=idx)
    s.iloc[-1] = 0.10

    z = _robust_z_series(s)
    assert z.iloc[:ROBUST_Z_WINDOW].isna().all()

    prior = s.iloc[-(ROBUST_Z_WINDOW + 1) : -1].to_numpy()
    med = float(np.median(prior))
    mad = float(np.median(np.abs(prior - med)))
    expected = (float(s.iloc[-1]) - med) / (MAD_NORMAL_SCALE * mad)
    assert z.iloc[-1] == pytest.approx(expected)

    # Changing x_t must not change median/MAD used for that day
    s2 = s.copy()
    s2.iloc[-1] = 0.20
    z2 = _robust_z_series(s2)
    expected2 = (0.20 - med) / (MAD_NORMAL_SCALE * mad)
    assert z2.iloc[-1] == pytest.approx(expected2)


def test_detect_historical_shocks_dual_gate_and_display_filter():
    from config.thresholds import ROBUST_Z_WINDOW, SHOCK_ABS_FLOOR
    from src.analytics import detect_historical_shocks

    n = ROBUST_Z_WINDOW + 10
    idx = pd.date_range("2015-01-01", periods=n, freq="B")

    # Low-vol history: MAD small → modest moves get large z
    low_vol = np.full(n, 0.001)
    low_vol[::2] = -0.001
    dxy_low = low_vol.copy()
    dxy_low[-3] = 0.08  # z high + above floor → shock
    dxy_low[-2] = 0.015  # z high but below floor 0.02 → not shock

    # High-vol history: MAD large → 0.05 clears floor but z < 4
    high_vol = np.full(n, 0.02)
    high_vol[::2] = -0.02
    dxy_high = high_vol.copy()
    dxy_high[-1] = 0.05  # above floor, z too small

    hits_low = detect_historical_shocks(pd.DataFrame({"DXY": dxy_low}, index=idx))
    dates_low = set(hits_low["date"]) if not hits_low.empty else set()
    assert idx[-3].date().isoformat() in dates_low
    assert idx[-2].date().isoformat() not in dates_low

    hits_high = detect_historical_shocks(pd.DataFrame({"DXY": dxy_high}, index=idx))
    dates_high = set(hits_high["date"]) if not hits_high.empty else set()
    assert idx[-1].date().isoformat() not in dates_high

    # F_NET has no floor → never included
    mixed = detect_historical_shocks(
        pd.DataFrame({"DXY": dxy_low, "F_NET": low_vol}, index=idx)
    )
    assert "F_NET" not in set(mixed["instrument_id"])

    filtered = detect_historical_shocks(
        pd.DataFrame({"DXY": dxy_low}, index=idx),
        display_start=idx[-5],
        display_end=idx[-1],
    )
    assert idx[-3].date().isoformat() in set(filtered["date"])
    early_only = detect_historical_shocks(
        pd.DataFrame({"DXY": dxy_low}, index=idx),
        display_start=idx[-2],
        display_end=idx[-1],
    )
    early_dates = set(early_only["date"]) if not early_only.empty else set()
    assert idx[-3].date().isoformat() not in early_dates
    assert SHOCK_ABS_FLOOR["DXY"] == 0.02
