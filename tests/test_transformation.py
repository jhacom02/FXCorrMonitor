"""Tests for transformation and alignment."""

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

from config.instruments import INSTRUMENT_BY_ID, TARGET_ID
from src.transformation import (
    align_transformed,
    apply_as_of_cutoff,
    compute_diff_bp,
    compute_level,
    compute_log_return,
    pivot_raw_market_data,
)


def test_log_return():
    s = pd.Series([100.0, 110.0, 99.0])
    r = compute_log_return(s)
    assert pd.isna(r.iloc[0])
    assert abs(r.iloc[1] - math.log(110 / 100)) < 1e-12
    assert abs(r.iloc[2] - math.log(99 / 110)) < 1e-12


def test_diff_bp():
    s = pd.Series([1.569, 1.529])
    d = compute_diff_bp(s)
    assert pd.isna(d.iloc[0])
    assert abs(d.iloc[1] - (-4.0)) < 1e-9


def test_flow_level_preserved():
    s = pd.Series([-100.0, 50.0, 0.0])
    out = compute_level(s)
    assert list(out.values) == [-100.0, 50.0, 0.0]


def test_no_forward_fill_on_missing():
    s = pd.Series([100.0, np.nan, 110.0])
    r = compute_log_return(s)
    # Middle stays NaN; third return uses 110/NaN → NaN (no ffill from 100)
    assert pd.isna(r.iloc[1])
    assert pd.isna(r.iloc[2])


def test_as_of_cutoff_excludes_future():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    wide = pd.DataFrame(
        {
            TARGET_ID: [1300.0, 1301.0, 1302.0],
            "DXY": [100.0, 101.0, 102.0],
        },
        index=idx,
    )
    clipped, as_of = apply_as_of_cutoff(wide, as_of_date=pd.Timestamp("2024-01-03"))
    assert as_of == pd.Timestamp("2024-01-03")
    assert clipped.index.max() == pd.Timestamp("2024-01-03")
    assert len(clipped) == 2


def test_as_of_cutoff_defaults_to_prior_session():
    """Same-day Infomax open/intraday must not become analysis_as_of."""
    from datetime import date as date_cls

    idx = pd.to_datetime(["2026-07-30", "2026-07-31", "2026-08-03"])
    wide = pd.DataFrame(
        {
            TARGET_ID: [1418.0, 1435.5, 1429.7],
            "DXY": [100.0, 101.0, 102.0],
        },
        index=idx,
    )
    clipped, as_of = apply_as_of_cutoff(wide, run_date=date_cls(2026, 8, 3))
    assert as_of == pd.Timestamp("2026-07-31")
    assert clipped.index.max() == pd.Timestamp("2026-07-31")
    assert pd.Timestamp("2026-08-03") not in clipped.index


def test_as_of_cutoff_errors_without_prior_session():
    from datetime import date as date_cls

    idx = pd.to_datetime(["2026-08-03"])
    wide = pd.DataFrame({TARGET_ID: [1429.7]}, index=idx)
    with pytest.raises(ValueError, match="실행일 이전"):
        apply_as_of_cutoff(wide, run_date=date_cls(2026, 8, 3))


def test_previous_us_close_no_future_leak():
    """Seoul date must not receive same-day or later US observation."""
    idx = pd.to_datetime(
        [
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        ]
    )
    # USDKRW all days; SPX only on US calendar with distinctive values
    wide = pd.DataFrame(
        {
            TARGET_ID: [1300.0, 1301.0, 1302.0, 1303.0],
            "SPX": [4000.0, 4100.0, 4200.0, 4300.0],
        },
        index=idx,
    )
    instruments = [INSTRUMENT_BY_ID[TARGET_ID], INSTRUMENT_BY_ID["SPX"]]
    result = align_transformed(wide, instruments=instruments)
    raw_aligned = result["raw_aligned_wide"]

    # On 2024-01-04 Seoul, previous US close should be 2024-01-03 value 4100 (not 4200)
    v = raw_aligned.loc[pd.Timestamp("2024-01-04"), "SPX"]
    assert v == 4100.0

    # On 2024-01-03, previous is 4000 (Jan 2), not 4100
    v2 = raw_aligned.loc[pd.Timestamp("2024-01-03"), "SPX"]
    assert v2 == 4000.0


def test_active_false_excluded_from_default_analysis(monkeypatch):
    from config import instruments as inst_mod
    from config.instruments import Instrument, get_active_instruments, get_driver_instruments

    inactive = Instrument(
        instrument_id="FAKE_INACTIVE",
        display_name="Fake",
        category="외환 환율",
        sheet_name="x",
        source_code="x",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        active=False,
        color="#000000",
    )
    monkeypatch.setattr(inst_mod, "INSTRUMENTS", list(inst_mod.INSTRUMENTS) + [inactive])
    active_ids = {i.instrument_id for i in get_active_instruments(include_inactive=False)}
    assert "FAKE_INACTIVE" not in active_ids
    all_ids = {i.instrument_id for i in get_active_instruments(include_inactive=True)}
    assert "FAKE_INACTIVE" in all_ids
    from config.instruments import INSTRUMENTS as live

    drivers = [i for i in (list(live) + [inactive]) if i.active and i.instrument_id != TARGET_ID]
    assert all(d.instrument_id != "FAKE_INACTIVE" for d in drivers)
    assert "FAKE_INACTIVE" not in {d.instrument_id for d in get_driver_instruments()}
