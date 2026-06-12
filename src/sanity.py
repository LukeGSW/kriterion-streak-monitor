# ============================================================
# sanity.py — Quarantena automatica dei dati sospetti
# ============================================================
# Lezione appresa dallo Streak Monitor: i re-export giornalieri
# su Drive possono produrre file corrotti (righe duplicate,
# win rate impossibili, file stale). Questo modulo intercetta
# i casi anomali PRIMA che entrino nel calcolo dei pesi.
#
# Un sistema in quarantena è ESCLUSO dall'analisi e listato
# nel report con il motivo. Un sistema "stale" è incluso ma
# segnalato con warning.
# ============================================================

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from parser import ParsedSystem

logger = logging.getLogger(__name__)


@dataclass
class SanityResult:
    ok:          list = field(default_factory=list)   # list[ParsedSystem]
    quarantined: list = field(default_factory=list)   # list[(name, reason)]
    warnings:    list = field(default_factory=list)   # list[(name, message)]


def run_sanity_checks(
    parsed: dict[str, ParsedSystem],
    thresholds: dict,
    today: datetime | None = None,
) -> SanityResult:
    """
    Applica i controlli di qualità dati a tutti i sistemi parsati.

    thresholds (da settings.yaml → sanity):
        max_win_rate, max_dup_ratio, min_trades, stale_days
    """
    today = today or datetime.now()
    max_wr   = thresholds.get('max_win_rate', 0.90)
    max_dup  = thresholds.get('max_dup_ratio', 0.30)
    min_tr   = thresholds.get('min_trades', 10)
    stale_d  = thresholds.get('stale_days', 90)

    res = SanityResult()

    for name, ps in sorted(parsed.items()):
        # 1. Trade minimi
        if ps.n_trades < min_tr:
            res.quarantined.append(
                (name, f"solo {ps.n_trades} trade chiusi (minimo {min_tr})"))
            continue

        # 2. Quota duplicati: file probabilmente corrotto dal re-export
        dup_ratio = ps.n_dupes / ps.n_raw_rows if ps.n_raw_rows else 0.0
        if dup_ratio > max_dup:
            res.quarantined.append(
                (name, f"{dup_ratio:.0%} di righe duplicate nel CSV "
                       f"(soglia {max_dup:.0%}) — verifica l'export su Drive"))
            continue

        # 3. Win rate implausibile: dati quasi certamente errati
        if ps.win_rate > max_wr:
            res.quarantined.append(
                (name, f"win rate {ps.win_rate:.1%} > {max_wr:.0%} — "
                       f"dati sospetti (righe duplicate o export errato)"))
            continue

        # 4. Staleness: incluso ma segnalato
        if ps.last_exit:
            age = (today - ps.last_exit).days
            if age > stale_d:
                res.warnings.append(
                    (name, f"ultimo trade chiuso {age} giorni fa "
                           f"({ps.last_exit.date()}) — sistema fermo o file non aggiornato"))

        res.ok.append(ps)

    logger.info(
        f"Sanity: {len(res.ok)} ok, {len(res.quarantined)} in quarantena, "
        f"{len(res.warnings)} warning"
    )
    for name, reason in res.quarantined:
        logger.warning(f"QUARANTENA {name}: {reason}")

    return res
