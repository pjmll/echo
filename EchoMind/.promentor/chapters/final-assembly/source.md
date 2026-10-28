# 源码导读：组装 Mini EchoMind

## 系统集成要点

### 1. 模块依赖关系

```text
mini_echomind.py
├── intent_tools (Ch1)      # 意图识别
├── routing (Ch2)           # 路由决策
├── mcp_tools (Ch3)         # 工具框架
├── rag_tools (Ch4)         # RAG 优化
├── memory_tools (Ch5)      # 记忆管理
└── monitor_tools (Ch6)     # 监控降权
```

所有模块都是纯标准库实现，无外部依赖。Mini EchoMind 通过组合这些模块实现完整功能。

### 2. 核心类：MiniEchoMind

```python
class MiniEchoMind:
    def __init__(self):
        # Ch3: 工具框架
        self.breaker = mcp_tools.CircuitBreaker(failure_threshold=3, recovery_s=60.0)
        self.cache = mcp_tools.TTLToolCache(maxsize=100)
        
        # Ch5: 记忆管理
        self.working_memory = {}  # {key: List[Message]}
        self.summaries = {}       # {key: str}
        
        # Ch6: 监控
        self.agent_stats = {}     # {agent: {total, success, total_ms, history}}
        self.penalties = {}       # {agent: float}
        
        # Ch2: 路由
        self.agents = ["general", "technical", "billing"]
```

### 3. 请求处理流程

`handle_request` 方法是系统的入口，按顺序调用各章组件：

1. **意图识别**（Ch1）：`intent_tools.pattern_recognize(message)` + `intent_tools.vote(...)`
2. **路由决策**（Ch2）：`routing.domain_scores(...)` + `routing.route_decision(...)`
3. **记忆检索**（Ch5）：`memory_tools.wm_key(...)` + 从 `self.working_memory` 读取
4. **上下文压缩**（Ch5）：`memory_tools.compress_partition(...)` + `memory_tools.merge_summary(...)`
5. **知识检索**（Ch3+Ch4）：`mcp_tools.validate_params(...)` + `rag_tools.merge_dedupe(...)` + `rag_tools.apply_rerank(...)`
6. **上下文格式化**（Ch5）：`memory_tools.format_context(...)`
7. **LLM 生成**：mock 函数返回固定回复
8. **监控采集**（Ch6）：`monitor_tools.z_score(...)` + `monitor_tools.routing_penalty(...)`

### 4. 反馈闭环实现

```python
def update_penalties(self):
    """Monitor → Orchestrator 反馈闭环"""
    for agent, stats in self.agent_stats.items():
        sr = stats["success"] / stats["total"] if stats["total"] else 1.0
        ms = stats["total_ms"] / stats["total"] if stats["total"] else 0.0
        
        # Ch6: 计算降权
        penalty = monitor_tools.routing_penalty(sr, ms)
        self.penalties[agent] = penalty
    
    # Ch2: 路由时使用 penalty
    # routing_score 会乘以 (1.0 - penalty)
```

### 5. 降级路径

- **工具失败**：`self.breaker.record_failure()` → 熔断器打开 → 后续调用返回 fallback
- **Agent 失败**：`routing_penalty` 增加 → `routing_score` 降低 → 选择其他 Agent
- **LLM 失败**：mock 函数返回固定字符串 "抱歉，系统暂时无法处理您的请求"

### 6. 统计信息

`get_stats()` 返回系统运行状态：

```python
{
    "agents": {
        "general": {"total": 10, "success": 9, "penalty": 0.1},
        "technical": {"total": 5, "success": 5, "penalty": 0.0},
    },
    "cache_hits": 3,
    "breaker_state": "closed",
    "working_memory_size": 2,
}
```

用于监控和调试。
