# ============================================================
# parser.py — Parser CSV MultiCharts per trade CHIUSI
# ============================================================
# Versione per il Portfolio Allocator:
#   - Deduplica per trade_id (i re-export giornalieri su Drive
#     possono accodare righe duplicate)
#   - Ignora i file _Open.csv (non servono per l'allocazione)
#   - Applica il fattore di normalizzazione size dal settings
# ============================================================

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Indici colonne formato MultiCharts (zero-based, no header)
COL_TRADE_ID   = 0
COL_ENTRY_DATE = 4
COL_EXIT_DATE  = 6
COL_PNL        = 13


@dataclass
class Trade:
    trade_id:   str
    entry_date: datetime
    exit_date:  datetime
    pnl:        float


@dataclass
class ParsedSystem:
    system_name: str
    trades:      list          # list[Trade], ordinati per exit_date
    n_raw_rows:  int           # righe lette dal CSV
    n_dupes:     int           # righe rimosse perché duplicate

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        nz = [t for t in self.trades if t.pnl != 0.0]
        if not nz:
            return 0.0
        return sum(1 for t in nz if t.pnl > 0) / len(nz)

    @property
    def last_exit(self) -> Optional[datetime]:
        return self.trades[-1].exit_date if self.trades else None


def _parse_mc_date(raw: str) -> datetime:
    """Formato MultiCharts 1YYMMDD (es. 1210104 = 2021-01-04)."""
    s = str(raw).strip()
    if len(s) == 7 and s.startswith('1'):
        return datetime.strptime(s[1:], '%y%m%d')
    return datetime.strptime(s, '%Y%m%d')


def parse_system_csv(
    content: str,
    system_name: str,
    size_factor: float = 1.0,
) -> Optional[ParsedSystem]:
    """
    Parsa un CSV di trade chiusi, deduplica per trade_id e applica
    il fattore di normalizzazione size al PnL.

    Returns:
        ParsedSystem, oppure None se il file non contiene trade validi.
    """
    lines = [l.strip() for l in content.strip().splitlines() if l.strip()]
    seen: set = set()
    trades: list[Trade] = []
    n_raw = 0
    n_dupes = 0

    for line_num, line in enumerate(lines, 1):
        fields = line.split(',')
        if len(fields) < COL_PNL + 1:
            continue
        n_raw += 1

        trade_id = fields[COL_TRADE_ID].strip()
        if trade_id in seen:
            n_dupes += 1
            continue

        try:
            entry = _parse_mc_date(fields[COL_ENTRY_DATE])
            exit_ = _parse_mc_date(fields[COL_EXIT_DATE])
            pnl   = float(fields[COL_PNL]) * size_factor
        except (ValueError, IndexError) as e:
            logger.warning(f"{system_name} riga {line_num}: errore parsing ({e}), saltata")
            continue

        seen.add(trade_id)
        trades.append(Trade(trade_id, entry, exit_, pnl))

    if not trades:
        logger.warning(f"{system_name}: nessun trade valido, sistema saltato")
        return None

    trades.sort(key=lambda t: t.exit_date)

    if n_dupes:
        logger.info(f"{system_name}: rimosse {n_dupes} righe duplicate su {n_raw}")

    return ParsedSystem(system_name, trades, n_raw, n_dupes)


def infer_family(system_name: str, prefixes: list[str]) -> str:
    """Prefisso famiglia dal nome sistema; fallback: nome intero."""
    for p in prefixes:
        if system_name.startswith(p):
            return p
    return system_name
