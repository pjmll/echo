# Ch 5: 记忆与上下文构建

本章学什么：**当对话变长、上下文窗口有限时，如何让 LLM 既看到完整历史又不超出 token 限制？**

难度：mid。涉及状态管理、摘要生成、上下文格式化——都是生产级对话系统的核心挑战。

## 1. 工作记忆 vs 长期记忆

EchoMind 的记忆分两层：

- **工作记忆（Working Memory）**：当前对话的原始消息列表，存在 Redis 中，key 由 `user_id + conv_id` 生成。
- **长期记忆（Long-term Memory）**：对话摘要 + 用户画像，经过压缩后存储，用于跨会话回忆。

`memory/conversation_memory.py` 是这两层的管理者。

## 2. 工作记忆 Key 生成（:381-:383）

```python
@staticmethod
def _wm_key(user_id: str, conv_id: str) -> str:
    return f"wm:{user_id}:{conv_id}"
```

**为什么用这个格式？** Redis 的 key 命名约定是 `namespace:entity:id`。`wm:` 前缀区分工作记忆和其他类型的 key（如 `profile:` 用户画像、`summary:` 对话摘要）。这种分层命名让运维可以按前缀扫描/清理特定类型的数据。

## 3. 上下文压缩（:256-:303）

当工作记忆超过阈值时，触发压缩：

```python
async def _compress(self, user_id: str, conv_id: str) -> None:
    messages = await self._get_working_memory(user_id, conv_id)
    if len(messages) <= 10:
        return
    
    to_compress = messages[:-5]   # 保留最近 5 条
    text = self._safe_text("\n".join(f"{m.role.value}: {m.content}" for m in to_compress))
    
    summary = await self._generate_summary(text)  # LLM 调用
    old_summary = await self._get_summary(user_id, conv_id)
    new_summary = await self._merge_summary(old_summary, summary)
    
    await self._save_summary(user_id, conv_id, new_summary)
    await self._set_working_memory(user_id, conv_id, messages[-5:])  # 只保留最近 5 条
```

**设计决策：为什么保留最近 5 条？**

- 太少（如 2 条）：LLM 丢失当前话题的上下文，回复会显得"失忆"。
- 太多（如 10 条）：压缩收益小，频繁触发 LLM 摘要调用增加延迟和成本。
- 5 条是经验平衡点：覆盖最近 2-3 轮对话（user+assistant 各算一条），足够维持连贯性。

**压缩触发条件**：`len(messages) > 10`。这意味着工作记忆最多积累到 10 条才压缩，避免频繁操作。

## 4. 摘要合并（:445-:460）

```python
async def _merge_summary(self, old_summary: str, new_summary: str) -> str:
    if not old_summary:
        return new_summary
    if not new_summary:
        return old_summary
    
    prompt = f"""将以下两段对话摘要合并为一段简洁的摘要，保留关键信息：

旧摘要：
{old_summary}

新摘要：
{new_summary}

合并后的摘要（不超过 200 字）："""
    
    resp = await self._client.messages.create(...)
    return extract_text_content(resp.content).strip()
```

**为什么需要合并而不是替换？** 对话是渐进的，旧摘要包含早期上下文（如用户身份、问题背景），新摘要包含近期发展。直接替换会丢失历史信息。合并让摘要"滚动更新"，始终反映完整对话脉络。

**LLM 的角色**：摘要合并不是简单的字符串拼接——LLM 需要理解语义，去重冗余信息，保持逻辑连贯。这是少数必须用 LLM 的环节之一。

## 5. 上下文格式化（:169-:230）

最终传给 LLM 的上下文由三部分组成：

```python
def _build_context(self, history: List[Message], summary: str, knowledge: str) -> str:
    parts = []
    
    if summary:
        parts.append(f"[对话摘要]\n{summary}")
    
    if knowledge:
        parts.append(f"[相关知识]\n{knowledge}")
    
    if history:
        history_text = "\n".join(f"{m.role.value}: {m.content}" for m in history[-10:])
        parts.append(f"[最近对话]\n{history_text}")
    
    return "\n\n".join(parts)
```

**为什么是这个顺序？** 

1. **摘要在前**：提供全局背景，让 LLM 理解"我们在聊什么"。
2. **知识居中**：RAG 检索的文档片段，是回答问题的依据。
3. **历史在后**：最近的原始对话，保持语境连贯。

这个顺序符合 LLM 的注意力机制——重要信息放前面（摘要），具体依据放中间（知识），即时语境放后面（历史）。

**历史截断**：`history[-10:]` 只取最近 10 条。即使工作记忆有更多消息，传给 LLM 的也只有最近 10 条——这是 token 预算的硬限制。

## 6. Lab：提取记忆管理的确定性内核

实现 `memory_tools.py`（纯标准库）：

- `wm_key(user_id, conv_id)` — §2 的 Redis key 生成
- `compress_partition(messages, keep_recent=5)` — §3 的压缩分区逻辑（不调用 LLM，只做分区）
- `merge_summary(old_summary, new_summary)` — §4 的摘要合并（规则版本，不调用 LLM）
- `format_context(history, summary, knowledge)` — §5 的上下文格式化

LLM 调用（摘要生成、合并）在 Final 章覆盖；本章聚焦确定性逻辑。
