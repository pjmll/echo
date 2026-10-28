"""Ch5 行为测试：记忆与上下文构建。学生不可修改本文件。"""
import memory_tools


# ── wm_key ────────────────────────────────────────────────────────────────────

def test_wm_key_basic():
    assert memory_tools.wm_key("user123", "conv456") == "wm:user123:conv456"


def test_wm_key_empty_ids():
    assert memory_tools.wm_key("", "") == "wm::"


def test_wm_key_special_chars():
    assert memory_tools.wm_key("user:123", "conv/456") == "wm:user:123:conv/456"


# ── compress_partition ────────────────────────────────────────────────────────

def test_compress_partition_short_list():
    messages = [{"role": "user", "content": "hi"}]
    to_compress, to_keep = memory_tools.compress_partition(messages, keep_recent=5)
    assert to_compress == []
    assert to_keep == messages


def test_compress_partition_exact_keep():
    messages = [{"role": "user", "content": f"msg{i}"} for i in range(5)]
    to_compress, to_keep = memory_tools.compress_partition(messages, keep_recent=5)
    assert to_compress == []
    assert len(to_keep) == 5


def test_compress_partition_splits_correctly():
    messages = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    to_compress, to_keep = memory_tools.compress_partition(messages, keep_recent=5)
    assert len(to_compress) == 5
    assert len(to_keep) == 5
    assert to_compress[0]["content"] == "msg0"
    assert to_keep[0]["content"] == "msg5"


def test_compress_partition_custom_keep():
    messages = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
    to_compress, to_keep = memory_tools.compress_partition(messages, keep_recent=3)
    assert len(to_compress) == 17
    assert len(to_keep) == 3


def test_compress_partition_empty():
    to_compress, to_keep = memory_tools.compress_partition([], keep_recent=5)
    assert to_compress == []
    assert to_keep == []


def test_compress_partition_does_not_mutate():
    messages = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    original_len = len(messages)
    memory_tools.compress_partition(messages, keep_recent=5)
    assert len(messages) == original_len


# ── merge_summary ─────────────────────────────────────────────────────────────

def test_merge_summary_old_empty():
    result = memory_tools.merge_summary("", "新摘要内容")
    assert result == "新摘要内容"


def test_merge_summary_new_empty():
    result = memory_tools.merge_summary("旧摘要内容", "")
    assert result == "旧摘要内容"


def test_merge_summary_both_empty():
    result = memory_tools.merge_summary("", "")
    assert result == ""


def test_merge_summary_both_present():
    result = memory_tools.merge_summary("旧摘要", "新摘要")
    assert "旧摘要" in result
    assert "新摘要" in result
    assert "\n\n" in result


def test_merge_summary_strips_whitespace():
    result = memory_tools.merge_summary("  旧摘要  ", "  新摘要  ")
    assert result == "旧摘要\n\n新摘要"


def test_merge_summary_whitespace_only_old():
    result = memory_tools.merge_summary("   \n  ", "新摘要")
    assert result == "新摘要"


def test_merge_summary_whitespace_only_new():
    result = memory_tools.merge_summary("旧摘要", "   \n  ")
    assert result == "旧摘要"


# ── format_context ────────────────────────────────────────────────────────────

def test_format_context_all_empty():
    result = memory_tools.format_context([], summary="", knowledge="")
    assert result == ""


def test_format_context_only_summary():
    result = memory_tools.format_context([], summary="这是摘要", knowledge="")
    assert "[对话摘要]" in result
    assert "这是摘要" in result


def test_format_context_only_knowledge():
    result = memory_tools.format_context([], summary="", knowledge="这是知识")
    assert "[相关知识]" in result
    assert "这是知识" in result


def test_format_context_only_history():
    history = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好！"}]
    result = memory_tools.format_context(history, summary="", knowledge="")
    assert "[最近对话]" in result
    assert "user: 你好" in result
    assert "assistant: 你好！" in result


def test_format_context_all_parts():
    history = [{"role": "user", "content": "问题"}]
    result = memory_tools.format_context(history, summary="摘要", knowledge="知识")
    assert "[对话摘要]" in result
    assert "[相关知识]" in result
    assert "[最近对话]" in result
    # Order: summary -> knowledge -> history
    summary_idx = result.index("[对话摘要]")
    knowledge_idx = result.index("[相关知识]")
    history_idx = result.index("[最近对话]")
    assert summary_idx < knowledge_idx < history_idx


def test_format_context_history_truncates_to_10():
    history = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
    result = memory_tools.format_context(history, summary="", knowledge="")
    # Should only contain last 10 messages
    assert "msg10" in result
    assert "msg19" in result
    assert "msg0" not in result
    assert "msg9" not in result


def test_format_context_double_newline_separator():
    history = [{"role": "user", "content": "hi"}]
    result = memory_tools.format_context(history, summary="s", knowledge="k")
    # Parts should be separated by double newline
    assert "\n\n" in result


def test_format_context_history_format():
    history = [
        {"role": "user", "content": "问题1"},
        {"role": "assistant", "content": "回答1"},
        {"role": "user", "content": "问题2"},
    ]
    result = memory_tools.format_context(history, summary="", knowledge="")
    lines = result.split("\n")
    # Skip the [最近对话] header line
    content_lines = [l for l in lines if l and not l.startswith("[")]
    assert len(content_lines) == 3
    assert content_lines[0] == "user: 问题1"
    assert content_lines[1] == "assistant: 回答1"
    assert content_lines[2] == "user: 问题2"
