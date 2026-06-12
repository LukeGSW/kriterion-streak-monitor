# ============================================================
# notify_failure.py — Alert email se la run trimestrale fallisce
# ============================================================
# Invocato dalla GitHub Action solo con `if: failure()`.
# Manda un'email minimale così il silenzio non viene mai
# scambiato per un "tutto ok": se al 1° del trimestre non
# arriva né il report né questo alert, controllare GitHub.
# ============================================================

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from notifier import send_report


def main() -> int:
    run_url = os.environ.get('GITHUB_RUN_URL', 'GitHub → repository → Actions')
    now = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;
                background:#0a0e1a;padding:24px;border-radius:10px">
      <h2 style="color:#ef4444;margin:0 0 10px">❌ Portfolio Allocator — run trimestrale FALLITA</h2>
      <p style="color:#f1f5f9;font-size:14px;line-height:1.6">
        La run del {now} non è andata a buon fine:
        <b>nessun report e nessun peso sono stati generati questo trimestre.</b>
      </p>
      <p style="color:#94a3b8;font-size:13px;line-height:1.6">
        Cause comuni: credenziali Drive scadute, App Password Gmail revocata,
        formato CSV cambiato, cartella Drive vuota.<br>
        Log completi: <a href="{run_url}" style="color:#3b82f6">{run_url}</a>
      </p>
      <p style="color:#94a3b8;font-size:13px">
        Dopo aver risolto, rilancia manualmente: GitHub → Actions →
        Portfolio Allocator → <b>Run workflow</b>.
      </p>
    </div>"""

    date_str = datetime.now(timezone.utc).strftime('%d/%m/%Y')
    ok = send_report(html, subject=f"❌ Portfolio Allocator — RUN FALLITA {date_str}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
