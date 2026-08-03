"""Instrument metadata and fixed chart colors for FXCorrMonitor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    display_name: str
    category: str
    sheet_name: str
    source_code: str
    source_column: str
    data_type: str
    transformation: str
    alignment: str
    active: bool = True
    note: str | None = None
    color: str = "#7F8C9B"


NONE_COLOR = "#D0D7DE"
MIXED_COLOR = "#6E7681"
SPECIAL_COLORS = {
    "NONE": NONE_COLOR,
    "MIXED": MIXED_COLOR,
}

INSTRUMENTS: list[Instrument] = [
    Instrument(
        instrument_id="USDKRW",
        display_name="USDKRW",
        category="기준 환율",
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
        category="외환 환율",
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
        category="외환 환율",
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
        category="외환 환율",
        sheet_name="이종통화 종합 CNH",
        source_code="USDCNH",
        source_column="KR_MID_Close",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        color="#DB6D28",
    ),
    Instrument(
        instrument_id="EURUSD",
        display_name="EURUSD",
        category="외환 환율",
        sheet_name="이종통화 종합 EUR",
        source_code="EURUSD",
        source_column="KR_MID_Close",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        color="#BF8700",
    ),
    Instrument(
        instrument_id="KOSPI",
        display_name="KOSPI",
        category="국내 주식",
        sheet_name="KOSPI",
        source_code="001",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="same_day",
        color="#3FB950",
    ),
    Instrument(
        instrument_id="KOSPI_FOREIGN_NET",
        display_name="외국인순매수",
        category="국내 주식",
        sheet_name="KOSPI",
        source_code="001",
        source_column="외국인순매수금액",
        data_type="flow",
        transformation="level",
        alignment="same_day",
        note="인포맥스 원자료 단위",
        color="#56D364",
    ),
    Instrument(
        instrument_id="SPX",
        display_name="S&P 500",
        category="미국 주식",
        sheet_name="S&P 500",
        source_code="SPI:SPX",
        source_column="현재가",
        data_type="price",
        transformation="log_return",
        alignment="previous_us_close",
        active=True,
        color="#58A6FF",
    ),
    Instrument(
        instrument_id="NDX",
        display_name="Nasdaq 100",
        category="미국 주식",
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
        category="변동성 지표",
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
        display_name="WTI 선물",
        category="원자재",
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
        display_name="금 선물",
        category="원자재",
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
        display_name="미국채 2Y",
        category="미국 금리",
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
        display_name="미국채 10Y",
        category="미국 금리",
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
        display_name="국고채 3Y",
        category="한국 금리",
        sheet_name="국고 3Y",
        source_code="KR1035G00003",
        source_column="민평3사 수익률(산출일) 당일",
        data_type="yield",
        transformation="diff_bp",
        alignment="same_day",
        note="민평3사 평가수익률",
        color="#8B949E",
    ),
    Instrument(
        instrument_id="KTB10Y",
        display_name="국고채 10Y",
        category="한국 금리",
        sheet_name="국고 10Y",
        source_code="KR1035G00010",
        source_column="민평3사 수익률(산출일) 당일",
        data_type="yield",
        transformation="diff_bp",
        alignment="same_day",
        note="민평3사 평가수익률",
        color="#F0C14A",
    ),
]

INSTRUMENT_BY_ID: dict[str, Instrument] = {i.instrument_id: i for i in INSTRUMENTS}

INSTRUMENT_COLORS: dict[str, str] = {
    i.instrument_id: i.color for i in INSTRUMENTS
} | SPECIAL_COLORS

DEFAULT_DRIVER_IDS: list[str] = [
    "DXY",
    "USDCNH",
    "USDJPY",
    "EURUSD",
    "KOSPI",
    "KOSPI_FOREIGN_NET",
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
    return INSTRUMENT_COLORS.get(instrument_id, "#7F8C9B")
