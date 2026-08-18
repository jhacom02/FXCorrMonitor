"""Unit tests for Infomax snapshot helpers (no Excel COM)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infomax.snapshot_daily import (
    MAPPING,
    USDKRW_CELL,
    _read_cell,
    cells_to_rows,
    lookback_dates,
    parse_number,
)


def test_parse_number_keeps_zero_rejects_errors():
    assert parse_number(0) == 0.0
    assert parse_number(None) is None
    assert parse_number("#N/A") is None
    assert parse_number("-") is None
    assert parse_number("        ") is None
    assert parse_number("1,416.10") == 1416.10
    # Excel COM CVErr for #N/A
    assert parse_number(-2146826259) is None


class _FakeRange:
    def __init__(self, value2=None, value=None, text=None):
        self.Value2 = value2
        self.Value = value if value is not None else value2
        self.Text = text if text is not None else str(value if value is not None else value2 or "")


class _FakeSheet:
    def __init__(self, cells: dict[str, _FakeRange]):
        self._cells = cells

    def Range(self, addr: str) -> _FakeRange:
        return self._cells[addr]


def test_read_cell_prefers_value2_over_formatted_blank():
    ws = _FakeSheet(
        {
            "D3": _FakeRange(value2=1416.1, value="        ", text="1,416.10"),
            "E4": _FakeRange(value2=None, value="...", text="..."),
        }
    )
    assert _read_cell(ws, "D3") == 1416.1
    assert parse_number(_read_cell(ws, "E4")) is None


def test_usdkrw_cell_constant():
    assert USDKRW_CELL == "D3"
    assert MAPPING[0] == ("D3", "USDKRW")


def test_lookback_excludes_today():
    dates = lookback_dates(7, today=date(2026, 8, 10))
    assert dates[0] == date(2026, 8, 3)
    assert dates[-1] == date(2026, 8, 9)
    assert len(dates) == 7


def test_cells_to_rows_f_net_and_skip():
    values = {cell: 1.0 for cell, _ in MAPPING}
    values["F8"] = "-"
    values["D3"] = 1409.5
    rows, skips = cells_to_rows(
        values, date(2026, 8, 7), source_file="x.xlsx", loaded_at="t"
    )
    ids = {r["instrument_id"] for r in rows}
    assert "USDKRW" in ids and "F_NET" not in ids
    assert any("F_NET" in s for s in skips)
    assert len(MAPPING) == 16
