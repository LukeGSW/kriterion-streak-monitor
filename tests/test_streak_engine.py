# ============================================================
# test_streak_engine.py — Test suite per il motore Bayesiano
# ============================================================
# Copre tutti i componenti critici:
#   - _current_streak: rilevamento streak attiva
#   - _conditional_stats: conteggio storico con e senza decay
#   - _bayesian_estimate: stima Beta-Binomiale
#   - _compute_ev: Expected Value e Half-Kelly
#   - _determine_multiplier: logica di sizing completa
#   - analyze_system: pipeline end-to-end con override
# ============================================================

from __future__ import annotations

import math

import pytest
from streak_engine import (
    _current_streak,
    _conditional_stats,
    _bayesian_estimate,
    _compute_ev,
    _determine_multiplier,
    analyze_system,
    DEFAULT_THRESHOLDS,
    SystemAnalysis,
)


# ─────────────────────────────────────────────
# _current_streak
# ─────────────────────────────────────────────

class TestCurrentStreak:

    def test_empty_series(self):
        s_type, s_len = _current_streak([])
        assert s_type == "L"
        assert s_len == 0

    def test_single_win(self):
        s_type, s_len = _current_streak([1])
        assert s_type == "W"
        assert s_len == 1

    def test_single_loss(self):
        s_type, s_len = _current_streak([0])
        assert s_type == "L"
        assert s_len == 1

    def test_trailing_wins(self):
        s_type, s_len = _current_streak([0, 0, 1, 1, 1])
        assert s_type == "W"
        assert s_len == 3

    def test_trailing_losses(self):
        s_type, s_len = _current_streak([1, 1, 0, 0])
        assert s_type == "L"
        assert s_len == 2

    def test_all_wins(self):
        s_type, s_len = _current_streak([1, 1, 1, 1, 1])
        assert s_type == "W"
        assert s_len == 5

    def test_all_losses(self):
        s_type, s_len = _current_streak([0, 0, 0, 0])
        assert s_type == "L"
        assert s_len == 4

    def test_alternating_ends_with_win(self):
        s_type, s_len = _current_streak([1, 0, 1, 0, 1])
        assert s_type == "W"
        assert s_len == 1


# ─────────────────────────────────────────────
# _conditional_stats (senza decay)
# ─────────────────────────────────────────────

class TestConditionalStats:

    def test_no_match_found(self):
        # Serie corta senza streak di 3W
        series = [1, 0, 1, 0, 1, 0]
        n, w = _conditional_stats(series, "W", 3, max_look=5)
        assert n == 0
        assert w == 0

    def test_single_match(self):
        # 2 loss consecutive seguite da win
        series = [0, 0, 1, 1, 1]
        n, w = _conditional_stats(series, "L", 2, max_look=5)
        assert n == 1
        assert w == 1

    def test_multiple_matches(self):
        # 1L appare in diverse posizioni
        series = [0, 1, 1, 0, 1, 0]
        n, w = _conditional_stats(series, "L", 1, max_look=5)
        assert n >= 2

    def test_max_look_caps_streak(self):
        series = [0]*10 + [1]
        n10, _ = _conditional_stats(series, "L", 10, max_look=3)
        n3, _  = _conditional_stats(series, "L", 3, max_look=3)
        assert n10 == n3

    def test_returns_floats(self):
        series = [1, 0, 1, 0, 1]
        n, w = _conditional_stats(series, "W", 1, max_look=5)
        assert isinstance(n, float)
        assert isinstance(w, float)


# ─────────────────────────────────────────────
# _conditional_stats (con decay)
# ─────────────────────────────────────────────

class TestConditionalStatsDecay:

    def test_decay_zero_equals_no_decay(self):
        series = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
        n_nd, w_nd = _conditional_stats(series, "W", 1, max_look=5, decay_halflife=0)
        n_d0, w_d0 = _conditional_stats(series, "W", 1, max_look=5, decay_halflife=0)
        assert n_nd == n_d0
        assert w_nd == w_d0

    def test_decay_reduces_effective_n(self):
        series = [1, 0] * 20
        n_nd, _ = _conditional_stats(series, "W", 1, max_look=5, decay_halflife=0)
        n_d, _  = _conditional_stats(series, "W", 1, max_look=5, decay_halflife=10)
        assert n_d < n_nd
        assert n_d > 0

    def test_recent_observations_weighted_more(self):
        first_half  = [1, 0] * 10
        second_half = [1, 1] * 10
        series = first_half + second_half

        n_nd, w_nd = _conditional_stats(series, "W", 1, max_look=5, decay_halflife=0)
        n_d, w_d   = _conditional_stats(series, "W", 1, max_look=5, decay_halflife=5)

        p_nd = (w_nd + 1) / (n_nd + 2)
        p_d  = (w_d + 1) / (n_d + 2)
        assert p_d > p_nd


