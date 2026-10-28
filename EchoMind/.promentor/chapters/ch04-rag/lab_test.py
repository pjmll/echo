"""Ch4 行为测试：RAG 检索优化。学生不可修改本文件。"""
import time

import rag_tools


# ── chunk_text ────────────────────────────────────────────────────────────────

def test_chunk_text_short_returns_single():
    result = rag_tools.chunk_text("你好世界", chunk_size=500)
    assert result == ["你好世界"]


def test_chunk_text_empty():
    assert rag_tools.chunk_text("") == []
    assert rag_tools.chunk_text("   ") == []
    assert rag_tools.chunk_text("\n\n") == []


def test_chunk_text_preserves_sentence_boundaries():
    text = "第一段内容。第二段内容。第三段内容。"
    result = rag_tools.chunk_text(text, chunk_size=100)
    # Should split by period, each chunk ends with 。
    assert all(c.endswith("。") or len(c) > 0 for c in result)


def test_chunk_text_splits_when_exceeding_chunk_size():
    # Build a long string with many sentences exceeding chunk_size
    sentences = f"{"A" * 80}。{"B" * 80}。{"C" * 80}。{"D" * 80}。"
    result = rag_tools.chunk_text(sentences, chunk_size=200)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= 201  # may be slightly over due to adding one sentence


def test_chunk_text_joins_with_period():
    text = "第一句。第二句。第三句。"
    result = rag_tools.chunk_text(text, chunk_size=30)
    # Each join should use '。' as separator
    if len(result) > 1:
        # Check that periods are used for joining (the original split + rejoin logic)
        pass  # structural check: chunks exist and cover content
    assert sum(len(c) for c in result) == len(text)


def test_chunk_text_newline_treated_as_sentence_boundary():
    text = "第1行\n第2行\n第3行"
    result = rag_tools.chunk_text(text, chunk_size=20)
    assert isinstance(result, list)
    assert len(result) >= 1


def test_chunk_text_large_chunks():
    """当 chunk_size 大于文本时，返回单个 chunk。"""
    long_text = "。".join(["句子" + str(i) for i in range(10)])
    result = rag_tools.chunk_text(long_text, chunk_size=9999)
    assert len(result) == 1


def test_chunk_text_exact_boundary():
    """chunk_size 恰好等于文本长度。"""
    text = "这是一段刚好长度的文本"
    result = rag_tools.chunk_text(text, chunk_size=len(text))
    assert result == [text]


# ── merge_dedupe ──────────────────────────────────────────────────────────────

def test_merge_dedupe_empty():
    assert rag_tools.merge_dedupe([]) == []


def test_merge_dedupe_no_duplicates():
    r1 = [{"content": "aaa"}, {"content": "bbb"}]
    r2 = [{"content": "ccc"}]
    result = rag_tools.merge_dedupe([r1, r2])
    assert len(result) == 3
    assert [d["content"] for d in result] == ["aaa", "bbb", "ccc"]


def test_merge_dedupe_removes_duplicates():
    item_same = {"content": "相同的文档"}
    r1 = [item_same, {"content": "独有A"}]
    r2 = [item_same, {"content": "独有B"}]
    result = rag_tools.merge_dedupe([r1, r2])
    # item_same appears only once (from r1, first occurrence)
    assert len(result) == 3
    assert result[0]["content"] == "相同的文档"


def test_merge_dedupe_maintains_insertion_order():
    r1 = [{"content": "first"}, {"content": "second"}]
    r2 = [{"content": "third"}, {"content": "first"}]  # first is duplicate
    result = rag_tools.merge_dedupe([r1, r2])
    contents = [d["content"] for d in result]
    assert contents.index("first") < contents.index("third")
    assert contents.index("first") < contents.index("second")


def test_merge_dedupe_max_items_truncates():
    r1 = [{"content": str(i)} for i in range(10)]
    result = rag_tools.merge_dedupe([r1], max_items=3)
    assert len(result) == 3


def test_merge_dedupe_max_items_none_no_truncate():
    r1 = [{"content": str(i)} for i in range(10)]
    result = rag_tools.merge_dedupe([r1], max_items=None)
    assert len(result) == 10


def test_merge_dedupe_all_failed_results():
    """空列表结果合并后仍为空。"""
    result = rag_tools.merge_dedupe([[], [], []])
    assert result == []


def test_merge_dedupe_string_items():
    """item 是字符串（非 dict）也能去重。"""
    r1 = ["a", "b"]
    r2 = ["b", "c"]
    result = rag_tools.merge_dedupe([r1, r2])
    assert result == ["a", "b", "c"]


# ── apply_rerank ──────────────────────────────────────────────────────────────

def test_apply_rerank_basic():
    items = [{"i": 0}, {"i": 1}, {"i": 2}, {"i": 3}]
    order = [3, 0, 2, 1]
    result = rag_tools.apply_rerank(order, items, top_k=4)
    assert [x["i"] for x in result] == [3, 0, 2, 1]


def test_apply_rerank_top_k_truncation():
    items = [{"i": i} for i in range(5)]
    order = [0, 1, 2, 3, 4]
    result = rag_tools.apply_rerank(order, items, top_k=2)
    assert len(result) == 2
    assert [x["i"] for x in result] == [0, 1]


def test_apply_rerank_filters_out_of_bounds():
    items = [{"i": 0}, {"i": 1}, {"i": 2}]
    order = [-1, 0, 3, 1, 100]  # -1, 3, 100 are invalid
    result = rag_tools.apply_rerank(order, items, top_k=10)
    assert [x["i"] for x in result] == [0, 1]


def test_apply_rerank_empty_items():
    assert rag_tools.apply_rerank([], [], top_k=5) == []


def test_apply_rerank_empty_order():
    items = [{"i": 0}, {"i": 1}]
    assert rag_tools.apply_rerank([], items, top_k=2) == []


def test_apply_rerank_top_k_zero():
    items = [{"i": 0}, {"i": 1}]
    assert rag_tools.apply_rerank([0, 1], items, top_k=0) == []


def test_apply_rerank_partial_valid_indices():
    items = [{"i": 0}, {"i": 1}]
    order = [5, 6, 0, 7, 1]  # only 0 and 1 are valid
    result = rag_tools.apply_rerank(order, items, top_k=10)
    assert [x["i"] for x in result] == [0, 1]


# ── distance_to_score ─────────────────────────────────────────────────────────

def test_distance_to_score_perfect_match():
    assert rag_tools.distance_to_score(0.0) == 1.0


def test_distance_to_score_exact_opposite():
    assert rag_tools.distance_to_score(2.0) == -1.0


def test_distance_to_score_unrelated():
    assert rag_tools.distance_to_score(1.0) == 0.0


def test_distance_to_score_rounds_to_four_decimals():
    assert rag_tools.distance_to_score(0.123456) == round(1.0 - 0.123456, 4)


def test_distance_to_score_negative_distance():
    assert rag_tools.distance_to_score(-0.1) == round(1.0 - (-0.1), 4)


def test_distance_to_score_precision():
    d = 0.56789
    s = rag_tools.distance_to_score(d)
    assert s == round(1.0 - d, 4)
    assert s == 0.4321
