# ============================================================
# test_parser.py — Test suite per il parser CSV MultiCharts
# ============================================================
# Copre:
#   - _parse_mc_date: conversione date proprietarie
#   - _infer_family: estrazione famiglia dal nome sistema
#   - parse_csv_content: parsing trade chiusi
#   - parse_open_csv_content: parsing posizioni aperte
#   - build_system_data: assemblaggio SystemData
#   - to_win_series / to_pnl_series: serie derivate
# ============================================================

from __future__ import annotations

from datetime import datetime

import pytest
from parser import (
    _parse_mc_date,
    _infer_family,
    parse_csv_content,
    parse_open_csv_content,
    build_system_data,
    SystemData,
    TradeRecord,
)


# ─────────────────────────────────────────────
# _parse_mc_date
# ─────────────────────────────────────────────

class TestParseMcDate:

    def test_standard_mc_format(self):
        """Formato 1YYMMDD → datetime corretto."""
        result = _parse_mc_date("1240315")
        assert result == datetime(2024, 3, 15)

    def test_year_2020(self):
        result = _parse_mc_date("1200101")
        assert result == datetime(2020, 1, 1)

    def test_year_2025(self):
        result = _parse_mc_date("1251231")
        assert result == datetime(2025, 12, 31)

    def test_fallback_yyyymmdd(self):
        """Se non inizia con 1 e 7 cifre, prova YYYYMMDD."""
        result = _parse_mc_date("20240315")
        assert result == datetime(2024, 3, 15)

    def test_whitespace_stripped(self):
        result = _parse_mc_date("  1240315  ")
        assert result == datetime(2024, 3, 15)

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            _parse_mc_date("invalid")


# ─────────────────────────────────────────────
# _infer_family
# ─────────────────────────────────────────────

class TestInferFamily:

    def test_bias_intraweek(self):
        assert _infer_family("BiasIntraweekAAPL") == "BiasIntraweek"

    def test_breakout(self):
        assert _infer_family("BreakOutNVDA") == "BreakOut"

    def test_shortcover(self):
        assert _infer_family("ShortCoverMES") == "ShortCover"

    def test_zscore(self):
        assert _infer_family("ZScoreAMD") == "ZScore"

    def test_unknown_returns_full_name(self):
        assert _infer_family("MYMSushi") == "MYMSushi"

    def test_empty_string(self):
        assert _infer_family("") == ""


# ─────────────────────────────────────────────
# parse_csv_content
# ─────────────────────────────────────────────

class TestParseCsvContent:

    SAMPLE_ROW = (
        "1,Strategy1,AAPL,Stock,1240101,930,1240102,1600,"
        "Long,150.00,155.00,100,15000.00,500.00,3.33,5"
    )

    def test_single_valid_row(self):
        records = parse_csv_content(self.SAMPLE_ROW, "TestSystem")
        assert len(records) == 1
        r = records[0]
        assert r.symbol == "AAPL"
        assert r.pnl == 500.0
        assert r.direction == "Long"

    def test_empty_content(self):
        records = parse_csv_content("", "TestSystem")
        assert records == []

    def test_multiple_rows(self):
        content = "\n".join([
            f"{i},Strategy1,AAPL,Stock,124010{i},930,124010{i+1},1600,"
            f"Long,150.00,{155+i}.00,100,15000.00,{100*i}.00,{i}.00,5"
            for i in range(1, 5)
        ])
        records = parse_csv_content(content, "TestSystem")
        assert len(records) == 4

    def test_short_row_skipped(self):
        """Riga con troppi pochi campi viene saltata."""
        content = "1,Strategy1,AAPL"
        records = parse_csv_content(content, "TestSystem")
        assert records == []

    def test_malformed_number_skipped(self):
        """Riga con numero invalido viene saltata gracefully."""
        content = (
            "1,Strategy1,AAPL,Stock,1240101,930,1240102,1600,"
            "Long,NOT_A_NUMBER,155.00,100,15000.00,500.00,3.33,5"
        )
        records = parse_csv_content(content, "TestSystem")
        assert records == []

    def test_pnl_extraction(self):
        records = parse_csv_content(self.SAMPLE_ROW, "TestSystem")
        assert records[0].pnl == 500.0
        assert records[0].entry_price == 150.0
        assert records[0].exit_price == 155.0


