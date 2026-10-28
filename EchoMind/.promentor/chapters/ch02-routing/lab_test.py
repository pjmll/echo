"""Ch2 行为测试：多 Agent 路由与编排。学生不可修改本文件。"""
import pytest

import routing


# ── domain_scores ─────────────────────────────────────────────────────────────

def test_domain_scores_keys():
    scores = routing.domain_scores("greeting", "你好")
    assert set(scores.keys()) == {"general", "technical", "billing"}


def test_domain_scores_general_base_score():
    scores = routing.domain_scores(None, "zzz")
    assert scores["general"] == pytest.approx(0.1)
    assert scores["technical"] == 0.0
    assert scores["billing"] == 0.0


def test_domain_scores_billing_intent_plus_keyword():
    # refund 意图 +0.75，消息含 "退款" +0.18
    scores = routing.domain_scores("refund", "我要申请退款")
    assert scores["billing"] == pytest.approx(0.93)


def test_domain_scores_technical_intent_keyword_and_entity():
    # technical_login +0.75，"401" 关键词 +0.18，error_code 实体 +0.2
    scores = routing.domain_scores(
        "technical_login", "登录一直报 401", {"error_code": ["401"]}
    )
    assert scores["technical"] == pytest.approx(1.13)


def test_domain_scores_keyword_cap():
    msg = "崩溃 报错 error crash 无法登录 登录失败 500 401 验证码"
    scores = routing.domain_scores(None, msg)
    assert scores["technical"] == pytest.approx(0.45)


def test_domain_scores_general_keyword_cap():
    scores = routing.domain_scores(None, "订单 物流 快递 配送")
    assert scores["general"] == pytest.approx(0.45)


def test_domain_scores_entities_add_signal():
    scores = routing.domain_scores(
        None, "zzz", {"amount": ["50 元"], "order_id": ["AB1234"]}
    )
    assert scores["billing"] == pytest.approx(0.15)
    assert scores["general"] == pytest.approx(0.2)


def test_domain_scores_greeting_intent():
    scores = routing.domain_scores("greeting", "你好")
    assert scores["general"] == pytest.approx(0.65)


def test_domain_scores_rounded_to_three_decimals():
    scores = routing.domain_scores("technical_crash", "应用崩溃了报错500", {"error_code": ["500"]})
    for value in scores.values():
        assert value == round(value, 3)


# ── needs_clarification ───────────────────────────────────────────────────────

def test_clarification_low_confidence_other():
    assert routing.needs_clarification("other", 0.3, "我不知道该怎么办") is True


def test_clarification_high_confidence_other():
    assert routing.needs_clarification("other", 0.6, "我不知道该怎么办") is False


def test_clarification_known_intent_never_clarifies():
    assert routing.needs_clarification("refund", 0.1, "我不知道该怎么办") is False


def test_clarification_short_message_exempt():
    assert routing.needs_clarification("other", 0.1, "嗯") is False
    assert routing.needs_clarification("other", 0.1, "   ") is False


# ── routing_score ─────────────────────────────────────────────────────────────

def test_routing_score_fresh_agent_is_one():
    assert routing.routing_score(0, 0, 0.0) == pytest.approx(1.0)


def test_routing_score_healthy_agent():
    # sr=1.0, avg=100ms → latency=1/1.1 → 0.7 + 0.3/1.1
    expected = 1.0 * 0.7 + (1.0 / 1.1) * 0.3
    assert routing.routing_score(10, 10, 1000.0) == pytest.approx(expected)


def test_routing_score_success_dominates_latency():
    healthy_slow = routing.routing_score(10, 10, 5000.0)
    failing_fast = routing.routing_score(10, 5, 100.0)
    assert healthy_slow > failing_fast


def test_routing_score_penalty_multiplies():
    base = routing.routing_score(10, 10, 1000.0)
    assert routing.routing_score(10, 10, 1000.0, penalty=0.5) == pytest.approx(base * 0.5)


def test_routing_score_full_penalty_zeroes():
    assert routing.routing_score(10, 10, 1000.0, penalty=1.0) == 0.0


# ── best_agent ────────────────────────────────────────────────────────────────

def _agent(name, total=10, success=10, total_ms=1000.0, penalty=0.0):
    return {"name": name, "total": total, "success": success,
            "total_ms": total_ms, "penalty": penalty}


def test_best_agent_prefers_unpenalized():
    agents = [_agent("healthy"), _agent("penalized", penalty=0.6)]
    assert routing.best_agent(agents)["name"] == "healthy"


