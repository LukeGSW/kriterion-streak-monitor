# ============================================================
# streak_engine.py — Motore Bayesiano di analisi streak
# ============================================================
# Cuore del sistema. Per ogni sistema calcola:
#   - La streak attiva (N W o L consecutive finali)
#   - P(W | streak corrente) con Laplace smoothing
#   - Intervallo credibile Bayesiano Beta-Binomiale
#   - Livello di confidenza (Low / Medium / High)
#   - Moltiplicatore raccomandato (0.5x / 1x / 1.5x / 2x)
#
# Approccio Bayesiano Beta-Binomiale:
#   Prior uniforme Beta(1,1) + osservazioni → Beta(n_wins+1, n_losses+1)
#   Con Laplace smoothing: p = (n_wins+1)/(n_total+2)
#   Questo garantisce stime sempre finite anche con 0 osservazioni.
# ============================================================

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
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

    # Output operativo
    multiplier:           float         # 0.5 / 1.0 / 1.5 / 2.0
    confidence:           str           # "Low" / "Medium" / "High"
    sizing_reason:        str           # spiegazione testuale del segnale

    # Stato posizione
    has_open_position:    bool
    last_trade_date:      str
    last_trade_result:    str           # "W" o "L"

    # Confronto con sessione precedente
    prev_multiplier:      float = 1.0
    multiplier_changed:   bool  = False

    # Timestamp analisi
    analyzed_at:          str = field(default_factory=lambda: datetime.utcnow().isoformat())


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
) -> tuple[int, int]:
    """
    Conta le occorrenze storiche di una streak e quante furono seguite da W.

    Cerca tutte le posizioni nella serie in cui appaiono streak_len risultati
    consecutivi del tipo specificato, e conta il risultato del trade successivo.

    Args:
        win_series:  sequenza binaria W=1/L=0
        streak_type: "W" o "L"
        streak_len:  lunghezza della streak da cercare
        max_look:    lunghezza massima da analizzare (default 5)

    Returns:
        (n_total, n_wins_after) — denominatore e numeratore Bayesiano
    """
    streak_len = min(streak_len, max_look)
    streak_val = 1 if streak_type == "W" else 0
    n_total    = 0
    n_wins     = 0

    # Scorri la serie cercando streak di esattamente streak_len+
    for i in range(len(win_series) - streak_len):
        # Verifica che le posizioni i..i+streak_len-1 siano tutte streak_val
        if all(win_series[i + k] == streak_val for k in range(streak_len)):
            # Elemento successivo alla streak
            next_result = win_series[i + streak_len]
            n_total += 1
            if next_result == 1:
                n_wins += 1

    return n_total, n_wins


def _bayesian_estimate(n_total: int, n_wins: int) -> tuple[float, float, float]:
    """
    Stima Bayesiana Beta-Binomiale con prior uniforme + Laplace smoothing.

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


def _determine_multiplier(
    p_win: float,
    n_obs: int,
    streak_type: str,
    thresholds: dict,
) -> tuple[float, str, str]:
    """
    Assegna il moltiplicatore di sizing basato sulla stima Bayesiana.

    Logica conservativa a livelli di confidenza:
      Low    (n_obs < n_min_low):    sempre 1x, dati insufficienti
      Medium (n_obs < n_min_medium): max 1.5x
      High   (n_obs ≥ n_min_medium): range completo 0.5x-2x

    Args:
        p_win:       P(W|streak) stimata (Laplace posterior mean)
        n_obs:       numero di osservazioni per questa streak
        streak_type: "W" o "L" — usato per il messaggio
        thresholds:  dizionario soglie da settings.yaml

    Returns:
        (multiplier, confidence, reason)
    """
    n_low    = thresholds["n_min_low"]
    n_med    = thresholds["n_min_medium"]
    p_up15   = thresholds["p_increase_15x"]
    p_up2    = thresholds["p_increase_2x"]
    p_dn     = thresholds["p_decrease_05x"]

    # ── Low confidence: campione troppo piccolo
    if n_obs < n_low:
        reason = f"Dati insufficienti ({n_obs} osservazioni, minimo {n_low})"
        return 1.0, "Low", reason

    confidence = "Medium" if n_obs < n_med else "High"

    # ── Segnale ribassista: P(W) bassa → riduci esposizione
    if p_win <= p_dn:
        reason = f"P(W|{streak_type}{n_obs}) = {p_win:.1%} ≤ {p_dn:.0%} — probabilità loss elevata"
        return 0.5, confidence, reason

    # ── Segnale rialzista: P(W) alta → aumenta esposizione
    if p_win >= p_up2 and confidence == "High":
        reason = f"P(W|{streak_type}{n_obs}) = {p_win:.1%} ≥ {p_up2:.0%} — alta prob. win (confidenza alta)"
        return 2.0, confidence, reason

    if p_win >= p_up15:
        mult   = 1.5
        reason = f"P(W|{streak_type}{n_obs}) = {p_win:.1%} ≥ {p_up15:.0%} — prob. win sopra soglia"
        # Cap a 1.5x per confidenza Medium
        return mult, confidence, reason

    # ── Neutro: nessun segnale significativo
    reason = f"P(W|{streak_type}{n_obs}) = {p_win:.1%} — nessun segnale significativo"
    return 1.0, confidence, reason


# ─────────────────────────────────────────────
# Entry point pubblico
# ─────────────────────────────────────────────

def analyze_system(
    data: SystemData,
    thresholds: Optional[dict] = None,
    prev_state: Optional[dict] = None,
) -> SystemAnalysis:
    """
    Analizza un sistema e restituisce il SystemAnalysis completo.

    Args:
        data:       SystemData dal parser
        thresholds: soglie di sizing (default se None)
        prev_state: stato della notte precedente da state.json (per rilevare cambi)

    Returns:
        SystemAnalysis pronto per report e state.json
    """
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

    # Cerca la streak più lunga utile (cap a max_look)
    look_len = min(streak_len, thr["max_streak_look"])

    # ── Statistiche condizionali
    n_total, n_wins_after = _conditional_stats(win_seq, streak_type, look_len, thr["max_streak_look"])

    # ── Stima Bayesiana
    p_win, ci_lo, ci_hi = _bayesian_estimate(n_total, n_wins_after)

    # ── Moltiplicatore
    streak_label = f"{streak_type}{look_len}"
    multiplier, confidence, reason = _determine_multiplier(p_win, n_total, streak_label, thr)

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
        n_obs_for_streak     = n_total,
        n_wins_after_streak  = n_wins_after,
        p_win_given_streak   = p_win,
        ci_lower_80          = ci_lo,
        ci_upper_80          = ci_hi,
        multiplier           = multiplier,
        confidence           = confidence,
        sizing_reason        = reason,
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
        multiplier           = 1.0,
        confidence           = "Low",
        sizing_reason        = "Nessun trade disponibile",
        has_open_position    = data.has_open_position,
        last_trade_date      = "N/A",
        last_trade_result    = "N/A",
    )
