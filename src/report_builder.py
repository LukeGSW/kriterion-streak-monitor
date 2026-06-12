# ============================================================
# report_builder.py — Report HTML trimestrale
# ============================================================
# HTML con stili interamente inline → renderizza correttamente
# sia in Gmail sia aperto nel browser. Niente JavaScript
# (Gmail lo blocca): i "grafici" sono barre CSS.
# ============================================================

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

# Palette Kriterion
BG, CARD, TXT, MUT = '#0a0e1a', '#1a2235', '#f1f5f9', '#94a3b8'
ACC, GOLD, POS, NEG = '#3b82f6', '#f59e0b', '#10b981', '#ef4444'

TD = f'padding:7px 9px;border-bottom:1px solid #1d2740;text-align:right;color:{TXT};font-size:13px'
TH = f'padding:7px 9px;border-bottom:1px solid #26314d;text-align:right;color:{MUT};font-size:11px;font-weight:600'


def _bar(value: float, max_value: float, color: str, label: str) -> str:
    pct = max(2, min(100, abs(value) / max_value * 100)) if max_value else 2
    return (f'<div style="background:#111827;border-radius:4px;height:16px;width:100%;margin:2px 0">'
            f'<div style="background:{color};height:16px;border-radius:4px;width:{pct:.0f}%;'
            f'font-size:10px;color:#fff;padding-left:6px;line-height:16px;white-space:nowrap">{label}</div></div>')


def _kpi(value: str, label: str) -> str:
    return (f'<td style="background:{CARD};border-radius:10px;padding:13px;vertical-align:top">'
            f'<div style="font-size:21px;font-weight:700;color:{GOLD}">{value}</div>'
            f'<div style="font-size:11px;color:{MUT};margin-top:3px">{label}</div></td>')


