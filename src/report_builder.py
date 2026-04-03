# ============================================================
# report_builder.py — Generatore email HTML notturna
# ============================================================
# Costruisce il report HTML completo da inviare ogni notte.
# Il formato è una email HTML responsive con:
#   - Header con data e sommario esecutivo
#   - Esposizione aggregata per famiglia (v2.0)
#   - Tabella principale ordinata per urgenza del segnale
#   - Color-coding per moltiplicatore
#   - Colonna EV condizionale (v2.0)
#   - Indicatore di cambio rispetto alla sessione precedente
#   - Footer con metodologia
# ============================================================

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

from streak_engine import SystemAnalysis


# ─────────────────────────────────────────────
# Mappatura colori per moltiplicatore
# ─────────────────────────────────────────────

MULT_COLORS = {
    2.0: {"bg": "#0d47a1", "text": "#e3f2fd", "badge_bg": "#1565c0", "label": "2×"},
    1.5: {"bg": "#1b5e20", "text": "#e8f5e9", "badge_bg": "#2e7d32", "label": "1.5×"},
    1.0: {"bg": "#212121", "text": "#eeeeee", "badge_bg": "#424242", "label": "1×"},
    0.5: {"bg": "#bf360c", "text": "#fbe9e7", "badge_bg": "#d84315", "label": "0.5×"},
}

CONFIDENCE_ICONS = {
    "High":   "🟢",
    "Medium": "🟡",
    "Low":    "🔴",
}

STREAK_ICONS = {
    "W": "📈",
    "L": "📉",
}


# ─────────────────────────────────────────────
# Ordinamento righe per urgenza
# ─────────────────────────────────────────────

def _sort_key(a: SystemAnalysis) -> tuple:
    """
    Ordina i sistemi per priorità operativa:
    1. Sistemi con moltiplicatore cambiato → in cima
    2. Poi per moltiplicatore: 2x e 0.5x prima (segnali forti), poi 1.5x, poi 1x
    3. Poi per confidenza: High prima
    4. Poi per nome sistema
    """
    mult_priority = {2.0: 0, 0.5: 1, 1.5: 2, 1.0: 3}
    conf_priority = {"High": 0, "Medium": 1, "Low": 2}

    return (
        0 if a.multiplier_changed else 1,
        mult_priority.get(a.multiplier, 9),
        conf_priority.get(a.confidence, 9),
        a.system_name,
    )


# ─────────────────────────────────────────────
# Costruzione HTML
# ─────────────────────────────────────────────

def _summary_pills(analyses: list[SystemAnalysis]) -> str:
    """Genera le pillole di sommario nel header."""
    counts = {2.0: 0, 1.5: 0, 1.0: 0, 0.5: 0}
    for a in analyses:
        counts[a.multiplier] = counts.get(a.multiplier, 0) + 1

    changed = sum(1 for a in analyses if a.multiplier_changed)

    pills_html = ""
    for mult, cnt in [(2.0, counts[2.0]), (1.5, counts[1.5]),
                       (1.0, counts[1.0]), (0.5, counts[0.5])]:
        if cnt == 0:
            continue
        c = MULT_COLORS[mult]
        pills_html += f"""
        <span style="
            display:inline-block;
            background:{c['badge_bg']};
            color:{c['text']};
            padding:6px 14px;
            border-radius:20px;
            font-size:14px;
            font-weight:bold;
            margin:4px;
        ">{MULT_COLORS[mult]['label']} &nbsp;{cnt} sistemi</span>"""

    changed_html = ""
    if changed > 0:
        changed_html = f"""
        <span style="
            display:inline-block;
            background:#f57f17;
            color:#fff8e1;
            padding:6px 14px;
            border-radius:20px;
            font-size:14px;
            font-weight:bold;
            margin:4px;
        ">⚡ {changed} cambio/i rispetto a ieri</span>"""

    return pills_html + changed_html


