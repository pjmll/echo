# 源码导读：RAG 检索优化

## 核心文件：`mcp/knowledge_base.py`

### _chunk_text（:161-:184）

- 按句子切分（:169）：`text.replace("\n", "。").split("。")` ——换行符和句号同等对待作为句子边界。
- 贪心拼接（:170-:179）：遍历句子，当前 chunk + 新句子超过 `chunk_size` 时 flush 当前 chunk，新句子成为下一个 chunk 的起点。
- **关键 invariant**：每个 chunk 以"。"结尾（除了可能的最后一个不足 chunk_size 的 chunk）。空句子被跳过（:172-:173）。
- 早返回（:163-:164）：短文本直接 `[text]`（strip 后非空），零次循环。

### distance_to_score（:125）

在 `search()` 方法中：`round(1.0 - dist, 4)`。ChromaDB 返回的 distances 数组对应 documents 数组，一一对齐。

## 核心文件：`mcp/tool_manager.py`

### search_with_rewrite 合并去重（:337-:44）

```python
seen, merged = set(), []
for r in results:
    if isinstance(r, ToolResult) and r.success and isinstance(r.data, list):
        for item in r.data:
            key = hashlib.md5(str(item).encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                merged.append(item)
```

- 外层过滤（:339）：只处理 `ToolResult` 且成功且 data 是 list——其他结果静默忽略。
- `str(item)` 泛化：无论 item 是 dict 还是 str 都能生成一致字符串。
- md5 做集合成员：比存原始字符串省内存。

### apply_rerank 核心（:384-:386）

```python
order = json.loads(raw[s:e])                    # LLM 产出索引列表
reranked = [items[i] for i in order if 0 <= i < len(items)]
return reranked[:top_k]
```

- 索引合法性过滤（:385）：`0 <= i < len(items)` ——LLM 可能输出越界值。
- top_k 截断（:386）：即使 LLM 返回了全部排序，也只取前 K 个。

### _rerank 入口（:355-:389）

- 提前返回（:362）：`len(items) <= top_k` → 直接返回 items，不耗 LLM token。
- prompt 构造（:366-:374）：每个 item 序列化到前 200 字符（`:200`）防 prompt 爆炸。
- 降级路径（:387-:389）：解析失败 → warn + 返回 `items[:top_k]`。
