# Ch 3: MCP 工具框架

本章学什么：**当 Agent 开始调用工具，你就从"写业务"变成了"写基础设施"**。工具会超时、会挂、会被重复调用、会收到 LLM 编造的参数——MCPToolManager 用一条固定的执行链把这四类风险全部结构化。

难度：mid。没有烧脑算法，但每一个组件都是生产系统的标配模式，值得逐行看懂。

## 1. 一次工具调用的完整执行链

`MCPToolManager.call()`（mcp/tool_manager.py:157-:235）是所有工具调用的唯一入口：

```text
缓存检查 → 熔断检查 → 参数校验 → 执行（含超时）→ 可选重排 → 缓存写入
   ↓           ↓           ↓            ↓
 命中即返回   熔断即降级   非法即报错   失败即降级+记失败
```

**设计决策：顺序为什么是这样？**

- **缓存在最前**：命中缓存的请求连熔断器都不该惊动——它是免费的。
- **熔断在参数校验前**：熔断器保护的是下游依赖，参数错误是调用方的锅，两者不该互相污染统计。注意 :192-:194：熔断拒绝时也走 `_fallback_result`，调用方拿到的是降级数据而不是裸异常。
- **缓存写入在最后**（:217-:218）：写入的是**重排后**的最终结果。如果缓存原始结果，下次命中就会跳过重排——缓存的位置决定了它缓存什么。

## 2. 三态熔断器 CircuitBreaker（:71-:106）

```text
CLOSED ──连续失败 >= threshold──→ OPEN ──静默 recovery_s 秒──→ HALF_OPEN
   ↑                                                          │
   └────────────探测成功──────────────────────────────────────┘
                探测失败 → 回到 OPEN（重置 opened_at）
```

三个状态各司其职：
- **CLOSED**：放行一切，只记账。
- **OPEN**：拒绝一切（`allow()` 返回 False），给下游喘息时间。这是"防雪崩"的关键——依赖挂了还拼命打，只会把连接池和线程全部拖死。
- **HALF_OPEN**：`allow()` 里**惰性转换**（:91-:93）——不需要后台定时器，检查 `time.monotonic() - opened_at >= recovery_s` 时顺手把状态改成 HALF_OPEN 并放行一次探测。

`record_success` 无条件回到 CLOSED 并清零计数；`record_failure` 累加，达阈值开闸。

**为什么用连续失败而不是失败率？** 连续失败对"依赖刚刚挂掉"这个事件反应最快。失败率需要窗口和最小样本量，对突发故障迟钝。工具调用的场景里，宁可反应过度（短暂误熔断，recovery_s 后自动探测恢复），不可反应迟钝。

## 3. TTL 缓存（:393-:419）

```python
self._cache: Dict[str, tuple] = {}   # key → (data, expire_at, reranked)
```

- key = `name + md5(params + rerank_top_k)`（:393-:395）。**rerank_top_k 参与 key**：同一查询 top_k=3 和 top_k=5 是不同缓存条目。
- 读取时惰性过期（:397-:404）：过期条目顺手删除，不需要后台清理任务。
- 容量控制（:415-:418）：达到 5000 条时删掉**插入序最早的 1/4**。Python dict 保序，`list(cache)[:1250]` 就是最老的 1250 条。这是 FIFO 驱逐，不是 LRU——没有维护访问序的开销，对工具缓存足够（热点数据反正会被 TTL 内命中）。

## 4. 参数校验 `_validate_params`（:425-:442）

LLM 生成工具参数，就一定会编造参数：缺必填、类型错、多传不存在的字段。校验依据工具注册时声明的 JSON Schema：

```python
_TYPE_MAP = {"string": str, "number": (int, float), "integer": int,
             "boolean": bool, "array": list, "object": dict}
```

两件事：required 缺失 → ValueError；properties 里声明了 type 且实参类型不符 → ValueError。**未声明的参数直接忽略**——宽容接收，严格校验已知字段。

注意 Agent 侧还有一层更严的校验（agent_orchestrator.py:350-:366 `_validate_tool_input`），`additionalProperties: False` 时会拒绝未知字段。两层校验面向不同威胁：工具层防"参数格式坏"，Agent 层防"LLM 编造字段"。

## 5. 降级 fallback（:237-:259）

工具注册时可以带一个 `fallback` 函数。失败路径全部汇入 `_fallback_result`：

- 有 fallback → 调用它，返回 `ToolResult(success=True, data=降级数据, error=原始错误)`。**success=True 但 error 非空**——降级数据可用，但错误被保留用于观测。
- 无 fallback → `success=False`，错误原样上抛给调用方。
- fallback 自己也可能挂（:257-:259）→ 双错误拼接。

看 api/main.py:132-:140 的实际用法：知识库挂了，返回一条"知识库暂时不可用，请稍后重试或转人工"的文档——Agent 拿到它仍能生成一条诚实的回复，而不是对着空结果编造。

## 6. 同步工具的异步适配（:261-:278）

```python
if inspect.iscoroutinefunction(tool.handler):
    return await tool.handler(params, context)
result = await asyncio.to_thread(tool.handler, params, context)
```

ChromaDB 客户端是同步的，直接 await 不了；扔进线程池又不阻塞事件循环。`asyncio.to_thread` 是同步库进入 asyncio 世界的标准桥。所有执行都包在 `asyncio.wait_for(..., timeout_s)` 里（:202）——超时也是失败，计入熔断统计。

## 7. Lab：重写工具框架的确定性内核

实现 `mcp_tools.py`（纯标准库，可用 time/hashlib/json）：

- `CircuitState` —— 枚举，值为 "closed"/"open"/"half_open"
- `CircuitBreaker` —— §2 的三态状态机
- `TTLToolCache` —— §3 的 TTL 缓存 + 容量驱逐
- `ToolResult` —— §5 的结果容器（dataclass）
- `validate_params(schema, params)` —— §4 的 JSON Schema 校验

查询改写/重排（LLM 环节）在 Ch4 覆盖；`call()` 的完整链条组装是 Final 章的挑战题。