def _portfolio_exposure(analyses: list[SystemAnalysis]) -> str:
    """
    v2.0 — Genera la sezione di esposizione aggregata per famiglia.
    Mostra la somma dei moltiplicatori per ogni famiglia di sistemi,
    evidenziando le famiglie con esposizione concentrata.
    """
    family_data = defaultdict(lambda: {"total_mult": 0.0, "count": 0, "open": 0})

    for a in analyses:
        fam = a.family
        family_data[fam]["total_mult"] += a.multiplier
        family_data[fam]["count"] += 1
        if a.has_open_position:
            family_data[fam]["open"] += 1

    # Ordina per esposizione totale decrescente
    sorted_families = sorted(family_data.items(), key=lambda x: x[1]["total_mult"], reverse=True)

    rows = ""
    for fam, d in sorted_families:
        avg_mult = d["total_mult"] / d["count"] if d["count"] > 0 else 1.0

        # Color-code basato sull'esposizione media
        if avg_mult >= 1.5:
            bar_color = "#1565c0"
        elif avg_mult <= 0.7:
            bar_color = "#d84315"
        else:
            bar_color = "#424242"

        # Barra proporzionale (max = 2x * n_sistemi, ma normalizziamo su avg)
        bar_width = min(avg_mult / 2.0 * 100, 100)

        rows += f"""
        <tr style="border-bottom:1px solid #2a2a4a;">
          <td style="padding:8px 12px;color:#e0e0e0;font-size:13px;font-weight:600;">
            {fam}
          </td>
          <td style="padding:8px 12px;color:#aaa;font-size:12px;text-align:center;">
            {d['count']}
          </td>
          <td style="padding:8px 12px;color:#e0e0e0;font-size:13px;text-align:center;font-weight:bold;">
            {d['total_mult']:.1f}×
          </td>
          <td style="padding:8px 12px;color:#aaa;font-size:12px;text-align:center;">
            {avg_mult:.2f}×
          </td>
          <td style="padding:8px 12px;text-align:center;">
            <div style="background:#333;border-radius:4px;height:8px;width:80px;display:inline-block;">
              <div style="background:{bar_color};height:8px;border-radius:4px;width:{bar_width:.0f}%;"></div>
            </div>
          </td>
          <td style="padding:8px 12px;color:#ffcc02;font-size:12px;text-align:center;">
            {d['open'] if d['open'] > 0 else '–'}
          </td>
        </tr>"""

    return f"""
    <tr>
      <td style="padding:16px 16px 0 16px;">
        <div style="color:#90caf9;font-size:13px;letter-spacing:1px;
                    text-transform:uppercase;margin-bottom:8px;padding:0 16px;">
          📋 Esposizione per famiglia
        </div>
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border-collapse:collapse;margin-bottom:16px;">
          <thead>
            <tr style="background:#0d0d1f;">
              <th style="padding:6px 12px;text-align:left;color:#666;font-size:10px;
                         letter-spacing:1px;text-transform:uppercase;">Famiglia</th>
              <th style="padding:6px 12px;text-align:center;color:#666;font-size:10px;
                         letter-spacing:1px;text-transform:uppercase;">Sistemi</th>
              <th style="padding:6px 12px;text-align:center;color:#666;font-size:10px;
                         letter-spacing:1px;text-transform:uppercase;">Esp. Totale</th>
              <th style="padding:6px 12px;text-align:center;color:#666;font-size:10px;
                         letter-spacing:1px;text-transform:uppercase;">Media</th>
              <th style="padding:6px 12px;text-align:center;color:#666;font-size:10px;
                         letter-spacing:1px;text-transform:uppercase;">Livello</th>
              <th style="padding:6px 12px;text-align:center;color:#666;font-size:10px;
                         letter-spacing:1px;text-transform:uppercase;">Aperte</th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </td>
    </tr>"""


