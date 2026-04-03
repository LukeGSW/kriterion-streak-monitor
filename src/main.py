# ============================================================
# main.py — Orchestratore della run notturna
# ============================================================
# Punto di ingresso del sistema. Coordina tutti i moduli:
#   1. Download CSV da Google Drive
#   2. Parsing di ogni sistema
#   3. Analisi streak Bayesiana (con EV e decay)
#   4. Costruzione email HTML
#   5. Invio email
#   6. Salvataggio state.json + storico giornaliero
#
# Eseguito automaticamente dalla GitHub Action ogni notte.
# Può essere eseguito manualmente da terminale per test.
# ============================================================

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Aggiungi src/ al path se eseguito da root del repo
sys.path.insert(0, str(Path(__file__).parent))

from drive_fetcher  import fetch_all_systems
from parser         import build_system_data
from streak_engine  import analyze_system, DEFAULT_THRESHOLDS
from report_builder import build_html_email
from notifier       import send_report

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

logging.basicConfig(
    level   = logging.INFO,
    format  = '%(asctime)s [%(levelname)s] %(name)s — %(message)s',
    datefmt = '%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("main")

# ─────────────────────────────────────────────
# Percorsi fissi
# ─────────────────────────────────────────────

REPO_ROOT    = Path(__file__).parent.parent
STATE_FILE   = REPO_ROOT / "state" / "system_state.json"
HISTORY_DIR  = REPO_ROOT / "state" / "history"
CONFIG_FILE  = REPO_ROOT / "config" / "settings.yaml"


# ─────────────────────────────────────────────
# Caricamento configurazione
# ─────────────────────────────────────────────

def load_config() -> dict:
    """Legge settings.yaml e ritorna il dizionario di configurazione."""
    if not CONFIG_FILE.exists():
        logger.warning(f"settings.yaml non trovato in {CONFIG_FILE}. Uso defaults.")
        return {}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def load_previous_state() -> dict:
    """Carica lo state.json della notte precedente."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_state(analyses: list, run_date: datetime) -> None:
    """Serializza i risultati dell'analisi in state.json."""
    state = {
        "last_updated": run_date.isoformat(),
        "systems": {}
    }

    for a in analyses:
        state["systems"][a.system_name] = {
            "symbol":               a.symbol,
            "family":               a.family,
            "n_trades":             a.n_trades,
            "win_rate":             round(a.win_rate, 4),
            "avg_win_usd":          round(a.avg_win_usd, 2),
            "avg_loss_usd":         round(a.avg_loss_usd, 2),
            "profit_factor":        round(a.profit_factor, 3),
            "streak_type":          a.current_streak_type,
            "streak_len":           a.current_streak_len,
            "n_obs_for_streak":     a.n_obs_for_streak,
            "n_wins_after_streak":  a.n_wins_after_streak,
            "p_win_given_streak":   round(a.p_win_given_streak, 4),
            "ci_lower_80":          round(a.ci_lower_80, 4),
            "ci_upper_80":          round(a.ci_upper_80, 4),
            # v2.0 — nuovi campi
            "ev_per_trade":         round(a.ev_per_trade, 2),
            "ev_normalized":        round(a.ev_normalized, 4),
            "half_kelly":           round(a.half_kelly, 4),
            "is_override":          a.is_override,
            # campi esistenti
            "multiplier":           a.multiplier,
            "confidence":           a.confidence,
            "sizing_reason":        a.sizing_reason,
            "has_open_position":    a.has_open_position,
            "last_trade_date":      a.last_trade_date,
            "last_trade_result":    a.last_trade_result,
            "multiplier_changed":   a.multiplier_changed,
            "prev_multiplier":      a.prev_multiplier,
            "analyzed_at":          a.analyzed_at,
        }

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    logger.info(f"state.json salvato con {len(analyses)} sistemi")


def save_history_snapshot(analyses: list, run_date: datetime) -> None:
    """
    Salva uno snapshot giornaliero in state/history/YYYY-MM-DD.json
    per consentire analisi storiche nella dashboard.
    Contiene solo i campi essenziali per ridurre lo spazio.
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    date_str = run_date.strftime('%Y-%m-%d')
    snapshot_file = HISTORY_DIR / f"{date_str}.json"

    snapshot = {
        "date": date_str,
        "systems": {}
    }

    for a in analyses:
        snapshot["systems"][a.system_name] = {
            "symbol":       a.symbol,
            "family":       a.family,
            "multiplier":   a.multiplier,
            "p_win":        round(a.p_win_given_streak, 4),
            "ev_norm":      round(a.ev_normalized, 4),
            "confidence":   a.confidence,
            "streak":       f"{a.current_streak_len}{a.current_streak_type}",
            "has_open":     a.has_open_position,
            "is_override":  a.is_override,
        }

    with open(snapshot_file, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    logger.info(f"Snapshot storico salvato: {snapshot_file.name}")


# ─────────────────────────────────────────────
# Run principale
# ─────────────────────────────────────────────

def run() -> None:
    """Esegue la pipeline completa di analisi notturna."""
    run_date = datetime.now(timezone.utc)
    logger.info(f"{'='*60}")
    logger.info(f"Streak Monitor — Run {run_date.strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info(f"{'='*60}")

    # ── 1. Carica configurazione
    config     = load_config()
    folder_id  = config.get('drive', {}).get('folder_id', os.environ.get('DRIVE_FOLDER_ID'))
    thresholds = {**DEFAULT_THRESHOLDS, **config.get('sizing', {}).get('thresholds', {})}
    overrides  = config.get('overrides', {})

    if overrides:
        logger.info(f"Override attivi: {list(overrides.keys())}")

    if not folder_id:
        logger.error("folder_id Drive non configurato. Imposta drive.folder_id in settings.yaml.")
        sys.exit(1)

    # ── 2. Carica stato precedente
    prev_state = load_previous_state()
    logger.info(f"Stato precedente: {len(prev_state.get('systems', {}))} sistemi")

    # ── 3. Download CSV da Google Drive
    logger.info("Download CSV da Google Drive...")
    try:
        raw_systems = fetch_all_systems(folder_id)
    except Exception as e:
        logger.error(f"Errore accesso Google Drive: {e}")
        sys.exit(1)

    if not raw_systems:
        logger.error("Nessun sistema trovato su Drive. Interruzione.")
        sys.exit(1)

    # ── 4. Parsing + analisi per ogni sistema
    analyses = []
    skipped  = 0

    for system_name, contents in sorted(raw_systems.items()):
        logger.info(f"Analisi: {system_name}")

        system_data = build_system_data(
            system_name   = system_name,
            closed_content= contents['closed'],
            open_content  = contents.get('open'),
        )

        if system_data is None:
            logger.warning(f"  → {system_name} saltato (dati insufficienti)")
            skipped += 1
            continue

        analysis = analyze_system(
            data       = system_data,
            thresholds = thresholds,
            prev_state = prev_state,
            overrides  = overrides,
        )

        # analyze_system ritorna None se il sistema è disabilitato via override
        if analysis is None:
            skipped += 1
            continue

        analyses.append(analysis)

        # Log sintetico del risultato
        streak_str = f"{analysis.current_streak_len}{analysis.current_streak_type}"
        ovr_flag   = " [OVERRIDE]" if analysis.is_override else ""
        logger.info(
            f"  → Streak: {streak_str} | P(W)={analysis.p_win_given_streak:.1%} | "
            f"EV={analysis.ev_per_trade:+.1f}$ | "
            f"Mult: {analysis.multiplier}x | Conf: {analysis.confidence}"
            + (" [CAMBIATO]" if analysis.multiplier_changed else "")
            + ovr_flag
        )

    logger.info(f"\nAnalisi completata: {len(analyses)} sistemi | {skipped} saltati")

    if not analyses:
        logger.error("Nessun sistema analizzato con successo. Email non inviata.")
        sys.exit(1)

    # ── 5. Costruisci email HTML
    html_body = build_html_email(analyses, run_date)

    # ── 6. Salva state.json + snapshot storico
    #    (prima dell'email: se email fallisce lo stato è comunque salvato)
    save_state(analyses, run_date)
    save_history_snapshot(analyses, run_date)

    # ── 7. Invia email
    logger.info("Invio email notturna...")
    success = send_report(html_body)

    if success:
        logger.info("✅ Report inviato con successo")
    else:
        logger.error("❌ Invio email fallito — controlla le credenziali Gmail")

    # ── 8. Riepilogo finale
    changed    = [a for a in analyses if a.multiplier_changed]
    non_unit   = [a for a in analyses if a.multiplier != 1.0]
    open_pos   = [a for a in analyses if a.has_open_position]
    overridden = [a for a in analyses if a.is_override]

    logger.info(f"\n{'='*40}")
    logger.info(f"RIEPILOGO FINALE")
    logger.info(f"  Sistemi analizzati:  {len(analyses)}")
    logger.info(f"  Segnali attivi:      {len(non_unit)}")
    logger.info(f"  Cambio vs ieri:      {len(changed)}")
    logger.info(f"  Posizioni aperte:    {len(open_pos)}")
    logger.info(f"  Override manuali:    {len(overridden)}")
    if non_unit:
        logger.info(f"\n  Sistemi con segnale:")
        for a in sorted(non_unit, key=lambda x: x.multiplier, reverse=True):
            logger.info(f"    {a.system_name:30s} → {a.multiplier}× ({a.confidence})")
    logger.info(f"{'='*40}")


if __name__ == "__main__":
    run()
