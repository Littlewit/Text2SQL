"""混合检索打分与分词的单元测试（FR-SCH-22）。"""

from app.services.schema_retrieval.hybrid_scorer import fuse_scores, keyword_score
from app.services.schema_retrieval.retriever import tokenize


def test_fuse_scores_weights():
    """融合得分符合加权组合，纯向量/纯关键词极端可解释。"""
    assert fuse_scores(1.0, 0.0) == 0.6  # 默认权重 0.6/0.4
    assert fuse_scores(0.0, 1.0) == 0.4
    assert fuse_scores(0.5, 0.5) == 0.5
    # 自定义权重
    assert fuse_scores(1.0, 0.0, vector_weight=1.0, keyword_weight=0.0) == 1.0


def test_keyword_score_exact_hit():
    """字面命中内容文本得满分（关键词兜底，避免纯语义漏召回）。"""
    assert keyword_score(["GMV"], "指标 GMV（gmv）：成交金额") == 1.0
    assert keyword_score(["gmv"], "指标 GMV（gmv）") == 1.0  # 忽略大小写语义由调用方统一
    assert keyword_score(["店铺", "订单金额"], "店铺 订单金额") == 1.0


def test_keyword_score_partial():
    """部分命中按比例计分；未命中为 0。"""
    assert 0 < keyword_score(["店铺", "退货率"], "店铺") < 1
    assert keyword_score(["不存在"], "其他内容") == 0.0
    assert keyword_score([], "任意") == 0.0


def test_tokenize():
    """分词：切分标点 + 生成 2-gram，支持中文字面命中。"""
    tokens = tokenize("上个月哪个店铺 GMV 最高？")
    assert "GMV" in tokens          # 原词保留
    assert "店铺" in tokens
    # 2-gram 覆盖：长词被切成相邻二字组合
    assert "上个" in tokens
    assert "哪个" in tokens
    # 去重
    assert len(tokens) == len(set(tokens))