def _table_row(a: SystemAnalysis) -> str:
    """Genera una riga HTML della tabella principale."""
    c = MULT_COLORS.get(a.multiplier, MULT_COLORS[1.0])
    conf_icon = CONFIDENCE_ICONS.get(a.confidence, "⚪")
    streak_icon = STREAK_ICONS.get(a.current_streak_type, "")
    changed_marker = " ⚡" if a.multiplier_changed else ""
    override_marker = " ⚙️" if a.is_override else ""

    # Indicatore streak: "3L" o "2W" ecc.
    streak_label = (
        f"{a.current_streak_len}{a.current_streak_type}"
        if a.current_streak_type != "N/A" else "N/A"
    )

    # Badge moltiplicatore
    mult_badge = f"""
    <span style="
        background:{c['badge_bg']};
        color:{c['text']};
        padding:4px 10px;
        border-radius:12px;
        font-weight:bold;
        font-size:15px;
    ">{c['label']}</span>"""

    # Posizione aperta
    position_html = (
        '<span style="color:#ffcc02;font-size:12px;">● APERTA</span>'
        if a.has_open_position
        else '<span style="color:#666;font-size:12px;">– –</span>'
    )

    # Cambio rispetto a ieri
    if a.multiplier_changed:
        prev_c = MULT_COLORS.get(a.prev_multiplier, MULT_COLORS[1.0])
        change_html = f"""
        <span style="color:{prev_c['badge_bg']};font-size:12px;">
            {prev_c['label']}
        </span>
        <span style="color:#888;">→</span>
        <span style="color:{c['badge_bg']};font-size:12px;font-weight:bold;">
            {c['label']}
        </span>"""
    else:
        change_html = '<span style="color:#555;font-size:12px;">—</span>'

    # EV condizionale (v2.0) — colore basato sul segno
    ev_val = a.ev_per_trade
    if ev_val > 0:
        ev_color = "#4caf50"
        ev_sign  = "+"
    elif ev_val < 0:
        ev_color = "#f44336"
        ev_sign  = ""
    else:
        ev_color = "#666"
        ev_sign  = ""

    row_bg = c['bg']

    return f"""
    <tr style="background:{row_bg}; border-bottom:1px solid #333;">
        <td style="padding:10px 12px; color:{c['text']}; font-weight:600; font-size:13px;">
            {a.system_name}{changed_marker}{override_marker}
        </td>
        <td style="padding:10px 12px; color:{c['text']}; text-align:center; font-size:13px;">
            {a.symbol}
        </td>
        <td style="padding:10px 12px; color:{c['text']}; text-align:center; font-size:13px;">
            {streak_icon} {streak_label}
        </td>
        <td style="padding:10px 12px; color:{c['text']}; text-align:center; font-size:13px;">
            {a.p_win_given_streak:.1%}
            <br><span style="color:#888;font-size:10px;">
                [{a.ci_lower_80:.0%}–{a.ci_upper_80:.0%}]
            </span>
        </td>
        <td style="padding:10px 12px; text-align:center; color:{ev_color}; font-size:13px;">
            {ev_sign}{ev_val:.0f}$
            <br><span style="color:#888;font-size:10px;">
                HK {a.half_kelly:.0%}
            </span>
        </td>
        <td style="padding:10px 12px; text-align:center;">
            {conf_icon} {a.confidence}
            <br><span style="color:#888;font-size:10px;">n={a.n_obs_for_streak}</span>
        </td>
        <td style="padding:10px 12px; text-align:center;">
            {mult_badge}
        </td>
        <td style="padding:10px 12px; text-align:center;">
            {position_html}
        </td>
        <td style="padding:10px 12px; text-align:center;">
            {change_html}
        </td>
    </tr>"""


def build_html_email(
    analyses: list[SystemAnalysis],
    run_date: Optional[datetime] = None,
) -> str:
    """
    Costruisce l'email HTML completa da inviare.

    Args:
        analyses: lista di SystemAnalysis (uno per sistema)
        run_date: data/ora della run (default = ora UTC)

    Returns:
        Stringa HTML completa dell'email
    """
    if run_date is None:
        from datetime import timezone
        run_date = datetime.now(timezone.utc)

    date_str = run_date.strftime('%d %B %Y — %H:%M UTC')

    # Ordina i sistemi per urgenza operativa
    sorted_analyses = sorted(analyses, key=_sort_key)

    summary    = _summary_pills(sorted_analyses)
    exposure   = _portfolio_exposure(sorted_analyses)
    rows       = "".join(_table_row(a) for a in sorted_analyses)

    n_total    = len(sorted_analyses)
    n_active   = sum(1 for a in sorted_analyses if a.multiplier != 1.0)
    n_open_pos = sum(1 for a in sorted_analyses if a.has_open_position)

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Streak Monitor — Report Notturno</title>
</head>
<body style="margin:0;padding:0;background:#0f0f1a;font-family:Arial,Helvetica,sans-serif;">

<!-- WRAPPER -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0f0f1a;">
<tr><td align="center" style="padding:24px 12px;">

