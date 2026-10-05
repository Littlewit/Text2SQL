"""评测元数据种子（M2-T6）：为 demo_business 建立召回/EX 评测所需的语义层。

内容：数据源改名、表/字段中文标注、指标（GMV/订单数/退货率）、同义词、
JOIN 路径、全量向量化。幂等：重复执行不产生重复数据（指标按 code 去重）。

用法：cd backend && python scripts/seed_eval_meta.py
"""

import asyncio
import sys
from datetime import date

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.domain.schemas_meta import (  # noqa: E402
    JoinPathCreate,
    MetricCreate,
    SynonymCreate,
)
from app.infra.db import get_session_factory, reset_engine  # noqa: E402
from app.infra.models import (  # noqa: E402
    ColumnMeta,
    Datasource,
    JoinPath,
    Metric,
    TableMeta,
)
from app.llm.embedding import get_embedder  # noqa: E402
from app.services import taxonomy_service, vectorizer  # noqa: E402

# 表/字段中文标注（覆盖评测问题中的业务词汇）
TABLE_NOTES = {
    "orders": ("订单表", "销售订单主表，含订单日期/金额/状态"),
    "shop": ("店铺表", "门店主数据，含名称/区域/城市"),
    "product": ("商品表", "商品主数据，含品类/价格"),
    "order_item": ("订单明细表", "订单商品明细，含数量/单价/金额"),
    "return_order": ("退货表", "退货记录，含退货金额/原因/日期"),
}
COLUMN_NOTES = {
    ("orders", "amount"): ("金额", "订单实付金额（元）"),
    ("orders", "order_date"): ("下单日期", "订单创建日期"),
    ("orders", "status"): ("订单状态码", "1=已支付 2=已发货 3=已完成 4=已退货（整型枚举）"),
    ("orders", "shop_id"): ("店铺ID", "外键 → shop.id"),
    ("shop", "name"): ("店铺名称", "门店名称"),
    ("shop", "region"): ("区域", "华东/华南/华北等大区"),
    ("shop", "city"): ("城市", "门店所在城市"),
    ("product", "category"): ("品类", "商品类目"),
    ("product", "name"): ("商品名称", "商品名称"),
    ("order_item", "quantity"): ("数量", "购买件数"),
    ("order_item", "amount"): ("明细金额", "数量×单价"),
    ("return_order", "return_amount"): ("退货金额", "退货实退金额（元）"),
    ("return_order", "return_date"): ("退货日期", "退货发生日期"),
    ("return_order", "reason"): ("退货原因", "质量/尺寸/七日无理由等"),
}

# 指标口径（评测问题对齐：GMV/订单量/退货率）
METRICS = [
    {"code": "gmv", "name": "GMV", "description": "商品交易总额，已支付订单实付金额合计",
     "formula": {"expr": "SUM(orders.amount)"}, "agg_type": "sum",
     "default_time_column": "orders.order_date", "unit": "元"},
    {"code": "order_count", "name": "订单量", "description": "订单笔数（去重订单ID计数）",
     "formula": {"expr": "COUNT(DISTINCT orders.id)"}, "agg_type": "count",
     "default_time_column": "orders.order_date", "unit": "单"},
    {"code": "return_rate", "name": "退货率", "description": "退货金额占 GMV 的比例",
     "formula": {"expr": "SUM(return_order.return_amount) / SUM(orders.amount)"},
     "agg_type": None, "default_time_column": "return_order.return_date", "unit": "%"},
]

SYNONYMS = [("销售额", "gmv"), ("GMV", "gmv"), ("成交额", "gmv"),
            ("订单数", "order_count"), ("订单量", "order_count"),
            ("退货率", "return_rate")]

JOIN_PATHS = [
    ("orders", "shop_id", "shop", "id"),
    ("order_item", "order_id", "orders", "id"),
    ("order_item", "product_id", "product", "id"),
    ("return_order", "order_item_id", "order_item", "id"),
]


