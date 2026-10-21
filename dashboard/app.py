"""Commerce Intelligence Platform · 交互式经营分析看板（首页）。

启动：项目根目录下运行  python -m streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(HERE), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src import config
import streamlit as st

from common import headline, fmt_money, fmt_num, fmt_pct

st.set_page_config(
    page_title="Commerce Intelligence Platform",
    page_icon="🛒",
    layout="wide",
)

st.title("🛒 Commerce Intelligence Platform")
st.markdown("**端到端电商数据分析与智能决策平台** · 基于 Olist 巴西电商公开数据（约 10 万订单）")

h = headline()

st.header("经营核心指标")
st.caption("分析窗口 %s ~ %s（剔除首尾不完整月份）" % (config.ANALYSIS_START_DATE[:7], config.ANALYSIS_END_DATE[:7]))

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("有效订单", fmt_num(h["orders_valid"]), help="剔除 canceled / unavailable")
c2.metric("实收收入", fmt_money(h["revenue"]), help="支付金额合计（含运费）")
c3.metric("GMV", fmt_money(h["gmv"]), help="商品金额合计（不含运费），与实收收入口径不同")
c4.metric("客单价 AOV", fmt_money(h["aov"]), help="实收收入 / 有效订单数")
c5.metric("平均评分", "%.2f / 5" % h["avg_review_score"], help="已签收订单评价")
c6.metric("迟到率", fmt_pct(h["late_delivery_rate"]), help="签收晚于承诺送达的订单占比")

st.divider()

st.header("页面导航")
cols = st.columns(4)
with cols[0]:
    st.subheader("📈 经营总览")
    st.write("收入趋势、地区与品类贡献、商家集中度——回答「生意做得怎么样、钱从哪来」。")
with cols[1]:
    st.subheader("👥 用户生命周期")
    st.write("履约漏斗、复购与留存队列、RFM 分群——回答「用户从哪来、留不留得住」。")
with cols[2]:
    st.subheader("🚚 履约与体验")
    st.write("配送时效、迟到与评分的关系（含品类分层对照）——回答「体验短板在哪」。")
with cols[3]:
    st.subheader("🧭 智能决策中心")
    st.write("把分析结果转成行动建议；阶段 3 将接入流失预测、销售预测与推荐。")

st.divider()
st.info(
    "**口径与边界（诚实声明）**\n\n"
    "- 实收收入（含运费）与 GMV（不含运费）是两个指标，全程分开使用；\n"
    "- 数据为观测数据，看板中的相关性发现不做因果断言；\n"
    "- 2016-09/10/12 与 2018-09 之后为不完整月份，趋势分析限定在窗口内；\n"
    "- Olist 无曝光/点击日志，漏斗从下单开始。"
)

st.caption("数据库：`%s` ｜ 指标口径见 reports/data_dictionary.md ｜ 业务结论见 reports/business_insights.md"
           % config.DATABASE_URL)
