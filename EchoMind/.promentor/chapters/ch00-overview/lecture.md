# Ch 0: 系统全景与环境搭建

本章学什么：**在写任何代码之前，先在脑中装下 EchoMind 的完整请求生命周期**。后面 6 个 Lab 都是这条流水线上的一个环节；如果你不知道环节之间的顺序和契约，单看任何一个模块都是盲人摸象。

## 1. EchoMind 是什么

一个面向客服/运营场景的多 Agent 运行时。它不是聊天机器人，而是一条**可观测、可评测、可降级**的处理流水线：

```text
用户请求 POST /chat
  → MemoryManager 读取三级记忆（工作记忆 / 情景记忆 / 用户画像）
  → IntentRecognizer 输出 intent / intent_group / urgency / entities
  → 按意图决定是否检索知识库（RAG 门控）
  → AgentOrchestrator 路由到 General / Technical / Billing / Escalation
  → Skills 注入、工具调用、回复生成
  → 写回 Redis 和 ChromaDB，异步更新用户画像
  → Monitor 采集在线指标并回写路由惩罚
  → Evaluator 做端到端质量评测
```

## 2. 六个主链路阶段

本课程把 `/chat` 的处理拆成六个阶段（这是 Lab 要你填写的核心内容）：

| # | 阶段 | 负责模块 | 一句话职责 |
|---|------|---------|-----------|
| 1 | `read_memory` | `memory/conversation_memory.py` | 取出当前会话的上下文（最近消息 + 语义相关历史 + 画像） |
| 2 | `intent_recognition` | `core/intent_recognizer.py` | 把自然语言变成结构化意图：类别、置信度、紧急度、实体 |
| 3 | `knowledge_check` | `api/main.py::_should_use_knowledge` | 判断这条消息值不值得走 RAG 检索（寒暄跳过，业务问题才查） |
| 4 | `agent_routing` | `agents/agent_orchestrator.py::_route_decision` | 决定主 Agent、辅助 Agent、升级路径 |
| 5 | `execute_agents` | `agents/agent_orchestrator.py::_execute` | 调用 LLM + 工具白名单生成回复，失败降级 |
| 6 | `write_memory` | `memory/conversation_memory.py::add_message` | 写回工作记忆，触发压缩，异步更新画像 |

**设计决策：为什么意图识别在路由之前？**
路由需要结构化输入（意图、紧急度、实体）才能打分。如果先路由再识别，路由只能基于原始文本做关键词匹配，无法处理"登录报错且被重复扣款"这种复合问题。意图识别是整个流水线的**信息提纯**步骤。

**设计决策：为什么 RAG 是"门控"而不是"必走"？**
`api/main.py:380-402` 的 `_should_use_knowledge` 会跳过寒暄类消息。对每条消息都检索知识库不仅浪费延迟，还会引入无关文档干扰回复质量。**按意图门控检索**是"意图驱动 RAG"的核心。

## 3. 模块地图与依赖方向

```text
api/main.py（入口，FastAPI lifespan 组装一切）
 ├── core/intent_recognizer.py     ← core/llm_utils.py
 ├── core/skill_loader.py          （无内部依赖）
 ├── agents/agent_orchestrator.py  ← core/intent_recognizer, agents/tools
 ├── memory/conversation_memory.py ← core/llm_utils
 ├── mcp/tool_manager.py           ← core/llm_utils
 ├── mcp/knowledge_base.py         （ChromaDB）
 ├── monitor/performance_monitor.py（读 orchestrator + tool_manager 的 stats，回写惩罚）
 └── evaluation/evaluator.py       ← orchestrator, intent_recognizer
```

注意两个反馈回路，它们是 EchoMind 与"一次性 demo"的分水岭：

1. **Monitor → Orchestrator**：`performance_monitor.py:238-240` 调用 `update_routing_penalties()`，把在线表现写回 `AgentStats.monitor_penalty`，`routing_score()` 随之降低，`_best_agent()` 自动绕开变差的 Agent。
2. **Evaluator → 基线**：`evaluator.py::_save_baseline` 把每次评测结果落盘，下次运行做回归检测。

## 4. 全局组件在 lifespan 中组装

`api/main.py:67-188` 用一个 `asynccontextmanager` 完成依赖注入：所有组件是模块级全局变量（`_orchestrator`、`_memory`、`_tool_manager`...），启动时构造、关闭时释放。这是 FastAPI 官方推荐的生命周期模式——不用全局单例类，也不用每次请求重新构造。

值得注意的细节：`KnowledgeBase` 被包装成 `Tool` 注册进 `MCPToolManager`（`api/main.py:142-157`），并带上 `cache_ttl=300`、`supports_rerank=True` 和一个 `knowledge_fallback` 降级函数。**知识库不是特殊公民，它只是工具框架里的一个普通工具**——这是消除特殊情况的典型手法。

## 5. 环境说明

- 项目自带 `.venv` 已损坏（指向 macOS 路径），课程 Lab 一律使用**系统 Python 3.12 + pytest**，不依赖虚拟环境。
- 所有 Lab 只重写**确定性逻辑**（打分、状态机、切片、哈希向量……），**不需要 LLM API Key、不需要 Redis/ChromaDB** 就能跑测试。
- 原项目测试可用以下命令验证环境：`python -m pytest tests/ -q`（需要已安装 anthropic/fastapi 等依赖）。

## 6. Lab：把流水线写下来

你要实现 `overview.py`：

1. `CHAT_FLOW` —— 六个阶段名组成的有序列表（就是上面表格第 1 列的六个字符串，顺序即执行顺序）。
2. `render_flow(stages=None)` —— 把阶段列表渲染成 `"a -> b -> c"` 格式；不传参数时渲染 `CHAT_FLOW`。

这个 Lab 不难，但它是后面所有章节的地图。写完之后，每当你实现一个模块，回到这张图确认它在哪个位置、上下游契约是什么。
