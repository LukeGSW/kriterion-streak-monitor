# ============================================================
# streak_engine.py — Motore Bayesiano di analisi streak
# ============================================================
# Cuore del sistema. Per ogni sistema calcola:
#   - La streak attiva (N W o L consecutive finali)
#   - P(W | streak corrente) con Laplace smoothing
#   - Intervallo credibile Bayesiano Beta-Binomiale
#   - Expected Value condizionale alla streak
#   - Half-Kelly fraction per il sizing ottimale
#   - Livello di confidenza (Low / Medium / High)
#   - Moltiplicatore raccomandato (0.5x / 1x / 1.5x / 2x)
#
# Approccio Bayesiano Beta-Binomiale:
#   Prior uniforme Beta(1,1) + osservazioni → Beta(n_wins+1, n_losses+1)
#   Con Laplace smoothing: p = (n_wins+1)/(n_total+2)
#   Questo garantisce stime sempre finite anche con 0 osservazioni.
#
# v2.0 — Miglioramenti:
#   - Expected Value condizionale: EV = P(W)*avg_win - P(L)*|avg_loss|
#   - Decay factor esponenziale: osservazioni recenti pesano di più
#   - Supporto override manuali da settings.yaml
#   - Breakeven trades esclusi dalla serie W/L (gestito in parser.py)
# ============================================================

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from scipy.stats import beta as beta_dist

from parser import SystemData

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Soglie di sizing (configurabili via settings.yaml)
# ─────────────────────────────────────────────

DEFAULT_THRESHOLDS = {
    "p_increase_15x":  0.65,   # P(W|streak) ≥ soglia → 1.5x
    "p_increase_2x":   0.75,   # P(W|streak) ≥ soglia E n ≥ 15 → 2x
    "p_decrease_05x":  0.35,   # P(W|streak) ≤ soglia → 0.5x
    "n_min_low":       5,      # n < 5  → Low confidence, sempre 1x
    "n_min_medium":    15,     # 5 ≤ n < 15 → Medium, max 1.5x
    "max_streak_look": 5,      # max lunghezza streak analizzata
    # v2.0 — nuove soglie
    "decay_halflife":  50,     # halflife del decay esponenziale (in numero di trade)
    "ev_boost":        0.30,   # EV normalizzato ≥ soglia → boost di 1 livello (alzato da 0.15)
    "ev_penalize":    -0.10,   # EV normalizzato ≤ soglia → penalizza di 1 livello
    # v2.1 — guardrail anti-aggressività
    "ev_boost_pw_floor": 0.50, # P(W) minima per abilitare EV boost (no boost sotto il 50%)
    "ev_boost_hk_floor": 0.02, # Half-Kelly minimo per abilitare EV boost (edge reale richiesto)
}


# ─────────────────────────────────────────────
# Dataclass risultato analisi
# ─────────────────────────────────────────────

@dataclass
class SystemAnalysis:
    """Risultato completo dell'analisi streak per un sistema."""

    # Identificazione
    system_name:          str
    symbol:               str
    family:               str

    # Statistiche base
    n_trades:             int
    win_rate:             float
    avg_win_usd:          float
    avg_loss_usd:         float
    profit_factor:        float

    # Streak corrente
    current_streak_type:  str           # "W" o "L"
    current_streak_len:   int           # lunghezza streak attiva

    # Analisi condizionale
    n_obs_for_streak:     int           # quante volte vista questa streak in storico
    n_wins_after_streak:  int           # di queste, quante seguite da W
    p_win_given_streak:   float         # stima Bayesiana P(W|streak)
    ci_lower_80:          float         # 10° percentile Beta posteriore
    ci_upper_80:          float         # 90° percentile Beta posteriore

    # v2.0 — Expected Value e Kelly
    ev_per_trade:         float = 0.0   # EV condizionale alla streak (USD)
    ev_normalized:        float = 0.0   # EV / |avg_loss| — adimensionale, confrontabile
    half_kelly:           float = 0.0   # Half-Kelly fraction (0 = no edge, 1 = full Kelly)

    # Output operativo
    multiplier:           float = 1.0   # 0.5 / 1.0 / 1.5 / 2.0
    confidence:           str   = "Low" # "Low" / "Medium" / "High"
    sizing_reason:        str   = ""    # spiegazione testuale del segnale

    # v2.0 — Override manuale
    is_override:          bool  = False # True se il moltiplicatore è stato forzato

    # Stato posizione
    has_open_position:    bool  = False
    last_trade_date:      str   = "N/A"
    last_trade_result:    str   = "N/A" # "W" o "L"

    # Confronto con sessione precedente
    prev_multiplier:      float = 1.0
    multiplier_changed:   bool  = False

    # Timestamp analisi
    analyzed_at:          str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─────────────────────────────────────────────
