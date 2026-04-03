# ============================================================
# conftest.py — Fixtures condivise per la test suite
# ============================================================

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Aggiungi src/ al path per import diretti
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from parser import TradeRecord, SystemData
from datetime import datetime


# ─────────────────────────────────────────────
# Fixtures: trade di esempio
# ─────────────────────────────────────────────

def _make_trade(pnl: float, idx: int = 0, symbol: str = "AAPL") -> TradeRecord:
    """Helper per creare un TradeRecord sintetico."""
    return TradeRecord(
        trade_id    = str(idx),
        strategy    = "TestStrategy",
        symbol      = symbol,
        asset_type  = "Stock",
        entry_date  = datetime(2024, 1, 1 + idx),
        exit_date   = datetime(2024, 1, 2 + idx),
        direction   = "Long",
        entry_price = 100.0,
        exit_price  = 100.0 + pnl,
        quantity    = 1,
        capital     = 10000.0,
        pnl         = pnl,
        pnl_pct     = pnl / 10000.0 * 100,
        bars        = 1,
        is_open     = False,
    )


@pytest.fixture
def basic_system() -> SystemData:
    """Sistema con 10 trade: 6 W, 4 L (WR 60%)."""
    pnls = [100, -50, 150, 200, -80, 100, -60, 200, -40, 100]
    trades = [_make_trade(p, i) for i, p in enumerate(pnls)]
    return SystemData(
        system_name   = "TestSystem",
        strategy      = "TestStrategy",
        symbol        = "AAPL",
        family        = "Test",
        closed_trades = trades,
        open_trade    = None,
    )


@pytest.fixture
def all_wins_system() -> SystemData:
    """Sistema con tutti trade vincenti."""
    trades = [_make_trade(100, i) for i in range(20)]
    return SystemData(
        system_name   = "AllWins",
        strategy      = "WinStrategy",
        symbol        = "MSFT",
        family        = "Test",
        closed_trades = trades,
        open_trade    = None,
    )


@pytest.fixture
def all_losses_system() -> SystemData:
    """Sistema con tutti trade perdenti."""
    trades = [_make_trade(-100, i) for i in range(20)]
    return SystemData(
        system_name   = "AllLosses",
        strategy      = "LossStrategy",
        symbol        = "TSLA",
        family        = "Test",
        closed_trades = trades,
        open_trade    = None,
    )


@pytest.fixture
def single_trade_system() -> SystemData:
    """Sistema con un solo trade."""
    return SystemData(
        system_name   = "SingleTrade",
        strategy      = "TestStrategy",
        symbol        = "SPY",
        family        = "Test",
        closed_trades = [_make_trade(50, 0)],
        open_trade    = None,
    )


@pytest.fixture
def empty_system() -> SystemData:
    """Sistema senza trade chiusi."""
    return SystemData(
        system_name   = "Empty",
        strategy      = "TestStrategy",
        symbol        = "QQQ",
        family        = "Test",
        closed_trades = [],
        open_trade    = None,
    )


@pytest.fixture
def system_with_open() -> SystemData:
    """Sistema con trade chiusi + posizione aperta."""
    trades = [_make_trade(100, i) for i in range(10)]
    open_trade = TradeRecord(
        trade_id    = "OPEN",
        strategy    = "TestStrategy",
        symbol      = "AAPL",
        asset_type  = "Stock",
        entry_date  = datetime(2024, 1, 15),
        exit_date   = None,
        direction   = "Long",
        entry_price = 150.0,
        exit_price  = 155.0,
        quantity    = 1,
        capital     = 10000.0,
        pnl         = 500.0,
        pnl_pct     = None,
        bars        = 3,
        is_open     = True,
    )
    return SystemData(
        system_name   = "WithOpen",
        strategy      = "TestStrategy",
        symbol        = "AAPL",
        family        = "Test",
        closed_trades = trades,
        open_trade    = open_trade,
    )


@pytest.fixture
def breakeven_system() -> SystemData:
    """Sistema con trade breakeven (PnL = 0)."""
    pnls = [100, 0, -50, 0, 100, 0, -30, 100]
    trades = [_make_trade(p, i) for i, p in enumerate(pnls)]
    return SystemData(
        system_name   = "Breakeven",
        strategy      = "TestStrategy",
        symbol        = "META",
        family        = "Test",
        closed_trades = trades,
        open_trade    = None,
    )
