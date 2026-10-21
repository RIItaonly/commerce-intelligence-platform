# 数据字典

数据库：`data/warehouse/commerce.db`（SQLite，本地默认；可通过 `.env` 切换 PostgreSQL）
数据来源：[Olist Brazilian E-commerce Public Dataset](https://github.com/olist/work-at-olist-data)（约 10 万订单，2016-09 ~ 2018-10）
金额单位：巴西雷亚尔（R$）。时间字段统一为 `YYYY-MM-DD HH:MM:SS` 字符串（SQLite）或 `TIMESTAMP`（PostgreSQL）。

## 分层结构

| 层 | 内容 | 物理形态 | SQL 位置 |
| --- | --- | --- | --- |
| raw | 原始 CSV 原样入库 | 表 | `sql/staging/00_schema.sql` |
| staging | 类型规范 + 业务清洗 + 派生字段 | 视图 | `sql/staging/01_staging_views.sql` |
| marts | 事实表 / 维度表（预聚合防 fan-out） | 视图 | `sql/marts/*.sql` |
| analytics | 业务分析视图（KPI/留存/RFM/履约/归因） | 视图 | `sql/analytics/*.sql` |

## raw 表（1 行 = 1 条原始记录）

### raw_orders（订单，99,441 行，粒度 order_id）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_id | TEXT PK | 订单 ID |
| customer_id | TEXT | 订单级客户 ID（每次下单唯一，≠ 真实用户） |
| order_status | TEXT | created / approved / invoiced / processing / shipped / delivered / canceled / unavailable |
| order_purchase_timestamp | TS | 下单时间 |
| order_approved_at | TS | 支付审核时间（少量早于下单时间，见质量报告） |
| order_delivered_carrier_date | TS | 交给承运商时间 |
| order_delivered_customer_date | TS | 签收时间 |
| order_estimated_delivery_date | TS | 平台承诺送达时间 |

### raw_order_items（订单明细，112,650 行，粒度 order_id + order_item_id）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_id / order_item_id | TEXT / INT | 联合主键 |
| product_id / seller_id | TEXT | 商品 / 商家 |
| shipping_limit_date | TS | 商家最晚发货时间 |
| price | REAL | 商品单价（GMV 的构成单元） |
| freight_value | REAL | 该明细分摊运费 |

### raw_order_payments（支付，103,886 行，粒度 order_id + payment_sequential）

payment_sequential 为一单多笔支付的序号；payment_type ∈ credit_card / boleto / voucher / debit_card / not_defined；payment_installments 为分期数；payment_value 为该笔金额。

### raw_order_reviews（评价，99,224 行，粒度 review_id；一单可有多条）

review_score ∈ 1~5；review_creation_date 为问卷发送时间，review_answer_timestamp 为回答时间。**同一订单多条评价在 stg_reviews 按最新回答保留 1 条**。

### raw_customers（99,441 行，粒度 customer_id）

customer_id（订单级，PK）与 customer_unique_id（真实用户 ID，一人多单时重复）——**所有用户级分析都用 customer_unique_id**；customer_zip_code_prefix / city / state 为收货地址。

### raw_products（32,951 行，粒度 product_id）

品类葡语名（product_category_name）、名称/描述长度、照片数、重量、三维尺寸。品类缺失填充为 unknown。

### raw_sellers（3,095 行，粒度 seller_id）：商家地址。

### raw_category_translation（71 行）：品类葡语名 → 英文名映射。

## staging 视图（清洗与派生字段）

| 视图 | 粒度 | 说明 |
| --- | --- | --- |
| stg_customers | customer_id | 城市小写、州大写规范化 |
| stg_orders | order_id | +order_date/order_month（DATE_TRUNC day/month）、is_valid_order（非 canceled/unavailable）、is_delivered、delivery_days / estimated_days / delay_days（DAYS_BETWEEN 派生）、is_late_delivery（签收晚于承诺） |
| stg_order_items | order_id+item_id | +item_total_value（price+freight） |
| stg_payments | order_id+seq | 支付类型小写规范化 |
| stg_reviews | order_id（去重后） | +is_bad_review（≤2 分）；ROW_NUMBER 保留最新评价 |
| stg_products | product_id | +category_name_en（翻译映射）、volume_cm3（三维乘积） |
| stg_sellers | seller_id | 地址规范化 |

## marts 视图（分析用事实/维度）

| 视图 | 粒度 | 关键列 |
| --- | --- | --- |
| fct_order | **order_id（1 行/订单）** | 客户/州/城市、状态、时间、item_count、product_gmv、freight_total、payment_total、review_score、is_bad_review、配送字段、is_valid_order |
| fct_order_item | order_id+item_id | +品类（英/葡）、商家州、价格/运费/评价/履约字段 |
| fct_payment | order_id+seq | 支付明细 + 订单月份/状态 |
| dim_customer | customer_unique_id | 首末单时间、n_orders、lifetime_revenue、n_paid_orders |
| dim_product / dim_seller | product_id / seller_id | 商品/商家属性 |

**fan-out 防护**：fct_order 先把 items/payments 预聚合到订单粒度再 JOIN；质量检查 `grain_*` 校验行数与金额合计与原始表一致（见 `reports/data_quality_report.md`）。

## analytics 视图（业务分析）

| 视图 | 粒度 | 说明 |
| --- | --- | --- |
| analytics_monthly_kpi | order_month | 订单数（总/有效/签收/取消/不可用）、GMV、实收收入、运费、件数、AOV、平均配送天数、迟到率、平均评分、差评数 |
| analytics_category_performance | 品类 | 订单/件数/商品数/商家数、GMV、均价、均运费、配送、迟到率、评分（仅有效订单） |
| analytics_state_performance | 买家州 | 订单、用户数、GMV、收入、AOV、运费、配送、迟到率、评分（仅有效订单） |
| analytics_seller_performance | seller_id | 订单/件数/品类数/活跃月数、GMV、配送、迟到率、评分（仅有效订单） |
| analytics_cohort_retention | 首购月 × period_index | 各队列各期活跃用户数（MONTH_INDEX 计算期数） |
| analytics_rfm | customer_unique_id | R/F/M 原始值 + NTILE(5) 分数（F 维退化，业务分群在 Python 层） |
| analytics_delivery_review | 配送时长分桶 | 评分、差评率、迟到率（已签收） |
| analytics_late_review | is_late_delivery | 迟到/准时两组的评分分布（已签收） |
| analytics_category_gmv_mom / analytics_state_gmv_mom | 月 × 品类 / 月 × 州 | GMV 与 LAG 环比差值 |
| analytics_order_funnel | 单行 | 下单→审核→支付→发货→签收→评价各环节订单数 |

## 核心指标口径（单一事实来源）

| 指标 | 定义 | 备注 |
| --- | --- | --- |
| GMV | 有效订单的 `SUM(price)`（商品金额，**不含运费**） | 明细粒度聚合 |
| 实收收入 | 有效订单的 `SUM(payment_total)`（支付金额，**含运费**） | 与 GMV 不可混用 |
| AOV | 实收收入 / 有效订单数 | 订单粒度 |
| 有效订单 | status ∉ {canceled, unavailable} | `is_valid_order` |
| 迟到订单 | 已签收且 `delivered_customer_date > estimated_delivery_date` | `is_late_delivery` |
| 差评 | review_score ≤ 2 | `is_bad_review` |
| 真实用户 | customer_unique_id（非订单级 customer_id） | 用户级分析一律用它 |
| 分析时间窗 | 2017-01-01 ~ 2018-08-31 | 首尾月不完整，趋势分析剔除；`src/config.py` 可改 |

## 已知数据特点

1. 一单多商品/多支付/多评价 → 必须先定粒度再聚合（质量检查已校验）。
2. 一单多条评价 → stg_reviews 按最新回答去重。
3. 少量审核/签收时间早于下单时间（运营系统回填）→ 漏斗按时间戳是否存在判定。
4. 品类缺失 → unknown 单独成组。
5. 无曝光/点击/加购日志 → 漏斗从下单开始；推荐只能基于购买行为。
6. 非随机实验数据 → 只做相关性分析，因果结论仅来自阶段 3 的独立模拟实验模块。
