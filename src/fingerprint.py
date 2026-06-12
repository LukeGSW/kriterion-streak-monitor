# ============================================================
# fingerprint.py — Immutabilità dello storico tra le run
# ============================================================
# Principio: i trade passati non cambiano mai. Se il PnL di un
# anno CHIUSO differisce da quello registrato nella baseline,
# il file è stato rigenerato da una configurazione diversa
# (altro timeframe, altro workspace, altra size) e il sistema
# NON deve entrare nel calcolo dei pesi.
#
# Caso reale che questo modulo intercetta: re-export di
# ShortCoverMNQ da chart 60-min invece che da chart al minuto
# → stesso sistema, PnL storico da +11k a −54k.
#
# Baseline: output/fingerprints.json (committata dalla Action).
# - Sistema nuovo → baseline creata automaticamente (nota nel report)
# - Anno corrente → può crescere liberamente (trade nuovi)
# - Anni chiusi → devono coincidere al centesimo
# ============================================================

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from parser import ParsedSystem

logger = logging.getLogger(__name__)

TOLERANCE_USD = 0.01


def compute_fingerprint(ps: ParsedSystem) -> dict:
    """PnL per anno (attribuito alla data di uscita) + n trade per anno."""
    by_year: dict[str, dict] = {}
    for t in ps.trades:
        y = str(t.exit_date.year)
        d = by_year.setdefault(y, {'pnl': 0.0, 'n': 0})
        d['pnl'] += t.pnl
        d['n'] += 1
    for d in by_year.values():
        d['pnl'] = round(d['pnl'], 2)
    return by_year


def check_fingerprints(
    systems: list[ParsedSystem],
    baseline_path: Path,
    current_year: int | None = None,
) -> tuple[list, list, dict]:
    """
    Confronta i sistemi con la baseline e la aggiorna.

    Returns:
        (mutations, new_systems, updated_baseline)
        mutations:   list[(system_name, reason)] — storico mutato → quarantena
        new_systems: list[system_name] — baseline creata ora (informativo)
    """
    current_year = current_year or datetime.now(timezone.utc).year

    baseline: dict = {}
    if baseline_path.exists():
        try:
            baseline = json.loads(baseline_path.read_text(encoding='utf-8')).get('systems', {})
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Baseline fingerprint illeggibile ({e}): verrà ricreata.")

    mutations: list[tuple[str, str]] = []
    new_systems: list[str] = []
    updated: dict = {}

    for ps in systems:
        fp = compute_fingerprint(ps)
        name = ps.system_name

        if name not in baseline:
            new_systems.append(name)
            updated[name] = fp
            continue

        base = baseline[name]
        diffs = []
        for year, vals in base.items():
            if int(year) >= current_year:
                continue  # l'anno corrente può cambiare (trade nuovi)
            cur = fp.get(year)
            if cur is None:
                diffs.append(f"{year}: {vals['n']} trade ({vals['pnl']:+,.0f}$) SPARITI")
            elif abs(cur['pnl'] - vals['pnl']) > TOLERANCE_USD or cur['n'] != vals['n']:
                diffs.append(
                    f"{year}: PnL {vals['pnl']:+,.0f}$→{cur['pnl']:+,.0f}$, "
                    f"trade {vals['n']}→{cur['n']}"
                )

        if diffs:
            reason = ("STORICO MUTATO rispetto alla baseline — file rigenerato da "
                      "configurazione diversa (timeframe/workspace/size)? Dettaglio: "
                      + "; ".join(diffs[:4]))
            mutations.append((name, reason))
            # NON aggiorna la baseline: resta quella buona finché non
            # viene ripristinato il file corretto (o ri-approvata con verify.py)
            updated[name] = base
        else:
            # storico coerente → aggiorna con anno corrente che cresce
            updated[name] = fp

    # sistemi presenti in baseline ma assenti oggi: mantieni la baseline
    for name, fp in baseline.items():
        if name not in updated:
            updated[name] = fp

    return mutations, new_systems, updated


def save_fingerprints(baseline_path: Path, systems_fp: dict) -> None:
    payload = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'note': 'Baseline immutabilità storico. Per ri-approvare un sistema '
                'dopo una correzione voluta: python src/verify.py --approve NomeSistema',
        'systems': systems_fp,
    }
    baseline_path.parent.mkdir(exist_ok=True)
    baseline_path.write_text(json.dumps(payload, indent=1), encoding='utf-8')
    logger.info(f"Fingerprint aggiornate: {baseline_path}")
