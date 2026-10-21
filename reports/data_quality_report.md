# 数据质量报告

- 生成时间：2026-10-20 20:23:13
- 数据库：`sqlite:///D:/agent项目集/端到端电商智能决策平台/data/warehouse/commerce.db`
- 分析时间窗：2017-01-01 ~ 2018-08-31（剔除首尾不完整月份）

## 概览

| 通过 | 警告 | 失败 |
| --- | --- | --- |
| 27 | 4 | 0 |

## 检查明细

| 类别 | 检查项 | 状态 | 数值 | 说明 |
| --- | --- | --- | --- | --- |
| 主键唯一性 | raw_orders.order_id 无重复 | PASS | 0 | — |
| 主键唯一性 | raw_order_items.(order_id, order_item_id) 无重复 | PASS | 0 | — |
| 主键唯一性 | raw_customers.customer_id 无重复 | PASS | 0 | — |
| 主键唯一性 | raw_products.product_id 无重复 | PASS | 0 | — |
| 主键唯一性 | raw_sellers.seller_id 无重复 | PASS | 0 | — |
| 主键唯一性 | raw_order_reviews.review_id 无重复 | PASS | 0 | — |
| 空值 | raw_orders.order_purchase_timestamp 无空值 | PASS | 0 | — |
| 空值 | raw_order_items.price 无空值 | PASS | 0 | — |
| 空值 | raw_order_payments.payment_value 无空值 | PASS | 0 | — |
| 空值 | raw_products.product_category_name 空值（已知数据特点） | WARN | 610 | 缺失品类在 staging 层填充为 'unknown'，不影响主键与金额计算 |
| 关联完整性 | order_items → orders 无孤儿 | PASS | 0 | — |
| 关联完整性 | order_payments → orders 无孤儿 | PASS | 0 | — |
| 关联完整性 | order_reviews → orders 无孤儿 | PASS | 0 | — |
| 关联完整性 | orders → customers 无孤儿 | PASS | 0 | — |
| 关联完整性 | order_items → products 无孤儿 | PASS | 0 | — |
| 关联完整性 | order_items → sellers 无孤儿 | PASS | 0 | — |
| 时间异常 | 下单时间覆盖范围 | PASS | 2016-09-04 ~ 2018-10-17 | 首尾月份不完整，趋势分析限定 2017-01-01 ~ 2018-08-31 |
| 时间异常 | 签收时间早于下单时间的订单 | PASS | 0 | 物流时间戳为运营系统回填，存在少量异常；分析时不单独剔除 |
| 时间异常 | 审核时间早于下单时间的订单 | PASS | 0 | Olist 已知数据特点，漏斗分析按时间戳是否存在判定 |
| 数值异常 | price <= 0 的明细行 | PASS | 0 | — |
| 数值异常 | freight_value < 0 的明细行 | PASS | 0 | — |
| 数值异常 | payment_value <= 0 的支付记录 | WARN | 9 | 可能为全额券/赠品类支付 |
| 数值异常 | review_score 超出 1-5 范围 | PASS | 0 | — |
| 粒度一致性 | fct_order 行数 = raw_orders 行数（1 行 / order_id） | PASS | 99,441 / 99,441 | — |
| 粒度一致性 | fct_order_item 行数 = raw_order_items 行数 | PASS | 112,650 / 112,650 | — |
| 粒度一致性 | fct_order.item_count 合计 = 明细行数 | PASS | 112,650 / 112,650 | — |
| 粒度一致性 | 支付金额合计一致（防重复计算） | PASS | R$ 16,008,872.12 / R$ 16,008,872.12 | — |
| 粒度一致性 | 商品金额（GMV）合计一致 | PASS | R$ 13,591,643.70 / R$ 13,591,643.70 | — |
| 粒度一致性 | dim_customer 每 customer_unique_id 仅 1 行 | PASS | 96,096 / 96,096 | — |
| 粒度一致性 | stg_reviews 按订单去重（1 单多评价保留最新） | WARN | 98,410 → 98,128（去重 282 条） | 保证订单粒度聚合不产生 fan-out |
| 月份覆盖度 | 订单量 < 100 的不完整月份 | WARN | 2016-09（4 单）、2016-12（1 单）、2018-09（16 单）、2018-10（4 单） | 趋势分析已限定 2017-01-01 ~ 2018-08-31 |

## 已知数据特点与处理口径

1. **粒度**：一笔订单可含多个商品、多条支付、多条评价。所有事实表先预聚合到目标粒度再关联，
   `fct_order`（1 行/订单）与 `fct_order_item`（1 行/明细）均通过行数与金额合计校验，无 fan-out。
2. **评价去重**：同一订单存在多条评价时按最新回答时间保留 1 条（见 `grain_review_dedup`）。
3. **品类缺失**：少量商品无品类，staging 层填充为 `unknown`，单独成组不剔除。
4. **不完整月份**：2016-09/10/12 与 2018-09 之后订单量极少，趋势类分析限定在分析时间窗内。
5. **时间戳异常**：少量订单审核/签收时间早于下单时间，为运营系统回填特点，不单独剔除，
   漏斗分析按时间戳是否存在判定。
6. **指标口径**：GMV = 商品金额（不含运费）；实收收入 = 支付金额（含运费）；两者不混用。

## 结论

全部关键检查通过（无 FAIL），数据集可用于后续分析；WARN 项为已知数据特点，已在报告中说明处理方式。
