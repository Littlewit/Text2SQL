-- ============================================================
-- Text2SQL 示例业务库（零售/店铺/GMV 域）
-- 用途：本地开发与评测的演示数据源，支撑 SC-01~03 与 AC-01~03 验收
-- 前置：在 demo_business 数据库内执行（见 seed_demo_business.ps1）
-- 注意：业务库不需要 pgvector；平台通过只读账号连接本库
-- ============================================================

-- 店铺维度表
CREATE TABLE shop (
    id       SERIAL PRIMARY KEY,
    name     VARCHAR(64) NOT NULL,
    region   VARCHAR(32) NOT NULL,       -- 区域：华东/华南/华北
    city     VARCHAR(32) NOT NULL,
    open_date DATE NOT NULL
);
COMMENT ON TABLE shop IS '店铺主数据，含所属区域';
COMMENT ON COLUMN shop.region IS '大区，取值：华东/华南/华北';

-- 商品维度表
CREATE TABLE product (
    id       SERIAL PRIMARY KEY,
    name     VARCHAR(128) NOT NULL,
    category VARCHAR(32) NOT NULL,       -- 品类：家电/服饰/食品/美妆
    price    NUMERIC(10,2) NOT NULL
);
COMMENT ON TABLE product IS '商品主数据';

-- 订单主表
CREATE TABLE orders (
    id         SERIAL PRIMARY KEY,
    shop_id    INT NOT NULL REFERENCES shop(id),
    order_no   VARCHAR(32) NOT NULL UNIQUE,
    order_date DATE NOT NULL,
    status     INT NOT NULL,              -- 1已支付 2已发货 3已完成 4已退货
    amount     NUMERIC(12,2) NOT NULL     -- 订单实付金额（元）
);
COMMENT ON COLUMN orders.status IS '订单状态：1=已支付 2=已发货 3=已完成 4=已退货';
COMMENT ON COLUMN orders.amount IS '订单实付金额，单位元';
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_shop ON orders(shop_id);

-- 订单明细
CREATE TABLE order_item (
    id         SERIAL PRIMARY KEY,
    order_id   INT NOT NULL REFERENCES orders(id),
    product_id INT NOT NULL REFERENCES product(id),
    quantity   INT NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL,
    amount     NUMERIC(12,2) NOT NULL     -- 明细金额 = quantity * unit_price
);
COMMENT ON TABLE order_item IS '订单商品明细';

-- 退货单
CREATE TABLE return_order (
    id             SERIAL PRIMARY KEY,
    order_item_id  INT NOT NULL REFERENCES order_item(id),
    return_date    DATE NOT NULL,
    return_amount  NUMERIC(12,2) NOT NULL,
    reason         VARCHAR(32)
);
COMMENT ON TABLE return_order IS '退货记录，退货率派生指标的数据来源';

-- ---------- 种子数据 ----------

INSERT INTO shop (name, region, city, open_date) VALUES
 ('旗舰店A', '华东', '上海', '2023-01-01'),
 ('旗舰店B', '华东', '杭州', '2023-03-15'),
 ('门店C',   '华南', '广州', '2023-05-01'),
 ('门店D',   '华南', '深圳', '2023-06-20'),
 ('门店E',   '华北', '北京', '2023-08-01'),
 ('门店F',   '华北', '天津', '2024-01-10');

INSERT INTO product (name, category, price) VALUES
 ('智能电视65寸', '家电', 3999.00),
 ('无线耳机',     '家电', 599.00),
 ('羽绒服',       '服饰', 899.00),
 ('运动鞋',       '服饰', 499.00),
 ('坚果礼盒',     '食品', 128.00),
 ('咖啡豆',       '食品', 88.00),
 ('口红套装',     '美妆', 329.00),
 ('香水',         '美妆', 519.00),
 ('空气炸锅',     '家电', 399.00),
 ('连衣裙',       '服饰', 699.00);

-- 订单：近三个月（含「上个月」「这个季度」可解析的自然月数据）
-- 金额分布刻意让 2026-09 华东店铺领先，支撑 SC-01「上个月哪个店铺 GMV 最高」
INSERT INTO orders (shop_id, order_no, order_date, status, amount)
SELECT s.id,
       'SO' || to_char(d, 'YYYYMMDD') || lpad(g::text, 4, '0'),
       d::date,
       (ARRAY[1,2,3,3,3,4])[1 + (g % 6)],
       round((150 + (g * 37 + extract(day from d)::int * 13) % 800)::numeric, 2)
FROM generate_series('2026-07-01'::date, '2026-09-30'::date, interval '1 day') d
CROSS JOIN generate_series(1, 30) g
JOIN shop s ON s.id = 1 + (g % 6);

INSERT INTO order_item (order_id, product_id, quantity, unit_price, amount)
SELECT o.id,
       1 + (o.id % 10),
       1 + (o.id % 3),
       p.price,
       round(p.price * (1 + (o.id % 3)), 2)
FROM orders o
JOIN product p ON p.id = 1 + (o.id % 10);

-- 退货：约 8% 的明细有退货，支撑 SC-02「退货率超过 10% 的商品」
INSERT INTO return_order (order_item_id, return_date, return_amount, reason)
SELECT oi.id, (o.order_date + interval '2 day')::date, round(oi.amount * 0.8, 2),
       (ARRAY['质量问题','尺码不符','不想要了'])[1 + (oi.id % 3)]
FROM order_item oi JOIN orders o ON o.id = oi.order_id
WHERE oi.id % 12 = 0;

ANALYZE;
