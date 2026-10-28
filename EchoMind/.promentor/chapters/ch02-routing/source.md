# 源码导读：多 Agent 路由与编排

## 核心文件：`agents/agent_orchestrator.py`

### 路由数据结构（:89-:171）

- `AgentStats`（:89-:109）：**性能路由的载体**。total/success/total_ms 由每次 `handle()` 更新（:206-:214），`monitor_penalty` 由 Ch6 的 Monitor 写入（:1104-:1114）。`routing_score()`（:105-:109）是唯一的评分出口——路由、监控、API stats 全用它。
- `RoutingDecision`（:156-:171）：frozen 语义的决策结果。`agent_types` property（:164-:166）= primary + supporting；`multi_agent`（:168-:170）驱动 run() 里的并行分支。
- `_INTENT_ROUTING`（:626-:639）：静态映射表，保留给 `_route`（:850-:866）；主链路已升级为 `_route_decision`。读它只为理解演进：静态表 → 打分制的动机。

### _route_decision（:868-:927）

```python
if req.urgency == UrgencyLevel.CRITICAL:          # :875 紧急通道，无条件短路
    return RoutingDecision(primary_agent=AgentType.ESCALATION, ..., confidence=1.0)

if req.intent in (ESCALATION, HUMAN_HANDOFF):     # :882 转人工通道
    return RoutingDecision(..., confidence=max(req.intent_confidence, 0.8))

scores = self._domain_scores(req)                 # :889 三信号打分
available_scores = {                              # :890-:894 过滤无实例的领域
    a: s for a, s in scores.items()
    if a == AgentType.GENERAL or self._pool.get(a)    # GENERAL 永远可用
}
ordered = sorted(available_scores.items(), key=..., reverse=True)   # :902
primary_agent, primary_score = ordered[0]         # :903

collaboration_targets = self._collaboration_targets(req)            # :905
supporting_agents = [t for t in collaboration_targets
                     if t != primary_agent and t in available_scores]  # :906-:910
if not supporting_agents:                         # :912-:919 阈值兜底
    supporting_agents = [a for a, s in ordered[1:]
                         if a != GENERAL and s >= 0.45 and s >= primary_score * 0.55]
```

注意 :893 的 `a == AgentType.GENERAL or` ——GENERAL 不需要池里有实例也可选？不，池里永远有（:662）。这行是让"过滤"只作用于领域 Agent，general 作为兜底不参与过滤。

### _domain_scores（:929-:987）

- :932-:936 初始分：general 0.1 底分。
- :938-:965 意图加分三段：general 系 +0.55、technical 系 +0.75、billing 系 +0.75。
- :967-:977 关键词：三个词表，`min(0.45, hits * 0.18)` / `min(0.35, hits * 0.12)` 封顶。
- :979-:985 实体：error_code→technical +0.2，amount→billing +0.15，order_id→general +0.1。
- :987 统一 `round(score, 3)`。

### _collaboration_targets（:1007-:1038）

复合问题检测：意图属于 technical 系**或**消息命中 technical 关键词 → 加入 TECHNICAL；billing 同理。:1037-:1038 `dict.fromkeys` 保序去重 + 过滤无实例类型。

### _needs_clarification（:1040-:1048）

三个条件缺一不可：`intent == OTHER`、`len(text) > 2`、`confidence < 0.5`。被 run()（:752-:766）消费：命中时直接构造澄清响应，routing_reason="低置信度 OTHER 意图，先澄清用户需求"。

### run 主流程（:737-:802）

- :745-:750 意图未识别时现场识别（API 层已识别则跳过——一次识别两处消费的契约在这里兑现）。
- :769-:771 `decision.multi_agent` → `run_parallel`。
- :777-:784 升级检查：Agent 主动 escalate、或 CRITICAL、或升级类意图 → escalated=True。

### run_parallel + ResponseComposer（:804-:846, :561-:610）

- :812 `asyncio.gather(*tasks, return_exceptions=True)` —— 单个 Agent 挂掉不拖垮整组。
- Composer :569-:574 单响应直接返回（不浪费一次 LLM 调用）；:604-:610 LLM 合并失败时确定性拼接兜底。

### _best_agent + _execute（:1050-:1081）

- :1058 `max(agents, key=lambda a: a.stats.routing_score())` —— 性能路由就这一行。
- :1075-:1079 专属 Agent 失败 → GeneralAgent 重试（ESCALATION 不降级：升级节点失败不能悄悄吞掉）。

## 关联文件：`agents/tools.py`

工具白名单按角色分组（:224-:292），`get_tools()` 合并 shared RAG 工具（agent_orchestrator.py:198-:203, :431-:434）。路由决定"谁来答"，白名单决定"它能用什么"——两层隔离。Ch3 细讲工具框架。
