# Final: 组装 Mini EchoMind

本章学什么：**把前 6 章的组件拼成一个可运行的最小系统**。

难度：hard。不是新知识点，而是系统集成——理解各组件如何协作、数据如何流动、错误如何传播。

## 1. 系统全景回顾

```text
用户请求
   ↓
┌─────────────────────────────────────────────────────────┐
│  Ch1: 意图识别                                           │
│  - 三路融合投票（LLM + Embedding + Pattern）              │
│  - 实体提取、紧急度判断                                   │
└─────────────────────────────────────────────────────────┘
   ↓ intent, entities, urgency
┌─────────────────────────────────────────────────────────┐
│  Ch2: 多 Agent 路由                                      │
│  - domain_scores 计算                                    │
│  - route_decision 选择 primary/supporting                │
│  - routing_score 性能加权                                │
└─────────────────────────────────────────────────────────┘
   ↓ primary_agent, supporting_agents
┌─────────────────────────────────────────────────────────┐
│  Ch5: 记忆与上下文构建                                   │
│  - wm_key 生成 Redis key                                 │
│  - compress_partition 分区压缩                           │
│  - format_context 格式化上下文                           │
└─────────────────────────────────────────────────────────┘
   ↓ context_string
┌─────────────────────────────────────────────────────────┐
│  Ch3: MCP 工具框架                                       │
│  - CircuitBreaker 熔断保护                               │
│  - TTLToolCache 缓存加速                                 │
│  - validate_params 参数校验                              │
└─────────────────────────────────────────────────────────┘
   ↓ tool_results
┌─────────────────────────────────────────────────────────┐
│  Ch4: RAG 检索优化                                       │
│  - chunk_text 文本分块                                   │
│  - merge_dedupe 去重合并                                 │
│  - apply_rerank LLM 重排                                 │
│  - distance_to_score 相似度转换                          │
└─────────────────────────────────────────────────────────┘
   ↓ knowledge_context
┌─────────────────────────────────────────────────────────┐
│  Ch6: 监控与路由降权                                     │
│  - z_score 异常检测                                      │
│  - routing_penalty 降权系数                              │
│  - check_threshold 阈值告警                              │
└─────────────────────────────────────────────────────────┘
   ↓ penalties (feedback to Ch2)
┌─────────────────────────────────────────────────────────┐
│  LLM 生成回复                                            │
└─────────────────────────────────────────────────────────┘
   ↓
用户响应
```

## 2. 数据流：一次请求的完整生命周期

```python
async def handle_request(user_id: str, conv_id: str, message: str) -> str:
    # 1. 意图识别 (Ch1)
    intent_result = await intent_recognizer.recognize(message)
    intent = intent_result["intent"]
    entities = intent_result["entities"]
    urgency = intent_result["urgency"]
    
    # 2. 路由决策 (Ch2)
    scores = domain_scores(intent, message, entities)
    available = get_available_agents()
    decision = route_decision(intent, urgency, 0.9, scores, available, [])
    primary_agent = decision["primary"]
    
    # 3. 记忆检索 (Ch5)
    key = wm_key(user_id, conv_id)
    history = await redis.get(key)  # List[Message]
    summary = await redis.get(f"summary:{user_id}:{conv_id}")
    
    # 4. 上下文压缩 (Ch5)
    to_compress, to_keep = compress_partition(history, keep_recent=5)
    if to_compress:
        new_summary = await generate_summary(to_compress)  # LLM
        summary = merge_summary(summary, new_summary)
        await redis.set(key, to_keep)  # 更新工作记忆
    
    # 5. 知识检索 (Ch3 + Ch4)
    if should_use_knowledge(intent):
        tool_result = await tool_manager.call(
            "knowledge_search",
            {"query": message, "top_k": 5},
            rerank_top_k=3
        )
        knowledge = format_knowledge(tool_result.data)
    else:
        knowledge = ""
    
    # 6. 上下文格式化 (Ch5)
    context = format_context(to_keep, summary, knowledge)
    
    # 7. LLM 生成回复
    response = await llm.generate(
        system_prompt=get_agent_prompt(primary_agent),
        context=context,
        user_message=message
    )
    
    # 8. 监控采集 (Ch6)
    monitor.record_agent_stats(primary_agent, success=True, latency_ms=...)
    
    # 9. 保存对话
    await redis.append(key, Message("user", message))
    await redis.append(key, Message("assistant", response))
    
    return response
```