# Funzioni core
# ─────────────────────────────────────────────

def _current_streak(win_series: list[int]) -> tuple[str, int]:
    """
    Calcola la streak attiva alla fine della sequenza W/L.

    Returns:
        (tipo, lunghezza) es. ("L", 3) = tre loss consecutive finali
    """
    if not win_series:
        return ("L", 0)

    streak_type = "W" if win_series[-1] == 1 else "L"
    streak_val  = 1 if streak_type == "W" else 0
    count = 0

    for result in reversed(win_series):
        if result == streak_val:
            count += 1
        else:
            break

    return (streak_type, count)


def _conditional_stats(
    win_series: list[int],
    streak_type: str,
    streak_len: int,
    max_look: int = 5,
    decay_halflife: float = 0,
) -> tuple[float, float]:
    """
    Conta le occorrenze storiche di una streak e quante furono seguite da W.

    Con decay_halflife > 0, applica un peso esponenziale decrescente:
    le osservazioni più recenti nella serie pesano di più.
    Il peso di un'osservazione a distanza d dalla fine è: exp(-d * ln(2) / halflife)

    Args:
        win_series:      sequenza binaria W=1/L=0
        streak_type:     "W" o "L"
        streak_len:      lunghezza della streak da cercare
        max_look:        lunghezza massima da analizzare (default 5)
        decay_halflife:  halflife del decay in numero di trade (0 = no decay)

    Returns:
        (n_total_eff, n_wins_eff) — denominatore e numeratore (pesati se decay attivo)
    """
    streak_len = min(streak_len, max_look)
    streak_val = 1 if streak_type == "W" else 0
    n_total    = 0.0
    n_wins     = 0.0
    series_len = len(win_series)

    # Precalcola il fattore di decay (lambda)
    use_decay = decay_halflife > 0
    if use_decay:
        decay_lambda = math.log(2) / decay_halflife

    for i in range(series_len - streak_len):
        # Verifica che le posizioni i..i+streak_len-1 siano tutte streak_val
        if all(win_series[i + k] == streak_val for k in range(streak_len)):
            next_result = win_series[i + streak_len]

            if use_decay:
                # Distanza dalla fine della serie (più vicino = peso maggiore)
                dist_from_end = series_len - 1 - (i + streak_len)
                weight = math.exp(-decay_lambda * dist_from_end)
            else:
                weight = 1.0

            n_total += weight
            if next_result == 1:
                n_wins += weight

    return n_total, n_wins


def _bayesian_estimate(n_total: float, n_wins: float) -> tuple[float, float, float]:
    """
    Stima Bayesiana Beta-Binomiale con prior uniforme + Laplace smoothing.

    Accetta parametri float per supportare il decay pesato.
    Beta posteriore: Beta(alpha = n_wins+1, beta = n_losses+1)
    Laplace posterior mean: (n_wins+1) / (n_total+2)

    Returns:
        (p_mean, ci_lower_80, ci_upper_80)
    """
    alpha = n_wins + 1       # prior Beta(1,1) + wins osservati
    beta  = (n_total - n_wins) + 1   # + losses osservati

    p_mean     = alpha / (alpha + beta)
    ci_lower   = beta_dist.ppf(0.10, alpha, beta)
    ci_upper   = beta_dist.ppf(0.90, alpha, beta)

    return p_mean, ci_lower, ci_upper


