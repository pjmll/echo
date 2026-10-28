# 源码导读：系统全景

本章只需读懂两处：`/chat` 主链路和 lifespan 组装。其余模块留到对应章节细读。

## 核心文件：`api/main.py`

### lifespan 组装（:67-:188）

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _orchestrator, _memory, _tool_manager, _monitor, _evaluator, _skill_manager
    ...
```

关键顺序（:86-:180）：
1. `IntentRecognizer`（:86）—— 单独构造一份给 Evaluator 用；Orchestrator 内部还会构造自己的实例。
2. `SkillManager.load()`（:94-:98）—— 启动时扫描 skills/ 目录，之后每次 LLM 调用动态注入。
3. `AgentOrchestrator`（:101）—— 持有 skill_manager。
4. `MemoryManager`（:109）—— Redis + ChromaDB 连接在这里建立。
5. `KnowledgeBase` 包装成 `Tool` 注册（:125-:157）—— **注意 :154-:156**：`cache_ttl=300.0, supports_rerank=True, fallback=knowledge_fallback`。知识库从此和任何工具同构。
6. `PerformanceMonitor.start()`（:170）—— 后台采集任务启动。
7. `EndToEndEvaluator`（:173）。

**为什么用 lifespan 而不是模块级直接构造？** 组件创建涉及网络连接（Redis/ChromaDB），模块导入时做这些事会让测试和 CLI 模式无法运行。lifespan 把"组装"推迟到应用真正启动时。

### /chat 主链路（:272-:340）

这是全课程的地图，逐段对照：

```python
# 1. 读取记忆上下文                                        (:287)
mem_ctx = await _memory.get_context(req.user_id, conv_id, query=req.message)

# 2. 构建编排请求（含对话历史，用于意图识别上下文）          (:290-:309)
intent_result = await _orchestrator.recognize_intent(req.message, history=history)
orch_req = OrcReq(..., entities=..., intent=..., intent_group=..., urgency=..., intent_confidence=...)

# 3. 执行                                                  (:312)
result = await _orchestrator.run(orch_req)

# 4. 写入记忆                                              (:315-:316)
await _memory.add_message(...)   # user + assistant 两条

# 5. 异步更新用户画像（不阻塞响应）                          (:319)
asyncio.create_task(_memory.update_profile(req.user_id, conv_id))
```

**值得注意的两个决策：**

- `recognize_intent` 在 API 层**先于** `orchestrator.run` 调用（:295），识别结果通过 `OrcReq` 传入。为什么？因为 API 层需要 intent 做 RAG 门控（`_should_use_knowledge`），而 orchestrator 的 `run()` 遇到 `req.intent is not None` 会跳过内部识别（agent_orchestrator.py:745）。**一次识别，两处消费**。
- 画像更新用 `asyncio.create_task` 扔进后台（:319）——画像是 LLM 提炼的慢操作，不能阻塞用户响应。

### RAG 门控（:380-:402）

```python
def _should_use_knowledge(message: str, intent=None) -> bool:
    intent_value = getattr(intent, "value", intent)
    if intent_value in {"greeting", "feedback", "escalation", "human_handoff", "other"}:
        return False   # 寒暄和升级类不检索
    if intent_value in {"query", "request", "technical", ...}:
        return True    # 业务类直接检索
    ...                # 无意图时退化为关键词/长度启发式
```

三层判断：意图黑名单 → 意图白名单 → 关键词兜底。**意图是首选信号，关键词只是降级**。

## 参考文件：`README.md:124-:137`

运行时架构的文字版，与上面代码一一对应。Lab 中 `CHAT_FLOW` 的六个阶段名就是从这里的主链路抽象出来的。
