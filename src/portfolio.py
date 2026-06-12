# ============================================================
# portfolio.py — Motore di analisi allocazione
# ============================================================
# Pipeline:
#   1. Serie PnL mensili per famiglia (attribuzione a data uscita)
#   2. Statistiche per famiglia (PnL, vol, Sharpe, maxDD, % mesi +)
#   3. Matrice di correlazione (pairwise, min 12 mesi comuni)
#   4. Contributo alla varianza di portafoglio (pesi correnti = 1×)
#   5. Test di persistenza vol/Sharpe (split-half rank correlation)
#   6. Pesi inverse-volatility con cap, arrotondati a step operativi
#   7. Validazione walk-forward: equal weight vs inverse-vol,
#      ribilanciamento mensile, bootstrap sulla differenza Sharpe
#
# Razionale (validato empiricamente): la volatilità delle famiglie
# è persistente nel tempo, lo Sharpe no → si pesa per rischio,
# non si inseguono i rendimenti passati.
# ============================================================

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from parser import ParsedSystem, infer_family

logger = logging.getLogger(__name__)


@dataclass
class AllocationResult:
    fam_monthly:    pd.DataFrame        # PnL mensile per famiglia
    fam_systems:    dict                # famiglia → [nomi sistemi]
    stats:          pd.DataFrame        # statistiche per famiglia
    corr:           pd.DataFrame        # correlazioni mensili
    risk_contrib:   pd.Series           # % contributo varianza (pesi 1×)
    vol_rank_corr:  float               # persistenza vol (split-half)
    sharpe_rank_corr: float             # persistenza Sharpe (split-half)
    weights_iv:     pd.Series           # pesi inverse-vol esatti
    weights_rec:    pd.Series           # pesi arrotondati operativi
    excluded:       list = field(default_factory=list)  # famiglie senza storia suff.
    wf:             dict = field(default_factory=dict)  # risultati walk-forward
    portfolio_stats: dict = field(default_factory=dict)


# ─────────────────────────────────────────────
# Costruzione serie
# ─────────────────────────────────────────────

def build_family_monthly(
    systems: list[ParsedSystem],
    family_prefixes: list[str],
) -> tuple[pd.DataFrame, dict]:
    """PnL mensile per famiglia, attribuito alla data di uscita del trade."""
    rows = []
    fam_systems: dict[str, list] = {}
    for ps in systems:
        fam = infer_family(ps.system_name, family_prefixes)
        fam_systems.setdefault(fam, []).append(ps.system_name)
        for t in ps.trades:
            rows.append((fam, t.exit_date, t.pnl))

    df = pd.DataFrame(rows, columns=['family', 'exit', 'pnl'])
    df['month'] = df['exit'].dt.to_period('M')
    fam_m = df.pivot_table(index='month', columns='family',
                           values='pnl', aggfunc='sum').fillna(0.0)
    fam_m = fam_m.sort_index()
    return fam_m, fam_systems


# ─────────────────────────────────────────────
# Statistiche e rischio
# ─────────────────────────────────────────────

def _max_dd(series: pd.Series) -> float:
    eq = series.cumsum()
    return float((eq - eq.cummax()).min())


def family_stats(fam_m: pd.DataFrame) -> pd.DataFrame:
    out = []
    for c in fam_m.columns:
        s = fam_m[c]
        active = s[s != 0]
        vol = s.std()
        out.append(dict(
            family=c,
            months_active=len(active),
            pnl_total=round(s.sum()),
            pnl_mean_m=round(s.mean()),
            vol_m=round(vol),
            sharpe_ann=round(s.mean() / vol * np.sqrt(12), 2) if vol > 0 else 0.0,
            max_dd=round(_max_dd(s)),
            pct_pos_months=round((s > 0).mean() * 100, 1),
        ))
    return pd.DataFrame(out).set_index('family')


def correlation_matrix(fam_m: pd.DataFrame, min_periods: int = 12) -> pd.DataFrame:
    return fam_m.replace(0, np.nan).corr(min_periods=min_periods)


