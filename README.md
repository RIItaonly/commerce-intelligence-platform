# Commerce Intelligence Platform

端到端电商数据科学与智能决策平台 —— 基于巴西 Olist 公开电商数据，覆盖「原始数据 → 数据质量 → SQL 指标 → 业务分析 → 机器学习 → 实验评估 → 应用/工程化」的完整闭环。

## 1. 核心业务问题

以平台数据科学团队视角，回答管理层真正关心的问题：

1. 平台收入为什么变化？哪些品类、地区、商家贡献最大？
2. 用户在哪个环节流失？哪些用户可能停止购买？
3. 应该向什么用户推荐什么商品？
4. 未来 30 天的销售额/订单量会如何变化？
5. 一项促销活动究竟有没有带来增量收入？
6. 如何把分析和模型封装成可交互使用的决策工具？

## 2. 系统架构

```
数据层         CSV(真实 Olist 9 张表) → 入库 → 数据质量校验 → 数据字典
              │
分析/工程层    staging(清洗) → marts(维度/事实) → analytics(SQL 指标、留存、RFM、归因)
              │
建模层         流失预测 / 客群分群 / 商品推荐 / 时间序列预测
              │
实验层         模拟 A/B 测试：功效分析、随机分组、假设检验、效应量
              │
应用层         Streamlit 决策看板 · FastAPI 预测/推荐接口 · Docker · CI 测试
```

| 层 | 目录 | 说明 |
| --- | --- | --- |
| 数据接入 | `src/ingestion/` | 原始 CSV 导入、类型规范、粒度校验 |
| 数据质量 | `src/cleaning/` | 主键唯一性、空值、关联完整性、时间异常 |
| 数据建模 | `sql/staging/`、`sql/marts/` | 清洗视图 → 维度表/事实表 |
| SQL 指标 | `sql/analytics/` | CTE、窗口函数、多表关联、条件聚合 |
| 业务分析 | `src/analytics/` | 漏斗、留存队列、RFM、履约体验、收入归因 |
| 特征/建模 | `src/features/`、`src/models/` | 时间切分的特征工程与模型 |
| 实验统计 | `src/experiment/` | 假设检验、功效与样本量、模拟 A/B |
| 应用 | `dashboard/`、`src/api/`、`src/monitoring/` | Streamlit 看板、FastAPI 服务、漂移监控 |
| 交付物 | `reports/`、`outputs/` | 业务洞察、模型卡、实验报告、图表 |

## 3. 数据与粒度（最重要的一节）

