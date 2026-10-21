"""时间序列预测：未来 30 天订单量与收入。

模型：
1. Seasonal Naive（周季节基线）：用上周同一天作为预测；
2. SARIMA(1,1,1)(1,0,1,7)：显式建模周季节性与趋势；
3. LightGBM：日期特征 + 滞后/滚动特征，递归多步预测。

验证：
- 滚动原点（rolling origin）：3 个起点，每个预测未来 30 天，训练数据只到起点之前；
- 不使用随机打乱，严格按时间顺序；
- 指标 MAE / RMSE / MAPE（仅对非零实际值）；
- 预测区间用滚动验证残差的经验 10%/90% 分位（80% 区间）。

数据边界：
- 只用 2017-01-01 ~ 2018-08-31，避开不完整月份；
- 2017-11 的 Black Friday 是异常峰值，SARIMA/LightGBM 都难以提前预知，报告中单独说明；
- 30 天预测适合运营排期参考，不应被包装成长期业务预测。

用法：python -m src.models.forecasting
产物（models/artifacts/）：
  forecast_metrics.json
  forecast_orders.csv
  forecast_revenue.csv
  forecast_validation.csv
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

from src import config, sql_engine

TRAIN_START = "2017-01-01"
# 数据在 2018-08-23 之后出现断崖式下降（最后一周订单未完整采集），
# 若把这段当成真实需求，所有模型都会被"训练"出一段假衰退。因此截到最后一个完整日。
TRAIN_END = "2018-08-22"
HORIZON = 30
ORIGINS = ["2018-06-01", "2018-06-16", "2018-07-01", "2018-07-16"]
FUTURE_START = "2018-08-23"
RANDOM_STATE = 42

TARGETS = {"orders": "订单量", "revenue": "收入"}


def load_daily() -> pd.DataFrame:
    df = sql_engine.read_sql(
        """
        SELECT
            order_date,
            COUNT(*) AS orders,
            SUM(payment_total) AS revenue
        FROM fct_order
        WHERE is_valid_order = 1
          AND order_date BETWEEN ? AND ?
        GROUP BY order_date
        ORDER BY order_date
        """,
        params=[TRAIN_START, TRAIN_END],
    )
    df["date"] = pd.to_datetime(df["order_date"])
    full_range = pd.date_range(TRAIN_START, TRAIN_END, freq="D")
    df = df.set_index("date").reindex(full_range).rename_axis("date").reset_index()
    df["orders"] = df["orders"].fillna(0).astype(int)
    df["revenue"] = df["revenue"].fillna(0.0)
    return df[["date", "orders", "revenue"]]


def seasonal_naive(history: pd.Series, horizon: int) -> np.ndarray:
    values = history.to_numpy(dtype=float)
    preds = []
    for step in range(horizon):
        index = len(values) - 7 + (step % 7)
        preds.append(values[index] if index >= 0 else values.mean())
    return np.array(preds, dtype=float)


def sarima_forecast(history: pd.Series, horizon: int) -> np.ndarray:
    """对数尺度上的 SARIMA，避免负预测。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = SARIMAX(
            np.log1p(history.to_numpy(dtype=float)),
            order=(1, 1, 1),
            seasonal_order=(1, 0, 1, 7),
            enforce_stationarity=False,
            enforce_invertibility=False,
        )
        fitted = model.fit(disp=False, maxiter=100)
        forecast = fitted.get_forecast(steps=horizon).predicted_mean
    return np.clip(np.expm1(np.asarray(forecast, dtype=float)), 0, None)


def _calendar_features(date: pd.Timestamp) -> Dict[str, float]:
    return {
        "dow": date.dayofweek,
        "dom": date.day,
        "month": date.month,
        "is_weekend": int(date.dayofweek >= 5),
        "day_of_year": date.dayofyear,
    }


def _lag_features(history: List[float], date: pd.Timestamp) -> Dict[str, float]:
    """用历史序列构造滞后与滚动特征（history 的最后一项是 date 前一天）。"""
    values = np.asarray(history, dtype=float)
    features = _calendar_features(date)
    for lag in (1, 7, 14, 21, 28):
        features["lag_%d" % lag] = float(values[-lag]) if len(values) >= lag else float(values.mean())
    for window in (7, 14, 28):
        segment = values[-window:] if len(values) >= window else values
        features["roll_mean_%d" % window] = float(segment.mean())
        features["roll_std_%d" % window] = float(segment.std(ddof=0)) if len(segment) > 1 else 0.0
    return features


def _training_frame(series: pd.Series) -> pd.DataFrame:
    dates = series.index
    rows = []
    for i in range(28, len(series)):
        date = dates[i]
        features = _lag_features(list(series.iloc[:i].to_numpy(dtype=float)), date)
        features["y"] = float(series.iloc[i])
        rows.append(features)
    return pd.DataFrame(rows)


def lightgbm_forecast(history: pd.Series, horizon: int) -> np.ndarray:
    from lightgbm import LGBMRegressor  # 延迟导入：避免 pytest 等场景在收集阶段加载原生库

    frame = _training_frame(history)
    feature_columns = [c for c in frame.columns if c != "y"]
    model = LGBMRegressor(
        n_estimators=400,
        learning_rate=0.04,
        num_leaves=15,
        min_child_samples=20,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=RANDOM_STATE,
        verbose=-1,
    )
    model.fit(frame[feature_columns], frame["y"])
    values = list(history.to_numpy(dtype=float))
    predictions = []
    last_date = history.index[-1]
    for step in range(1, horizon + 1):
        date = last_date + pd.Timedelta(days=step)
        features = _lag_features(values, date)
        prediction = float(model.predict(pd.DataFrame([features]))[0])
        prediction = max(0.0, prediction)
        predictions.append(prediction)
        values.append(prediction)
    return np.array(predictions, dtype=float)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> Dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    error = actual - predicted
    nonzero = actual != 0
    mape = float(np.mean(np.abs(error[nonzero] / actual[nonzero]))) if nonzero.any() else float("nan")
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "mape": mape,
        "n": int(len(actual)),
    }


