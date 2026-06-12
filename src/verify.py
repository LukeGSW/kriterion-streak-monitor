# ============================================================
# verify.py — Riconciliazione equity Drive ↔ MultiCharts
# ============================================================
# Scopo: essere CERTI che i CSV su Drive siano la stessa equity
# che vedi su MultiCharts, prima di usare qualsiasi peso.
#
# Per ogni sistema stampa i numeri da confrontare 1:1 con lo
# Strategy Performance Report di MultiCharts:
#   - Total Net Profit  (somma PnL del CSV)
#   - Total # of Trades
#   - primo/ultimo trade
#   - "impronta timeframe": % di entrate a minuto :00
#     (un sistema su dati minuto con 100% di entrate a ore esatte
#      è quasi certamente esportato dal chart sbagliato)
#
# Uso:
#   python src/verify.py                      → legge da Drive
#   python src/verify.py --local /path/csv    → legge da cartella
#   python src/verify.py --approve            → dopo il confronto
#       manuale, salva questi dati come baseline di immutabilità
#       (output/fingerprints.json)
#   python src/verify.py --approve NomeSistema → ri-approva solo
#       un sistema (es. dopo una correzione voluta dell'export)
# ============================================================

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from parser import parse_system_csv
from fingerprint import compute_fingerprint, save_fingerprints

logging.basicConfig(level=logging.WARNING)

ROOT = Path(__file__).parent.parent
FP_PATH = ROOT / 'output' / 'fingerprints.json'
CONFIG_FILE = ROOT / 'config' / 'settings.yaml'


def load_settings() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', default=None, help='cartella CSV locale (salta Drive)')
    ap.add_argument('--approve', nargs='?', const='ALL', default=None,
                    help='salva baseline immutabilità (tutti o singolo sistema)')
    args = ap.parse_args()

    settings = load_settings()
    norm = settings.get('size_normalization') or {}

    # ── carica CSV
    if args.local:
        raw = {}
        for p in sorted(Path(args.local).glob('*.csv')):
            if not p.name.endswith('_Open.csv'):
                raw[p.stem] = p.read_text(encoding='utf-8-sig', errors='replace')
    else:
        from drive_fetcher import fetch_all_closed_csvs
        raw = fetch_all_closed_csvs(settings.get('drive', {}).get('folder_id', ''))

    if not raw:
        print('Nessun CSV trovato.')
        return 1

    systems = []
    for name, content in sorted(raw.items()):
        ps = parse_system_csv(content, name, size_factor=float(norm.get(name, 1.0)))
        if ps:
            systems.append(ps)

    # ── foglio di riconciliazione
    print()
    print('FOGLIO DI RICONCILIAZIONE — confronta con MultiCharts Strategy Performance Report')
    print('(Net Profit e # Trades devono coincidere; %@:00 alta su sistemi a dati minuto = export dal chart sbagliato)')
    print()
    hdr = (f'{"SISTEMA":32} {"NET PROFIT $":>13} {"# TRADE":>8} {"PRIMO":>11} '
           f'{"ULTIMO":>11} {"%@:00":>6} {"DUP":>4} {"NORM":>5}')
    print(hdr)
    print('-' * len(hdr))
    for ps in systems:
        net = sum(t.pnl for t in ps.trades)
        at00 = sum(1 for t in ps.trades
                   if t.entry_date.minute == 0) / ps.n_trades * 100
        factor = float(norm.get(ps.system_name, 1.0))
        print(f'{ps.system_name:32} {net:13,.2f} {ps.n_trades:8d} '
              f'{ps.trades[0].exit_date.strftime("%Y-%m-%d"):>11} '
              f'{ps.trades[-1].exit_date.strftime("%Y-%m-%d"):>11} '
              f'{at00:5.0f}% {ps.n_dupes:4d} '
              f'{"×" + str(factor) if factor != 1.0 else "—":>5}')

    # nota: se è attiva una normalizzazione, il Net Profit stampato è già
    # scalato — per il confronto con MultiCharts usare il fattore inverso.
    if any(float(norm.get(ps.system_name, 1.0)) != 1.0 for ps in systems):
        print('\nNB: per i sistemi con NORM attiva, il Net Profit sopra è già scalato; '
              'su MultiCharts vedrai il valore non scalato.')

    # ── approvazione baseline
    if args.approve:
        import json
        existing = {}
        if FP_PATH.exists():
            try:
                existing = json.loads(FP_PATH.read_text(encoding='utf-8')).get('systems', {})
            except Exception:
                pass

        if args.approve == 'ALL':
            to_save = {ps.system_name: compute_fingerprint(ps) for ps in systems}
            existing.update(to_save)
            save_fingerprints(FP_PATH, existing)
            print(f'\n✅ Baseline approvata per {len(to_save)} sistemi → {FP_PATH}')
            print('   Commit e push del file per renderla attiva nelle run trimestrali.')
        else:
            target = [ps for ps in systems if ps.system_name == args.approve]
            if not target:
                print(f'\n❌ Sistema "{args.approve}" non trovato.')
                return 1
            existing[args.approve] = compute_fingerprint(target[0])
            save_fingerprints(FP_PATH, existing)
            print(f'\n✅ Baseline ri-approvata per {args.approve} → {FP_PATH}')
    else:
        print('\nQuando i numeri corrispondono a MultiCharts:')
        print('  python src/verify.py [--local DIR] --approve     → blocca la baseline')

    return 0


if __name__ == '__main__':
    sys.exit(main())