<!-- CARD PRINCIPALE -->
<table width="960" cellpadding="0" cellspacing="0"
       style="max-width:960px;background:#1a1a2e;border-radius:12px;
              border:1px solid #2a2a4a;overflow:hidden;">

  <!-- HEADER -->
  <tr>
    <td style="background:linear-gradient(135deg,#1a237e,#0d47a1);
               padding:28px 32px;">
      <table width="100%"><tr>
        <td>
          <div style="color:#90caf9;font-size:12px;letter-spacing:2px;
                      text-transform:uppercase;margin-bottom:4px;">
            Kriterion Quant · Streak Monitor
          </div>
          <div style="color:#ffffff;font-size:24px;font-weight:bold;">
            📊 Report Notturno
          </div>
          <div style="color:#bbdefb;font-size:14px;margin-top:6px;">
            {date_str}
          </div>
        </td>
        <td style="text-align:right;vertical-align:top;">
          <div style="color:#e3f2fd;font-size:13px;line-height:1.8;">
            Sistemi analizzati: <strong>{n_total}</strong><br>
            Segnali attivi: <strong>{n_active}</strong><br>
            Posizioni aperte: <strong>{n_open_pos}</strong>
          </div>
        </td>
      </tr></table>
    </td>
  </tr>

  <!-- SOMMARIO PILLOLE -->
  <tr>
    <td style="padding:16px 32px;background:#12122a;border-bottom:1px solid #2a2a4a;">
      <div style="font-size:13px;color:#888;margin-bottom:8px;">
        Distribuzione moltiplicatori
      </div>
      {summary}
    </td>
  </tr>

  <!-- ESPOSIZIONE PER FAMIGLIA (v2.0) -->
  {exposure}

  <!-- TABELLA SISTEMI -->
  <tr>
    <td style="padding:0 16px 16px 16px;">
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border-collapse:collapse;margin-top:16px;border-radius:8px;overflow:hidden;">

        <!-- INTESTAZIONE COLONNE -->
        <thead>
          <tr style="background:#0d0d1f;">
            <th style="padding:10px 12px;text-align:left;color:#90caf9;
                       font-size:11px;letter-spacing:1px;text-transform:uppercase;
                       border-bottom:2px solid #1565c0;">Sistema</th>
            <th style="padding:10px 12px;text-align:center;color:#90caf9;
                       font-size:11px;letter-spacing:1px;text-transform:uppercase;
                       border-bottom:2px solid #1565c0;">Ticker</th>
            <th style="padding:10px 12px;text-align:center;color:#90caf9;
                       font-size:11px;letter-spacing:1px;text-transform:uppercase;
                       border-bottom:2px solid #1565c0;">Streak</th>
            <th style="padding:10px 12px;text-align:center;color:#90caf9;
                       font-size:11px;letter-spacing:1px;text-transform:uppercase;
                       border-bottom:2px solid #1565c0;">P(W|streak)</th>
            <th style="padding:10px 12px;text-align:center;color:#90caf9;
                       font-size:11px;letter-spacing:1px;text-transform:uppercase;
                       border-bottom:2px solid #1565c0;">EV | Kelly</th>
            <th style="padding:10px 12px;text-align:center;color:#90caf9;
                       font-size:11px;letter-spacing:1px;text-transform:uppercase;
                       border-bottom:2px solid #1565c0;">Confidenza</th>
            <th style="padding:10px 12px;text-align:center;color:#90caf9;
                       font-size:11px;letter-spacing:1px;text-transform:uppercase;
                       border-bottom:2px solid #1565c0;">Moltiplicatore</th>
            <th style="padding:10px 12px;text-align:center;color:#90caf9;
                       font-size:11px;letter-spacing:1px;text-transform:uppercase;
                       border-bottom:2px solid #1565c0;">Posizione</th>
            <th style="padding:10px 12px;text-align:center;color:#90caf9;
                       font-size:11px;letter-spacing:1px;text-transform:uppercase;
                       border-bottom:2px solid #1565c0;">Δ Ieri</th>
          </tr>
        </thead>

        <!-- RIGHE SISTEMI -->
        <tbody>
          {rows}
        </tbody>

      </table>
    </td>
  </tr>

  <!-- LEGENDA -->
  <tr>
    <td style="padding:12px 32px;background:#12122a;border-top:1px solid #2a2a4a;">
      <div style="color:#666;font-size:11px;line-height:1.8;">
        <strong style="color:#888;">Legenda moltiplicatori:</strong>
        &nbsp;
        <span style="color:#1565c0;">■</span> 2× (segnale forte, confidenza alta) &nbsp;|&nbsp;
        <span style="color:#2e7d32;">■</span> 1.5× (segnale positivo) &nbsp;|&nbsp;
        <span style="color:#424242;">■</span> 1× (neutro) &nbsp;|&nbsp;
        <span style="color:#d84315;">■</span> 0.5× (segnale difensivo)
        &nbsp;|&nbsp; ⚙️ = override manuale
        <br>
        <strong style="color:#888;">Confidenza:</strong>
        🟢 Alta (≥15 osservazioni) &nbsp;|&nbsp;
        🟡 Media (5-14 obs) &nbsp;|&nbsp;
        🔴 Bassa (&lt;5 obs, sempre 1×)
        <br>
        <strong style="color:#888;">EV|Kelly:</strong>
        Expected Value condizionale alla streak (USD) e Half-Kelly fraction.
        <br>
        <strong style="color:#888;">Metodologia:</strong>
        Bayesiano Beta-Binomiale con Laplace smoothing e decay temporale.
        P(W|streak) = stima posteriore con prior uniforme Beta(1,1).
        CI 80% = intervallo credibile [10°,90° percentile].
        EV = P(W)×avg_win − P(L)×|avg_loss|.
      </div>
    </td>
  </tr>

  <!-- FOOTER -->
  <tr>
    <td style="padding:16px 32px;text-align:center;">
      <div style="color:#444;font-size:11px;">
        Generato automaticamente da Streak Monitor v2.0 — Kriterion Quant
        <br>
        Dati aggiornati da MultiCharts via Google Drive
      </div>
    </td>
  </tr>

</table>
<!-- END CARD -->

</td></tr>
</table>
<!-- END WRAPPER -->

</body>
</html>"""

    return html
