"""页 2 · 用户生命周期：漏斗、复购、留存队列与 RFM 分群。"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(HERE), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common import (cohort_data, fmt_money, fmt_num, fmt_pct, funnel_data,
                    new_vs_returning, repeat_summary, rfm_overview, rfm_segments)

st.set_page_config(page_title="用户生命周期", page_icon="👥", layout="wide")
st.title("👥 用户生命周期")

# ---------------- 复购概览 ----------------
r = repeat_summary()
o = rfm_overview()
c1, c2, c3, c4 = st.columns(4)
c1.metric("真实用户数", fmt_num(r["customers"]))
c2.metric("复购用户占比", fmt_pct(r["repeat_customer_share"]), help="≥2 个有效订单")
c3.metric("复购用户收入贡献", fmt_pct(r["repeat_revenue_share"]),
          help="人数占比小但收入贡献更高，值得定向运营")
c4.metric("仅 1 单用户占比", fmt_pct(o["single_order_share"]))

st.divider()

# ---------------- 漏斗 ----------------
left, right = st.columns([2, 3])

with left:
    st.subheader("履约漏斗")
    f = funnel_data()
    fig = go.Figure(go.Funnel(
        y=f["label"], x=f["orders"],
        textinfo="value+percent initial",
        marker=dict(color="#4C78A8"),
        connector=dict(line=dict(color="#ddd", width=1)),
    ))
    fig.update_layout(template="plotly_white", height=420, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("**注意：** Olist 无曝光/点击日志，漏斗从下单开始；各阶段按时间戳是否存在判定，"
               "非严格子集关系（支付/评价环节可能略高于上一环）。")

with right:
    st.subheader("月度收入：新客 vs 老客")
    nvr = new_vs_returning()
    st.markdown("**回答：** 增长靠拉新还是靠复购？—— 老客收入占比仅爬升到 %.1f%%，"
                "平台处于典型的「拉新驱动」阶段，留存运营是最大机会点。"
                % (nvr["returning_revenue"].iloc[-1] /
                   (nvr["new_revenue"].iloc[-1] + nvr["returning_revenue"].iloc[-1]) * 100
                   if (nvr["new_revenue"].iloc[-1] + nvr["returning_revenue"].iloc[-1]) else 0))
    fig = go.Figure()
    fig.add_bar(x=nvr["month"], y=nvr["new_revenue"], name="新客收入", marker_color="#4C78A8")
    fig.add_bar(x=nvr["month"], y=nvr["returning_revenue"], name="老客收入", marker_color="#F58518")
    fig.update_layout(barmode="stack", template="plotly_white", height=420,
                      legend=dict(orientation="h", y=1.1), margin=dict(l=10, r=10, t=30, b=10))
    fig.update_yaxes(title_text="实收收入 (R$)")
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ---------------- 留存队列 ----------------
st.subheader("留存队列热力图（按首购月份）")
rates, sizes = cohort_data()
st.markdown("**回答：** 每个月拉来的新客，之后还会回来吗？—— 各队列首购后 1 个月留存均不足 1%%，"
            "且跨队列基本一致，说明低复购是平台性问题而非某个月拉新质量差。")

fig = px.imshow(
    rates,
    text_auto=".1%",
    color_continuous_scale="Blues",
    labels=dict(x="首购后月数", y="首购月份", color="留存率"),
    aspect="auto",
)
fig.update_layout(template="plotly_white", height=430, margin=dict(l=10, r=10, t=30, b=10))
fig.update_coloraxes(colorbar_tickformat=".0%")
st.plotly_chart(fig, use_container_width=True)
st.caption("仅展示队列人数 ≥ 50 的月份；空白 = 该期数据尚未发生。")

st.divider()

# ---------------- RFM 分群 ----------------
st.subheader("RFM 客户分群（规则版）")
seg = rfm_segments()

seg_chart = seg.melt(
    id_vars="segment", value_vars=["customer_share", "revenue_share"],
    var_name="指标", value_name="占比",
)
seg_chart["指标"] = seg_chart["指标"].map({"customer_share": "人数占比", "revenue_share": "收入占比"})

left, right = st.columns([3, 2])
with left:
    fig = px.bar(
        seg_chart, x="占比", y="segment", color="指标", orientation="h", barmode="group",
        color_discrete_map={"人数占比": "#4C78A8", "收入占比": "#F58518"},
        category_orders={"segment": seg["segment"].tolist()[::-1]},
        labels={"segment": "分群", "占比": "占比"},
        template="plotly_white", height=420,
    )
    fig.update_xaxes(tickformat=".0%")
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)

with right:
    show = seg[["segment", "customers", "customer_share", "revenue", "revenue_share",
                "avg_monetary", "avg_recency_days"]].copy()
    show["customers"] = show["customers"].map(fmt_num)
    show["customer_share"] = show["customer_share"].map(fmt_pct)
    show["revenue"] = show["revenue"].map(fmt_money)
    show["revenue_share"] = show["revenue_share"].map(fmt_pct)
    show["avg_monetary"] = show["avg_monetary"].map(fmt_money)
    show["avg_recency_days"] = show["avg_recency_days"].map(lambda v: "%.0f 天" % v)
    st.dataframe(show, use_container_width=True, hide_index=True,
                 column_config={
                     "segment": st.column_config.TextColumn("分群"),
                     "customers": st.column_config.TextColumn("人数"),
                     "customer_share": st.column_config.TextColumn("人数占比"),
                     "revenue": st.column_config.TextColumn("累计收入"),
                     "revenue_share": st.column_config.TextColumn("收入占比"),
                     "avg_monetary": st.column_config.TextColumn("客单价均值"),
                     "avg_recency_days": st.column_config.TextColumn("平均近度"),
                 })

st.caption("说明：Olist 约 %.1f%% 用户仅 1 单，F 维 NTILE 退化，故分群用业务规则（复购次数 + 最近购买间隔）；"
           "高价值客户门槛 R$ %.0f（累计消费前 20%%）。K-Means 版本见阶段 3。"
           % (o["single_order_share"] * 100, o["high_value_threshold"]))

with st.expander("数据来源与口径"):
    st.markdown(
        "- 视图：`analytics_order_funnel`、`analytics_cohort_retention`、`analytics_rfm`\n"
        "- SQL：`sql/analytics/05/06/09_*.sql` ｜ Python：`src/analytics/retention.py`、`rfm.py`、`funnel.py`\n"
        "- 用户级分析一律使用 customer_unique_id（真实用户），而非订单级 customer_id"
    )