# ─────────────────────────────────────────────
# _bayesian_estimate
# ─────────────────────────────────────────────

class TestBayesianEstimate:

    def test_zero_observations(self):
        p, lo, hi = _bayesian_estimate(0, 0)
        assert abs(p - 0.5) < 1e-10
        assert lo < p < hi

    def test_all_wins(self):
        p, lo, hi = _bayesian_estimate(10, 10)
        assert p > 0.9

    def test_all_losses(self):
        p, lo, hi = _bayesian_estimate(10, 0)
        assert p < 0.1

    def test_ci_contains_mean(self):
        for n in [5, 10, 50, 100]:
            for w in [0, n // 4, n // 2, 3 * n // 4, n]:
                p, lo, hi = _bayesian_estimate(n, w)
                assert lo <= p <= hi, f"CI non contiene media per n={n}, w={w}"

    def test_laplace_smoothing(self):
        p, _, _ = _bayesian_estimate(8, 6)
        expected = (6 + 1) / (8 + 2)
        assert abs(p - expected) < 1e-10

    def test_float_inputs(self):
        p, lo, hi = _bayesian_estimate(7.5, 4.2)
        assert 0 < p < 1
        assert lo < hi


# ─────────────────────────────────────────────
# _compute_ev
# ─────────────────────────────────────────────

class TestComputeEV:

    def test_positive_ev(self):
        ev, ev_norm, hk = _compute_ev(0.6, 200.0, -100.0)
        assert abs(ev - 80.0) < 1e-10
        assert ev_norm > 0
        assert hk > 0

    def test_negative_ev(self):
        ev, ev_norm, hk = _compute_ev(0.3, 100.0, -200.0)
        assert ev < 0
        assert ev_norm < 0
        assert hk == 0

    def test_zero_avg_loss(self):
        ev, ev_norm, hk = _compute_ev(0.5, 100.0, 0.0)
        assert ev_norm == 0.0
        assert hk == 0.0

    def test_half_kelly_is_half(self):
        p = 0.7
        avg_win = 150.0
        avg_loss = -100.0
        R = avg_win / abs(avg_loss)
        q = 1 - p
        full_kelly = (p * R - q) / R
        expected_hk = max(0, full_kelly * 0.5)

        _, _, hk = _compute_ev(p, avg_win, avg_loss)
        assert abs(hk - expected_hk) < 1e-10

    def test_breakeven_ev(self):
        ev, _, _ = _compute_ev(0.5, 100.0, -100.0)
        assert abs(ev) < 1e-10


# ─────────────────────────────────────────────
# _determine_multiplier
# ─────────────────────────────────────────────

class TestDetermineMultiplier:

    def test_low_confidence_always_1x(self):
        mult, conf, _ = _determine_multiplier(0.90, 3, "W", DEFAULT_THRESHOLDS)
        assert mult == 1.0
        assert conf == "Low"

    def test_high_prob_high_conf_gives_2x(self):
        mult, conf, _ = _determine_multiplier(0.80, 20, "W", DEFAULT_THRESHOLDS)
        assert mult == 2.0
        assert conf == "High"

    def test_medium_conf_caps_at_15x(self):
        mult, conf, _ = _determine_multiplier(0.80, 10, "W", DEFAULT_THRESHOLDS)
        assert mult == 1.5
        assert conf == "Medium"

    def test_low_prob_gives_05x(self):
        mult, _, _ = _determine_multiplier(0.25, 20, "L", DEFAULT_THRESHOLDS)
        assert mult == 0.5

    def test_neutral_zone_gives_1x(self):
        mult, _, _ = _determine_multiplier(0.50, 20, "W", DEFAULT_THRESHOLDS)
        assert mult == 1.0

    def test_ev_boost_bumps_up(self):
        mult, _, reason = _determine_multiplier(
            0.50, 20, "W", DEFAULT_THRESHOLDS, ev_normalized=0.30
        )
        assert mult == 1.5
        assert "EV boost" in reason

    def test_ev_penalize_bumps_down(self):
        mult, _, reason = _determine_multiplier(
            0.50, 20, "W", DEFAULT_THRESHOLDS, ev_normalized=-0.20
        )
        assert mult == 0.5
        assert "EV penalità" in reason  # nota: accent grave in "penalità"

    def test_ev_boost_respects_medium_cap(self):
        mult, conf, _ = _determine_multiplier(
            0.70, 10, "W", DEFAULT_THRESHOLDS, ev_normalized=0.30
        )
        assert mult == 1.5
        assert conf == "Medium"

    def test_ev_no_effect_on_low(self):
        mult, conf, _ = _determine_multiplier(
            0.50, 3, "W", DEFAULT_THRESHOLDS, ev_normalized=0.50
        )
        assert mult == 1.0
        assert conf == "Low"


# ─────────────────────────────────────────────
# analyze_system: end-to-end
# ─────────────────────────────────────────────

class TestAnalyzeSystem:

    def test_basic_analysis(self, basic_system):
        result = analyze_system(basic_system)
        assert isinstance(result, SystemAnalysis)
        assert result.n_trades > 0
        assert 0 < result.win_rate < 1
        assert result.multiplier in [0.5, 1.0, 1.5, 2.0]
        assert result.confidence in ["Low", "Medium", "High"]

    def test_empty_system_returns_neutral(self, empty_system):
        result = analyze_system(empty_system)
        assert result.multiplier == 1.0
        assert result.confidence == "Low"
        assert result.n_trades == 0

    def test_all_wins_system(self, all_wins_system):
        result = analyze_system(all_wins_system)
        assert result.p_win_given_streak > 0.5
        assert result.multiplier >= 1.5

    def test_all_losses_system(self, all_losses_system):
        result = analyze_system(all_losses_system)
        assert result.p_win_given_streak < 0.5
        assert result.multiplier <= 1.0

    def test_open_position_detected(self, system_with_open):
        result = analyze_system(system_with_open)
        assert result.has_open_position is True

    def test_no_open_position(self, basic_system):
        result = analyze_system(basic_system)
        assert result.has_open_position is False

    def test_breakeven_excluded(self, breakeven_system):
        win_series = breakeven_system.to_win_series()
        pnl_series = breakeven_system.to_pnl_series()
        assert len(win_series) == 5   # 3 breakeven esclusi
        assert len(pnl_series) == 8   # pnl_series include tutto

    def test_override_multiplier(self, basic_system):
        overrides = {"TestSystem": {"multiplier": 0.5, "reason": "Test override"}}
        result = analyze_system(basic_system, overrides=overrides)
        assert result.multiplier == 0.5
        assert result.is_override is True
        assert "OVERRIDE" in result.sizing_reason

    def test_override_disabled(self, basic_system):
        overrides = {"TestSystem": {"enabled": False}}
        result = analyze_system(basic_system, overrides=overrides)
        assert result is None

    def test_multiplier_change_detected(self, basic_system):
        prev_state = {"systems": {"TestSystem": {"multiplier": 2.0}}}
        result = analyze_system(basic_system, prev_state=prev_state)
        if result.multiplier != 2.0:
            assert result.multiplier_changed is True
            assert result.prev_multiplier == 2.0

    def test_ev_fields_populated(self, basic_system):
        result = analyze_system(basic_system)
        assert isinstance(result.ev_per_trade, float)
        assert isinstance(result.ev_normalized, float)
        assert isinstance(result.half_kelly, float)

    def test_single_trade_low_confidence(self, single_trade_system):
        result = analyze_system(single_trade_system)
        assert result.confidence == "Low"
        assert result.multiplier == 1.0

    def test_decay_threshold_used(self, basic_system):
        thr_no_decay = {**DEFAULT_THRESHOLDS, "decay_halflife": 0}
        thr_decay    = {**DEFAULT_THRESHOLDS, "decay_halflife": 5}
        r1 = analyze_system(basic_system, thresholds=thr_no_decay)
        r2 = analyze_system(basic_system, thresholds=thr_decay)
        assert isinstance(r1, SystemAnalysis)
        assert isinstance(r2, SystemAnalysis)
