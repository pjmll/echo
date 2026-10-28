# Ch 2: 多 Agent 路由与编排

本章学什么：**多个专业 Agent 摆在面前，一次请求该给谁？** 这是 EchoMind 简历上最重的一句话——"路由驱动的多 Agent 编排"。路由做错，后面所有 LLM 能力都白费。

难度：hard。核心是一个打分-排序-协作的决策系统，外加两个容易被忽略的机制：性能路由和降级。

## 1. Agent 池与三层路由

Orchestrator 持有 `_pool: Dict[AgentType, List[BaseAgent]]`——每种类型可以有**多个实例**。路由分三层：

1. **意图路由**：`IntentCategory → AgentType` 静态映射表（`_INTENT_ROUTING`，agent_orchestrator.py:626-639），technical_login→TECHNICAL、refund→BILLING……
2. **性能路由**：同类型多实例时，选 `routing_score()` 最高的（`_best_agent`，:1050-:1058）
3. **降级路由**：专属 Agent 不可用或执行失败 → 落到 GeneralAgent（:863-:866, :1075-:1079）

**设计决策：为什么 General 是万能兜底？** 通用客服 Agent 的职责本来就是"分诊与首轮接待"（profile.mission），它见过所有类型的问题。降级到它不是妥协，而是回到分诊台重新走一遍。

## 2. 静态映射不够用：`_route_decision` 的打分制

`_route`（:850-:866）那个静态映射表在代码里还在，但主链路实际走的是 `_route_decision`（:868-:927）。为什么升级？因为静态映射表达不了三件事：

1. **复合问题**："登录报错且被重复扣款"同时属于 technical 和 billing，映射表只能二选一。
2. **主次结构**：复合问题需要"主 Agent 负责结论、辅 Agent 补充"，而不是简单拼接。
3. **置信度**：路由决策本身要携带置信度供 API 透出、供监控归因。

`_route_decision` 的决策顺序（注意前置短路的顺序性）：

```python
# 1. CRITICAL 紧急度 → 直接升级，跳过一切打分     (:875-:880)
# 2. escalation / human_handoff 意图 → 直接升级   (:882-:887)
# 3. 打分排序 → primary                            (:889-:903)
# 4. 协作 Agent → supporting                       (:905-:919)
```

**为什么升级判断在打分之前？** 用户喊"转人工"时，任何领域打分都是在拖延。紧急通道必须是无条件的短路。

## 3. 领域打分 `_domain_scores`（:929-:987）

给 technical/billing/general 三个领域各打一个分，信号来自三处：

```python
scores = {GENERAL: 0.1, TECHNICAL: 0.0, BILLING: 0.0}   # general 有 0.1 底分

# 信号 1：意图（最强）—— technical 系意图 → TECHNICAL +0.75
# 信号 2：关键词 —— 每命中一个 +0.18，封顶 0.45
# 信号 3：实体 —— error_code → TECHNICAL +0.2；amount → BILLING +0.15
```

三个细节值得咀嚼：

- **general 的 0.1 底分**：让"什么都不像"的请求自然落到 general，不需要显式的 else 分支。消除特殊情况。
- **关键词封顶 0.45**：防止关键词堆砌（"崩溃崩溃崩溃"）压过高置信意图。意图 0.75 > 封顶 0.45，**信号强度排序是刻意的：意图 > 关键词**。
- **实体是独立信号**：intent 说 billing、消息里出现 401 错误码 → technical 也会得分。这是复合问题能被检测出来的原因。

## 4. 主/辅 Agent：`supporting` 的两条来源（:905-:919）

```python
collaboration_targets = self._collaboration_targets(req)   # 来源 1：显式协作检测
supporting_agents = [t for t in collaboration_targets
                     if t != primary_agent and t in available_scores]

if not supporting_agents:                                   # 来源 2：分数阈值兜底
    supporting_agents = [
        a for a, s in ordered[1:]
        if a != GENERAL and s >= 0.45 and s >= primary_score * 0.55
    ]
```

来源 2 的两个阈值是防误伤的护栏：`s >= 0.45`（绝对分够高）且 `s >= primary * 0.55`（相对主 Agent 不太弱）。只有非 general 的领域 Agent 才能当辅助——general 是兜底，不是协作者。

有 supporting 时走 `run_parallel`（:804-:846）：`asyncio.gather` 并行执行所有 Agent，再由 `ResponseComposer`（:561-:610）合并。Composer 的降级设计同样精妙：LLM 合并失败时退回**确定性拼接**（主 Agent 原文 + "补充说明：" + 辅 Agent 原文），永远不丢结论。

## 5. 性能路由：`routing_score`（:105-:109）

```python
latency_score = 1.0 / (1.0 + self.avg_ms / 1000)
base_score = self.success_rate * 0.7 + latency_score * 0.3
return base_score * max(0.0, 1.0 - self.monitor_penalty)
```

三个设计决策：

- **成功率权重 0.7 > 延迟权重 0.3**：答对比答快重要。
- **延迟用 `1/(1+x)` 而不是线性归一**：无界延迟映射到 (0,1]，不需要知道"最慢是多少"。100ms→0.91，1000ms→0.5，10000ms→0.09——平滑衰减，无参数可调错。
- **monitor_penalty 是乘法项**：Ch6 的 Monitor 发现某 Agent 在线表现恶化时写入 penalty，分数被按比例削减。新 Agent（total=0）的 success_rate 定义为 1.0——**没被证明差之前，先给机会**。

## 6. 澄清短路：`_needs_clarification`（:1040-:1048）

低置信度的 `other` 意图（confidence < 0.5 且消息长度 > 2）不走路由，直接返回一句澄清追问。为什么长度 ≤ 2 豁免？"嗯"、"？"这种超短消息追问也没意义，交给 general 兜底更自然。

**路由系统的最高原则：不确定时，问；而不是猜。**

## 7. Lab：重写路由决策内核

实现 `routing.py`（纯标准库）：

- `domain_scores(intent, message, entities=None)` —— §3 的三信号打分
- `needs_clarification(intent, confidence, message)` —— §6
- `routing_score(total, success, total_ms, penalty=0.0)` —— §5
- `best_agent(agents)` —— 按 routing_score 选最优实例（§1 性能路由）
- `route_decision(intent, urgency, confidence, scores, available, collaboration_targets)` —— §2+§4 的完整决策，返回 `{"primary", "supporting", "reason", "confidence"}`

LLM 执行环节（`BaseAgent._call_llm` 的 tool_use 循环）不在 Lab 内——它是 I/O 密集逻辑，Ch3 会覆盖它的工具框架部分。
