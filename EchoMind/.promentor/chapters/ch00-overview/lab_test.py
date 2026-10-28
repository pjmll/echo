"""Ch0 行为测试：系统全景。学生不可修改本文件。"""
import overview


def test_chat_flow_has_six_stages():
    assert isinstance(overview.CHAT_FLOW, list)
    assert len(overview.CHAT_FLOW) == 6, "CHAT_FLOW 应恰好包含六个阶段"


def test_chat_flow_ordering():
    assert overview.CHAT_FLOW == [
        "read_memory",
        "intent_recognition",
        "knowledge_check",
        "agent_routing",
        "execute_agents",
        "write_memory",
    ], "阶段顺序错误：对照 lecture.md 的六阶段表格"


def test_render_flow_default_renders_chat_flow():
    expected = (
        "read_memory -> intent_recognition -> knowledge_check"
        " -> agent_routing -> execute_agents -> write_memory"
    )
    assert overview.render_flow() == expected


def test_render_flow_custom_stages():
    assert overview.render_flow(["gather", "act", "respond"]) == "gather -> act -> respond"


def test_render_flow_single_stage():
    assert overview.render_flow(["only"]) == "only"


def test_render_flow_empty_list():
    assert overview.render_flow([]) == ""
