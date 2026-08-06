"""Central analysis and display thresholds for FXCorrMonitor."""

from __future__ import annotations

DISPLAY_MIN_ABS_DEFAULT = 0.30
SIG_ABS_BY_WINDOW: dict[int, float] = {20: 0.44, 60: 0.25, 120: 0.18}
ANALYSIS_WINDOWS: tuple[int, ...] = (20, 60, 120)

STATUS_ABS_DELTA = 0.10
MIXED_SCORE_GAP = 0.05
MIN_PERIOD_RATIO = 0.8

MAD_NORMAL_SCALE = 1.4826
ROBUST_Z_WINDOW = 252
ROBUST_Z_ABS_MIN = 4.0

SHOCK_ABS_FLOOR: dict[str, float] = {
    "DXY": 0.02,
    "USDJPY": 0.02,
    "USDCNH": 0.02,
    "EURUSD": 0.02,
    "KOSPI": 0.05,
    "SPX": 0.05,
    "NDX": 0.05,
    "VIX": 0.30,
    "WTI": 0.15,
    "GOLD": 0.03,
    "UST2Y": 20.0,
    "UST10Y": 20.0,
    "KTB3Y": 20.0,
    "KTB10Y": 20.0,
}

CORR_GUIDE_SOFT = 0.30
CORR_GUIDE_STRONG = 0.70


def sig_abs(window: int) -> float:
    if window not in SIG_ABS_BY_WINDOW:
        raise KeyError(f"상관계수 유의성 임계값이 없습니다. window={window}")
    return float(SIG_ABS_BY_WINDOW[window])


def display_floor(window: int, user_min_abs: float) -> float:
    return max(float(user_min_abs), sig_abs(window))
