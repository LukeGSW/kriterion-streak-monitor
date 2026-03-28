# ============================================================
# parser.py — Parser universale CSV formato MultiCharts
# ============================================================
# Legge qualsiasi file esportato da MultiCharts/TradeStation.
# Nessun parametro hardcodato: funziona con qualsiasi sistema
# o ticker presente nella cartella Drive.
# ============================================================

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Indici colonne del formato CSV MultiCharts (zero-based, no header)
COL_TRADE_ID    = 0
COL_STRATEGY    = 1
COL_SYMBOL      = 2
COL_ASSET_TYPE  = 3
COL_ENTRY_DATE  = 4
COL_ENTRY_TIME  = 5
COL_EXIT_DATE   = 6
COL_EXIT_TIME   = 7
COL_DIRECTION   = 8
COL_ENTRY_PRICE = 9
COL_EXIT_PRICE  = 10
COL_QUANTITY    = 11
COL_CAPITAL     = 12
COL_PNL         = 13
COL_PNL_PCT     = 14
COL_BARS        = 15


@dataclass
class TradeRecord:
    """Singolo trade chiuso o aperto, normalizzato."""
    trade_id:     str
    strategy:     str
    symbol:       str
    asset_type:   str
    entry_date:   datetime
    exit_date:    Optional[datetime]
    direction:    str
    entry_price:  float
    exit_price:   Optional[float]
    quantity:     int
    capital:      float
    pnl:          Optional[float]   # None se trade aperto
    pnl_pct:      Optional[float]
    bars:         Optional[int]
    is_open:      bool = False

    @property
    def is_winner(self) -> Optional[bool]:
        """True = win, False = loss, None = trade aperto."""
        if self.pnl is None:
            return None
        return self.pnl > 0


@dataclass
class SystemData:
    """Dati completi di un sistema: trades chiusi + eventuale trade aperto."""
    system_name:    str          # nome del file senza estensione (es. BiasIntraweekAAPL)
    strategy:       str          # nome strategia da MultiCharts
    symbol:         str          # ticker (es. AAPL)
    family:         str          # prefisso famiglia (es. BiasIntraweek)
    closed_trades:  list[TradeRecord]
    open_trade:     Optional[TradeRecord]

    @property
    def n_trades(self) -> int:
        return len(self.closed_trades)

    @property
    def has_open_position(self) -> bool:
        return self.open_trade is not None

    def to_pnl_series(self) -> list[float]:
        """Restituisce la serie di PnL dei trade chiusi in ordine cronologico."""
        return [t.pnl for t in self.closed_trades if t.pnl is not None]

    def to_win_series(self) -> list[int]:
        """Restituisce la sequenza binaria W=1 / L=0 dei trade chiusi."""
        return [1 if t.pnl > 0 else 0 for t in self.closed_trades if t.pnl is not None]


# ─────────────────────────────────────────────
# Funzioni di parsing
# ─────────────────────────────────────────────

def _parse_mc_date(raw: str) -> datetime:
    """
    Converte la data nel formato proprietario MultiCharts → datetime.

    Formato: 1YYMMDD  (es. 1210104 = 2021-01-04)
    Il leading '1' è un prefisso fisso del formato di export.
    """
    s = str(raw).strip()
    if len(s) == 7 and s.startswith('1'):
        return datetime.strptime(s[1:], '%y%m%d')
    # Fallback: prova YYYYMMDD standard
    return datetime.strptime(s, '%Y%m%d')


def _infer_family(system_name: str) -> str:
    """
    Estrae il prefisso famiglia dal nome del sistema.
    Es: 'BiasIntraweekAAPL' → 'BiasIntraweek'
         'BreakOutNVDA'      → 'BreakOut'
         'ZScoreAMD'         → 'ZScore'
         'MYMSushi'          → 'MYMSushi'
    """
    prefixes = ['BiasIntraweek', 'BreakOut', 'ShortCover', 'ZScore']
    for p in prefixes:
        if system_name.startswith(p):
            return p
    return system_name  # sistema sconosciuto → usa il nome intero come famiglia