def risk_contribution(fam_m: pd.DataFrame, weights: pd.Series | None = None) -> pd.Series:
    """% contributo alla varianza di portafoglio. Default: pesi 1×."""
    cols = list(fam_m.columns)
    w = (weights.reindex(cols).fillna(1.0) if weights is not None
         else pd.Series(1.0, index=cols))
    cov = fam_m.cov()
    wv = w.values
    pvar = wv @ cov.values @ wv
    rc = (cov.values @ wv) * wv / pvar
    return pd.Series(rc, index=cols).sort_values(ascending=False)


def persistence_check(fam_m: pd.DataFrame) -> tuple[float, float]:
    """Rank-correlation di vol e Sharpe tra prima e seconda metà del campione."""
    h = len(fam_m) // 2
    a, b = fam_m.iloc[:h], fam_m.iloc[h:]
    v = spearmanr(a.std(), b.std()).statistic
    sh_a = (a.mean() / a.std()).fillna(0)
    sh_b = (b.mean() / b.std()).fillna(0)
    s = spearmanr(sh_a, sh_b).statistic
    return float(v), float(s)


# ─────────────────────────────────────────────
# Pesi inverse-volatility
# ─────────────────────────────────────────────

def _iv_weights(vols: pd.Series, w_min: float, w_max: float) -> pd.Series:
    """Inverse-vol normalizzati a gross = n famiglie, con cap iterativo."""
    vols = vols.replace(0, np.nan).dropna()
    k = len(vols)
    w = (1.0 / vols)
    w = w / w.sum() * k
    # cap iterativo: clip e rinormalizza i non-cappati finché converge
    for _ in range(20):
        clipped = w.clip(w_min, w_max)
        if np.allclose(clipped.sum(), k, atol=1e-9):
            w = clipped
            break
        free = (clipped > w_min) & (clipped < w_max)
        if not free.any():
            w = clipped / clipped.sum() * k
            break
        residual = k - clipped[~free].sum()
        w = clipped.copy()
        w[free] = clipped[free] / clipped[free].sum() * residual
    return w


def compute_weights(
    fam_m: pd.DataFrame,
    lookback: int,
    w_min: float,
    w_max: float,
    step: float,
    min_history: int,
) -> tuple[pd.Series, pd.Series, list]:
    """
    Pesi correnti: inverse-vol su `lookback` mesi trailing.
    Le famiglie con storia < min_history mesi restano a 1× (escluse dal calcolo).
    """
    recent = fam_m.iloc[-lookback:]
    excluded = []
    eligible = []
    for c in fam_m.columns:
        active_months = int((fam_m[c] != 0).sum())
        if active_months < min_history:
            excluded.append(c)
        else:
            eligible.append(c)

    w_iv = _iv_weights(recent[eligible].std(), w_min, w_max)
    # arrotondamento operativo
    w_rec = (w_iv / step).round() * step
    w_rec = w_rec.clip(w_min, w_max)

    # le escluse restano a 1.0 (default prudente)
    for c in excluded:
        w_iv.loc[c] = 1.0
        w_rec.loc[c] = 1.0

    return w_iv.reindex(fam_m.columns), w_rec.reindex(fam_m.columns), excluded


# ─────────────────────────────────────────────
# Walk-forward
# ─────────────────────────────────────────────

