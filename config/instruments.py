"""Instrument metadata for FXCorrMonitor. Series colors come from styles.css."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.theme import load_css_vars

_CSS = load_css_vars()


def _tok(name: str) -> str:
    if name not in _CSS:
        raise KeyError(f"missing CSS token --{name}")
    return _CSS[name]


def css_instrument_color(instrument_id: str) -> str:
    key = f"fx-color-{instrument_id}"
    if key in _CSS:
        return _CSS[key]
    return _tok("fx-inst-fallback")


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    display_name: str
    sheet_name: str
    source_code: str
    source_column: str
    data_type: str
    transformation: str
    alignment: str
    active: bool = True
    color: str = ""


NONE_COLOR = _tok("fx-color-NONE")
MIXED_COLOR = _tok("fx-color-MIXED")
SPECIAL_COLORS = {
    "NONE": NONE_COLOR,
    "MIXED": MIXED_COLOR,
}

INSTRUMENTS: list[Instrument] = [
    Instrument(
        instrument_id="USDKRW",
        display_name="USDKRW",
        sheet_name="서울외환(기업용) USDKRW 스팟",
        source_code="USDSP_SMBCC_EXT",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        color="#E6EDF3",
    ),
    Instrument(
        instrument_id="DXY",
        display_name="DXY",
        sheet_name="달러인덱스 Dollars",
        source_code="DOLLAR",
        source_column="KR_MID_Close",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        color="#F85149",
    ),
    Instrument(
        instrument_id="USDJPY",
        display_name="USDJPY",
        sheet_name="이종통화 종합 JPY",
        source_code="USDJPY",
        source_column="KR_MID_Close",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        color="#FF7B72",
    ),
    Instrument(
        instrument_id="USDCNH",
        display_name="USDCNH",
        sheet_name="이종통화 종합 CNH",
        source_code="USDCNH",
        source_column="KR_MID_Close",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        color="#F0883E",
    ),
    Instrument(
        instrument_id="EURUSD",
        display_name="EURUSD",
        sheet_name="이종통화 종합 EUR",
        source_code="EURUSD",
        source_column="KR_MID_Close",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        color="#DB61A2",
    ),
    Instrument(
        instrument_id="KOSPI",
        display_name="KOSPI",
        sheet_name="KOSPI",
        source_code="1",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        color="#3FB950",
    ),
    Instrument(
        instrument_id="F_NET",
        display_name="F_NET",
        sheet_name="KOSPI",
        source_code="1",
        source_column="외국인순매수금액",
        data_type="flow",
        transformation="level",
        alignment="same_day",
        color="#F0C14A",
    ),
    Instrument(
        instrument_id="SPX",
        display_name="SPX",
        sheet_name="S&P 500",
        source_code="SPI:SPX",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="previous_us_close",
        color="#58A6FF",
    ),
    Instrument(
        instrument_id="NDX",
        display_name="NDX",
        sheet_name="나스닥 100",
        source_code="NAS:NDX",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="previous_us_close",
        color="#79C0FF",
    ),
    Instrument(
        instrument_id="VIX",
        display_name="VIX",
        sheet_name="VOLATILITY S&P500",
        source_code="CBI:VIX",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="previous_us_close",
        color="#A371F7",
    ),
    Instrument(
        instrument_id="WTI",
        display_name="WTI",
        sheet_name="WTI 2026 9 (연결선물)",
        source_code="NYM:CL",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="previous_us_close",
        color="#D29922",
    ),
    Instrument(
        instrument_id="GOLD",
        display_name="GOLD",
        sheet_name="금 2026 12 (연결선물)",
        source_code="COM:GC",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="previous_us_close",
        color="#E3B341",
    ),
    Instrument(
        instrument_id="UST2Y",
        display_name="UST2Y",
        sheet_name="미국(종합) 2년",
        source_code="US02Y",
        source_column="MID_Close",
        data_type="yield",
        transformation="diff_bp",
        alignment="previous_us_close",
        color="#39C5CF",
    ),
    Instrument(
        instrument_id="UST10Y",
        display_name="UST10Y",
        sheet_name="미국(종합) 10년",
        source_code="US10Y",
        source_column="MID_Close",
        data_type="yield",
        transformation="diff_bp",
        alignment="previous_us_close",
        color="#76E3EA",
    ),
    Instrument(
        instrument_id="KTB3Y",
        display_name="KTB3Y",
        sheet_name="금투협 최종호가 국고채권(3년)",
        source_code="BONDKSDCAL11",
        source_column="대표수익률",
        data_type="yield",
        transformation="diff_bp",
        alignment="same_day",
        color="#C084FC",
    ),
    Instrument(
        instrument_id="KTB10Y",
        display_name="KTB10Y",
        sheet_name="금투협 최종호가 국고채권(10년)",
        source_code="BONDKSDCAL13",
        source_column="대표수익률",
        data_type="yield",
        transformation="diff_bp",
        alignment="same_day",
        color="#E879F9",
    ),
]

INSTRUMENT_BY_ID: dict[str, Instrument] = {i.instrument_id: i for i in INSTRUMENTS}

INSTRUMENT_COLORS: dict[str, str] = {
    i.instrument_id: i.color for i in INSTRUMENTS
}

DEFAULT_DRIVER_IDS: list[str] = [
    "DXY",
    "USDJPY",
    "USDCNH",
    "EURUSD",
    "KOSPI",
    "F_NET",
    "SPX",
    "NDX",
    "VIX",
    "WTI",
    "GOLD",
    "UST2Y",
    "UST10Y",
    "KTB3Y",
    "KTB10Y",
]

TARGET_ID = "USDKRW"


def get_active_instruments(include_inactive: bool = False) -> list[Instrument]:
    if include_inactive:
        return list(INSTRUMENTS)
    return [i for i in INSTRUMENTS if i.active]


def get_driver_instruments(include_inactive: bool = False) -> list[Instrument]:
    return [i for i in get_active_instruments(include_inactive) if i.instrument_id != TARGET_ID]


def instrument_to_row(instrument: Instrument, updated_at: str) -> dict[str, Any]:
    row = asdict(instrument)
    row["source_sheet"] = row.pop("sheet_name")
    row.pop("color", None)
    row["active"] = 1 if instrument.active else 0
    row["updated_at"] = updated_at
    return row


def color_for(instrument_id: str) -> str:
    return INSTRUMENT_COLORS.get(instrument_id) or css_instrument_color(instrument_id)