def parse_csv_content(content: str, system_name: str, is_open: bool = False) -> list[TradeRecord]:
    """
    Parsa il contenuto testuale di un CSV MultiCharts.

    Args:
        content:     stringa grezza del file CSV
        system_name: nome del sistema (per logging)
        is_open:     True se il file è un _Open.csv (trade aperto)

    Returns:
        Lista di TradeRecord (vuota se file privo di dati)
    """
    records = []
    lines = [l.strip() for l in content.strip().splitlines() if l.strip()]

    for line_num, line in enumerate(lines, 1):
        fields = line.split(',')

        # Numero minimo di colonne per un trade chiuso
        if len(fields) < COL_PNL + 1 and not is_open:
            logger.debug(f"{system_name} riga {line_num}: troppo corta ({len(fields)} campi), saltata")
            continue

        if len(fields) < COL_CAPITAL + 1:
            continue

        try:
            entry_date = _parse_mc_date(fields[COL_ENTRY_DATE])

            exit_date  = None
            exit_price = None
            pnl        = None
            pnl_pct    = None
            bars       = None

            if not is_open and len(fields) > COL_EXIT_DATE:
                exit_date  = _parse_mc_date(fields[COL_EXIT_DATE])
                exit_price = float(fields[COL_EXIT_PRICE])
                pnl        = float(fields[COL_PNL])
                pnl_pct    = float(fields[COL_PNL_PCT]) if len(fields) > COL_PNL_PCT else None
                bars       = int(fields[COL_BARS])       if len(fields) > COL_BARS    else None

            record = TradeRecord(
                trade_id    = fields[COL_TRADE_ID],
                strategy    = fields[COL_STRATEGY],
                symbol      = fields[COL_SYMBOL],
                asset_type  = fields[COL_ASSET_TYPE],
                entry_date  = entry_date,
                exit_date   = exit_date,
                direction   = fields[COL_DIRECTION],
                entry_price = float(fields[COL_ENTRY_PRICE]),
                exit_price  = exit_price,
                quantity    = int(fields[COL_QUANTITY]),
                capital     = float(fields[COL_CAPITAL]),
                pnl         = pnl,
                pnl_pct     = pnl_pct,
                bars        = bars,
                is_open     = is_open,
            )
            records.append(record)

        except (ValueError, IndexError) as e:
            logger.warning(f"{system_name} riga {line_num}: errore parsing ({e}), saltata")

    return records


def build_system_data(
    system_name: str,
    closed_content: str,
    open_content: Optional[str] = None,
) -> Optional[SystemData]:
    """
    Costruisce un SystemData completo da contenuto CSV chiusi + aperto.

    Args:
        system_name:    nome del sistema (es. 'BiasIntraweekAAPL')
        closed_content: contenuto del file storico (.csv)
        open_content:   contenuto del file _Open.csv (None se non esiste)

    Returns:
        SystemData oppure None se non ci sono trade sufficienti
    """
    closed_trades = parse_csv_content(closed_content, system_name, is_open=False)

    # Ordina per data di entrata (sicurezza ordine cronologico)
    closed_trades.sort(key=lambda t: t.entry_date)

    if not closed_trades:
        logger.warning(f"{system_name}: nessun trade chiuso trovato, sistema saltato")
        return None

    open_trade = None
    if open_content:
        open_records = parse_csv_content(open_content, f"{system_name}_Open", is_open=True)
        if open_records:
            open_trade = open_records[0]

    # Metadata dal primo trade chiuso (tutti i trade di un sistema hanno stessi metadati)
    first = closed_trades[0]

    return SystemData(
        system_name   = system_name,
        strategy      = first.strategy,
        symbol        = first.symbol,
        family        = _infer_family(system_name),
        closed_trades = closed_trades,
        open_trade    = open_trade,
    )
