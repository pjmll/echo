"""Ch3 行为测试：MCP 工具框架。学生不可修改本文件。"""
import time

import mcp_tools


# ── CircuitBreaker ────────────────────────────────────────────────────────────

def _cb(threshold=3, recovery_s=0.05):
    return mcp_tools.CircuitBreaker(failure_threshold=threshold, recovery_s=recovery_s)


def test_breaker_initially_closes():
    cb = _cb()
    assert cb.state == mcp_tools.CircuitState.CLOSED
    assert cb.fail_count == 0
    assert cb.allow() is True


def test_breaker_opens_after_threshold():
    cb = _cb()
    for _ in range(cb.threshold - 1):
        cb.record_failure()
        assert cb.state == mcp_tools.CircuitState.CLOSED

    cb.record_failure()
    assert cb.state == mcp_tools.CircuitState.OPEN
    assert cb.fail_count >= cb.threshold
    assert cb.allow() is False


def test_breaker_half_open_after_recovery_and_recovers():
    cb = _cb()
    # Trip it
    for _ in range(cb.threshold):
        cb.record_failure()
    assert cb.state == mcp_tools.CircuitState.OPEN

    # Wait for recovery
    time.sleep(0.06)
    assert cb.allow() is True
    assert cb.state == mcp_tools.CircuitState.HALF_OPEN

    # Probe succeeds → close
    cb.record_success()
    assert cb.state == mcp_tools.CircuitState.CLOSED
    assert cb.fail_count == 0
    assert cb.allow() is True


def test_breaker_half_open_probe_fails_reopens():
    cb = _cb()
    for _ in range(cb.threshold):
        cb.record_failure()
    time.sleep(0.06)
    assert cb.allow() is True  # → HALF_OPEN
    assert cb.state == mcp_tools.CircuitState.HALF_OPEN

    cb.record_failure()
    assert cb.state == mcp_tools.CircuitState.OPEN
    assert cb.allow() is False


# ── ToolResult ────────────────────────────────────────────────────────────────

def test_tool_result_defaults():
    r = mcp_tools.ToolResult(success=True, data=[1], tool_name="t")
    assert r.error is None
    assert r.cached is False
    assert r.latency_ms == 0.0
    assert r.reranked is False


def test_tool_result_full():
    r = mcp_tools.ToolResult(success=False, data=None, tool_name="x", error="boom", cached=True, reranked=True)
    assert not r.success
    assert r.error == "boom"
    assert r.cached is True
    assert r.reranked is True


# ── TTLToolCache ──────────────────────────────────────────────────────────────

def test_cache_get_empty():
    c = mcp_tools.TTLToolCache(maxsize=4)
    assert c.get("nope") is None


def test_cache_set_and_get():
    c = mcp_tools.TTLToolCache(maxsize=4)
    c.set("k1", "v1", ttl=10.0)
    assert c.get("k1") == "v1"
    assert len(c) == 1


def test_cache_expiry_removes_entry():
    c = mcp_tools.TTLToolCache(maxsize=4)
    c.set("k1", "v1", ttl=0.05)
    assert c.get("k1") == "v1"
    time.sleep(0.06)
    assert c.get("k1") is None


def test_cache_evicts_oldest_when_full():
    c = mcp_tools.TTLToolCache(maxsize=4)
    for i in range(4):
        c.set(f"k{i}", f"v{i}", ttl=10.0)
    # Fill one more → 4//4=1 oldest deleted
    c.set("k4", "v4", ttl=10.0)

    assert c.get("k0") is None  # evicted
    assert c.get("k1") == "v1"
    assert c.get("k4") == "v4"
    assert len(c) == 4


def test_cache_overwrite_expires_ttl():
    c = mcp_tools.TTLToolCache(maxsize=4)
    c.set("k1", "old", ttl=0.05)
    time.sleep(0.02)
    c.set("k1", "new", ttl=10.0)  # overwrite refreshes TTL
    time.sleep(0.05)
    assert c.get("k1") == "new"


def test_cache_noop_on_small_ttl_for_get():
    """TTL <= 0 → never expired once get hits? Actually spec: expire_at = monotonict()+ttl. If ttl=0, expires immediately."""
    c = mcp_tools.TTLToolCache(maxsize=4)
    c.set("k1", "v1", ttl=0.0)
    assert c.get("k1") is None  # already expired (time passes between set and get)


# ── validate_params ───────────────────────────────────────────────────────────

def test_validate_params_missing_required():
    schema = {"required": ["query"], "properties": {"query": {"type": "string"}}}
    try:
        mcp_tools.validate_params(schema, {})
        raise AssertionError("should have raised ValueError for missing required param")
    except ValueError as e:
        assert "query" in str(e).lower()


def test_validate_params_wrong_type():
    schema = {"required": ["name"], "properties": {"name": {"type": "string"}, "count": {"type": "integer"}}}
    try:
        mcp_tools.validate_params(schema, {"name": 123})
        raise AssertionError("should have raised ValueError for wrong type")
    except ValueError as e:
        assert "name" in str(e).lower()


def test_validate_params_number_accepts_int_and_float():
    schema = {"required": [], "properties": {"val": {"type": "number"}}}
    mcp_tools.validate_params(schema, {"val": 42})       # int ok for number
    mcp_tools.validate_params(schema, {"val": 3.14})      # float ok for number


def test_validate_params_unknown_params_ignored():
    schema = {"required": ["q"], "properties": {"q": {"type": "string"}}}
    mcp_tools.validate_params(schema, {"q": "ok", "extra": 999})  # extra ignored


def test_validate_params_valid_returns_none():
    schema = {"required": ["a", "b"], "properties": {"a": {"type": "string"}, "b": {"type": "boolean"}}}
    result = mcp_tools.validate_params(schema, {"a": "hello", "b": True})
    assert result is None