# ─────────────────────────────────────────────
# parse_open_csv_content
# ─────────────────────────────────────────────

class TestParseOpenCsvContent:

    SAMPLE_OPEN = (
        "Strategy1,AAPL,Stock,1240115,930,Long,"
        "150.00,155.00,3,15000.00,500.00,1240118"
    )

    def test_valid_open_trade(self):
        result = parse_open_csv_content(self.SAMPLE_OPEN, "TestSystem")
        assert result is not None
        assert result.is_open is True
        assert result.symbol == "AAPL"
        assert result.pnl == 500.0

    def test_empty_content(self):
        result = parse_open_csv_content("", "TestSystem")
        assert result is None

    def test_short_row(self):
        result = parse_open_csv_content("Strategy1,AAPL,Stock", "TestSystem")
        assert result is None

    def test_whitespace_only(self):
        result = parse_open_csv_content("   \n  \n  ", "TestSystem")
        assert result is None


# ─────────────────────────────────────────────
# build_system_data
# ─────────────────────────────────────────────

class TestBuildSystemData:

    CLOSED_CSV = "\n".join([
        f"{i},Strategy1,AAPL,Stock,124010{i},930,124010{i+1},1600,"
        f"Long,150.00,{155 if i%2==0 else 145}.00,100,15000.00,"
        f"{500 if i%2==0 else -500}.00,{3.33 if i%2==0 else -3.33},5"
        for i in range(1, 6)
    ])

    OPEN_CSV = (
        "Strategy1,AAPL,Stock,1240110,930,Long,"
        "150.00,155.00,3,15000.00,500.00,1240115"
    )

    def test_basic_build(self):
        result = build_system_data("BiasIntraweekAAPL", self.CLOSED_CSV)
        assert result is not None
        assert result.system_name == "BiasIntraweekAAPL"
        assert result.family == "BiasIntraweek"
        assert result.symbol == "AAPL"
        assert len(result.closed_trades) == 5

    def test_with_open_trade(self):
        result = build_system_data("BiasIntraweekAAPL", self.CLOSED_CSV, self.OPEN_CSV)
        assert result is not None
        assert result.has_open_position is True

    def test_without_open_trade(self):
        result = build_system_data("BiasIntraweekAAPL", self.CLOSED_CSV, None)
        assert result is not None
        assert result.has_open_position is False

    def test_empty_closed_returns_none(self):
        result = build_system_data("TestSystem", "")
        assert result is None

    def test_chronological_order(self):
        result = build_system_data("TestSystem", self.CLOSED_CSV)
        if result:
            dates = [t.entry_date for t in result.closed_trades]
            assert dates == sorted(dates)


# ─────────────────────────────────────────────
# to_win_series / to_pnl_series
# ─────────────────────────────────────────────

class TestDerivedSeries:

    def test_win_series_binary(self):
        """Win series contiene solo 0 e 1."""
        result = build_system_data("TestSystem", TestBuildSystemData.CLOSED_CSV)
        if result:
            ws = result.to_win_series()
            assert all(v in (0, 1) for v in ws)

    def test_pnl_series_length(self):
        result = build_system_data("TestSystem", TestBuildSystemData.CLOSED_CSV)
        if result:
            assert len(result.to_pnl_series()) == len(result.closed_trades)

    def test_breakeven_excluded_from_win_series(self, breakeven_system):
        """Trade con PnL=0 vengono esclusi dalla win_series."""
        ws = breakeven_system.to_win_series()
        ps = breakeven_system.to_pnl_series()
        # 3 trade breakeven su 8 totali → win_series ha 5 elementi
        assert len(ws) == 5
        assert len(ps) == 8

    def test_breakeven_included_in_pnl_series(self, breakeven_system):
        """to_pnl_series include anche i breakeven."""
        ps = breakeven_system.to_pnl_series()
        assert 0.0 in ps
