-- analytics 层 · 履约与体验（仅已签收订单）
-- 视图 1：配送时长分桶 × 评分/迟到率（bucket_sort 用于排序）
-- 视图 2：迟到与否 × 评分分布（用于「迟到 vs 准时」对比及后续按品类/地区控制）
DROP VIEW IF EXISTS analytics_delivery_review;
CREATE VIEW analytics_delivery_review AS
SELECT
    bucket_sort,
    delivery_bucket,
    COUNT(*)                                                        AS orders,
    AVG(delivery_days)                                              AS avg_delivery_days,
    AVG(review_score)                                               AS avg_review_score,
    AVG(CASE WHEN review_score IS NOT NULL THEN is_bad_review * 1.0 END) AS bad_review_rate,
    SUM(is_late_delivery) * 1.0 / COUNT(*)                          AS late_delivery_rate
FROM (
    SELECT
        CASE
            WHEN delivery_days <= 3  THEN 1
            WHEN delivery_days <= 7  THEN 2
            WHEN delivery_days <= 14 THEN 3
            WHEN delivery_days <= 21 THEN 4
            WHEN delivery_days <= 30 THEN 5
            ELSE 6
        END AS bucket_sort,
        CASE
            WHEN delivery_days <= 3  THEN '0-3 天'
            WHEN delivery_days <= 7  THEN '4-7 天'
            WHEN delivery_days <= 14 THEN '8-14 天'
            WHEN delivery_days <= 21 THEN '15-21 天'
            WHEN delivery_days <= 30 THEN '22-30 天'
            ELSE '30 天以上'
        END AS delivery_bucket,
        delivery_days,
        review_score,
        is_bad_review,
        is_late_delivery
    FROM fct_order
    WHERE is_delivered = 1
) t
GROUP BY bucket_sort, delivery_bucket;

DROP VIEW IF EXISTS analytics_late_review;
CREATE VIEW analytics_late_review AS
SELECT
    is_late_delivery,
    COUNT(*)                                                        AS orders,
    AVG(delivery_days)                                              AS avg_delivery_days,
    AVG(review_score)                                               AS avg_review_score,
    AVG(CASE WHEN review_score IS NOT NULL THEN is_bad_review * 1.0 END) AS bad_review_rate,
    SUM(CASE WHEN review_score = 1 THEN 1 ELSE 0 END)               AS reviews_1,
    SUM(CASE WHEN review_score = 2 THEN 1 ELSE 0 END)               AS reviews_2,
    SUM(CASE WHEN review_score = 3 THEN 1 ELSE 0 END)               AS reviews_3,
    SUM(CASE WHEN review_score = 4 THEN 1 ELSE 0 END)               AS reviews_4,
    SUM(CASE WHEN review_score = 5 THEN 1 ELSE 0 END)               AS reviews_5
FROM fct_order
WHERE is_delivered = 1
GROUP BY is_late_delivery;
