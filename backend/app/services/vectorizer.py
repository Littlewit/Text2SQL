"""向量化服务：标注对象 → schema_embedding（FR-SCH-20/23）。

标注内容变更后自动重新向量化对应对象（增量）；
Celery 异步化在 T3/T5 接入，T2 以内联调用保证标注后立即可检索。
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import ColumnMeta, Metric, SchemaEmbedding, Synonym, TableMeta
from app.llm.embedding import EmbeddingClient


def _table_content(tm: TableMeta) -> str:
    """表的向量化文本：中文名 + 表名 + 描述。"""
    return f"表 {tm.table_name}（{tm.cn_name or tm.table_name}）：{tm.description or ''}"


def _column_content(cm: ColumnMeta, tm: TableMeta | None) -> str:
    """字段的向量化文本：所属表 + 中文名 + 字段名 + 描述 + 枚举展示名。"""
    parts = [f"{tm.cn_name or tm.table_name}.{cm.cn_name or cm.column_name}" if tm else cm.column_name]
    parts.append(cm.description or "")
    parts.append(cm.column_name)
    if cm.sample_values and cm.sample_values.get("values"):
        parts.append("取值: " + "、".join(str(v) for v in cm.sample_values["values"][:10]))
    return " ".join(p for p in parts if p)


def _metric_content(m: Metric) -> str:
    return f"指标 {m.name}（{m.code}）：{m.description or ''} 单位:{m.unit or ''}"


def _synonym_content(s: Synonym) -> str:
    return f"同义词 {s.term}"


async def vectorize_object(
    db: AsyncSession,
    embedder: EmbeddingClient,
    object_type: str,
    object_id: int,
) -> None:
    """为单个对象重建向量：先删旧行再插入（模型版本变化时同样适用，DR-04）。"""
    content, ds_id = await _load_content(db, object_type, object_id)
    if content is None:
        return  # 对象已删除：移除其向量
    await db.execute(
        delete(SchemaEmbedding).where(
            SchemaEmbedding.object_type == object_type,
            SchemaEmbedding.object_id == object_id,
            SchemaEmbedding.model_version == embedder.model_version,
        )
    )
    vec = (await embedder.embed([content]))[0]
    db.add(
        SchemaEmbedding(
            object_type=object_type,
            object_id=object_id,
            datasource_id=ds_id,
            content_text=content,
            embedding=vec,
            model_version=embedder.model_version,
        )
    )
    await db.commit()


async def _load_content(db: AsyncSession, object_type: str, object_id: int):
    """加载对象并生成向量化文本；返回 (content, datasource_id)，对象不存在返回 (None, None)。"""
    if object_type == "table":
        tm = await db.get(TableMeta, object_id)
        return (_table_content(tm), tm.datasource_id) if tm else (None, None)
    if object_type == "column":
        cm = await db.get(ColumnMeta, object_id)
        if cm is None:
            return None, None
        tm = await db.get(TableMeta, cm.table_meta_id)
        return (_column_content(cm, tm), tm.datasource_id if tm else None)
    if object_type == "metric":
        m = await db.get(Metric, object_id)
        return (_metric_content(m), m.datasource_id) if m else (None, None)
    if object_type == "synonym":
        s = await db.get(Synonym, object_id)
        return (_synonym_content(s), s.datasource_id) if s else (None, None)
    return None, None


async def revectorize_datasource(db: AsyncSession, embedder: EmbeddingClient, ds_id: int) -> int:
    """全量重建某数据源的全部向量（Embedding 模型变更时使用，DR-04）。"""
    count = 0
    table_ids = (
        await db.execute(select(TableMeta.id).where(TableMeta.datasource_id == ds_id))
    ).scalars()
    for tid in table_ids:
        await vectorize_object(db, embedder, "table", tid)
        count += 1
        cols = (
            await db.execute(select(ColumnMeta.id).where(ColumnMeta.table_meta_id == tid))
        ).scalars()
        for cid in cols:
            await vectorize_object(db, embedder, "column", cid)
            count += 1
    metrics = (
        await db.execute(
            select(Metric.id).where((Metric.datasource_id == ds_id) | (Metric.datasource_id.is_(None)))
        )
    ).scalars()
    for mid in metrics:
        await vectorize_object(db, embedder, "metric", mid)
        count += 1
    return count