def _compute_ev(p_win: float, avg_win: float, avg_loss: float) -> tuple[float, float, float]:
    """
    Calcola Expected Value condizionale e Half-Kelly fraction.

    EV = P(W) × avg_win - (1-P(W)) × |avg_loss|
    Half-Kelly = 0.5 × (p × R - q) / R   dove R = avg_win/|avg_loss|, q = 1-p

    Args:
        p_win:    P(W|streak) Bayesiana
        avg_win:  media dei trade vincenti (positiva)
        avg_loss: media dei trade perdenti (negativa o zero)

    Returns:
        (ev_usd, ev_normalized, half_kelly)
    """
    abs_loss = abs(avg_loss) if avg_loss != 0 else 0.0

    # EV assoluto in USD
    ev_usd = p_win * avg_win - (1.0 - p_win) * abs_loss

    # EV normalizzato: EV / |avg_loss| — adimensionale
    ev_norm = ev_usd / abs_loss if abs_loss > 0 else 0.0

    # Half-Kelly: 0.5 × (p × R - q) / R
    # con R = avg_win / |avg_loss|
    if abs_loss > 0 and avg_win > 0:
        R = avg_win / abs_loss
        q = 1.0 - p_win
        kelly_full = (p_win * R - q) / R
        half_kelly = max(0.0, kelly_full * 0.5)  # floor a 0: mai shortare
    else:
        half_kelly = 0.0

    return ev_usd, ev_norm, half_kelly


def _determine_multiplier(
    p_win: float,
    n_obs: float,
    streak_type: str,
    thresholds: dict,
    ev_normalized: float = 0.0,
    half_kelly: float = 0.0,
) -> tuple[float, str, str]:
    """
    Assegna il moltiplicatore di sizing basato su P(W|streak) + EV condizionale.

    Logica primaria (invariata): soglie P(W|streak) per livello di confidenza.
    Logica secondaria (v2.0+): l'EV normalizzato può fare bump up/down di 1 livello
    solo se la confidenza è Medium o High (mai su Low) E sono soddisfatti i guardrail:
      - P(W) >= ev_boost_pw_floor (default 0.50): non si boosta sotto il 50%
      - Half-Kelly >= ev_boost_hk_floor (default 0.02): serve edge reale

    Args:
        p_win:         P(W|streak) stimata (Laplace posterior mean)
        n_obs:         numero effettivo di osservazioni (float per decay)
        streak_type:   "W" o "L" — usato per il messaggio
        thresholds:    dizionario soglie da settings.yaml
        ev_normalized: EV / |avg_loss| — usato per boost/penalità
        half_kelly:    Half-Kelly fraction — usato come guardrail per il boost

    Returns:
        (multiplier, confidence, reason)
    """
    n_low    = thresholds["n_min_low"]
    n_med    = thresholds["n_min_medium"]
    p_up15   = thresholds["p_increase_15x"]
    p_up2    = thresholds["p_increase_2x"]
    p_dn     = thresholds["p_decrease_05x"]
    ev_boost_thr    = thresholds.get("ev_boost", 0.30)
    ev_penalize_thr = thresholds.get("ev_penalize", -0.10)
    pw_floor        = thresholds.get("ev_boost_pw_floor", 0.50)
    hk_floor        = thresholds.get("ev_boost_hk_floor", 0.02)

    # n_obs è float con decay: confronta con soglie arrotondando
    n_obs_int = round(n_obs)

    # ── Low confidence: campione troppo piccolo
    if n_obs_int < n_low:
        reason = f"Dati insufficienti ({n_obs_int} obs, minimo {n_low})"
        return 1.0, "Low", reason

    confidence = "Medium" if n_obs_int < n_med else "High"

    # ── Logica primaria: soglie P(W|streak)
    if p_win <= p_dn:
        base_mult = 0.5
        reason = f"P(W|{streak_type}) = {p_win:.1%} ≤ {p_dn:.0%} — prob. loss elevata"
    elif p_win >= p_up2 and confidence == "High":
        base_mult = 2.0
        reason = f"P(W|{streak_type}) = {p_win:.1%} ≥ {p_up2:.0%} — alta prob. win"
    elif p_win >= p_up15:
        base_mult = 1.5
        reason = f"P(W|{streak_type}) = {p_win:.1%} ≥ {p_up15:.0%} — prob. win sopra soglia"
    else:
        base_mult = 1.0
        reason = f"P(W|{streak_type}) = {p_win:.1%} — nessun segnale significativo"

    # ── Logica secondaria v2.0+: EV boost/penalize con guardrail
    # Il boost richiede TRE condizioni simultanee:
    #   1. EV_norm >= ev_boost_thr (edge significativo su base rischio)
    #   2. P(W) >= pw_floor (la probabilità stessa deve confermare il segnale)
    #   3. Half-Kelly >= hk_floor (edge reale secondo Kelly — non solo EV alto per skew)
    # La penalità richiede solo EV_norm <= ev_penalize_thr (è conservativa, giusto così).
    MULT_LEVELS = [0.5, 1.0, 1.5, 2.0]
    final_mult = base_mult

    if confidence != "Low" and ev_normalized != 0.0:
        idx = MULT_LEVELS.index(base_mult) if base_mult in MULT_LEVELS else 1

        # Boost: tutte e tre le condizioni devono essere soddisfatte
        ev_qualifies  = ev_normalized >= ev_boost_thr
        pw_qualifies  = p_win >= pw_floor
        hk_qualifies  = half_kelly >= hk_floor
        can_boost     = ev_qualifies and pw_qualifies and hk_qualifies

        if can_boost and idx < len(MULT_LEVELS) - 1:
            candidate = MULT_LEVELS[idx + 1]
            if confidence == "Medium" and candidate > 1.5:
                candidate = 1.5  # cap Medium a 1.5x
            if candidate != base_mult:
                final_mult = candidate
                reason += f" | EV boost ({ev_normalized:+.2f} ≥ {ev_boost_thr:+.2f})"

        elif ev_normalized <= ev_penalize_thr and idx > 0:
            # Penalize: un livello in giù (nessun guardrail extra — è conservativa)
            final_mult = MULT_LEVELS[idx - 1]
            reason += f" | EV penalità ({ev_normalized:+.2f} ≤ {ev_penalize_thr:+.2f})"

    return final_mult, confidence, reason


