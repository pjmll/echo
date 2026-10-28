# 源码导读：记忆与上下文构建

## 核心文件：`memory/conversation_memory.py`

### _wm_key（:381-:383）

```python
@staticmethod
def _wm_key(user_id: str, conv_id: str) -> str:
    return f"wm:{user_id}:{conv_id}"
```

- 静态方法，纯函数。
- 格式：`wm:` 前缀 + user_id + `:` + conv_id。
- 用于 Redis 存储工作记忆的 key 生成。

### _compress（:256-:303）

- 触发条件（:265-:266）：`len(messages) <= 10` 时直接返回，不压缩。
- 分区逻辑（:268）：`to_compress = messages[:-5]` ——保留最近 5 条，压缩前面的。
- 文本构造（:272）：`"\n".join(f"{m.role.value}: {m.content}" for m in to_compress)`。
- 摘要生成（:275-:281）：调用 LLM，失败时降级为 `"对话包含 N 条消息（摘要生成失败）"`。
- 摘要合并（:286）：`new_summary = await self._merge_summary(old_summary, summary)`。
- 状态更新（:293-:295）：保存新摘要，工作记忆只保留最近 5 条。

### _merge_summary（:445-:460）

- 空值处理（:446-:449）：old_summary 为空返回 new_summary，反之亦然。
- LLM prompt（:451-:458）：要求合并两段摘要，保留关键信息，不超过 200 字。
- 返回（:460）：`extract_text_content(resp.content).strip()`。

### _build_context（:169-:230）

实际代码中上下文构建分散在多个方法中，但核心逻辑是：

1. 获取工作记忆（:169）：`messages = await self._get_working_memory(user_id, conv_id)`。
2. 获取摘要（:232）：`recent = await self._get_working_memory(...)` + 摘要拼接。
3. 知识检索（外部调用）：RAG 工具返回的文档片段。
4. 格式化（:169-:230 的组装逻辑）：按 `[对话摘要]` → `[相关知识]` → `[最近对话]` 顺序拼接。

**关键行**：
- :169：`messages = await self._get_working_memory(user_id, conv_id)` ——获取原始消息。
- :232：`recent = await self._get_working_memory(...)` ——再次获取用于上下文构建。
- :272：文本构造用于摘要生成。
- :286：摘要合并调用。

### _get_working_memory（:305-:320）

- 从 Redis 读取消息列表。
- 反序列化为 `Message` 对象。
- 返回 `List[Message]`。

### _set_working_memory（:322-:335）

- 序列化 `Message` 列表。
- 写入 Redis，设置 TTL（过期时间）。
- 用于压缩后更新工作记忆。
