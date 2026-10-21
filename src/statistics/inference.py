"""统计推断基础工具：置信区间、假设检验、效应量、功效/样本量、多重检验校正。

设计原则：
1. 每个函数只做一件事，返回**字典**而不是格式化字符串，方便被实验模块、报告和测试复用。
2. 统一暴露 p 值、置信区间与效应量，避免只看 p 值下结论。
3. 所有方法都是频率学派经典方法，参数与公式在 docstring 中写明。

注意：这里的检验只能回答「两组差异是否可能由抽样波动造成」，
不能自动推出因果结论；因果解释依赖随机分组或可信的识别策略。
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize, proportions_ztest


# ---------------------------------------------------------------- 描述统计与区间估计
def mean_ci(values: Sequence[float], confidence: float = 0.95) -> Dict[str, float]:
    """均值的 t 分布置信区间（大样本下与正态近似一致）。"""
    array = np.asarray(values, dtype=float)
    array = array[~np.isnan(array)]
    n = len(array)
    if n < 2:
        raise ValueError("至少需要 2 个观测值")
    mean = float(array.mean())
    se = float(array.std(ddof=1) / np.sqrt(n))
    tcrit = float(stats.t.ppf(1 - (1 - confidence) / 2, df=n - 1))
    return {
        "n": n,
        "mean": mean,
        "std": float(array.std(ddof=1)),
        "se": se,
        "ci_low": mean - tcrit * se,
        "ci_high": mean + tcrit * se,
        "confidence": confidence,
    }


def proportion_ci(successes: int, n: int, confidence: float = 0.95) -> Dict[str, float]:
    """单比例置信区间，默认 Wilson 区间（小样本/极端比例比 Wald 更稳健）。"""
    if n <= 0:
        raise ValueError("样本量必须大于 0")
    p = successes / n
    z = float(stats.norm.ppf(1 - (1 - confidence) / 2))
    denominator = 1 + z ** 2 / n
    center = (p + z ** 2 / (2 * n)) / denominator
    half = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / denominator
    return {
        "n": int(n),
        "successes": int(successes),
        "rate": float(p),
        "ci_low": float(max(0.0, center - half)),
        "ci_high": float(min(1.0, center + half)),
        "confidence": confidence,
    }


# ---------------------------------------------------------------- 假设检验
def two_proportion_test(
    successes_a: int,
    n_a: int,
    successes_b: int,
    n_b: int,
    confidence: float = 0.95,
) -> Dict[str, float]:
    """两比例 z 检验（H0: p_a = p_b），附差值的 Wald 置信区间与效应量。

    参数顺序为 (A, B)，差值定义为 p_b - p_a。
    """
    p_a = successes_a / n_a
    p_b = successes_b / n_b
    diff = p_b - p_a
    pooled = (successes_a + successes_b) / (n_a + n_b)
    se_pooled = np.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    z_value = diff / se_pooled if se_pooled > 0 else 0.0
    p_value = float(2 * (1 - stats.norm.cdf(abs(z_value))))

    se_diff = np.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    z_crit = float(stats.norm.ppf(1 - (1 - confidence) / 2))
    chi2, chi2_p = stats.chi2_contingency(
        [[successes_a, n_a - successes_a], [successes_b, n_b - successes_b]], correction=False
    )[:2]

    return {
        "rate_a": float(p_a),
        "rate_b": float(p_b),
        "diff": float(diff),
        "relative_lift": float(diff / p_a) if p_a > 0 else float("nan"),
        "z": float(z_value),
        "p_value": p_value,
        "ci_low": float(diff - z_crit * se_diff),
        "ci_high": float(diff + z_crit * se_diff),
        "chi2": float(chi2),
        "chi2_p_value": float(chi2_p),
        "cohens_h": cohens_h(p_a, p_b),
        "n_a": int(n_a),
        "n_b": int(n_b),
        "confidence": confidence,
    }


def welch_ttest(
    sample_a: Sequence[float], sample_b: Sequence[float], confidence: float = 0.95
) -> Dict[str, float]:
    """Welch t 检验（不假设两组方差相等），附均值差置信区间与 Cohen's d。

    差值定义为 mean_b - mean_a。
    """
    a = np.asarray(sample_a, dtype=float)
    b = np.asarray(sample_b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        raise ValueError("每组至少需要 2 个观测值")

    result = stats.ttest_ind(b, a, equal_var=False)
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    diff = float(b.mean() - a.mean())
    # Welch-Satterthwaite 自由度
    df = se ** 4 / (
        (a.var(ddof=1) / len(a)) ** 2 / (len(a) - 1)
        + (b.var(ddof=1) / len(b)) ** 2 / (len(b) - 1)
    )
    tcrit = float(stats.t.ppf(1 - (1 - confidence) / 2, df=df))

    return {
        "mean_a": float(a.mean()),
        "mean_b": float(b.mean()),
        "diff": diff,
        "relative_lift": float(diff / a.mean()) if a.mean() != 0 else float("nan"),
        "t": float(result.statistic),
        "p_value": float(result.pvalue),
        "ci_low": float(diff - tcrit * se),
        "ci_high": float(diff + tcrit * se),
        "cohens_d": cohens_d(a, b),
        "n_a": int(len(a)),
        "n_b": int(len(b)),
        "confidence": confidence,
    }


def chi_square_test(table: Sequence[Sequence[int]]) -> Dict[str, float]:
    """列联表卡方独立性检验，附 Cramér's V 效应量。"""
    array = np.asarray(table, dtype=float)
    chi2, p_value, dof, expected = stats.chi2_contingency(array)
    n = array.sum()
    v = float(np.sqrt(chi2 / (n * (min(array.shape) - 1)))) if n > 0 else 0.0
    return {
        "chi2": float(chi2),
        "p_value": float(p_value),
        "dof": int(dof),
        "n": int(n),
        "cramers_v": v,
        "min_expected": float(expected.min()),
    }