数据源：[Brazilian E-Commerce Public Dataset by Olist](https://github.com/olist/work-at-olist-data)，9 张关系表，约 10 万笔订单（2016-09 ~ 2018-10）。

**在做任何聚合前，必须先确定粒度**。Olist 中一笔订单可能对应多个商品、多条支付记录、一条评价，直接 JOIN 会产生 fan-out 导致重复计算。本项目的口径约定：

| 表 | 粒度 | 备注 |
| --- | --- | --- |
| `raw_orders` | 1 行 / order_id | 订单主表 |
| `raw_order_items` | 1 行 / (order_id, order_item_id) | 商品明细行 |
| `raw_order_payments` | 1 行 / (order_id, payment_sequential) | 可能多次支付 |
| `raw_order_reviews` | 1 行 / review_id | 少量订单有重复评价 |
| `raw_customers` | 1 行 / customer_id | **customer_id 是订单级标识**，跨订单识别同一人要用 `customer_unique_id` |

**指标口径（不可混用同一列）**

| 指标 | 定义 | 计算口径 |
| --- | --- | --- |
| GMV | 商品成交总额（不含运费） | `SUM(order_items.price)`，剔除 `canceled/unavailable` 订单 |
| 实收收入 | 实际支付金额（含运费） | `SUM(payments.payment_value)`，仅统计有效订单 |
| 客单价 AOV | 实收收入 / 有效订单数 | 按订单去重后的分母 |
| 取消率 | 取消+不可用订单占比 | Olist 无退款标记，**用取消/不可用做代理指标** |
| 准时交付率 | 实际签收时间 ≤ 预计交付时间 | 仅对已签收订单计算 |
| 平均配送时长 | 签收时间 − 下单时间 | 天数 |
| 差评率 | review_score ≤ 2 占比 | 评价粒度去重后计算 |

**时间范围限制**：2016-09/10/12 与 2018-09 之后月份数据不完整，趋势类分析默认限定 `2017-01-01 ~ 2018-08-31`，报告中必须注明。

## 4. 如何运行

### 4.1 本地快速启动（SQLite，零安装）

本机没有 PostgreSQL/Docker 时，使用自带 SQLite 引擎跑通全链路（`sql/` 中的 SQL 以 PostgreSQL 方言书写，由 `src/sql_engine.py` 做少量方言适配，如 `DATE_TRUNC` → `strftime`、`DAYS_BETWEEN` 伪函数）。

```powershell
# 0) （推荐）使用项目自带虚拟环境
.venv\Scripts\Activate.ps1        # 或直接用 .venv\Scripts\python.exe 替代 python

# 1) 下载原始数据（9 个 CSV，约 123MB）
python -m src.ingestion.download_data

# 2) 全链路：入库 → staging/marts/analytics 视图 → 质量校验 → 业务报告 → 模型与模型卡
python -m src.pipeline all

# 3) 基础测试（指标口径、fan-out、特征泄漏、评估函数、API 接口）
python -m pytest tests -q

# 4) 打开看板（http://localhost:8501）
streamlit run dashboard/app.py

# 5) 启动模型服务 API（http://localhost:8000/docs 查看 Swagger）
uvicorn src.api.app:app --port 8000

# 6) 模型监控：特征/预测分布漂移检查（输出 outputs/drift_report.csv）
python -m src.monitoring.drift
```

### 4.2 PostgreSQL + Docker（目标工程栈）

```powershell
# 本地 SQLite 栈：一条命令同时拉起 API(8000) 与看板(8501)
docker compose up -d

# 需要 PostgreSQL 时启用 postgres profile
docker compose --profile postgres up -d
# .env 中设置 DATABASE_URL=postgresql://commerce:commerce@localhost:5432/commerce
python -m src.pipeline all
```

Postgres 初始化脚本见 `sql/staging/00_schema.sql`；数据与模型产物通过挂载卷注入容器（不打进镜像）。

### 4.3 API 接口速览

| 接口 | 说明 |
| --- | --- |
| `GET /health` | 服务与模型产物健康检查 |
| `GET /churn/score/{customer_unique_id}` | 客户 30 天复购概率与流失风险分层 |
| `GET /churn/top-risk?n=20` | 流失风险最高客户名单（运营挽留） |
| `GET /segment/{customer_unique_id}` | KMeans 分群标签 + 规则分层对照 |
| `GET /recommend/{customer_unique_id}?k=10` | item-item 协同过滤推荐；冷启动回退热门并标注 `source` |
| `GET /forecast?target=orders\|revenue` | 未来 30 天订单量/收入预测（含 80% 区间） |
| `GET /model/metrics` | 各模型离线评估指标汇总 |

### 4.4 Notebooks

`notebooks/` 下四份可复现分析（均已实际执行、输出随文件保存）：

1. `01_data_quality.ipynb` — 数据质量体检：粒度、缺失、金额口径、不完整月份
2. `02_business_analysis.ipynb` — 趋势、品类、复购、配送体验
3. `03_modeling.ipynb` — 模型产物解读：模型比较、特征重要性、校准、分群、推荐、预测
4. `04_experiment.ipynb` — 模拟 A/B 结果与功效分析演示

## 5. 模块完成度

| 模块 | 内容 | 状态 |
| --- | --- | --- |
| 一 数据工程与 SQL | 入库、质量校验（27 项）、维度/事实表、SQL 指标分析、数据字典 | ✅ 已完成 |
| 二 业务分析与 BI | 四页交互看板、留存队列、RFM、收入归因、业务洞察报告 | ✅ 已完成 |
| 三 统计与 A/B 测试 | 描述统计、假设检验、功效/样本量、模拟实验 | ✅ 已完成 |
| 四 机器学习 | 流失预测、RFM 分群、推荐、预测；基线+模型比较+误差分析 | ✅ 已完成 |
| 五 时间序列 | 季节性朴素基线、统计模型 vs ML、滚动窗口验证 | ✅ 已完成 |
| 六 工程化/MLOps | pytest 30 项、FastAPI、Docker、GitHub Actions、漂移监控、notebooks | ✅ 已完成 |

**当前可交付物**：`reports/`（数据质量、数据字典、业务洞察、实验报告、模型卡）、
`models/artifacts/`（流失/分群/推荐/预测结果）、四页 Streamlit 看板（经营总览 / 用户生命周期 / 履约与体验 / 智能决策中心）、
FastAPI 模型服务（7 个接口）、`notebooks/` 01-04（已执行）、`outputs/drift_report.csv`（漂移监控）、
Dockerfile + docker-compose、GitHub Actions CI。

## 5.1 演示流程（10 分钟讲清楚这个项目）

1. **看板**（`streamlit run dashboard/app.py`）：经营总览看趋势与品类结构 → 用户生命周期看留存/RFM → 履约体验看配送与评分 → 智能决策中心看模型落地（流失名单、分群、推荐、预测、模拟 A/B）。
2. **API**（`uvicorn src.api.app:app --port 8000`）：打开 `http://localhost:8000/docs`，现场调用 `/churn/score`、`/recommend`、`/forecast`，说明离线训练 + 在线推理的职责划分与冷启动降级策略。
3. **报告**：`reports/business_insights.md`（业务结论）→ `reports/model_card.md`（模型方法与局限）→ `reports/experiment_report.md`（实验流程与诚实边界）。
4. **工程化**：`python -m pytest tests -q`（30 项测试）→ `python -m src.monitoring.drift`（漂移检查）→ `docker compose up -d`（一键拉起全栈）。

| 看板首页 | 智能决策中心 | API 文档 |
| --- | --- | --- |
| ![经营总览](outputs/screenshots/dashboard_overview.png) | ![智能决策中心](outputs/screenshots/dashboard_decision_center.png) | ![Swagger](outputs/screenshots/api_swagger.png) |

## 5.2 简历段落（可直接引用）

> **端到端电商智能决策平台**（Python / SQL(PostgreSQL 方言) / scikit-learn / LightGBM / statsmodels / FastAPI / Streamlit / Docker / GitHub Actions）
> 基于 Olist 约 10 万笔订单数据，搭建「数据工程 → BI 分析 → 统计建模 → 服务化」全链路：
> 设计粒度安全的维度/事实表（fan-out 防护并以 30 项 pytest 固化口径契约），构建四页交互看板与业务洞察报告；
> 以时间快照法构建无泄漏特征训练 30 天复购预测（PR-AUC 0.017、Top10% lift 2.9x，极端不平衡下以 PR-AUC/校准评估），
> 完成 RFM+KMeans 分群（轮廓 0.41）、item-item 协同过滤（Recall@10 0.0185，时间切分防泄漏）、SARIMA/LightGBM 预测（滚动原点验证）；
> 独立实现模拟 A/B 模块（SRM/功效/护栏/分层分析），严格区分观测发现与因果结论；
> 以 FastAPI 提供 7 个模型接口（含冷启动降级）、PSI/KS 漂移监控、Docker 一键部署与 GitHub Actions CI。

## 6. 结论边界（诚实声明）

- Olist **不是随机实验数据**：不能用它证明促销/改版的因果效果。因果结论只在独立的「模拟 A/B 模块」中给出，并与真实观测发现严格区分。
- Olist **没有曝光/点击/浏览日志**：可以做「基于购买行为的商品推荐」，但不能宣称是完整点击推荐系统。
- 流失标签与特征必须按时间构建（过去 N 天特征 → 未来 M 天是否流失），严禁把未来信息放进特征。
- 时间范围与不完整月份限制已知，模型结果不作为可靠的长期业务预测。

## 7. 参考项目

- [nishantsharma-sketch/olist-ecommerce-analysis](https://github.com/nishantsharma-sketch/olist-ecommerce-analysis)：清洗、关系建模、SQL、Power BI
- [whizey/Olist_ETL](https://github.com/whizey/Olist_ETL)：ETL / Spark / PostgreSQL / 商家分群架构
- [miguelvotre/olist-ecommerce-analytics](https://github.com/miguelvotre/olist-ecommerce-analytics)：dbt 分层建模、测试、仪表盘、部署
