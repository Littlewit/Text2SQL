"""集成测试：T2 Schema 管理链路（扫描 → 标注 → 向量化 → 混合检索召回）。

前置：dev 容器已启动且 demo_business 示例库已初始化（scripts/seed_demo_business.ps1）。
运行方式：pytest -m integration
"""

import pytest

from tests.integration.conftest import auth_header as _auth

pytestmark = pytest.mark.integration

# admin_token / datasource_id / scanned 夹具见本目录 conftest.py（T2/T3 共用）


def test_scan_discovers_demo_schema(client, admin_token, scanned):
    """扫描 demo_business：5 张表全部入库，含主外键信息（FR-SCH-02）。"""
    resp = client.post(f"/api/v1/admin/schema/datasources/{scanned}/scan", headers=_auth(admin_token))
    assert resp.status_code == 200
    stats = resp.json()["data"]
    assert stats["tables"] == 5  # shop/product/orders/order_item/return_order
    assert stats["columns"] > 20

    tables = client.get(
        "/api/v1/admin/schema/tables", headers=_auth(admin_token),
        params={"datasource_id": scanned},
    ).json()["data"]
    names = {t["table_name"] for t in tables}
    assert {"shop", "product", "orders", "order_item", "return_order"} <= names


def test_annotate_and_vectorize_and_recall(client, admin_token, scanned):
    """标注 → 向量化 → 混合检索召回目标表/字段/指标（T2 验收标准）。"""
    headers = _auth(admin_token)

    # 1) 纳入并标注 shop 表
    tables = client.get(
        "/api/v1/admin/schema/tables", headers=headers, params={"datasource_id": scanned}
    ).json()["data"]
    by_name = {t["table_name"]: t for t in tables}

    resp = client.patch(
        f"/api/v1/admin/schema/tables/{by_name['shop']['id']}",
        headers=headers,
        json={"cn_name": "店铺", "description": "店铺主数据，含所属区域（华东/华南/华北）", "included": True},
    )
    assert resp.status_code == 200
    # 完整度按字段标注占比计算（FR-SCH-15），表级标注不改变字段占比
    assert "annotation_score" in resp.json()["data"]

    # 2) 纳入并标注 orders 表与金额字段
    client.patch(
        f"/api/v1/admin/schema/tables/{by_name['orders']['id']}",
        headers=headers,
        json={"cn_name": "订单表", "description": "订单主表，含订单日期、状态与实付金额", "included": True},
    )
    cols = client.get(
        f"/api/v1/admin/schema/tables/{by_name['orders']['id']}/columns", headers=headers
    ).json()["data"]
    amount_col = next(c for c in cols if c["column_name"] == "amount")
    client.patch(
        f"/api/v1/admin/schema/columns/{amount_col['id']}",
        headers=headers,
        json={"cn_name": "订单金额", "description": "订单实付金额，单位元", "usage_type": "metric", "unit": "元"},
    )

    # 3) 定义 GMV 指标与同义词（销售额/成交金额 → gmv）
    metric = client.post(
        "/api/v1/admin/metrics", headers=headers,
        json={
            "datasource_id": scanned,
            "name": "GMV", "code": "gmv",
            "description": "成交总额，订单实付金额求和",
            "formula": {"expr": "SUM(orders.amount)"},
            "agg_type": "sum", "default_time_column": "orders.order_date", "unit": "元",
        },
    )
    assert metric.status_code == 201
    gmv_id = metric.json()["data"]["id"]
    for term in ("销售额", "成交金额"):
        r = client.post(
            "/api/v1/admin/synonyms", headers=headers,
            json={"term": term, "target_type": "metric", "target_id": gmv_id, "datasource_id": scanned},
        )
        assert r.status_code == 201

    # 4) 混合检索验收：SC-01 问题应召回店铺/订单/GMV
    search = client.post(
        "/api/v1/admin/schema/search", headers=headers,
        json={"query": "上个月哪个店铺GMV最高？", "datasource_id": scanned, "top_k": 10},
    )
    assert search.status_code == 200
    results = search.json()["data"]
    types = {(r["object_type"], r["object_id"]) for r in results}
    assert ("metric", gmv_id) in types  # 指标命中
    # 店铺表或订单表在 Top-K 中
    tables_by_id = {t["id"]: t["table_name"] for t in by_name.values()}
    recalled_tables = {tables_by_id.get(oid) for otype, oid in types if otype == "table"}
    assert recalled_tables & {"shop", "orders"}, f"召回的表: {recalled_tables}"


def test_table_annotation_rollback(client, admin_token, scanned):
    """表标注回滚到上一版本（DR-03）。"""
    headers = _auth(admin_token)
    tables = client.get(
        "/api/v1/admin/schema/tables", headers=headers, params={"datasource_id": scanned}
    ).json()["data"]
    product = next(t for t in tables if t["table_name"] == "product")

    # 第一次标注
    client.patch(
        f"/api/v1/admin/schema/tables/{product['id']}", headers=headers,
        json={"cn_name": "商品表", "description": "商品主数据", "included": True},
    )
    # 第二次标注（将被回滚）
    client.patch(
        f"/api/v1/admin/schema/tables/{product['id']}", headers=headers,
        json={"cn_name": "错误标注"},
    )
    # 回滚 → 应恢复到第一次标注值
    resp = client.post(f"/api/v1/admin/schema/tables/{product['id']}/rollback", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["cn_name"] == "商品表"


def test_enum_dict_upsert(client, admin_token, scanned):
    """枚举字典 upsert：同 (column, raw) 更新而非重复创建（FR-SCH-11）。"""
    headers = _auth(admin_token)
    tables = client.get("/api/v1/admin/schema/tables", headers=headers).json()["data"]
    shop = next(t for t in tables if t["table_name"] == "shop")
    cols = client.get(f"/api/v1/admin/schema/tables/{shop['id']}/columns", headers=headers).json()["data"]
    region = next(c for c in cols if c["column_name"] == "region")

    r1 = client.put(
        "/api/v1/admin/enum-dicts", headers=headers,
        json={"column_meta_id": region["id"], "raw_value": "华东", "display_name": "华东大区"},
    )
    assert r1.status_code == 200
    r2 = client.put(
        "/api/v1/admin/enum-dicts", headers=headers,
        json={"column_meta_id": region["id"], "raw_value": "华东", "display_name": "华东区域"},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["id"] == r1.json()["data"]["id"]  # 幂等更新
    assert r2.json()["data"]["display_name"] == "华东区域"
