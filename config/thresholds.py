"""Central analysis and display thresholds for FXCorrMonitor."""

from __future__ import annotations

DISPLAY_MIN_ABS_DEFAULT = 0.30
SIG_ABS_BY_WINDOW: dict[int, float] = {5: 0.60, 20: 0.44, 60: 0.25, 120: 0.18}
ANALYSIS_WINDOWS: tuple[int, ...] = (5, 20, 60, 120)

STATUS_ABS_DELTA = 0.10
MIXED_SCORE_GAP = 0.05
MIN_PERIOD_RATIO = 0.8

MAD_NORMAL_SCALE = 1.4826
ROBUST_Z_WINDOW = 252
ROBUST_Z_ABS_MIN = 4.0

SHOCK_ABS_FLOOR: dict[str, float] = {
    "USDKRW": 23.0,
    "DXY": 1.4,
    "USDJPY": 2.7,
    "USDCNH": 0.07,
    "EURUSD": 0.02,
    "KOSPI": 0.038,
    "SPX": 0.027,
    "NDX": 0.035,
    "VIX": 0.30,
    "WTI": 0.084,
    "GOLD": 0.03,
    "UST2Y": 18.0,
    "UST10Y": 17.0,
    "KTB3Y": 12.0,
    "KTB10Y": 12.0,
}

SHOCK_FLOOR_SCALE: dict[str, str] = {
    "USDKRW": "abs",
    "DXY": "abs",
    "USDJPY": "abs",
    "USDCNH": "abs",
    "EURUSD": "abs",
    "KOSPI": "return",
    "SPX": "return",
    "NDX": "return",
    "VIX": "return",
    "WTI": "return",
    "GOLD": "return",
    "UST2Y": "bp",
    "UST10Y": "bp",
    "KTB3Y": "bp",
    "KTB10Y": "bp",
}

SHOCK_FLOOR_LABEL: dict[str, str] = {
    "USDKRW": "원",
    "DXY": "pt",
    "USDJPY": "엔",
    "USDCNH": "위안",
    "EURUSD": "달러",
    "KOSPI": "%",
    "SPX": "%",
    "NDX": "%",
    "VIX": "%",
    "WTI": "%",
    "GOLD": "%",
    "UST2Y": "bp",
    "UST10Y": "bp",
    "KTB3Y": "bp",
    "KTB10Y": "bp",
}

CORR_GUIDE_SOFT = 0.30
CORR_GUIDE_STRONG = 0.70


def sig_abs(window: int) -> float:
    if window not in SIG_ABS_BY_WINDOW:
        raise KeyError(f"상관계수 유의성 임계값이 없습니다. window={window}")
    return float(SIG_ABS_BY_WINDOW[window])


def display_floor(window: int, user_min_abs: float) -> float:
    return max(float(user_min_abs), sig_abs(window))
