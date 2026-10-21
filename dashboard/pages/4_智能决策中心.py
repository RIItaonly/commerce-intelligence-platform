"""页 4 · 智能决策中心：模型结果 → 行动建议。

阶段 3 版本：保留阶段 2 的行动优先级与机会点，接入
流失风险、销售预测、客户分群、商品推荐与模拟 A/B 实验结果。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(HERE), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common import (churn_calibration, churn_comparison, churn_importance,
                    churn_metrics, churn_scores, experiment_summary,
                    fmt_money, fmt_num, fmt_pct, forecast_history,
                    forecast_metrics, forecast_orders, forecast_revenue,
                    growth_attribution, headline, peak_attribution,
                    popular_items, recommendation_examples,
                    recommendation_metrics, rfm_overview, rfm_segments,
                    segmentation_metrics, segmentation_profiles,
                    seller_concentration)

st.set_page_config(page_title="智能决策中心", page_icon="🧭", layout="wide")
st.title("🧭 智能决策中心")
st.caption("模型结果 → 分层动作。历史数据用于预测与排序；因果结论只来自独立的模拟实验。")

# ---------------------------------------------------------------- 顶部摘要
fc = forecast_metrics()
orders_fc = fc["targets"]["orders"]
revenue_fc = fc["targets"]["revenue"]
risk_df = churn_scores()
rr = experiment_summary()

high_risk = int((risk_df["risk_band"] == "高流失风险（复购概率最低 10%）").sum())

m1, m2, m3, m4 = st.columns(4)
m1.metric("未来 30 天订单预测", fmt_num(orders_fc["forecast_total"]),
          help="最优模型 %s，滚动验证 MAPE %.1f%%" % (
              orders_fc["best_model"], orders_fc["metrics"][orders_fc["best_model"]]["mape"] * 100))
m2.metric("未来 30 天收入预测", fmt_money(revenue_fc["forecast_total"]),
          help="最优模型 %s，滚动验证 MAPE %.1f%%" % (
              revenue_fc["best_model"], revenue_fc["metrics"][revenue_fc["best_model"]]["mape"] * 100))
m3.metric("高风险客户（最新快照）", fmt_num(high_risk),
          help="共 %s 位客户参与打分；高风险 = 复购概率最低 10%%" % fmt_num(len(risk_df)))
m4.metric("模拟实验转化率提升", "%+.2f pp" % (rr["conversion_diff"] * 100),
          help="模拟数据，p = %.3f；不是 Olist 真实实验" % rr["conversion_p_value"])

st.caption("模型卡与完整实验报告：[reports/model_card.md] · [reports/experiment_report.md]")

tabs = st.tabs(["行动总览", "流失风险", "销售预测", "客户分群", "商品推荐", "模拟 A/B"])

# ---------------------------------------------------------------- 行动总览
with tabs[0]:
    seg = rfm_segments()
    o = rfm_overview()
    sc = seller_concentration()
    h = headline()
    growth = growth_attribution()["by_category"]
    peak = peak_attribution()

    st.subheader("行动优先级（基于历史分析 + 模型结果）")
    actions = {
        "流失风险（180-365 天未购）": ("高", "唤醒召回：优先触达流失模型的高风险客户，定向优惠券 + 爆品推送。"),
        "沉睡客户（超过 365 天未购）": ("中", "低成本触达（短信/邮件），避免高补贴；作为流失模型的历史样本。"),
        "活跃客户（180 天内有购买）": ("高", "防流失 + 提频：物流时效是核心体验抓手（见履约页），优先改善配送体验。"),
        "复购客户（2 单）": ("高", "升级运营：人数占 2.8% 但贡献 4.9% 收入，向忠诚计划导流。"),
        "忠诚客户（3 单以上）": ("中", "会员权益 + 封测反馈渠道；规模小（约 240 人），维护重于拉新。"),
        "近期活跃（90 天内首单）": ("高", "首购后 30 天是复购窗口，用推荐模型做下一单商品推荐。"),
    }
    rows = []
    for _, r in seg.iterrows():
        priority, action = actions.get(r["segment"], ("—", "—"))
        rows.append({
            "分群": r["segment"],
            "人数": fmt_num(r["customers"]),
            "人数占比": fmt_pct(r["customer_share"]),
            "累计收入": fmt_money(r["revenue"]),
            "收入占比": fmt_pct(r["revenue_share"]),
            "优先级": priority,
            "建议动作": action,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                 column_config={"建议动作": st.column_config.TextColumn(width="large")})

    st.divider()
    st.subheader("三大机会点")
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("##### 1️⃣ 复购留存")
        st.metric("仅 1 单用户占比", fmt_pct(o["single_order_share"]),
                  help="行业公开口径 Olist 约 96-97%，复购是最大的收入杠杆")
        st.info("**结论：** 复购用户收入贡献显著高于人数占比（5.7% vs 3.0%）。"
                "**建议：** 首购后 30 天定向推荐 + 运费券；流失模型负责分层，推荐模型负责选品。")

    with c2:
        st.markdown("##### 2️⃣ 履约体验")
        st.metric("整体迟到率", fmt_pct(h["late_delivery_rate"]),
                  help="迟到单平均评分 %.2f vs 准时单 %.2f" % (2.57, 4.30))
        st.info("**结论：** 迟到单差评率 54%，准时单仅 9.2%；RJ/BA 等州是重灾区。"
                "**建议：** 对长尾州优化承运商组合、对慢品类设置更真实的承诺时效。")

    with c3:
        st.markdown("##### 3️⃣ 品类增长")
        top_growth = growth.head(1).iloc[0]
        st.metric("同比增长第一品类", str(top_growth["key"]),
                  help="%s → %s（%s）" % (fmt_money(top_growth["prev_gmv"]),
                                         fmt_money(top_growth["cur_gmv"]),
                                         "%+.0f%%" % (top_growth["delta"] / top_growth["prev_gmv"] * 100
                                                      if top_growth["prev_gmv"] else 0)))
        st.info("**结论：** %s 贡献同比增量 %.1f%%；黑五月（%s）单月 GMV 冲至 %s。"
                "**建议：** 大促前向高贡献品类倾斜流量与库存。"
                % (top_growth["key"], top_growth["contribution_share"] * 100,
                   peak["peak_month"], fmt_money(peak["peak_gmv"])))

    st.divider()
    with st.expander("数据来源与口径"):
        st.markdown(
            "- 行动表来自 `analytics_rfm` 规则分群；模型结果来自 `models/artifacts/` 下的产物\n"
            "- 商家集中度：Top 10 GMV 占比 %s，Top 100 占比 %s（共 %s 家）\n"
            "- 边界：Olist 是观测数据，模型结论是预测性/相关性，不做因果断言；"
            "因果结论只来自独立模拟实验"
            % (fmt_pct(sc["top10_share"]), fmt_pct(sc["top100_share"]), fmt_num(sc["n_sellers"]))
        )

# ---------------------------------------------------------------- 流失风险
with tabs[1]:
    st.subheader("流失风险 / 复购倾向")
    st.markdown(
        "任务定义：以每月 1 日为快照，用**过去 90 天**行为预测**未来 30 天**是否复购；"
        "流失风险 = 1 − P(复购)。训练 2017-04 ~ 2018-03，测试 2018-04 ~ 2018-08，按时间切分防泄漏。"
    )

    cm = churn_metrics()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("测试集 PR-AUC", "%.3f" % cm["metrics"][cm["chosen_model"]]["pr_auc"],
              help="正类仅 %.2f%%，PR-AUC 比 accuracy 更有意义" % (cm["test"]["positive_rate"] * 100))
    k2.metric("测试集 ROC-AUC", "%.3f" % cm["metrics"][cm["chosen_model"]]["roc_auc"])
    k3.metric("top 10% lift", "%.2fx" % cm["metrics"][cm["chosen_model"]]["lift_at_10pct"],
              help="挑出预测复购概率最高的 10% 用户，其实际复购率是随机的多少倍")
    k4.metric("最优模型", cm["chosen_model"])

    col1, col2 = st.columns([3, 2])
    with col1:
        st.markdown("**模型对比（时间外测试集）**")
        cmp = churn_comparison().copy()
        cmp = cmp.rename(columns={
            "model": "模型", "pr_auc": "PR-AUC", "roc_auc": "ROC-AUC",
            "brier": "Brier", "lift_at_10pct": "top10% lift",
            "top10_recall": "top10 recall",
        })
        st.dataframe(
            cmp[["模型", "PR-AUC", "ROC-AUC", "Brier", "top10% lift", "top10 recall"]],
            use_container_width=True, hide_index=True,
            column_config={
                "PR-AUC": st.column_config.NumberColumn(format="%.4f"),
                "ROC-AUC": st.column_config.NumberColumn(format="%.3f"),
                "Brier": st.column_config.NumberColumn(format="%.4f"),
                "top10% lift": st.column_config.NumberColumn(format="%.2fx"),
                "top10 recall": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.caption("随机基线 = 按先验概率随机排序；Recency 规则 = 只看距上次购买天数。")
    with col2:
        st.markdown("**最新快照风险分层**")
        band_counts = (risk_df["risk_band"].value_counts()
                       .rename_axis("band").reset_index(name="customers"))
        band_counts["band"] = band_counts["band"].map({
            "高流失风险（复购概率最低 10%）": "高风险（后 10%）",
            "中高流失风险（最低 10%-40%）": "中高风险（10%-40%）",
            "常规（复购概率前 60%）": "常规（前 60%）",
        })
        order = ["高风险（后 10%）", "中高风险（10%-40%）", "常规（前 60%）"]
        band_counts["band"] = pd.Categorical(band_counts["band"], categories=order, ordered=True)
        band_counts = band_counts.sort_values("band")
        fig = px.bar(band_counts, x="band", y="customers", color="band",
                     color_discrete_sequence=["#EF553B", "#FFA15A", "#636EFA"],
                     labels={"band": "", "customers": "客户数"})
        fig.update_layout(height=300, showlegend=False, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**主要特征（LightGBM 重要性）**")
        imp = churn_importance().head(12).copy()
        imp["feature"] = imp["feature"].str.replace("num__", "", regex=False)
        labels = {
            "avg_delivery_days_90d": "近 90 天平均配送天数",
            "freight_share_90d": "近 90 天运费占比",
            "recency_days": "距上次购买天数",
            "tenure_days": "客户生命周期天数",
            "avg_order_value_90d": "近 90 天客单价",
            "gmv_90d": "近 90 天 GMV",
            "lifetime_revenue": "历史累计收入",
            "avg_installments_90d": "近 90 天平均分期数",
            "revenue_90d": "近 90 天收入",
            "avg_review_90d": "近 90 天平均评分",
            "orders_90d": "近 90 天订单数",
            "late_rate_90d": "近 90 天迟到率",
        }
        imp["特征"] = imp["feature"].map(labels).fillna(imp["feature"])
        fig = px.bar(imp.sort_values("importance_share"), x="importance_share", y="特征",
                     orientation="h", labels={"importance_share": "重要性占比"})
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)
    with col4:
        st.markdown("**校准质量**")
        cal = churn_calibration().copy()
        cal["预测复购率"] = cal["mean_predicted"].map(lambda v: "%.2f%%" % (v * 100))
        cal["实际复购率"] = cal["observed_rate"].map(lambda v: "%.2f%%" % (v * 100))
        cal["绝对误差"] = cal["abs_gap"].map(lambda v: "%.3f pp" % (v * 100))
        st.dataframe(cal[["n", "预测复购率", "实际复购率", "绝对误差"]],
                     use_container_width=True, hide_index=True)
        st.caption("ECE = %.4f（按预测概率十分位分箱，越低越好）" % cal["ece"].iloc[0])
        st.markdown(
            "**读法：** 正类极稀有（约 0.4%），概率绝对值很小；模型的价值在于**排序**，"
            "不是承诺某个用户一定复购。"
        )

    st.markdown("**高风险客户示例（按流失风险排序，仅展示前 15 位）**")
    top = risk_df.sort_values("churn_risk", ascending=False).head(15).copy()
    view = pd.DataFrame({
        "客户": top["customer_unique_id"].str[:10] + "…",
        "州": top["customer_state"],
        "距上次购买（天）": top["recency_days"].round(0).astype(int),
        "近 90 天订单": top["orders_90d"].astype(int),
        "近 90 天收入": top["revenue_90d"].map(fmt_money),
        "历史订单": top["lifetime_orders"].astype(int),
        "流失风险": top["churn_risk"].map(fmt_pct),
    })
    st.dataframe(view, use_container_width=True, hide_index=True)
    st.warning(
        "**边界：** 测试集从未在训练集出现的客户子集 PR-AUC 更低（见模型卡），"
        "说明模型部分依赖老客户行为；Olist 约 97% 用户只买一次，"
        "这里的高风险分层适合**排序触达**，不能理解为「发券后一定复购」的因果效果。"
    )

# ---------------------------------------------------------------- 销售预测
with tabs[2]:
    st.subheader("未来 30 天销售预测")
    history = forecast_history()
    orders_pred = forecast_orders()
    revenue_pred = forecast_revenue()

    target = st.radio("预测目标", ["订单量", "收入"], horizontal=True)
    key = "orders" if target == "订单量" else "revenue"
    pred = orders_pred if key == "orders" else revenue_pred
    target_metrics = fc["targets"][key]
    best = target_metrics["best_model"]

    f1, f2, f3 = st.columns(3)
    f1.metric("未来 30 天合计", fmt_num(target_metrics["forecast_total"]) if key == "orders"
              else fmt_money(target_metrics["forecast_total"]))
    f2.metric("日均", fmt_num(target_metrics["forecast_mean"]) if key == "orders"
              else fmt_money(target_metrics["forecast_mean"]))
    f3.metric("最优模型", best,
              help="滚动验证 MAE %.1f / MAPE %.1f%%" % (
                  target_metrics["metrics"][best]["mae"], target_metrics["metrics"][best]["mape"] * 100))

    hist = history[["date", key]].dropna().tail(150)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["date"], y=hist[key], name="历史",
                             line=dict(color="#636EFA")))
    fig.add_trace(go.Scatter(x=pred["date"], y=pred["upper_80"], line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=pred["date"], y=pred["lower_80"], fill="tonexty",
                             fillcolor="rgba(239,85,59,0.15)", line=dict(width=0),
                             name="80% 预测区间"))
    fig.add_trace(go.Scatter(x=pred["date"], y=pred["forecast"], name="预测（%s）" % best,
                             line=dict(color="#EF553B")))
    fig.update_layout(height=400, margin=dict(l=10, r=10, t=20, b=10),
                      legend=dict(orientation="h", y=1.02),
                      yaxis_title=target, xaxis_title="")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**滚动原点验证（每次只用起点前数据训练，预测未来 30 天）**")
    rows = []
    for name, m in target_metrics["metrics"].items():
        rows.append({"模型": name, "MAE": m["mae"], "RMSE": m["rmse"], "MAPE": m["mape"]})
    met = pd.DataFrame(rows).sort_values("MAE")
    st.dataframe(met, use_container_width=True, hide_index=True,
                 column_config={
                     "MAE": st.column_config.NumberColumn(format="%.0f"),
                     "RMSE": st.column_config.NumberColumn(format="%.0f"),
                     "MAPE": st.column_config.NumberColumn(format="%.1f%%"),
                 })
    st.caption("验证起点：%s；训练区间：%s ~ %s" % (
        "、".join(fc["rolling_origins"]), fc["train_period"][0], fc["train_period"][1]))

    st.info(
        "**限制：** 2018-08-23 之后采集不完整，训练与预测均已截断；"
        "2017-11 Black Friday 是未建模的异常峰值，会抬高验证误差；"
        "预测区间来自残差分位数，适合运营排期与容量参考，不适合财务承诺。"
    )

# ---------------------------------------------------------------- 客户分群
with tabs[3]:
    st.subheader("客户分群（RFM + K-Means）")
    sm = segmentation_metrics()
    profiles = segmentation_profiles().copy()

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("分群数 k", str(sm["chosen_k"]))
    s2.metric("轮廓系数", "%.3f" % sm["silhouette"])
    s3.metric("bootstrap ARI", "%.3f" % sm["stability"]["bootstrap_ari_mean"],
              help="重抽样后分群一致性，越接近 1 越稳定")
    s4.metric("参与分群客户", fmt_num(sm["n_customers"]))

    col1, col2 = st.columns([3, 2])
    with col1:
        view = pd.DataFrame({
            "分群": profiles["cluster_name"],
            "客户数": profiles["customers"].map(fmt_num),
            "客户占比": profiles["customer_share"].map(fmt_pct),
            "收入占比": profiles["revenue_share"].map(fmt_pct),
            "平均 Recency（天）": profiles["avg_recency_days"].round(0).astype(int),
            "平均 Frequency": profiles["avg_frequency"].round(2),
            "平均消费额": profiles["avg_monetary"].map(fmt_money),
        })
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.caption("frequency 在 Olist 上信息量很低（约 97% 客户仅 1 单），分群主要驱动因素是 recency 与 monetary。")
    with col2:
        fig = px.scatter(profiles, x="customer_share", y="revenue_share",
                         size="customers", color="cluster_name", text="cluster_name",
                         size_max=50,
                         labels={"customer_share": "客户占比", "revenue_share": "收入占比",
                                 "cluster_name": "分群"})
        fig.add_shape(type="line", x0=0, y0=0, x1=0.4, y1=0.4,
                      line=dict(dash="dash", color="#999"))
        fig.update_traces(textposition="top center", textfont_size=10)
        fig.update_layout(height=360, showlegend=False, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_tickformat=".0%", yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("虚线为「收入占比 = 客户占比」；位于虚线上方代表该群收入贡献高于人数占比。")

    st.markdown("**与规则分群的对照（各规则分群落入最多的 K-Means 群）**")
    rule = pd.DataFrame(sm["rule_segment_dominant_cluster"]).rename(columns={
        "rule_segment": "规则分群", "dominant_cluster": "主要 K-Means 分群",
        "dominant_share": "占比",
    })
    rule["占比"] = rule["占比"].map(fmt_pct)
    st.dataframe(rule, use_container_width=True, hide_index=True)
    st.warning("分群是**描述性**的，不能解释为「该群体对营销更敏感」；要回答敏感度必须做实验。")

# ---------------------------------------------------------------- 商品推荐
with tabs[4]:
    st.subheader("商品推荐（热门基线 + item-item 协同过滤）")
    rm = recommendation_metrics()
    ev = rm["evaluation"]

    r1, r2, r3 = st.columns(3)
    r1.metric("可推荐目录", fmt_num(rm["catalog_size"]),
              help="训练期最热门的商品；Recall 分母包含全部测试购买商品，指标偏保守")
    r2.metric("评估 warm 用户", fmt_num(ev["n_warm_users"]))
    r3.metric("冷启动占比", fmt_pct(ev["cold_start_share"]),
              help="测试期有购买、训练期无购买的用户占比")

    def _metric_rows():
        rows = []
        for k in ["k=5", "k=10", "k=20"]:
            pop = ev["metrics"]["popularity"][k]
            cf = ev["metrics"]["item_item"][k]
            rows.append({
                "K": int(k.split("=")[1]),
                "热门 Recall@K": pop["recall"],
                "CF Recall@K": cf["recall"],
                "热门 NDCG@K": pop["ndcg"],
                "CF NDCG@K": cf["ndcg"],
                "CF 覆盖率": cf["coverage"],
            })
        return pd.DataFrame(rows)

    col1, col2 = st.columns([3, 2])
    with col1:
        st.markdown("**离线评估（时间切分：训练 < 2018-05-01，测试 ≥ 2018-05-01）**")
        st.dataframe(_metric_rows(), use_container_width=True, hide_index=True,
                     column_config={
                         "热门 Recall@K": st.column_config.NumberColumn(format="%.4f"),
                         "CF Recall@K": st.column_config.NumberColumn(format="%.4f"),
                         "热门 NDCG@K": st.column_config.NumberColumn(format="%.4f"),
                         "CF NDCG@K": st.column_config.NumberColumn(format="%.4f"),
                         "CF 覆盖率": st.column_config.NumberColumn(format="%.1f%%"),
                     })
        st.caption("CF 在 Recall@K 与 NDCG@K 上略优于热门基线，且覆盖率显著更高；"
                   "绝对水平低是因为推荐目录只覆盖 Top-3,000 商品。")
    with col2:
        st.markdown("**热门商品 Top 10**")
        pop = popular_items().head(10).rename(columns={
            "rank": "排名", "category_name_en": "品类", "users": "购买用户数",
            "lines": "购买件数", "avg_price": "均价",
        })
        pop["均价"] = pop["avg_price"].map(lambda v: "R$ %.2f" % v)
        st.dataframe(pop[["排名", "品类", "购买用户数", "购买件数", "均价"]],
                     use_container_width=True, hide_index=True)

    st.markdown("**推荐结果示例**")
    ex = recommendation_examples()
    users = ex["customer_unique_id"].drop_duplicates().head(4)
    ex = ex[ex["customer_unique_id"].isin(users)].copy()
    ex["客户"] = ex["customer_unique_id"].str[:10] + "…"
    ex["商品"] = ex["product_id"].str[:10] + "…"
    ex["命中真实购买"] = ex["is_actual_next_purchase"].map({1: "是", 0: "否"})
    ex["avg_price"] = ex["avg_price"].map(lambda v: "R$ %.2f" % v)
    st.dataframe(ex[["客户", "rank", "商品", "category", "avg_price", "命中真实购买"]]
                 .rename(columns={"rank": "排序", "category": "品类", "avg_price": "均价"}),
                 use_container_width=True, hide_index=True)
    st.info(
        "**边界：** Olist 没有曝光/点击日志，这是**基于购买行为**的推荐，不能评估 CTR；"
        "协同过滤学到的是共现关系，不是「买 A 导致买 B」。冷启动用户占比 97.8%，"
        "线上必须配合热门/内容策略。"
    )

# ---------------------------------------------------------------- 模拟 A/B
with tabs[5]:
    st.subheader("模拟 A/B 实验（独立模拟数据）")
    st.error(
        "**这不是 Olist 真实实验。** 数据由 `src/experiment/simulator.py` 按设定参数生成，"
        "仅用于验证随机化、检验、多重校正、护栏与功效分析的完整流程。"
    )

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("样本量", fmt_num(rr["n_users"]))
    e2.metric("对照组转化率", fmt_pct(rr["control_rate"]))
    e3.metric("实验组转化率", fmt_pct(rr["treatment_rate"]),
              delta="%+.2f pp" % (rr["conversion_diff"] * 100))
    e4.metric("SRM 检验 p", "%.3f" % rr["srm_p_value"],
              help="p > 0.05 表示样本比例未显著偏离 50/50")

    st.markdown(
        "- 两比例 z 检验：**p = %.3f**（%s）；ARPU 差值 %s，p = %.3f；事后功效 %.1f%%"
        % (rr["conversion_p_value"],
           "显著" if rr["conversion_p_value"] < 0.05 else "不显著",
           "R$ %.2f" % rr["arpu_diff"], rr["arpu_p_value"], rr["achieved_power"] * 100)
    )

    guardrails = pd.DataFrame(rr.get("guardrails", []))
    if not guardrails.empty:
        st.markdown("**护栏指标（越低越好）**")
        guardrails = guardrails.rename(columns={
            "metric": "指标", "control_rate": "对照组", "treatment_rate": "实验组",
            "diff": "差值", "p_value": "p 值",
        })
        guardrails["对照组"] = guardrails["对照组"].map(fmt_pct)
        guardrails["实验组"] = guardrails["实验组"].map(fmt_pct)
        guardrails["差值"] = guardrails["差值"].map(lambda v: "%+.2f pp" % (v * 100))
        guardrails["p 值"] = guardrails["p 值"].map(lambda v: "%.3f" % v)
        st.dataframe(guardrails[["指标", "对照组", "实验组", "差值", "p 值"]],
                     use_container_width=True, hide_index=True)

    regions = pd.DataFrame(rr.get("regions", []))
    if not regions.empty:
        st.markdown("**地区异质性（含 BH 多重检验校正）**")
        regions = regions.rename(columns={
            "group": "地区", "control_rate": "对照组", "treatment_rate": "实验组",
            "diff": "差值", "p_value": "原始 p", "p_adjusted": "BH 校正 p",
            "significant_bh": "校正后显著",
        })
        regions["对照组"] = regions["对照组"].map(fmt_pct)
        regions["实验组"] = regions["实验组"].map(fmt_pct)
        regions["差值"] = regions["差值"].map(lambda v: "%+.2f pp" % (v * 100))
        regions["原始 p"] = regions["原始 p"].map(lambda v: "%.3f" % v)
        regions["BH 校正 p"] = regions["BH 校正 p"].map(lambda v: "%.3f" % v)
        regions["校正后显著"] = regions["校正后显著"].map({True: "是", False: "否"})
        st.dataframe(regions[["地区", "对照组", "实验组", "差值", "原始 p", "BH 校正 p", "校正后显著"]],
                     use_container_width=True, hide_index=True)

    bv = rr.get("business_value", {})
    if bv:
        st.markdown("**业务价值换算（假设每月 10 万用户流量）**")
        b1, b2 = st.columns(2)
        b1.metric("每月增量收入", fmt_money(bv["incremental_revenue_per_100k"]))
        b2.metric("每月增量购买用户", fmt_num(bv["incremental_conversions_per_100k"]))
    st.caption("完整设计、功效表与结论边界见 reports/experiment_report.md。")
