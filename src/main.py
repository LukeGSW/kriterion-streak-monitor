# ============================================================
# main.py — Orchestratore Portfolio Allocator
# ============================================================
# Pipeline trimestrale:
#   1. Scarica TUTTI i CSV dalla cartella Drive (sistemi nuovi
#      inclusi automaticamente, nessuna lista hardcoded)
#   2. Parsa + deduplica + normalizza size
#   3. Sanity check → quarantena dati sospetti
#   4. Analisi allocazione (vol, correlazioni, risk contribution,
#      pesi inverse-vol, walk-forward)
#   5. Report HTML → email + salvataggio in output/
#
# Test locale senza Drive/email:
#   python src/main.py --local /percorso/cartella/csv --no-email
# ============================================================

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from parser import parse_system_csv
from sanity import run_sanity_checks
from portfolio import analyze
from report_builder import build_report, build_weights_yaml

logging.basicConfig(
    level=logging.DEBUG if os.environ.get('DEBUG_MODE') == 'true' else logging.INFO,
    format='%(asctime)s %(levelname)-7s %(name)s — %(message)s',
)
logger = logging.getLogger('main')

ROOT = Path(__file__).parent.parent
CONFIG_FILE = ROOT / 'config' / 'settings.yaml'
OUTPUT_DIR = ROOT / 'output'


def load_settings() -> dict:
    if not CONFIG_FILE.exists():
        logger.warning(f"settings.yaml non trovato in {CONFIG_FILE}. Uso defaults.")
        return {}
    with open(CONFIG_FILE, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def load_csvs_local(folder: str) -> dict[str, str]:
    """Modalità test: legge i CSV da una cartella locale."""
    out = {}
    for p in sorted(Path(folder).glob('*.csv')):
        if p.name.endswith('_Open.csv'):
            continue
        out[p.stem] = p.read_text(encoding='utf-8-sig', errors='replace')
    logger.info(f"Caricati {len(out)} CSV da {folder}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', help='cartella locale CSV (salta Drive)', default=None)
    ap.add_argument('--no-email', action='store_true', help='non inviare email')
    args = ap.parse_args()

    settings = load_settings()

    # ── 1. Acquisizione dati
    if args.local:
        raw = load_csvs_local(args.local)
    else:
        from drive_fetcher import fetch_all_closed_csvs
        folder_id = settings.get('drive', {}).get('folder_id', '')
        raw = fetch_all_closed_csvs(folder_id)

    if not raw:
        logger.error("Nessun CSV disponibile: pipeline interrotta.")
        return 1

    # ── 2. Parsing + dedup + normalizzazione size
    norm = settings.get('size_normalization') or {}
    parsed = {}
    for name, content in raw.items():
        factor = float(norm.get(name, 1.0))
        if factor != 1.0:
            logger.info(f"{name}: normalizzazione size ×{factor}")
        ps = parse_system_csv(content, name, size_factor=factor)
        if ps:
            parsed[name] = ps

    logger.info(f"Sistemi parsati: {len(parsed)}")

    # ── 3. Sanity / quarantena
    sanity = run_sanity_checks(parsed, settings.get('sanity', {}))
    if not sanity.ok:
        logger.error("Nessun sistema supera i sanity check: pipeline interrotta.")
        return 1

    # ── 4. Analisi
    result = analyze(sanity.ok, settings)
    logger.info(
        "Pesi consigliati: "
        + ', '.join(f"{c}={result.weights_rec[c]:.2f}"
                    for c in result.weights_rec.index)
    )

    # ── 5. Report + output
    html = build_report(result, sanity, settings)
    weights_yaml = build_weights_yaml(result, sanity)

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc)
    quarter = f"{stamp.year}-Q{(stamp.month - 1) // 3 + 1}"
    report_path = OUTPUT_DIR / f'report_{quarter}.html'
    weights_path = OUTPUT_DIR / 'weights_proposed.yaml'
    report_path.write_text(html, encoding='utf-8')
    weights_path.write_text(weights_yaml, encoding='utf-8')
    logger.info(f"Output salvati: {report_path.name}, {weights_path.name}")

    # ── 6. Email
    if not args.no_email:
        from notifier import send_report
        subject = settings.get('email', {}).get(
            'subject', '📊 Portfolio Allocator — Report Trimestrale')
        subject = f"{subject} — {quarter}"
        ok = send_report(html, subject,
                         attachments={report_path.name: html,
                                      'weights_proposed.yaml': weights_yaml})
        if not ok:
            logger.error("Invio email fallito (report comunque salvato in output/).")
            return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
