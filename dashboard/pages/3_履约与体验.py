"""页 3 · 履约与体验：配送时效、迟到与评分的关系（含品类分层对照）。"""
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

from common import (category_control, delivery_buckets, delivery_correlation,
                    delivery_sample, delivery_stats, fmt_num, fmt_pct,
                    late_review, state_delivery)

st.set_page_config(page_title="履约与体验", page_icon="🚚", layout="wide")
st.title("🚚 履约与体验")
st.caption("口径：已签收订单（含少量窗口外月份）")

s = delivery_stats()
lr = late_review()

c1, c2, c3, c4 = st.columns(4)
c1.metric("平均配送天数", "%.1f 天" % s["avg_delivery_days"], help="中位数 %.0f 天，P90 %.0f 天" % (s["median_delivery_days"], s["p90_delivery_days"]))
c2.metric("承诺送达均值", "%.1f 天" % s["avg_estimated_days"])
c3.metric("迟到订单平均晚到", "%.1f 天" % s["avg_delay_days_when_late"])
c4.metric("迟到订单差评率", fmt_pct(lr["late"]["bad_review_rate"]),
          help="准时订单为 " + fmt_pct(lr["on_time"]["bad_review_rate"]))

st.divider()

# ---------------- 配送时长分桶 ----------------
st.subheader("配送时长与评分")
buckets = delivery_buckets()
st.markdown("**回答：** 送得越慢评分越低吗？—— 是：0-3 天评分 4.49，30 天以上跌至 2.25，"
            "差评率从 6.6%% 升至 63%%，且慢单中迟到占比也急剧上升。")

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_bar(x=buckets["delivery_bucket"], y=buckets["orders"], name="订单数",
            marker_color="#B6C8DC", hovertemplate="%{x}<br>%{y:,.0f} 单<extra></extra>")
fig.add_scatter(x=buckets["delivery_bucket"], y=buckets["avg_review_score"], name="平均评分",
                mode="lines+markers", line=dict(color="#4C78A8", width=3))
fig.add_scatter(x=buckets["delivery_bucket"], y=buckets["bad_review_rate"], name="差评率",
                mode="lines+markers", line=dict(color="#E45756", width=3, dash="dot"), secondary_y=True)
fig.update_layout(template="plotly_white", height=380, legend=dict(orientation="h", y=1.12),
                  margin=dict(l=10, r=10, t=30, b=10))
fig.update_yaxes(title_text="订单数", secondary_y=False)
fig.update_yaxes(title_text="差评率", tickformat=".0%", secondary_y=True, showgrid=False)
st.plotly_chart(fig, use_container_width=True)

# ---------------- 迟到 vs 准时 + 分层对照 ----------------
left, right = st.columns(2)

with left:
    st.subheader("迟到 vs 准时")
    cats = ["准时订单", "迟到订单"]
    fig = go.Figure()
    fig.add_bar(x=cats, y=[lr["on_time"]["avg_review_score"], lr["late"]["avg_review_score"]],
                name="平均评分", marker_color="#4C78A8", text=["%.2f" % lr["on_time"]["avg_review_score"],
                                                             "%.2f" % lr["late"]["avg_review_score"]],
                textposition="outside")
    fig.add_bar(x=cats, y=[lr["on_time"]["bad_review_rate"], lr["late"]["bad_review_rate"]],
                name="差评率", marker_color="#E45756",
                text=[fmt_pct(lr["on_time"]["bad_review_rate"]), fmt_pct(lr["late"]["bad_review_rate"])],
                textposition="outside", texttemplate="%{text}")
    fig.update_layout(template="plotly_white", height=380, barmode="group",
                      legend=dict(orientation="h", y=1.12), margin=dict(l=10, r=10, t=30, b=10))
    fig.update_yaxes(rangemode="tozero")
    st.plotly_chart(fig, use_container_width=True)
    corr = delivery_correlation()
    st.caption("评分差 %.2f 分（准时 %.2f vs 迟到 %.2f）；配送时长与评分 Spearman 相关 %.3f（n=%s，p<0.001）。"
               % (lr["diff"]["avg_review_score"], lr["on_time"]["avg_review_score"],
                  lr["late"]["avg_review_score"], corr["spearman_delivery_days"], fmt_num(corr["n"])))

with right:
    st.subheader("按品类分层对照")
    cc = category_control()
    st.markdown("**回答：** 低分是某几个品类的锅吗？—— 不是：样本量足够的品类内部，"
                "「迟到单评分低于准时单」方向全部一致（差值 -1.5 ~ -2.0 分），"
                "说明整体差异不是品类结构造成的。")
    fig = px.bar(cc.iloc[::-1], x="review_diff", y="category", orientation="h",
                 text=cc.iloc[::-1]["review_diff"].map(lambda v: "%+.2f" % v),
                 labels={"review_diff": "迟到单 − 准时单 评分差", "category": "品类"},
                 color_discrete_sequence=["#E45756"], template="plotly_white", height=380)
    fig.update_traces(textposition="outside")
    fig.update_layout(margin=dict(l=10, r=40, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)

st.warning(
    "**相关性 ≠ 因果**：以上均为观测数据。迟到与低评分的关联可能仍受商家质量、地区物流、商品属性等"
    "未观测因素影响，本页不做因果断言。因果评估方法见阶段 3 的模拟 A/B 实验模块。"
)

# ---------------- 州级履约 ----------------
st.subheader("各州履约表现")
sd = state_delivery().head(12)
fig = px.scatter(
    sd, x="avg_delivery_days", y="late_delivery_rate", size="orders", color="avg_review_score",
    color_continuous_scale="RdYlGn", range_color=[2.5, 4.5],
    hover_data={"state": True, "orders": True, "avg_delivery_days": ":.1f",
                "late_delivery_rate": ":.1%", "avg_review_score": ":.2f"},
    labels={"avg_delivery_days": "平均配送天数", "late_delivery_rate": "迟到率",
            "avg_review_score": "平均评分", "state": "州"},
    template="plotly_white", height=420,
)
fig.update_traces(text=sd["state"], textposition="top center")
fig.update_yaxes(tickformat=".0%")
fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(fig, use_container_width=True)
st.caption("**回答：** 哪些州的体验最差？—— RJ / BA 等州配送慢、迟到率高、评分低（气泡大小=订单量），"
           "是履约优化的优先地区；SP 量大但履约最好。")

# ---------------- 散点采样 ----------------
with st.expander("明细散点（抽样 6,000 单）"):
    sample = delivery_sample()
    fig = px.scatter(
        sample, x="delivery_days", y="review_score", color=sample["is_late_delivery"].map({0: "准时", 1: "迟到"}),
        labels={"delivery_days": "配送天数", "review_score": "评分", "color": ""},
        color_discrete_map={"准时": "#4C78A8", "迟到": "#E45756"},
        template="plotly_white", height=360, opacity=0.35,
    )
    fig.update_layout(legend=dict(orientation="h", y=1.1), margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

with st.expander("数据来源与口径"):
    st.markdown(
        "- 视图：`analytics_delivery_review`、`analytics_late_review`、`analytics_state_performance`\n"
        "- SQL：`sql/analytics/03/07_*.sql` ｜ Python：`src/analytics/fulfillment.py`\n"
        "- 迟到定义：签收时间晚于平台承诺送达时间"
    )
