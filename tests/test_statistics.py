"""统计工具的正确性测试（用可手算/已知性质的结果）。"""
import numpy as np
import pytest

from src.statistics import inference


def test_mean_ci_contains_sample_mean():
    result = inference.mean_ci([1, 2, 3, 4, 5])
    assert result["mean"] == pytest.approx(3.0)
    assert result["ci_low"] < 3.0 < result["ci_high"]
    assert result["n"] == 5


def test_wilson_interval_bounds():
    result = inference.proportion_ci(0, 100)
    assert result["rate"] == 0.0
    assert result["ci_low"] == pytest.approx(0.0, abs=1e-12)
    assert 0 < result["ci_high"] < 0.05  # 100 次 0 成功，上界仍很小


def test_two_proportion_test_known_direction():
    # 10% vs 13%，每组 1000 人：差异约 3pp，p 值应小于 0.05
    result = inference.two_proportion_test(100, 1000, 130, 1000)
    assert result["diff"] == pytest.approx(0.03, abs=1e-9)
    assert result["p_value"] < 0.05
    assert result["ci_low"] < result["diff"] < result["ci_high"]
    assert result["cohens_h"] > 0
    assert result["chi2_p_value"] == pytest.approx(result["p_value"], abs=1e-6)


def test_welch_ttest_detects_shift():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 500)
    b = rng.normal(0.5, 1, 500)
    result = inference.welch_ttest(a, b)
    assert result["diff"] == pytest.approx(0.5, abs=0.15)
    assert result["p_value"] < 1e-4
    assert result["cohens_d"] > 0.3


def test_chi_square_detects_association():
    result = inference.chi_square_test([[100, 900], [300, 700]])
    assert result["p_value"] < 1e-20
    assert result["cramers_v"] > 0.1


def test_bh_adjustment_is_monotone_and_controls_discovery():
    result = inference.adjust_pvalues([0.001, 0.02, 0.04, 0.5], method="bh")
    adjusted = result["adjusted"]
    assert all(0 <= value <= 1 for value in adjusted)
    assert adjusted[0] <= adjusted[1] <= adjusted[2] <= adjusted[3] + 1e-12
    assert result["rejected"][0] is True


def test_required_sample_size_decreases_with_effect():
    small_effect = inference.required_sample_size_proportion(0.03, 0.032)
    large_effect = inference.required_sample_size_proportion(0.03, 0.04)
    assert small_effect["n_per_group"] > large_effect["n_per_group"] > 0
    assert inference.achieved_power_proportion(0.03, 0.04, 100000) > 0.8
