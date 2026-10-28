# 源码导读：MCP 工具框架

## 核心文件：`mcp/tool_manager.py`

### CircuitBreaker（:71-:106）

- `state` / `fail_count` 是两个简单的可变属性，初始为 CLOSED / 0。
- `allow()` 是唯一的出口闸门：CLOSED → True；OPEN → 检查 elapsed ≥ recovery_s → HALF_OPEN → True；HALF_OPEN → True（放行一次探测）。
- `record_success()`（:98-:99）无条件关闭闸：fail_count=0, state=CLOSED。
- `record_failure()`（:102-:106）累加计数，达阈值开闸并记录 opened_at。注意 **opened_at 在打开瞬间重置**——每次从 OPEN 回到 HALF_OPEN 后再失败，opened_at 会再次刷新。这是有意为之：让下一次 recovery 窗口从这次失败开始算。

### ToolResult + ToolStats（:40-:68）

ToolResult 是**纯数据载体**，所有字段都有默认值方便构造。ToolStats 是监控统计的中间层，被 PerformanceMonitor 消费。

### TTL 缓存 _cache（:393-:419）

- key 生成（:393-:395）：`json.dumps(params, sort_keys=True)` + rerank_top_k 参与，保证同一工具的同一参数组合产生相同 key。
- get（:397-:404）：命中即返回；过期时先删除再返回 None —— **惰性清理**，不维护后台任务。
- set（:406-:419）：满 5000 时删最早插入的 1/4（dict 保序，`list(cache)[:1250]`）。

### call 主流程（:157-:235）

```text
缓存命中? ─→ 直接返回 (cached=True)              (:176-:189)
熔断拒绝? ─→ fallback_result                     (:192-:194)
超时等待 handler...                               (:196-:208)   ← success 路径
asyncio.wait_for(handler, timeout=timeout_s)      (:202)
重试重排? ─→ LLM 重新排序                          (:212-:214)
写缓存                                           (:217-:218)
```

失败路径（:223-:235）：TimeoutError 或 Exception → breaker.record_failure() → fallback_result 或裸错误。两条路径都走 breaker——成功和失败都记入统计。

### _fallback_result（:237-:259）

三个分支：有 fallback → 调用它（支持 sync/async）→ 返回 {success=True, error=原始错误}；无 fallback → {success=False, error=原样}；fallback 自己也失败 → 双错误拼接。

### _validate_params（:425-:442）

两重校验：required 缺失 → ValueError("缺少必需参数")；声明了 type 但类型不符 → ValueError("参数 X 类型错误")。未声明的参数安全忽略——宽容设计。

## 关联文件：`agents/tools.py`

所有 Agent 工具集中定义在这里，每个都是确定性函数（没有 LLM 调用、没有网络请求）。它们通过 `get_tools()` 白名单暴露给对应的 Agent 实例——Agent 调不到白名单外的工具。**白名单是角色隔离的第一道防线**。Ch2 已覆盖路由逻辑决定"谁来执行"，本 Lab 覆盖"如何安全执行"。