def rolling_validation(series: pd.Series) -> Tuple[pd.DataFrame, Dict[str, Dict[str, float]], Dict[str, float]]:
    """滚动原点验证，返回明细、平均指标、残差分位数。"""
    records = []
    for origin in ORIGINS:
        origin_date = pd.Timestamp(origin)
        history = series[series.index < origin_date]
        actual = series[(series.index >= origin_date) & (series.index < origin_date + pd.Timedelta(days=HORIZON))]
        if len(actual) < HORIZON:
            continue
        predictions = {
            "SeasonalNaive": seasonal_naive(history, HORIZON),
            "SARIMA": sarima_forecast(history, HORIZON),
            "LightGBM": lightgbm_forecast(history, HORIZON),
        }
        for model_name, values in predictions.items():
            for date, value in zip(actual.index, values):
                records.append(
                    {
                        "origin": origin,
                        "date": date,
                        "model": model_name,
                        "actual": float(series.loc[date]),
                        "predicted": float(value),
                    }
                )
    detail = pd.DataFrame(records)
    summary: Dict[str, Dict[str, float]] = {}
    residuals: Dict[str, float] = {}
    for model_name, group in detail.groupby("model"):
        summary[model_name] = _metrics(group["actual"], group["predicted"])
        residuals[model_name] = group["actual"] - group["predicted"]
    return detail, summary, residuals


def _interval_from_residuals(residuals: np.ndarray, point: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    lower_q, upper_q = np.quantile(residuals, [0.1, 0.9])
    return np.clip(point + lower_q, 0, None), np.clip(point + upper_q, 0, None)


def run() -> Dict[str, object]:
    daily = load_daily()
    print("  日粒度序列：%d 天（%s ~ %s）" % (len(daily), daily["date"].min().date(), daily["date"].max().date()))

    results: Dict[str, object] = {}
    validation_frames = []
    metrics: Dict[str, Dict[str, Dict[str, float]]] = {}
    forecasts: Dict[str, pd.DataFrame] = {}

    for target, label in TARGETS.items():
        series = daily.set_index("date")[target].astype(float)
        print("  滚动验证：%s …" % label)
        detail, summary, residuals = rolling_validation(series)
        detail["target"] = target
        validation_frames.append(detail)
        metrics[target] = summary

        best_model = min(summary, key=lambda name: summary[name]["rmse"])
        print("    %s 最优模型：%s（RMSE %.2f）" % (label, best_model, summary[best_model]["rmse"]))

        # 全量训练，预测未来 30 天
        history = series
        if best_model == "SeasonalNaive":
            point = seasonal_naive(history, HORIZON)
        elif best_model == "SARIMA":
            point = sarima_forecast(history, HORIZON)
        else:
            point = lightgbm_forecast(history, HORIZON)
        lower, upper = _interval_from_residuals(residuals[best_model].to_numpy(dtype=float), point)

        forecast = pd.DataFrame(
            {
                "date": pd.date_range(FUTURE_START, periods=HORIZON, freq="D"),
                "target": target,
                "model": best_model,
                "forecast": point.round(2),
                "lower_80": lower.round(2),
                "upper_80": upper.round(2),
            }
        )
        forecasts[target] = forecast
        results[target] = {
            "best_model": best_model,
            "metrics": summary,
            "forecast_total": float(point.sum()),
            "forecast_mean": float(point.mean()),
        }

    validation = pd.concat(validation_frames, ignore_index=True)
    artifact_dir = config.MODEL_DIR
    validation.to_csv(artifact_dir / "forecast_validation.csv", index=False, encoding="utf-8-sig")
    forecasts["orders"].to_csv(artifact_dir / "forecast_orders.csv", index=False, encoding="utf-8-sig")
    forecasts["revenue"].to_csv(artifact_dir / "forecast_revenue.csv", index=False, encoding="utf-8-sig")

    historical = daily.copy()
    historical["date"] = historical["date"].dt.strftime("%Y-%m-%d")
    historical.to_csv(artifact_dir / "forecast_history.csv", index=False, encoding="utf-8-sig")

    summary_json = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "train_period": [TRAIN_START, TRAIN_END],
        "horizon_days": HORIZON,
        "rolling_origins": ORIGINS,
        "targets": results,
        "notes": [
            "滚动原点验证：每个起点只用起点之前的数据训练，预测未来 30 天，未随机打乱时间顺序。",
            "原始数据在 2018-08-23 之后订单量断崖式下降（采集不完整），训练与预测均截到 2018-08-22。",
            "2017-11 Black Friday 是异常峰值，模型无法提前预知，误差会被这段抬高。",
            "预测区间来自滚动验证残差的经验 10%/90% 分位，是 80% 区间，不是保证。",
            "Olist 数据只覆盖约两年，长期趋势与结构性变化无法可靠外推。",
        ],
        "anomaly_months": ["2017-11"],
    }
    (artifact_dir / "forecast_metrics.json").write_text(
        json.dumps(summary_json, ensure_ascii=False, indent=2, default=float), encoding="utf-8"
    )

    for target, label in TARGETS.items():
        result = results[target]
        print("  %s：未来 30 天合计 %.0f，模型 %s" % (label, result["forecast_total"], result["best_model"]))
    return summary_json


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