def test_best_agent_prefers_faster():
    agents = [_agent("slow", total_ms=50000.0), _agent("fast", total_ms=100.0)]
    assert routing.best_agent(agents)["name"] == "fast"


def test_best_agent_tie_keeps_first():
    agents = [_agent("first"), _agent("second")]
    assert routing.best_agent(agents)["name"] == "first"


def test_best_agent_empty():
    assert routing.best_agent([]) is None


# ── route_decision ────────────────────────────────────────────────────────────

SCORES = {"general": 0.1, "technical": 1.13, "billing": 0.93}
ALL_AVAILABLE = {"general", "technical", "billing"}


def test_route_critical_urgency_short_circuits():
    d = routing.route_decision("refund", "critical", 0.9, SCORES, ALL_AVAILABLE, [])
    assert d["primary"] == "escalation"
    assert d["supporting"] == []
    assert d["confidence"] == 1.0


def test_route_critical_case_insensitive():
    d = routing.route_decision(None, "CRITICAL", 0.9, SCORES, ALL_AVAILABLE, [])
    assert d["primary"] == "escalation"


def test_route_human_handoff_short_circuits():
    d = routing.route_decision("human_handoff", "low", 0.6, SCORES, ALL_AVAILABLE, [])
    assert d["primary"] == "escalation"
    assert d["confidence"] == pytest.approx(0.8)


def test_route_escalation_keeps_high_confidence():
    d = routing.route_decision("escalation", None, 0.95, SCORES, ALL_AVAILABLE, [])
    assert d["primary"] == "escalation"
    assert d["confidence"] == pytest.approx(0.95)


def test_route_picks_highest_score_as_primary():
    d = routing.route_decision("technical_login", "high", 0.9, SCORES, ALL_AVAILABLE, [])
    assert d["primary"] == "technical"
    assert d["confidence"] == 1.0  # min(1.13, 1.0) 封顶


def test_route_collaboration_target_becomes_supporting():
    d = routing.route_decision("technical_login", None, 0.9, SCORES, ALL_AVAILABLE, ["billing"])
    assert d["primary"] == "technical"
    assert d["supporting"] == ["billing"]


def test_route_collaboration_excludes_primary():
    d = routing.route_decision("technical_login", None, 0.9, SCORES, ALL_AVAILABLE,
                               ["technical", "billing"])
    assert d["supporting"] == ["billing"]


def test_route_fallback_supporting_by_threshold():
    scores = {"general": 0.1, "technical": 0.9, "billing": 0.6}
    d = routing.route_decision("technical", None, 0.9, scores, ALL_AVAILABLE, [])
    assert d["primary"] == "technical"
    assert d["supporting"] == ["billing"]


def test_route_fallback_rejects_weak_score():
    scores = {"general": 0.1, "technical": 0.9, "billing": 0.3}
    d = routing.route_decision("technical", None, 0.9, scores, ALL_AVAILABLE, [])
    assert d["supporting"] == []


def test_route_fallback_rejects_relatively_weak_score():
    # billing 0.5 >= 0.45 但 < 1.0 * 0.55
    scores = {"general": 0.1, "technical": 1.0, "billing": 0.5}
    d = routing.route_decision("technical", None, 0.9, scores, ALL_AVAILABLE, [])
    assert d["supporting"] == []


def test_route_general_never_supporting():
    scores = {"general": 0.85, "technical": 0.9, "billing": 0.0}
    d = routing.route_decision("technical", None, 0.9, scores, ALL_AVAILABLE, [])
    assert d["primary"] == "technical"
    assert d["supporting"] == []


def test_route_filters_unavailable_domain():
    scores = {"general": 0.65, "technical": 0.9, "billing": 0.3}
    d = routing.route_decision("technical", None, 0.9, scores, {"general", "billing"}, [])
    assert d["primary"] == "general"  # technical 无实例，被过滤
    assert d["confidence"] == pytest.approx(0.65)


def test_route_general_always_available():
    scores = {"general": 0.65, "technical": 0.9, "billing": 0.3}
    d = routing.route_decision("greeting", None, 0.9, scores, set(), [])
    assert d["primary"] == "general"


def test_route_reason_mentions_primary():
    d = routing.route_decision("technical_login", None, 0.9, SCORES, ALL_AVAILABLE, [])
    assert isinstance(d["reason"], str) and d["reason"]
    assert d["primary"] in d["reason"]
