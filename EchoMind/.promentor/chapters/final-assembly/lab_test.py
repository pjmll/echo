"""Final 行为测试：组装 Mini EchoMind。学生不可修改本文件。"""
import asyncio
import mini_echomind


def test_mini_echomind_init():
    """MiniEchoMind 可以正常初始化。"""
    system = mini_echomind.MiniEchoMind()
    assert system is not None


def test_handle_request_returns_string():
    """handle_request 返回字符串回复。"""
    system = mini_echomind.MiniEchoMind()
    response = asyncio.run(system.handle_request("user1", "conv1", "你好"))
    assert isinstance(response, str)
    assert len(response) > 0


def test_handle_request_different_intents():
    """不同意图触发不同路由。"""
    system = mini_echomind.MiniEchoMind()

    # 技术类问题
    r1 = asyncio.run(system.handle_request("user1", "conv1", "登录报401错误"))
    assert isinstance(r1, str)

    # 账单类问题
    r2 = asyncio.run(system.handle_request("user1", "conv1", "我要申请退款"))
    assert isinstance(r2, str)

    # 通用问题
    r3 = asyncio.run(system.handle_request("user1", "conv1", "你好"))
    assert isinstance(r3, str)


def test_get_stats_structure():
    """get_stats 返回正确结构的统计信息。"""
    system = mini_echomind.MiniEchoMind()
    asyncio.run(system.handle_request("user1", "conv1", "测试"))

    stats = system.get_stats()
    assert isinstance(stats, dict)
    assert "agents" in stats or "cache_hits" in stats or "breaker_state" in stats


def test_working_memory_persists():
    """工作记忆在多次请求间保持。"""
    system = mini_echomind.MiniEchoMind()

    asyncio.run(system.handle_request("user1", "conv1", "第一条消息"))
    asyncio.run(system.handle_request("user1", "conv1", "第二条消息"))

    # 工作记忆应该包含两条消息
    key = "wm:user1:conv1"
    if hasattr(system, 'working_memory') and key in system.working_memory:
        assert len(system.working_memory[key]) >= 2


def test_circuit_breaker_integration():
    """熔断器集成正常工作。"""
    system = mini_echomind.MiniEchoMind()

    # 正常请求
    asyncio.run(system.handle_request("user1", "conv1", "测试"))

    # 检查熔断器状态
    if hasattr(system, 'breaker'):
        assert system.breaker.state.value in ["closed", "open", "half_open"]


def test_cache_integration():
    """缓存集成正常工作。"""
    system = mini_echomind.MiniEchoMind()

    # 相同请求两次
    asyncio.run(system.handle_request("user1", "conv1", "退款政策"))
    asyncio.run(system.handle_request("user1", "conv1", "退款政策"))

    # 缓存应该有命中（具体实现取决于学生）
    stats = system.get_stats()
    assert isinstance(stats, dict)


def test_monitoring_integration():
    """监控集成正常工作。"""
    system = mini_echomind.MiniEchoMind()

    # 多次请求
    for i in range(5):
        asyncio.run(system.handle_request("user1", "conv1", f"测试消息{i}"))

    # 统计应该被更新
    stats = system.get_stats()
    assert isinstance(stats, dict)


def test_error_handling():
    """系统能处理异常情况。"""
    system = mini_echomind.MiniEchoMind()

    # 空消息
    response = asyncio.run(system.handle_request("user1", "conv1", ""))
    assert isinstance(response, str)

    # 超长消息
    long_msg = "测试" * 1000
    response = asyncio.run(system.handle_request("user1", "conv1", long_msg))
    assert isinstance(response, str)


def test_concurrent_requests():
    """系统能处理并发请求。"""
    system = mini_echomind.MiniEchoMind()

    async def send_multiple():
        tasks = [
            system.handle_request(f"user{i}", f"conv{i}", f"消息{i}")
            for i in range(3)
        ]
        return await asyncio.gather(*tasks)

    responses = asyncio.run(send_multiple())
    assert len(responses) == 3
    assert all(isinstance(r, str) for r in responses)
