"""页 1 · 经营总览：收入如何变化，哪些地区/品类/商家贡献最大。"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(HERE), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from common import (delivery_buckets, fmt_money, fmt_num, fmt_pct, headline,
                    monthly, seller_concentration, top_categories, top_states)

st.set_page_config(page_title="经营总览", page_icon="📈", layout="wide")
st.title("📈 经营总览")

df = monthly()
h = headline()

# ---------------- 月度收入与订单量 ----------------
st.subheader("月度收入与订单量")
st.markdown("**回答：** 收入如何随时间变化？—— 2017-11（黑五）冲高，12 月回落，2018 年恢复平稳增长。")

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_bar(x=df["month"], y=df["revenue"], name="实收收入", marker_color="#4C78A8",
            hovertemplate="%{x}<br>收入 R$ %{y:,.0f}<extra></extra>")
fig.add_scatter(x=df["month"], y=df["orders_valid"], name="有效订单", mode="lines+markers",
                line=dict(color="#E45756", width=3), secondary_y=True,
                hovertemplate="%{x}<br>订单 %{y:,.0f}<extra></extra>")
fig.update_layout(template="plotly_white", height=380, legend=dict(orientation="h", y=1.12),
                  margin=dict(l=10, r=10, t=30, b=10))
fig.update_yaxes(title_text="实收收入 (R$)", secondary_y=False)
fig.update_yaxes(title_text="订单数", secondary_y=True, showgrid=False)
st.plotly_chart(fig, use_container_width=True)

# ---------------- 地区贡献 ----------------
left, right = st.columns(2)

with left:
    st.subheader("地区贡献（买家州）")
    ts = top_states(10)
    st.markdown("**回答：** 哪些地区贡献最大？—— SP 一州占收入 %.1f%%，东南部三州（SP/RJ/MG）合计过半；"
                "北部/东北部州单量小但运费高、配送慢。" % (ts["revenue_share"].iloc[0] * 100))
    fig = px.bar(ts.iloc[::-1], x="revenue", y="state", orientation="h",
                 text=ts.iloc[::-1]["revenue_share"].map(fmt_pct),
                 labels={"revenue": "实收收入 (R$)", "state": "州"},
                 color_discrete_sequence=["#4C78A8"], template="plotly_white", height=380)
    fig.update_traces(textposition="outside")
    fig.update_layout(margin=dict(l=10, r=40, t=20, b=10))
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("品类贡献")
    tc = top_categories(10)
    st.markdown("**回答：** 哪些品类贡献最大？—— health_beauty / watches_gifts / bed_bath_table 三大类合计约 %.0f%%，"
                "头部集中度不高、长尾品类众多。" % (tc["gmv_share"].head(3).sum() * 100))
    fig = px.bar(tc.iloc[::-1], x="gmv", y="category", orientation="h",
                 text=tc.iloc[::-1]["gmv_share"].map(fmt_pct),
                 labels={"gmv": "GMV (R$)", "category": "品类"},
                 color_discrete_sequence=["#72B7B2"], template="plotly_white", height=380)
    fig.update_traces(textposition="outside")
    fig.update_layout(margin=dict(l=10, r=40, t=20, b=10))
    st.plotly_chart(fig, use_container_width=True)

# ---------------- 月度体验质量 ----------------
st.subheader("月度服务质量")
st.markdown("**回答：** 单量上涨时服务质量有没有被拖垮？—— 迟到率在单量高峰期抬升，"
            "评分随单量上涨缓慢下降，说明履约能力是增长的瓶颈之一。")

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_scatter(x=df["month"], y=df["avg_review_score"], name="平均评分", mode="lines+markers",
                line=dict(color="#54A24B", width=3))
fig.add_scatter(x=df["month"], y=df["late_delivery_rate"], name="迟到率", mode="lines+markers",
                line=dict(color="#E45756", width=3, dash="dot"), secondary_y=True)
fig.update_layout(template="plotly_white", height=340, legend=dict(orientation="h", y=1.12),
                  margin=dict(l=10, r=10, t=30, b=10))
fig.update_yaxes(title_text="平均评分", rangemode="tozero", secondary_y=False)
fig.update_yaxes(title_text="迟到率", tickformat=".0%", secondary_y=True, showgrid=False)
st.plotly_chart(fig, use_container_width=True)

# ---------------- 商家集中度 ----------------
st.subheader("商家集中度")
sc = seller_concentration()
c1, c2, c3 = st.columns(3)
c1.metric("活跃商家数", fmt_num(sc["n_sellers"]))
c2.metric("Top 10 商家 GMV 占比", fmt_pct(sc["top10_share"]))
c3.metric("Top 100 商家 GMV 占比", fmt_pct(sc["top100_share"]))
st.caption("**解读：** 长尾特征明显——头部 3% 的商家贡献近一半 GMV，治理与扶持应优先头部，"
           "但增长的边际空间在中尾部商家。")

with st.expander("数据来源与口径"):
    st.markdown(
        "- 视图：`analytics_monthly_kpi`、`analytics_state_performance`、`analytics_category_performance`、"
        "`analytics_seller_performance`\n"
        "- SQL：`sql/analytics/01~04_*.sql` ｜ Python：`src/analytics/kpi.py`\n"
        "- 实收收入含运费，GMV 不含运费；均仅统计有效订单（非 canceled/unavailable）"
    )
