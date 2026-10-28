"""Ch1 行为测试：三路融合意图识别。学生不可修改本文件。"""
import pytest

import intent


# ── CATEGORIES ────────────────────────────────────────────────────────────────

EXPECTED_CATEGORIES = {
    "query", "complaint", "request", "greeting", "escalation", "technical",
    "billing", "account", "feedback", "order_status", "logistics", "refund",
    "invoice", "payment_issue", "account_security", "technical_login",
    "technical_crash", "human_handoff", "other",
}


def test_categories_complete():
    assert set(intent.CATEGORIES) == EXPECTED_CATEGORIES
    assert len(intent.CATEGORIES) == 19


# ── cosine ────────────────────────────────────────────────────────────────────

def test_cosine_identical_vectors():
    assert intent.cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    assert intent.cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector_guard():
    assert intent.cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert intent.cosine([1.0, 1.0], [0.0, 0.0]) == 0.0


def test_cosine_opposite_vectors():
    assert intent.cosine([1.0, 1.0], [-1.0, -1.0]) == pytest.approx(-1.0)


# ── local_embedding ───────────────────────────────────────────────────────────

def test_local_embedding_dims():
    vec = intent.local_embedding("我要退款")
    assert len(vec) == 256
    assert len(intent.local_embedding("我要退款", dims=64)) == 64


def test_local_embedding_deterministic():
    assert intent.local_embedding("登录失败401") == intent.local_embedding("登录失败401")


def test_local_embedding_different_texts_differ():
    assert intent.local_embedding("我要退款") != intent.local_embedding("应用崩溃了")


def test_local_embedding_similar_texts_more_similar():
    base = intent.local_embedding("我要申请退款")
    near = intent.local_embedding("申请退款")
    far = intent.local_embedding("服务器崩溃报错500")
    assert intent.cosine(base, near) > intent.cosine(base, far)


# ── pattern_recognize ─────────────────────────────────────────────────────────

SPECIFIC = {
    "refund": ["退款", "退货"],
    "technical_login": ["无法登录", "401"],
}
GENERIC = {
    "billing": ["退款", "扣款"],
    "greeting": ["你好", "hello"],
    "request": ["help"],
}


def test_pattern_single_hit_scores_half():
    cat, score = intent.pattern_recognize("我要退款", SPECIFIC, GENERIC)
    assert cat == "refund"
    assert score == pytest.approx(0.5)


def test_pattern_multi_hit_scores_higher():
    cat, score = intent.pattern_recognize("申请退款和退货", SPECIFIC, GENERIC)
    assert cat == "refund"
    assert score == pytest.approx(0.75)


def test_pattern_score_capped_at_one():
    cat, score = intent.pattern_recognize("退款退款退货", SPECIFIC, GENERIC)
    assert cat == "refund"
    assert score == pytest.approx(1.0)


def test_pattern_specific_beats_generic():
    # generic 里也有 "退款"（billing），但 specific 优先
    cat, _ = intent.pattern_recognize("退款", SPECIFIC, GENERIC)
    assert cat == "refund"


def test_pattern_falls_back_to_generic():
    cat, score = intent.pattern_recognize("你好", SPECIFIC, GENERIC)
    assert cat == "greeting"
    assert score == pytest.approx(0.5)


def test_pattern_case_insensitive():
    cat, _ = intent.pattern_recognize("HELP me", SPECIFIC, GENERIC)
    assert cat == "request"


def test_pattern_no_match_returns_other():
    assert intent.pattern_recognize("？？？", SPECIFIC, GENERIC) == ("other", 0.0)


# ── vote ──────────────────────────────────────────────────────────────────────

def test_vote_unanimous():
    result, conf, sources = intent.vote(
        {"intent": "refund", "confidence": 0.9},
        {"intent": "refund", "confidence": 0.6},
        {"intent": "refund", "confidence": 0.5},
    )
    assert result == "refund"
    assert conf == pytest.approx(0.9 * 0.7 + 0.6 * 0.2 + 0.5 * 0.1)
    assert sources == {"llm": 0.9, "embedding": 0.6, "pattern": 0.5}


def test_vote_weighted_disagreement():
    # llm(refund, 0.9)*0.7 + pat(refund, 0.5)*0.1 = 0.68 > emb(billing, 0.4)*0.2 = 0.08
    result, conf, _ = intent.vote(
        {"intent": "refund", "confidence": 0.9},
        {"intent": "billing", "confidence": 0.4},
        {"intent": "refund", "confidence": 0.5},
    )
    assert result == "refund"
    assert conf == pytest.approx(0.68)


