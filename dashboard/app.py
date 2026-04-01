# ============================================================
# dashboard/app.py — Streamlit Dashboard Streak Monitor
# ============================================================
# Dashboard di consultazione on-demand.
# Legge state.json aggiornato ogni notte dalla GitHub Action.
# Nessun calcolo real-time: fonte unica = state.json.
#
# Deploy: Streamlit Cloud → connetti il repo GitHub.
# Secrets Streamlit (Settings → Secrets):
#   GITHUB_STATE_URL = "https://raw.githubusercontent.com/TUO_USER/streak-monitor/main/state/system_state.json"
#   GITHUB_TOKEN     = "ghp_..." (solo se repo privato)
# ============================================================

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import requests
import streamlit as st

# ─────────────────────────────────────────────
# Configurazione pagina
# ─────────────────────────────────────────────

st.set_page_config(
    page_title = "Streak Monitor | Kriterion Quant",
    page_icon  = "📊",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

# CSS personalizzato dark theme
st.markdown("""
<style>
    /* Sfondo app */
    .stApp { background-color: #0f0f1a; }

    /* Cards sistema */
    .system-card {
        background: #1a1a2e;
        border: 1px solid #2a2a4a;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
        transition: border-color 0.2s;
    }
    .system-card:hover { border-color: #4a4a8a; }

    /* Badge moltiplicatore */
    .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 16px;
        font-weight: bold;
        font-size: 18px;
    }
    .badge-2x   { background:#1565c0; color:#e3f2fd; }
    .badge-15x  { background:#2e7d32; color:#e8f5e9; }
    .badge-1x   { background:#424242; color:#eeeeee; }
    .badge-05x  { background:#d84315; color:#fbe9e7; }

    /* Streak label */
    .streak-label {
        font-size: 14px;
        color: #90caf9;
        font-family: monospace;
    }

    /* Testo secondario */
    .secondary-text { color: #888; font-size: 12px; }

    /* Barra confidenza */
    .conf-bar-container {
        background: #333;
        border-radius: 4px;
        height: 6px;
        margin-top: 4px;
    }

    /* Posizione aperta badge */
    .open-badge {
        background: #f57f17;
        color: #fff8e1;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 11px;
        font-weight: bold;
    }

    /* Changed badge */
    .changed-badge {
        background: #6a1b9a;
        color: #f3e5f5;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 11px;
        font-weight: bold;
    }

    /* Titoli sezione */
    h2, h3 { color: #90caf9 !important; }

    /* Sidebar */
    [data-testid="stSidebar"] { background: #12122a; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Caricamento dati
# ─────────────────────────────────────────────

MULT_BADGE_CLASS = {
    2.0: "badge-2x",
    1.5: "badge-15x",
    1.0: "badge-1x",
    0.5: "badge-05x",
}

MULT_LABEL = {
    2.0: "2×",
    1.5: "1.5×",
    1.0: "1×",
    0.5: "0.5×",
}

CONF_COLORS = {
    "High":   "#4caf50",
    "Medium": "#ff9800",
    "Low":    "#f44336",
}

CONF_WIDTH = {
    "High":   "100%",
    "Medium": "60%",
    "Low":    "25%",
}


@st.cache_data(ttl=300)    # cache 5 minuti — il bottone "Forza Aggiornamento" svuota la cache on-demand
def load_state() -> Optional[dict]:
    """
    Scarica il file state.json dal repository GitHub.
    Usa il token se il repo è privato (configurabile nei secrets Streamlit).
    """
    url   = st.secrets.get("GITHUB_STATE_URL", "")
    token = st.secrets.get("GITHUB_TOKEN", "")

    if not url:
        st.error(
            "❌ `GITHUB_STATE_URL` non configurato nei Secrets di Streamlit.\n\n"
            "Vai su Settings → Secrets → aggiungi:\n"
            "`GITHUB_STATE_URL = https://raw.githubusercontent.com/TUO_USER/streak-monitor/main/state/system_state.json`"
        )
        return None

    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 404:
            st.warning("⚠️ state.json non trovato. La prima run notturna non è ancora avvenuta.")
        else:
            st.error(f"Errore HTTP: {e}")
        return None
    except Exception as e:
        st.error(f"Errore caricamento dati: {e}")
        return None


# ─────────────────────────────────────────────
# Componenti UI
# ─────────────────────────────────────────────

def render_system_card(name: str, sys: dict) -> None:
    """Renderizza la card HTML per un singolo sistema."""
    mult       = sys.get("multiplier", 1.0)
    conf       = sys.get("confidence", "Low")
    streak_t   = sys.get("streak_type", "N/A")
    streak_l   = sys.get("streak_len", 0)
    p_win      = sys.get("p_win_given_streak", 0.5)
    ci_lo      = sys.get("ci_lower_80", 0.0)
    ci_hi      = sys.get("ci_upper_80", 1.0)
    n_obs      = sys.get("n_obs_for_streak", 0)
    has_open   = sys.get("has_open_position", False)
    changed    = sys.get("multiplier_changed", False)
    prev_mult  = sys.get("prev_multiplier", 1.0)
    last_date  = sys.get("last_trade_date", "N/A")
    n_trades   = sys.get("n_trades", 0)
    win_rate   = sys.get("win_rate", 0)
    reason     = sys.get("sizing_reason", "")

    badge_class = MULT_BADGE_CLASS.get(mult, "badge-1x")
    badge_label = MULT_LABEL.get(mult, f"{mult}×")

    streak_icon = "📈" if streak_t == "W" else "📉" if streak_t == "L" else "—"
    streak_str  = f"{streak_l}{streak_t}" if streak_t != "N/A" else "N/A"

    open_html    = '<span class="open-badge">● APERTA</span>' if has_open else ""
    changed_html = f'<span class="changed-badge">⚡ CAMBIATO da {MULT_LABEL.get(prev_mult, prev_mult)}×</span>' if changed else ""

    conf_color = CONF_COLORS.get(conf, "#888")
    conf_width = CONF_WIDTH.get(conf, "25%")

    st.markdown(f"""
    <div class="system-card">
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div>
          <div style="color:#e0e0e0; font-weight:bold; font-size:15px; margin-bottom:4px;">
            {name}
            &nbsp;{open_html}&nbsp;{changed_html}
          </div>
          <div class="secondary-text">
            {sys.get('symbol','?')} &nbsp;·&nbsp; {sys.get('family','?')}
            &nbsp;·&nbsp; {n_trades} trade OOS &nbsp;·&nbsp; WR {win_rate:.0%}
          </div>
        </div>
        <div style="text-align:right;">
          <span class="badge {badge_class}">{badge_label}</span>
        </div>
      </div>

      <hr style="border:0; border-top:1px solid #2a2a4a; margin:10px 0;">

      <div style="display:flex; gap:24px; flex-wrap:wrap;">
        <div>
          <div class="secondary-text">Streak attiva</div>
          <div class="streak-label">{streak_icon} {streak_str}</div>
        </div>
        <div>
          <div class="secondary-text">P(W|streak)</div>
          <div style="color:#e0e0e0; font-size:14px;">
            {p_win:.1%}
            <span class="secondary-text">[{ci_lo:.0%}–{ci_hi:.0%}]</span>
          </div>
        </div>
        <div>
          <div class="secondary-text">Confidenza (n={n_obs})</div>
          <div style="color:{conf_color}; font-size:13px;">{conf}</div>
          <div class="conf-bar-container">
            <div style="background:{conf_color}; width:{conf_width}; height:6px; border-radius:4px;"></div>
          </div>
        </div>
        <div>
          <div class="secondary-text">Ultimo trade chiuso</div>
          <div style="color:#e0e0e0; font-size:13px;">{last_date}</div>
        </div>
      </div>

      <div style="margin-top:8px;" class="secondary-text">
        💬 {reason}
      </div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Layout principale
# ─────────────────────────────────────────────

def main() -> None:

    # ── Header
    st.markdown("""
    <div style="background:linear-gradient(135deg,#1a237e,#0d47a1);
                border-radius:12px; padding:24px 32px; margin-bottom:24px;">
      <div style="color:#90caf9; font-size:12px; letter-spacing:2px;
                  text-transform:uppercase; margin-bottom:4px;">
        Kriterion Quant
      </div>
      <div style="color:#fff; font-size:28px; font-weight:bold;">
        📊 Streak Monitor
      </div>
      <div style="color:#bbdefb; font-size:14px; margin-top:6px;">
        Dashboard di gestione esposizione per trading system multipli
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Carica dati
    state = load_state()
    if state is None:
        st.stop()

    last_updated = state.get("last_updated", "N/A")
    systems      = state.get("systems", {})

    if not systems:
        st.warning("Nessun sistema trovato nel file di stato.")
        st.stop()

    # Formato data leggibile
    try:
        dt_obj   = datetime.fromisoformat(last_updated)
        dt_label = dt_obj.strftime("%d/%m/%Y alle %H:%M UTC")
    except Exception:
        dt_label = last_updated

    st.caption(f"🕐 Ultimo aggiornamento: **{dt_label}** — aggiornato ogni notte automaticamente")

    # ── Sidebar filtri
    with st.sidebar:
        st.header("⚙️ Filtri")

        all_families = sorted(set(s.get('family', 'Altro') for s in systems.values()))
        sel_families = st.multiselect(
            "Famiglia sistema",
            options   = all_families,
            default   = all_families,
        )

        all_mults = [2.0, 1.5, 1.0, 0.5]
        sel_mults = st.multiselect(
            "Moltiplicatore",
            options   = all_mults,
            default   = all_mults,
            format_func = lambda x: MULT_LABEL.get(x, str(x)),
        )

        sel_changed_only = st.checkbox("Solo sistemi con cambio rispetto a ieri", value=False)
        sel_open_only    = st.checkbox("Solo sistemi con posizione aperta", value=False)

        st.divider()
        if st.button("🔄 Forza Aggiornamento"):
            load_state.clear()
            st.rerun()
        st.caption("Dati: MultiCharts via Google Drive\nAggiornamento: 02:00 CET ogni notte")

    # ── Applica filtri
    filtered = {
        name: sys for name, sys in systems.items()
        if sys.get('family', 'Altro') in sel_families
        and sys.get('multiplier', 1.0)    in sel_mults
        and (not sel_changed_only or sys.get('multiplier_changed', False))
        and (not sel_open_only    or sys.get('has_open_position', False))
    }

    # ── KPI metriche in cima
    n_total   = len(systems)
    n_filt    = len(filtered)
    n_2x      = sum(1 for s in systems.values() if s.get('multiplier') == 2.0)
    n_15x     = sum(1 for s in systems.values() if s.get('multiplier') == 1.5)
    n_05x     = sum(1 for s in systems.values() if s.get('multiplier') == 0.5)
    n_changed = sum(1 for s in systems.values() if s.get('multiplier_changed'))
    n_open    = sum(1 for s in systems.values() if s.get('has_open_position'))

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Sistemi totali",     n_total)
    c2.metric("Segnali 2×",         n_2x,  delta=None)
    c3.metric("Segnali 1.5×",       n_15x, delta=None)
    c4.metric("Segnali 0.5×",       n_05x, delta=None)
    c5.metric("⚡ Cambio vs ieri",  n_changed)
    c6.metric("● Pos. aperte",      n_open)

    st.divider()

    # ── Cards dei sistemi filtrati
    if not filtered:
        st.info("Nessun sistema corrisponde ai filtri selezionati.")
        st.stop()

    st.subheader(f"Sistemi ({n_filt} visualizzati su {n_total})")

    # Ordinamento: prima i segnali forti, poi per nome
    def sort_key(item):
        name, sys = item
        mult_p = {2.0: 0, 0.5: 1, 1.5: 2, 1.0: 3}
        conf_p = {"High": 0, "Medium": 1, "Low": 2}
        return (
            0 if sys.get('multiplier_changed') else 1,
            mult_p.get(sys.get('multiplier', 1.0), 9),
            conf_p.get(sys.get('confidence', 'Low'), 9),
            name,
        )

    sorted_systems = sorted(filtered.items(), key=sort_key)

    # Layout a 2 colonne
    col_a, col_b = st.columns(2)

    for idx, (name, sys) in enumerate(sorted_systems):
        with (col_a if idx % 2 == 0 else col_b):
            render_system_card(name, sys)

    # ── Expander metodologia
    st.divider()
    with st.expander("ℹ️ Metodologia — come funziona il motore di analisi"):
        st.markdown("""
        ### Modello Bayesiano Beta-Binomiale

        Per ogni sistema, il motore analizza la sequenza storica di trade Win/Loss
        e calcola la probabilità condizionale di vittoria dato lo stato della streak corrente.

        **Formula:**
        - Viene identificata la streak attiva alla fine della sequenza (es. 3 Loss consecutive)
        - Si contano tutti gli episodi storici analoghi (quante volte in passato ci sono state 3L)
        - Si applica Laplace smoothing: `P(W) = (n_wins + 1) / (n_total + 2)`
        - L'intervallo credibile [CI 80%] è il 10°–90° percentile della distribuzione Beta posteriore

        **Livelli di confidenza:**
        - 🟢 **Alta**: ≥ 15 osservazioni storiche — range completo 0.5×, 1×, 1.5×, 2×
        - 🟡 **Media**: 5–14 osservazioni — massimo 1.5×
        - 🔴 **Bassa**: < 5 osservazioni — sempre 1× (dati insufficienti)

        **Logica di sizing:**
        | P(W|streak) | Confidenza | Moltiplicatore |
        |---|---|---|
        | ≥ 75% | Alta | **2×** |
        | ≥ 65% | Media/Alta | **1.5×** |
        | 35%–65% | qualsiasi | **1×** |
        | ≤ 35% | Media/Alta | **0.5×** |

        > Il sistema è intenzionalmente conservativo: preferisce restare a 1× piuttosto che
        > segnalare falsi positivi su campioni piccoli.
        """)


if __name__ == "__main__":
    main()