# ---------------------------------------------------------------- 效应量
def cohens_h(p1: float, p2: float) -> float:
    """两比例差异的 Cohen's h（0.2 小 / 0.5 中 / 0.8 大）。"""
    return float(2 * np.arcsin(np.sqrt(p2)) - 2 * np.arcsin(np.sqrt(p1)))


def standardized_mean_diff(sample_a: Sequence[float], sample_b: Sequence[float]) -> float:
    """标准化均值差（SMD），用于随机化后的协变量平衡性检查。

    经验阈值：|SMD| < 0.1 通常认为两组在该协变量上平衡。
    """
    a = np.asarray(sample_a, dtype=float)
    b = np.asarray(sample_b, dtype=float)
    pooled_var = (a.var(ddof=1) + b.var(ddof=1)) / 2
    if pooled_var <= 0:
        return 0.0
    return float((b.mean() - a.mean()) / np.sqrt(pooled_var))


def cohens_d(sample_a: Sequence[float], sample_b: Sequence[float]) -> float:
    """两均值差异的 Cohen's d（合并标准差）。"""
    a = np.asarray(sample_a, dtype=float)
    b = np.asarray(sample_b, dtype=float)
    n_a, n_b = len(a), len(b)
    pooled_var = ((n_a - 1) * a.var(ddof=1) + (n_b - 1) * b.var(ddof=1)) / (n_a + n_b - 2)
    if pooled_var <= 0:
        return 0.0
    return float((b.mean() - a.mean()) / np.sqrt(pooled_var))


# ---------------------------------------------------------------- 功效与样本量
def required_sample_size_proportion(
    baseline_rate: float,
    expected_rate: float,
    alpha: float = 0.05,
    power: float = 0.8,
    ratio: float = 1.0,
) -> Dict[str, float]:
    """两比例检验每组所需样本量（双侧）。

    使用 Cohen's h 作为效应量，适用于「相对提升」较小的场景。
    """
    effect = abs(proportion_effectsize(expected_rate, baseline_rate))
    analysis = NormalIndPower()
    n_per_group = analysis.solve_power(
        effect_size=effect, alpha=alpha, power=power, ratio=ratio, alternative="two-sided"
    )
    return {
        "baseline_rate": baseline_rate,
        "expected_rate": expected_rate,
        "absolute_lift": expected_rate - baseline_rate,
        "relative_lift": (expected_rate - baseline_rate) / baseline_rate if baseline_rate else float("nan"),
        "cohens_h": float(effect),
        "n_per_group": float(np.ceil(n_per_group)),
        "n_total": float(np.ceil(n_per_group) * (1 + ratio)),
        "alpha": alpha,
        "power": power,
    }


def achieved_power_proportion(
    baseline_rate: float,
    expected_rate: float,
    n_per_group: int,
    alpha: float = 0.05,
    ratio: float = 1.0,
) -> float:
    """在给定每组样本量下，两比例检验能达到的统计功效。"""
    effect = abs(proportion_effectsize(expected_rate, baseline_rate))
    return float(
        NormalIndPower().power(
            effect_size=effect, nobs1=n_per_group, alpha=alpha, ratio=ratio, alternative="two-sided"
        )
    )


def required_sample_size_mean(
    delta: float,
    sd: float,
    alpha: float = 0.05,
    power: float = 0.8,
    ratio: float = 1.0,
) -> Dict[str, float]:
    """两均值检验每组所需样本量（Cohen's d = delta / sd）。"""
    if sd <= 0:
        raise ValueError("标准差必须大于 0")
    effect = abs(delta) / sd
    n_per_group = NormalIndPower().solve_power(
        effect_size=effect, alpha=alpha, power=power, ratio=ratio, alternative="two-sided"
    )
    return {
        "delta": delta,
        "sd": sd,
        "cohens_d": float(effect),
        "n_per_group": float(np.ceil(n_per_group)),
        "n_total": float(np.ceil(n_per_group) * (1 + ratio)),
        "alpha": alpha,
        "power": power,
    }


# ---------------------------------------------------------------- 多重检验
def adjust_pvalues(p_values: Sequence[float], method: str = "bh") -> Dict[str, object]:
    """多重假设检验校正。

    method:
      - "bh" / "fdr_bh"：Benjamini-Hochberg，控制错误发现率（探索型分析常用）
      - "holm"：Holm-Bonferroni，控制族错误率（更保守）
    """
    p = np.asarray(p_values, dtype=float)
    alias = {"bh": "fdr_bh", "fdr": "fdr_bh", "holm": "holm"}
    if method not in alias:
        raise ValueError("不支持的校正方法：%s" % method)
    rejected, adjusted, _, _ = multipletests(p, alpha=0.05, method=alias[method])
    return {
        "method": alias[method],
        "p_values": [float(v) for v in p],
        "adjusted": [float(v) for v in adjusted],
        "rejected": [bool(v) for v in rejected],
    }


def significance_label(p_value: float, alpha: float = 0.05) -> str:
    """把 p 值翻译成便于报告使用的显著性标签。"""
    if p_value < 0.001:
        return "p < 0.001"
    if p_value < alpha:
        return "p = %.3f（显著）" % p_value
    return "p = %.3f（不显著）" % p_value