# ─────────────────────────────────────────────
# Entry point pubblico
# ─────────────────────────────────────────────

def analyze_system(
    data: SystemData,
    thresholds: Optional[dict] = None,
    prev_state: Optional[dict] = None,
    overrides: Optional[dict] = None,
) -> Optional[SystemAnalysis]:
    """
    Analizza un sistema e restituisce il SystemAnalysis completo.

    Args:
        data:       SystemData dal parser
        thresholds: soglie di sizing (default se None)
        prev_state: stato della notte precedente da state.json (per rilevare cambi)
        overrides:  dict di override manuali da settings.yaml (opzionale)

    Returns:
        SystemAnalysis pronto per report e state.json.
        None se il sistema è disabilitato via override.
    """
    # ── Check override: sistema disabilitato?
    ovr = (overrides or {}).get(data.system_name, {})
    if ovr.get("enabled") is False:
        logger.info(f"{data.system_name}: disabilitato via override, saltato")
        return None

    thr       = thresholds or DEFAULT_THRESHOLDS
    win_seq   = data.to_win_series()
    pnl_seq   = data.to_pnl_series()
    n         = len(win_seq)

    if n == 0:
        logger.warning(f"{data.system_name}: sequenza vuota, ritorno 1x di default")
        return _empty_analysis(data)

    # ── Statistiche base
    wins      = sum(win_seq)
    losses    = n - wins
    win_rate  = wins / n

    win_pnls  = [p for p, w in zip(pnl_seq, win_seq) if w == 1]
    loss_pnls = [p for p, w in zip(pnl_seq, win_seq) if w == 0]
    avg_win   = sum(win_pnls)  / len(win_pnls)  if win_pnls  else 0.0
    avg_loss  = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0

    gross_win  = sum(win_pnls)
    gross_loss = abs(sum(loss_pnls))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float('inf')

    # ── Streak corrente
    streak_type, streak_len = _current_streak(win_seq)

    # ── Cascade: parte dalla lunghezza reale della streak e scala verso
    # il basso finché non trova abbastanza osservazioni storiche.
    max_look     = min(streak_len, thr["max_streak_look"])
    look_len     = 1
    n_total      = 0.0
    n_wins_after = 0.0
    decay_hl     = thr.get("decay_halflife", 0)

    for try_len in range(max_look, 0, -1):
        t, w = _conditional_stats(win_seq, streak_type, try_len, thr["max_streak_look"], decay_hl)
        if t >= thr["n_min_low"] or try_len == 1:
            look_len     = try_len
            n_total      = t
            n_wins_after = w
            break

    # ── Stima Bayesiana
    p_win, ci_lo, ci_hi = _bayesian_estimate(n_total, n_wins_after)

    # ── Expected Value condizionale e Half-Kelly
    ev_usd, ev_norm, hk = _compute_ev(p_win, avg_win, avg_loss)

    # ── Moltiplicatore — nel label segnala se la streak è stata scalata
    if look_len < streak_len:
        streak_label = f"{streak_type}{look_len}(↓{streak_len})"
    else:
        streak_label = f"{streak_type}{look_len}"

    multiplier, confidence, reason = _determine_multiplier(
        p_win, n_total, streak_label, thr, ev_norm, hk
    )

    # ── Override manuale: sovrascrive il moltiplicatore calcolato
    is_override = False
    if "multiplier" in ovr:
        forced_mult = float(ovr["multiplier"])
        ovr_reason  = ovr.get("reason", "override manuale")
        logger.info(f"{data.system_name}: override moltiplicatore → {forced_mult}× ({ovr_reason})")
        multiplier  = forced_mult
        reason      = f"⚙️ OVERRIDE: {ovr_reason}"
        is_override = True

    # ── Ultimo trade
    last_trade      = data.closed_trades[-1]
    last_trade_date = last_trade.exit_date.strftime('%Y-%m-%d') if last_trade.exit_date else "N/A"
    last_result     = "W" if last_trade.pnl and last_trade.pnl > 0 else "L"

    # ── Confronto con stato precedente
    prev_mult = 1.0
    changed   = False
    if prev_state and data.system_name in prev_state.get("systems", {}):
        prev_mult = prev_state["systems"][data.system_name].get("multiplier", 1.0)
        changed   = (multiplier != prev_mult)

    return SystemAnalysis(
        system_name          = data.system_name,
        symbol               = data.symbol,
        family               = data.family,
        n_trades             = n,
        win_rate             = win_rate,
        avg_win_usd          = avg_win,
        avg_loss_usd         = avg_loss,
        profit_factor        = profit_factor,
        current_streak_type  = streak_type,
        current_streak_len   = streak_len,
        n_obs_for_streak     = round(n_total),
        n_wins_after_streak  = round(n_wins_after),
        p_win_given_streak   = p_win,
        ci_lower_80          = ci_lo,
        ci_upper_80          = ci_hi,
        ev_per_trade         = ev_usd,
        ev_normalized        = ev_norm,
        half_kelly           = hk,
        multiplier           = multiplier,
        confidence           = confidence,
        sizing_reason        = reason,
        is_override          = is_override,
        has_open_position    = data.has_open_position,
        last_trade_date      = last_trade_date,
        last_trade_result    = last_result,
        prev_multiplier      = prev_mult,
        multiplier_changed   = changed,
    )


def _empty_analysis(data: SystemData) -> SystemAnalysis:
    """Ritorna un'analisi neutra per sistemi senza trade sufficienti."""
    return SystemAnalysis(
        system_name          = data.system_name,
        symbol               = data.symbol,
        family               = data.family,
        n_trades             = 0,
        win_rate             = 0.0,
        avg_win_usd          = 0.0,
        avg_loss_usd         = 0.0,
        profit_factor        = 0.0,
        current_streak_type  = "N/A",
        current_streak_len   = 0,
        n_obs_for_streak     = 0,
        n_wins_after_streak  = 0,
        p_win_given_streak   = 0.5,
        ci_lower_80          = 0.0,
        ci_upper_80          = 1.0,
        ev_per_trade         = 0.0,
        ev_normalized        = 0.0,
        half_kelly           = 0.0,
        multiplier           = 1.0,
        confidence           = "Low",
        sizing_reason        = "Nessun trade disponibile",
        has_open_position    = data.has_open_position,
        last_trade_date      = "N/A",
        last_trade_result    = "N/A",
    )