def build_report(result, sanity, settings: dict) -> str:
    """Costruisce il report HTML completo (email-safe)."""
    now = datetime.now(timezone.utc)
    stats = result.stats
    rc = result.risk_contrib
    wf = result.wf
    ptf = result.portfolio_stats
    fams = list(result.fam_monthly.columns)

    # ── Header e KPI
    top_rc = rc.index[0]
    html = f"""<!DOCTYPE html><html lang="it"><body style="margin:0;background:{BG};font-family:Arial,Helvetica,sans-serif;padding:20px">
<div style="max-width:980px;margin:auto">
<div style="color:{ACC};font-size:11px;letter-spacing:3px">KRITERION QUANT &middot; PORTFOLIO ALLOCATOR</div>
<h1 style="color:{TXT};font-size:22px;margin:6px 0 2px">&#128202; Report Allocazione Trimestrale</h1>
<div style="color:{MUT};font-size:12px">{now.strftime('%d %B %Y — %H:%M UTC')} &middot; {len(sanity.ok)} sistemi inclusi &middot; {len(fams)} famiglie &middot; {ptf['months']} mesi di storia</div>

<table width="100%" cellspacing="8" style="margin:16px 0"><tr>
{_kpi(f"{ptf['sharpe']:.2f}", 'Sharpe annualizzato portafoglio (pesi correnti)')}
{_kpi(f"{ptf['div_ratio']:.2f}", 'Diversification ratio (&Sigma; vol famiglie / vol portafoglio)')}
{_kpi(f"{rc.iloc[0]:.0%}", f'Rischio del maggior contributore ({top_rc})')}
{_kpi(f"{result.vol_rank_corr:.2f} / {result.sharpe_rank_corr:.2f}", 'Persistenza vol / Sharpe (rank-corr split-half)')}
</tr></table>"""

    # ── Quarantena e warning
    if sanity.quarantined:
        items = ''.join(f'<li><b>{n}</b>: {r}</li>' for n, r in sanity.quarantined)
        html += (f'<div style="background:#3a1515;border-left:4px solid {NEG};padding:11px 16px;'
                 f'border-radius:8px;margin:10px 0;color:{TXT};font-size:13px">'
                 f'<b>&#9888;&#65039; {len(sanity.quarantined)} sistemi in QUARANTENA (esclusi dal calcolo):</b>'
                 f'<ul style="margin:6px 0 0 16px;padding:0">{items}</ul></div>')
    if sanity.warnings:
        items = ''.join(f'<li><b>{n}</b>: {m}</li>' for n, m in sanity.warnings)
        html += (f'<div style="background:#3a2b10;border-left:4px solid {GOLD};padding:11px 16px;'
                 f'border-radius:8px;margin:10px 0;color:{TXT};font-size:13px">'
                 f'<b>Warning (inclusi nel calcolo):</b>'
                 f'<ul style="margin:6px 0 0 16px;padding:0">{items}</ul></div>')

    # ── Pesi consigliati (la sezione operativa, in alto)
    html += (f'<h2 style="color:{ACC};font-size:16px;margin:26px 0 10px;border-bottom:1px solid #26314d;'
             f'padding-bottom:6px">&#9878;&#65039; Pesi consigliati per famiglia (inverse-volatility)</h2>'
             f'<table width="100%" cellspacing="0"><tr>'
             f'<th style="{TH};text-align:left">Famiglia</th><th style="{TH}">Sistemi</th>'
             f'<th style="{TH}">Vol 24m $/mese</th><th style="{TH}">Peso esatto</th>'
             f'<th style="{TH}">Peso operativo</th><th style="{TH};text-align:left;width:28%">&nbsp;</th></tr>')
    recent_vol = result.fam_monthly.iloc[-24:].std()
    order = result.weights_rec.sort_values(ascending=False).index
    for c in order:
        w = result.weights_rec[c]
        color = POS if w > 1 else (NEG if w < 1 else MUT)
        note = ' (storia &lt; 12 mesi &rarr; default 1&times;)' if c in result.excluded else ''
        html += (f'<tr><td style="{TD};text-align:left">{c}{note}</td>'
                 f'<td style="{TD}">{len(result.fam_systems.get(c, []))}</td>'
                 f'<td style="{TD}">{recent_vol[c]:,.0f}</td>'
                 f'<td style="{TD}">{result.weights_iv[c]:.2f}</td>'
                 f'<td style="{TD};color:{color};font-weight:700">{w:.2f}&times;</td>'
                 f'<td style="{TD}">{_bar(w, 2.0, color, f"{w:.2f}")}</td></tr>')
    html += '</table>'

    # ── Contributo al rischio
    html += (f'<h2 style="color:{ACC};font-size:16px;margin:26px 0 10px;border-bottom:1px solid #26314d;'
             f'padding-bottom:6px">Contributo al rischio di portafoglio (pesi correnti 1&times;)</h2>'
             f'<table width="100%" cellspacing="0">')
    max_rc = max(abs(v) for v in rc.values)
    for c in rc.index:
        v = rc[c]
        color = NEG if v > 0.20 else (GOLD if v > 0.10 else POS)
        html += (f'<tr><td style="{TD};text-align:left;width:30%">{c}</td>'
                 f'<td style="{TD};width:10%">{v:.1%}</td>'
                 f'<td style="{TD}">{_bar(v, max_rc, color, f"{v:.0%}")}</td></tr>')
    html += '</table>'

    # ── Scoreboard famiglie
    html += (f'<h2 style="color:{ACC};font-size:16px;margin:26px 0 10px;border-bottom:1px solid #26314d;'
             f'padding-bottom:6px">Statistiche per famiglia (PnL mensili, USD)</h2>'
             f'<table width="100%" cellspacing="0"><tr><th style="{TH};text-align:left">Famiglia</th>'
             f'<th style="{TH}">PnL tot</th><th style="{TH}">Vol/mese</th><th style="{TH}">Sharpe ann.</th>'
             f'<th style="{TH}">MaxDD</th><th style="{TH}">% mesi +</th><th style="{TH}">Mesi attivi</th></tr>')
    for c in stats.sort_values('vol_m', ascending=False).index:
        r = stats.loc[c]
        sh_color = POS if r.sharpe_ann >= 1 else (GOLD if r.sharpe_ann >= 0.5 else NEG)
        html += (f'<tr><td style="{TD};text-align:left">{c}</td>'
                 f'<td style="{TD}">{r.pnl_total:,.0f}</td><td style="{TD}">{r.vol_m:,.0f}</td>'
                 f'<td style="{TD};color:{sh_color}">{r.sharpe_ann:.2f}</td>'
                 f'<td style="{TD};color:{NEG}">{r.max_dd:,.0f}</td>'
                 f'<td style="{TD}">{r.pct_pos_months}%</td><td style="{TD}">{r.months_active}</td></tr>')
    html += '</table>'

    # ── Correlazioni
    html += (f'<h2 style="color:{ACC};font-size:16px;margin:26px 0 10px;border-bottom:1px solid #26314d;'
             f'padding-bottom:6px">Correlazioni mensili tra famiglie</h2>'
             f'<table width="100%" cellspacing="0"><tr><th style="{TH}"></th>')
    short = [c[:10] for c in fams]
    for s in short:
        html += f'<th style="{TH};text-align:center">{s}</th>'
    html += '</tr>'
    cv = result.corr.values
    for i, c in enumerate(fams):
        html += f'<tr><td style="{TD};text-align:left;font-size:11px">{c}</td>'
        for j in range(len(fams)):
            v = cv[i][j]
            if i == j:
                cell_bg, label = '#26314d', '1.00'
            elif np.isnan(v):
                cell_bg, label = CARD, '–'
            else:
                a = min(abs(v), 1) * 0.85
                cell_bg = (f'rgba(16,185,129,{a:.2f})' if v > 0 else f'rgba(239,68,68,{a:.2f})')
                if abs(v) < 0.05:
                    cell_bg = CARD
                label = f'{v:+.2f}'
            html += (f'<td style="padding:5px 4px;text-align:center;font-size:10.5px;'
                     f'color:{TXT};background:{cell_bg};border-bottom:1px solid #1d2740">{label}</td>')
        html += '</tr>'
    html += '</table>'

    # coppie rilevanti
    pairs = []
    for i, a in enumerate(fams):
        for b in fams[i + 1:]:
            v = result.corr.loc[a, b]
            if not np.isnan(v) and abs(v) > 0.30:
                pairs.append(f'{a} / {b}: <b>{v:+.2f}</b>')
    if pairs:
        html += (f'<div style="color:{MUT};font-size:12px;margin:8px 0">Coppie con |r| &gt; 0.30: '
                 + ' &middot; '.join(pairs) + '</div>')

    # ── Walk-forward
    html += (f'<h2 style="color:{ACC};font-size:16px;margin:26px 0 10px;border-bottom:1px solid #26314d;'
             f'padding-bottom:6px">Validazione walk-forward (out-of-sample)</h2>')
    if wf.get('enough_data'):
        html += (f'<table width="100%" cellspacing="0"><tr><th style="{TH};text-align:left">Strategia pesi</th>'
                 f'<th style="{TH}">PnL</th><th style="{TH}">Vol/mese</th>'
                 f'<th style="{TH}">Sharpe</th><th style="{TH}">MaxDD</th></tr>')
        for lbl, key in [('Equal weight (1&times; tutte)', 'ew'), ('Inverse-vol (ricalcolo mensile)', 'iv')]:
            s = wf[key]
            html += (f'<tr><td style="{TD};text-align:left">{lbl}</td>'
                     f'<td style="{TD}">{s["pnl"]:,.0f}</td><td style="{TD}">{s["vol_m"]:,.0f}</td>'
                     f'<td style="{TD}">{s["sharpe"]:.2f}</td><td style="{TD};color:{NEG}">{s["max_dd"]:,.0f}</td></tr>')
        html += (f'</table><div style="color:{TXT};font-size:13px;line-height:1.6;margin:8px 0">'
                 f'Periodo OOS: {wf["period"]} ({wf["months_oos"]} mesi, ribilanciamento mensile, nessun dato futuro). '
                 f'Riduzione max drawdown: <b style="color:{POS}">{wf["dd_reduction_pct"]:.0f}%</b>. '
                 f'Probabilit&agrave; bootstrap che inverse-vol abbia Sharpe superiore: '
                 f'<b>{wf["p_iv_better"]:.0%}</b>.</div>')
    else:
        html += f'<div style="color:{MUT};font-size:13px">{wf.get("note", "dati insufficienti")}</div>'

    # ── Note metodologiche
    html += (f'<h2 style="color:{ACC};font-size:16px;margin:26px 0 10px;border-bottom:1px solid #26314d;'
             f'padding-bottom:6px">Note metodologiche</h2>'
             f'<div style="color:{MUT};font-size:11.5px;line-height:1.7">'
             f'PnL attribuiti alla data di uscita, USD a size costante (eventuale normalizzazione da settings). '
             f'Dedup per trade_id. Correlazioni pairwise (min 12 mesi comuni). '
             f'Contributo al rischio = decomposizione varianza di portafoglio. '
             f'Pesi inverse-vol su {settings.get("allocation", {}).get("lookback_months", 24)} mesi trailing, '
             f'cap [{settings.get("allocation", {}).get("weight_min", 0.5)}–'
             f'{settings.get("allocation", {}).get("weight_max", 2.0)}], gross invariato. '
             f'I pesi sono pesi di RISCHIO, non giudizi di qualit&agrave; dei sistemi: '
             f'la vol &egrave; persistente (rank-corr {result.vol_rank_corr}), lo Sharpe no '
             f'(rank-corr {result.sharpe_rank_corr}) — per questo non si pesa sui rendimenti passati. '
             f'Ricalibrare i pesi al massimo una volta a trimestre.</div>'
             f'<div style="color:{MUT};font-size:11px;text-align:center;margin:18px 0">'
             f'Generato automaticamente da Portfolio Allocator — Kriterion Quant</div>'
             f'</div></body></html>')

    return html


def build_weights_yaml(result, sanity) -> str:
    """
    YAML con i pesi consigliati, pronto per essere copiato nel money
    management o negli overrides dello Streak Monitor.
    """
    lines = [
        '# Pesi consigliati per famiglia — Portfolio Allocator',
        f'# Generato: {datetime.now(timezone.utc).isoformat()}',
        '# NB: pesi di rischio (inverse-volatility), non giudizi di qualità.',
        'weights:',
    ]
    for c in result.weights_rec.sort_values(ascending=False).index:
        lines.append(f'  {c}: {result.weights_rec[c]:.2f}')
    if sanity.quarantined:
        lines.append('quarantined:')
        for n, r in sanity.quarantined:
            lines.append(f'  {n}: "{r}"')
    return '\n'.join(lines) + '\n'
