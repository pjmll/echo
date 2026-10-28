"""Ch6 行为测试：监控与路由降权闭环。学生不可修改本文件。"""
import monitor_tools


# ── z_score ───────────────────────────────────────────────────────────────────

def test_z_score_basic():
    values = [10.0, 12.0, 11.0, 13.0, 12.0]
    current = 20.0
    z = monitor_tools.z_score(values, current)
    assert z is not None
    assert z > 2.0  # 20 is far from mean ~11.6


def test_z_score_normal_value():
    values = [10.0, 12.0, 11.0, 13.0, 12.0]
    current = 11.5
    z = monitor_tools.z_score(values, current)
    assert z is not None
    assert z < 1.0  # 11.5 is close to mean


def test_z_score_zero_stdev():
    values = [5.0, 5.0, 5.0, 5.0]
    current = 10.0
    z = monitor_tools.z_score(values, current)
    assert z is None  # Cannot compute z-score with zero stdev


def test_z_score_insufficient_data():
    values = [10.0]
    current = 20.0
    z = monitor_tools.z_score(values, current)
    assert z is None  # Need at least 2 values


def test_z_score_empty_values():
    z = monitor_tools.z_score([], 10.0)
    assert z is None


def test_z_score_rounds_to_two_decimals():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    current = 10.0
    z = monitor_tools.z_score(values, current)
    assert z is not None
    # Check it's rounded to 2 decimals
    assert z == round(z, 2)


def test_z_score_negative_deviation():
    values = [10.0, 12.0, 11.0, 13.0, 12.0]
    current = 2.0  # Far below mean
    z = monitor_tools.z_score(values, current)
    assert z is not None
    assert z > 2.0  # abs() makes it positive


# ── routing_penalty ───────────────────────────────────────────────────────────

def test_routing_penalty_perfect():
    assert monitor_tools.routing_penalty(1.0, 1000.0) == 0.0


def test_routing_penalty_low_success_rate():
    penalty = monitor_tools.routing_penalty(0.80, 1000.0)
    assert penalty > 0.0
    assert penalty <= 0.5  # Only success rate penalty


def test_routing_penalty_high_latency():
    penalty = monitor_tools.routing_penalty(1.0, 5000.0)
    assert penalty > 0.0
    assert penalty <= 0.4  # Only latency penalty


def test_routing_penalty_both_issues():
    penalty = monitor_tools.routing_penalty(0.70, 6000.0)
    assert penalty > 0.0
    assert penalty <= 0.9  # Combined but capped


def test_routing_penalty_max_cap():
    # Very bad metrics should still cap at 0.9
    penalty = monitor_tools.routing_penalty(0.0, 20000.0)
    assert penalty == 0.9


def test_routing_penalty_success_rate_boundary():
    # Exactly 0.90 should have no penalty
    assert monitor_tools.routing_penalty(0.90, 1000.0) == 0.0
    # Just below 0.90 should have small penalty
    penalty = monitor_tools.routing_penalty(0.899, 1000.0)
    assert penalty > 0.0
    assert penalty < 0.1


def test_routing_penalty_latency_boundary():
    # Exactly 3000ms should have no penalty
    assert monitor_tools.routing_penalty(1.0, 3000.0) == 0.0
    # Just above 3000ms should have small penalty
    penalty = monitor_tools.routing_penalty(1.0, 3001.0)
    assert penalty > 0.0
    assert penalty < 0.1


def test_routing_penalty_linear_scaling():
    # Success rate penalty scales linearly
    p1 = monitor_tools.routing_penalty(0.85, 1000.0)
    p2 = monitor_tools.routing_penalty(0.80, 1000.0)
    assert p2 > p1  # Lower success rate -> higher penalty


# ── check_threshold ───────────────────────────────────────────────────────────

THRESHOLDS = {
    "agent_success_rate": (0.90, "error", "less_than"),
    "agent_avg_ms": (3000, "warning", "greater_than"),
}


def test_check_threshold_triggered_less_than():
    result = monitor_tools.check_threshold("agent_success_rate", 0.85, THRESHOLDS)
    assert result is not None
    assert result["triggered"] is True
    assert result["severity"] == "error"
    assert result["value"] == 0.85
    assert result["threshold"] == 0.90


def test_check_threshold_not_triggered_less_than():
    result = monitor_tools.check_threshold("agent_success_rate", 0.95, THRESHOLDS)
    assert result is None


def test_check_threshold_triggered_greater_than():
    result = monitor_tools.check_threshold("agent_avg_ms", 3500.0, THRESHOLDS)
    assert result is not None
    assert result["triggered"] is True
    assert result["severity"] == "warning"


def test_check_threshold_not_triggered_greater_than():
    result = monitor_tools.check_threshold("agent_avg_ms", 2500.0, THRESHOLDS)
    assert result is None


def test_check_threshold_unknown_metric():
    result = monitor_tools.check_threshold("unknown_metric", 100.0, THRESHOLDS)
    assert result is None


def test_check_threshold_boundary_equal():
    # Exactly at threshold should not trigger
    result = monitor_tools.check_threshold("agent_success_rate", 0.90, THRESHOLDS)
    assert result is None

    result = monitor_tools.check_threshold("agent_avg_ms", 3000.0, THRESHOLDS)
    assert result is None


def test_check_threshold_returns_dict_structure():
    result = monitor_tools.check_threshold("agent_success_rate", 0.80, THRESHOLDS)
    assert isinstance(result, dict)
    assert "metric" in result
    assert "value" in result
    assert "threshold" in result
    assert "severity" in result
    assert "triggered" in result
    assert result["metric"] == "agent_success_rate"