def test_vote_below_threshold_downgrades_to_other():
    result, conf, _ = intent.vote(
        {"intent": "query", "confidence": 0.3},
        {"intent": "other", "confidence": 0.0},
        {"intent": "other", "confidence": 0.0},
    )
    assert result == "other"
    assert conf == pytest.approx(0.21)


def test_vote_custom_threshold():
    result, _, _ = intent.vote(
        {"intent": "query", "confidence": 0.9},
        {"intent": "other", "confidence": 0.0},
        {"intent": "other", "confidence": 0.0},
        threshold=0.7,
    )
    assert result == "query"


def test_vote_llm_failed_falls_back_to_embedding():
    result, conf, sources = intent.vote(
        {"intent": "other", "confidence": 0.0, "failed": True},
        {"intent": "logistics", "confidence": 0.6},
        {"intent": "query", "confidence": 0.5},
    )
    assert result == "logistics"
    assert conf == pytest.approx(0.6)
    assert sources["embedding"] == 0.6


def test_vote_llm_and_embedding_failed_falls_back_to_pattern():
    result, conf, _ = intent.vote(
        {"intent": "other", "confidence": 0.0, "failed": True},
        {"intent": "other", "confidence": 0.0},
        {"intent": "refund", "confidence": 0.5},
    )
    assert result == "refund"
    assert conf == pytest.approx(0.5)


def test_vote_all_sources_dead():
    result, conf, sources = intent.vote(
        {"intent": "other", "confidence": 0.0, "failed": True},
        {"intent": "other", "confidence": 0.0},
        {"intent": "other", "confidence": 0.0},
    )
    assert result == "other"
    assert conf == 0.0
    assert sources == {"llm": 0.0, "embedding": 0.0, "pattern": 0.0}


def test_vote_none_confidence_treated_as_zero():
    result, conf, sources = intent.vote(
        {"intent": "refund", "confidence": None},
        {"intent": "refund", "confidence": 0.9},
        {"intent": "refund", "confidence": 0.5},
    )
    # 0*0.7 + 0.9*0.2 + 0.5*0.1 = 0.23 < 0.5 → other
    assert result == "other"
    assert conf == pytest.approx(0.23)
    assert sources["llm"] == 0.0


# ── extract_entities ──────────────────────────────────────────────────────────

def test_entities_fixed_keys():
    ents = intent.extract_entities("你好")
    assert set(ents.keys()) == {"order_id", "product", "date", "amount", "error_code"}
    assert ents["product"] == []
    assert ents["order_id"] == []


def test_entities_order_id():
    ents = intent.extract_entities("订单号 #A1234 还没发货")
    assert "A1234" in ents["order_id"]


def test_entities_order_id_english():
    ents = intent.extract_entities("order: XY-99887 not shipped")
    assert "XY-99887" in ents["order_id"]


def test_entities_amount():
    assert "50 元" in intent.extract_entities("这个月多扣了 50 元")["amount"]
    assert "¥99.5" in intent.extract_entities("退款 ¥99.5 什么时候到")["amount"]


def test_entities_error_code_with_prefix():
    ents = intent.extract_entities("请求返回 error_code: 500")
    assert ents["error_code"] == ["500"]


def test_entities_error_code_bare():
    ents = intent.extract_entities("页面报 401 错误")
    assert ents["error_code"] == ["401"]


def test_entities_error_code_ignores_non_4xx_5xx():
    ents = intent.extract_entities("订单号 #20250 金额 200 元")
    assert ents["error_code"] == []


def test_entities_date():
    assert "今天" in intent.extract_entities("今天下的单")["date"]
    assert "2026-01-01" in intent.extract_entities("2026-01-01 购买的商品")["date"]


def test_entities_dedupe_preserves_order():
    ents = intent.extract_entities("订单 #AB1234 和 #AB1234 重复了，还有 #CD5678")
    assert ents["order_id"] == ["AB1234", "CD5678"]


# ── urgency ───────────────────────────────────────────────────────────────────

def test_urgency_critical_keyword():
    assert intent.urgency("紧急处理", "query") == 4


def test_urgency_high_keyword():
    assert intent.urgency("马上给我解决", "query") == 3


def test_urgency_medium_keyword():
    assert intent.urgency("这周内处理一下", "query") == 2


def test_urgency_keyword_case_insensitive():
    assert intent.urgency("URGENT case", "query") == 4


def test_urgency_escalation_intent_default():
    assert intent.urgency("找你们经理", "escalation") == 3


def test_urgency_human_handoff_intent_default():
    assert intent.urgency("我要找人工", "human_handoff") == 3


def test_urgency_complaint_intent_default():
    assert intent.urgency("服务不行", "complaint") == 2


def test_urgency_plain_default():
    assert intent.urgency("我的订单什么时候到", "order_status") == 1