def walkforward(
    fam_m: pd.DataFrame,
    lookback: int,
    warmup: int,
    w_min: float,
    w_max: float,
    n_boot: int = 5000,
    seed: int = 42,
) -> dict:
    """
    Confronto out-of-sample: equal weight vs inverse-vol con
    ribilanciamento mensile (nessun dato futuro nelle stime).
    """
    if len(fam_m) < warmup + 12:
        return {'enough_data': False,
                'note': f"servono almeno {warmup + 12} mesi, disponibili {len(fam_m)}"}

    ew_pnl, iv_pnl = [], []
    for t in range(warmup, len(fam_m)):
        hist = fam_m.iloc[max(0, t - lookback):t]
        vols = hist.std()
        active = vols[vols > 0].index
        if len(active) == 0:
            continue
        w = _iv_weights(vols[active], w_min, w_max)
        row = fam_m.iloc[t]
        ew_pnl.append(float(row[active].sum()))
        iv_pnl.append(float((row[active] * w).sum()))

    ew = np.array(ew_pnl)
    iv = np.array(iv_pnl)

    def _stats(x):
        eq = np.cumsum(x)
        dd = float((eq - np.maximum.accumulate(eq)).min())
        sh = float(x.mean() / x.std() * np.sqrt(12)) if x.std() > 0 else 0.0
        return dict(pnl=round(float(x.sum())), vol_m=round(float(x.std())),
                    sharpe=round(sh, 2), max_dd=round(dd))

    # bootstrap della differenza di Sharpe mensile
    rng = np.random.default_rng(seed)
    n = len(ew)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        bi = rng.integers(0, n, n)
        e, v = ew[bi], iv[bi]
        se = e.mean() / e.std() if e.std() > 0 else 0.0
        sv = v.mean() / v.std() if v.std() > 0 else 0.0
        diffs[i] = sv - se

    s_ew, s_iv = _stats(ew), _stats(iv)
    return {
        'enough_data': True,
        'months_oos': n,
        'period': f"{fam_m.index[warmup]} → {fam_m.index[-1]}",
        'ew': s_ew,
        'iv': s_iv,
        'p_iv_better': round(float((diffs > 0).mean()), 3),
        'dd_reduction_pct': round((1 - s_iv['max_dd'] / s_ew['max_dd']) * 100, 1)
                            if s_ew['max_dd'] != 0 else 0.0,
        'equity_ew': np.cumsum(ew).round(0).tolist(),
        'equity_iv': np.cumsum(iv).round(0).tolist(),
        'equity_labels': [str(m) for m in fam_m.index[warmup:warmup + n]],
    }


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def analyze(systems: list[ParsedSystem], settings: dict) -> AllocationResult:
    alloc = settings.get('allocation', {})
    wf_cfg = settings.get('walkforward', {})
    prefixes = settings.get('families', {}).get('prefixes', [])

    lookback = alloc.get('lookback_months', 24)
    w_min = alloc.get('weight_min', 0.5)
    w_max = alloc.get('weight_max', 2.0)
    step = alloc.get('weight_step', 0.25)
    min_hist = alloc.get('min_history_months', 12)

    fam_m, fam_systems = build_family_monthly(systems, prefixes)
    stats = family_stats(fam_m)
    corr = correlation_matrix(fam_m)
    rc = risk_contribution(fam_m)
    vol_pc, sharpe_pc = persistence_check(fam_m)
    w_iv, w_rec, excluded = compute_weights(fam_m, lookback, w_min, w_max, step, min_hist)
    wf = walkforward(fam_m, lookback, wf_cfg.get('warmup_months', 24),
                     w_min, w_max, wf_cfg.get('bootstrap_samples', 5000))

    ptf = fam_m.sum(axis=1)
    ptf_stats = dict(
        pnl=round(float(ptf.sum())),
        sharpe=round(float(ptf.mean() / ptf.std() * np.sqrt(12)), 2) if ptf.std() > 0 else 0,
        max_dd=round(_max_dd(ptf)),
        months=len(ptf),
        div_ratio=round(float(np.array([fam_m[c].std() for c in fam_m.columns]).sum()
                              / ptf.std()), 2) if ptf.std() > 0 else 0,
    )

    return AllocationResult(
        fam_monthly=fam_m, fam_systems=fam_systems, stats=stats, corr=corr,
        risk_contrib=rc, vol_rank_corr=round(vol_pc, 2),
        sharpe_rank_corr=round(sharpe_pc, 2),
        weights_iv=w_iv.round(2), weights_rec=w_rec, excluded=excluded,
        wf=wf, portfolio_stats=ptf_stats,
    )