## 3. 反馈闭环：Monitor → Orchestrator

```python
# Monitor 定期采集 (每 10 秒)
async def monitor_loop():
    while True:
        agent_stats = orchestrator.get_stats()
        penalties = {}
        
        for agent_key, stats in agent_stats.items():
            sr = stats["success_rate"]
            ms = stats["avg_ms"]
            
            # 异常检测 (Ch6)
            z = z_score(stats["history"], sr)
            if z and z > 2.5:
                logger.warning(f"Agent {agent_key} 异常: z={z}")
            
            # 计算降权 (Ch6)
            penalties[agent_key] = routing_penalty(sr, ms)
        
        # 写回 Orchestrator (Ch2)
        orchestrator.update_routing_penalties(penalties)
        
        await asyncio.sleep(10)

# Orchestrator 使用 penalty 调整路由 (Ch2)
def routing_score(total, success, total_ms, penalty=0.0):
    sr = success / total if total else 1.0
    avg_ms = total_ms / total if total else 0.0
    latency_score = 1.0 / (1.0 + avg_ms / 1000.0)
    base = sr * 0.7 + latency_score * 0.3
    return base * (1.0 - penalty)  # penalty 降低评分
```

## 4. 错误传播与降级

```text
工具调用失败 (Ch3)
   ↓
CircuitBreaker.record_failure()
   ↓
连续失败 >= threshold → 熔断器打开
   ↓
后续调用 allow() == False → _fallback_result()
   ↓
返回降级数据 (success=True, error=原始错误)
   ↓
Agent 拿到降级数据 → 生成诚实回复 ("知识库暂时不可用")
   ↓
Monitor 采集到 success_rate 下降 (Ch6)
   ↓
routing_penalty 增加 → routing_score 降低 (Ch2)
   ↓
_best_agent() 选择其他 Agent
   ↓
熔断器 recovery_s 后 → HALF_OPEN → 探测成功 → CLOSED
   ↓
success_rate 回升 → penalty 下降 → 重新被选中
```

**关键设计**：每一层都有降级路径，没有单点故障。工具挂了 → fallback；Agent 挂了 → 路由到其他 Agent；LLM 挂了 → 返回固定回复。

## 5. Lab：组装 Mini EchoMind

实现 `mini_echomind.py`（纯标准库 + 前 6 章的模块）：

- `MiniEchoMind` 类 —— 集成所有组件
- `handle_request(user_id, conv_id, message)` —— 完整请求处理流程
- `get_stats()` —— 返回系统统计信息

**要求**：
1. 导入前 6 章的模块（intent_tools, routing, mcp_tools, rag_tools, memory_tools, monitor_tools）
2. 实现简化的 Orchestrator（路由选择）
3. 实现简化的 ToolManager（工具调用 + 熔断 + 缓存）
4. 实现简化的 Memory（工作记忆 + 摘要）
5. 实现简化的 Monitor（异常检测 + 降权）
6. 所有 LLM 调用用 mock 函数替代（返回固定字符串）

**挑战题**（不计入测试）：
- 实现完整的 `search_with_rewrite` 链路（查询改写 → 并行召回 → 去重 → 重排）
- 实现 Redis 持久化（用 dict 模拟）
- 实现 Prometheus 指标导出

## 6. 可运行入口

`.promentor/main.py` 提供了一个 CLI 入口，可以直接运行 Mini EchoMind：

```bash
cd .promentor
python main.py
```

进入交互模式后，输入消息即可看到完整的处理流程：意图识别 → 路由选择 → 知识检索 → 上下文构建 → 回复生成。

输入 `exit` 或 `quit` 退出。
