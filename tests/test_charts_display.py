"""Tests for chart display filter pipeline (min_abs → Top-N → force driver)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.charts import DISPLAY_MODE_TOP5, resolve_chart_instruments


def _corr_frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """rows: (instrument_id, display_name, abs/signed corr) on a single latest date."""
    as_of = pd.Timestamp("2024-06-10")
    records = []
    for iid, name, corr in rows:
        records.append(
            {
                "date": as_of,
                "instrument_id": iid,
                "display_name": name,
                "rolling_correlation": corr,
                "abs_correlation": abs(corr),
                "observation_count": 20,
            }
        )
    return pd.DataFrame(records)


def test_min_abs_excludes_low_spx_before_topn():
    df = _corr_frame(
        [
            ("KOSPI", "KOSPI", 0.52),
            ("KTB10Y", "KTB10Y", 0.36),
            ("KTB3Y", "KTB3Y", 0.31),
            ("VIX", "VIX", 0.30),
            ("SPX", "SPX", 0.24),
            ("DXY", "DXY", 0.40),
            ("NDX", "NDX", 0.35),
        ]
    )
    selected = ["KOSPI", "KTB10Y", "KTB3Y", "VIX", "SPX", "DXY", "NDX"]
    info = resolve_chart_instruments(
        df,
        selected_instruments=selected,
        current_driver_id="KOSPI",
        display_mode=DISPLAY_MODE_TOP5,
        min_abs_correlation=0.30,
    )
    assert "SPX" not in info["show_ids"]
    assert "SPX" not in info["passed_ids"]
    # Top-5 from passed: KOSPI, DXY, KTB10Y, NDX, KTB3Y/VIX — SPX excluded
    assert len([i for i in info["show_ids"] if i != "KOSPI"]) <= 5
    assert all(
        iid in info["passed_ids"] or iid == "KOSPI" for iid in info["show_ids"]
    )


def test_driver_forced_even_below_min_abs():
    df = _corr_frame(
        [
            ("KOSPI", "KOSPI", 0.25),
            ("DXY", "DXY", 0.55),
            ("VIX", "VIX", 0.45),
            ("SPX", "SPX", 0.40),
        ]
    )
    info = resolve_chart_instruments(
        df,
        selected_instruments=["KOSPI", "DXY", "VIX", "SPX"],
        current_driver_id="KOSPI",
        display_mode=DISPLAY_MODE_TOP5,
        min_abs_correlation=0.30,
    )
    assert "KOSPI" in info["show_ids"]
    assert info["driver_forced"] is True
    assert info["show_ids"][0] == "KOSPI"
    # Non-driver below threshold still excluded
    assert set(info["passed_ids"]) == {"DXY", "VIX", "SPX"}


def test_top5_only_from_passed():
    df = _corr_frame(
        [
            ("A", "A", 0.90),
            ("B", "B", 0.80),
            ("C", "C", 0.70),
            ("D", "D", 0.60),
            ("E", "E", 0.50),
            ("F", "F", 0.40),
            ("G", "G", 0.20),
        ]
    )
    info = resolve_chart_instruments(
        df,
        selected_instruments=["A", "B", "C", "D", "E", "F", "G"],
        current_driver_id=None,
        display_mode=DISPLAY_MODE_TOP5,
        min_abs_correlation=0.30,
    )
    assert "G" not in info["show_ids"]
    assert info["show_ids"] == ["A", "B", "C", "D", "E"]


def test_correlation_heatmap_builds_with_labels_and_desaturate():
    from src.charts import HEATMAP_COLORSCALE, correlation_heatmap

    rows = []
    for iid, name, c20, c60, c120 in [
        ("KOSPI", "KOSPI", 0.55, 0.40, 0.20),
        ("DXY", "DXY", -0.12, -0.05, 0.02),
        ("VIX", "VIX", -0.48, -0.30, -0.10),
    ]:
        for w, c in ((20, c20), (60, c60), (120, c120)):
            rows.append(
                {
                    "instrument_id": iid,
                    "display_name": name,
                    "window": w,
                    "rolling_correlation": c,
                }
            )
    multi = pd.DataFrame(rows)
    fig = correlation_heatmap(multi, current_driver_id="KOSPI", min_abs_correlation=0.30)
    assert len(fig.data) == 1
    hm = fig.data[0]
    assert list(hm.x) == ["20D", "60D", "120D"]
    assert "KOSPI" in list(hm.y)
    assert hm.colorscale[0][1].lower() == HEATMAP_COLORSCALE[0][1].lower()
    # Low-|ρ| cell is desaturated toward 0 for fill (DXY 20D = -0.12)
    kospi_idx = list(hm.y).index("KOSPI")
    dxy_idx = list(hm.y).index("DXY")
    assert abs(hm.z[kospi_idx][0] - 0.55) < 1e-9
    assert abs(hm.z[dxy_idx][0] - (-0.12 * 0.6)) < 1e-9
    assert hm.text[dxy_idx][0] == "-0.12"