async def main() -> None:
    get_settings.cache_clear()
    reset_engine()
    db = get_session_factory()()
    embedder = get_embedder()

    async with db:
        ds = (await db.execute(select(Datasource).where(Datasource.db_name == "demo_business"))).scalars().first()
        if ds is None:
            raise SystemExit("未找到 demo_business 数据源，请先接入并扫描")
        if ds.name != "demo_business":
            ds.name = "demo_business"  # 评测/生成链路按名称引用
            print(f"数据源改名 → demo_business (id={ds.id})")

        tables = {t.table_name: t for t in
                  (await db.execute(select(TableMeta).where(TableMeta.datasource_id == ds.id))).scalars()}
        cols: dict[tuple[str, str], ColumnMeta] = {}
        for tm in tables.values():
            for c in (await db.execute(select(ColumnMeta).where(ColumnMeta.table_meta_id == tm.id))).scalars():
                cols[(tm.table_name, c.column_name)] = c

        # 1. 表/字段标注（幂等：已有内容不覆盖）
        for name, (cn, desc) in TABLE_NOTES.items():
            tm = tables.get(name)
            if tm and not tm.cn_name:
                tm.cn_name, tm.description = cn, desc
        for (tn, cn_), (cn, desc) in COLUMN_NOTES.items():
            c = cols.get((tn, cn_))
            if c and not c.cn_name:
                c.cn_name, c.description = cn, desc

        # 2. JOIN 路径（幂等）
        existing_jp = set(
            (await db.execute(select(JoinPath).where(JoinPath.datasource_id == ds.id))).scalars().all()
        )
        for lt, lc, rt, rc in JOIN_PATHS:
            l_id, r_id = tables[lt].id, tables[rt].id
            has = any(p.left_table_id == l_id and p.left_column == lc
                      and p.right_table_id == r_id for p in existing_jp)
            if not has:
                await taxonomy_service.create_join_path(db, JoinPathCreate(
                    datasource_id=ds.id, left_table_id=l_id, left_column=lc,
                    right_table_id=r_id, right_column=rc, join_type="inner",
                ), operator_id=1)
                print(f"JOIN 路径: {lt}.{lc} → {rt}.{rc}")

        # 3. 指标（幂等：按 code）+ 指标名同义词
        for m in METRICS:
            exists = (await db.execute(select(Metric).where(Metric.code == m["code"]))).scalars().first()
            if not exists:
                fields = {k: v for k, v in m.items() if k != "status"}
                fields["datasource_id"] = ds.id
                created = await taxonomy_service.create_metric(
                    db, embedder, MetricCreate(**fields), operator_id=1,
                )
                print(f"指标: {m['code']}")
                target_id = created.id
            else:
                target_id = exists.id
            try:
                await taxonomy_service.create_synonym(db, embedder, SynonymCreate(
                    term=m["name"], target_type="metric", target_id=target_id, datasource_id=ds.id,
                ), operator_id=1)
            except Exception:
                pass  # 幂等：同义词已存在

        # 4. 业务词同义词（幂等：唯一冲突吞掉）
        from app.core.errors import AppError

        for term, code in SYNONYMS:
            target = (await db.execute(select(Metric).where(Metric.code == code))).scalars().first()
            try:
                await taxonomy_service.create_synonym(db, embedder, SynonymCreate(
                    term=term, target_type="metric", target_id=target.id, datasource_id=ds.id,
                ), operator_id=1)
            except AppError:
                pass  # 已存在

        # 4.5 枚举字典（orders.status 整型枚举 → Prompt 提供取值映射，防语义漂移）
        from app.domain.schemas_meta import EnumDictUpsert

        status_col = cols.get(("orders", "status"))
        if status_col:
            for raw_v, disp in (("1", "已支付"), ("2", "已发货"), ("3", "已完成"), ("4", "已退货")):
                try:
                    await taxonomy_service.upsert_enum_dict(db, EnumDictUpsert(
                        column_meta_id=status_col.id, raw_value=raw_v, display_name=disp,
                    ), operator_id=1)
                except AppError:
                    pass

        await db.commit()

        # 5. 全量向量化（检索/召回评测依赖）
        n = await vectorizer.revectorize_datasource(db, embedder, ds.id)
        await db.commit()
        print(f"向量化完成: {n} 条")

    from datetime import datetime

    print("done:", datetime.now().strftime("%H:%M:%S"), "| 评测基准日:", date.today().isoformat())


asyncio.run(main())
