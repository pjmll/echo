# Ch 4: RAG 检索优化

本章学什么：**当 LLM 召回的文档不够全、排得不好时，你在工具框架里加了哪几道保险？**

难度：easy-mid。没有复杂算法，但每一个步骤都解决了一个真实的 RAG 痛点。

## 1. 为什么需要检索优化链路

单一语义检索有两个经典问题：

- **召回不全**：用户问"退款流程"，知识库里有"退款政策"和"如何申请退款"两篇文档，但一条查询可能只命中其中一篇。
- **排序不准**：向量相似度分数（余弦距离）不等于"对用户有用"——最相关的文档不一定排在第一。

EchoMind 在 `MCPToolManager.search_with_rewrite()`（`mcp/tool_manager.py:312-351`）中用一条固定链路解决这两类问题：

```text
查询改写 → 并行召回 → 去重合并 → LLM 重排 → Top-K
   ↓           ↓          ↓          ↓         ↓
 多角度子查询  每路取 recall_k  按内容哈希  按相关性打分  截断返回
```

## 2. 文本分块 chunk_text（:161-:184）

RAG 的基石：长文档不能整体存进向量库（embedding 质量会稀释），也不能逐句存（碎片太多）。

```python
def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
    sentences = text.replace("\n", "。").split("。")
    for sent in sentences:
        if len(current) + len(sent) + 1 > chunk_size:
            chunks.append(current); current = sent
        else:
            current = f"{current}。{sent}" if current else sent
```

**设计决策：为什么要先按句号切再拼接？**

直接按字符数硬切会把句子劈成两半——"请在 7 天" + "内可以申请"——后续 embedding 无法理解破碎的语义。**按句号/分隔符边界切**保证每个 chunk 都是完整句子。`replace("\n", "。")` 把换行也当成句子边界，因为中文段落间的逻辑跳跃和句号类似。

**边界处理**：空文本→`[]`；短于 chunk_size→`[text]`；最后一个不足 chunk_size 的部分单独成 chunk。

## 3. 去重合并 merge_dedupe（:337-:44）

多个子查询可能召回同一份文档。例如"退款政策"和"如何申请退款"都会匹配到"退款政策"这篇文档。

```python
seen, merged = set(), []
for r in results:
    for item in r.data:
        key = hashlib.md5(str(item).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            merged.append(item)
```

**为什么不直接用 content 字符串做集合成员？** `str(item)` 是安全的泛化——item 可能是 dict（{"title": ..., "content": ...}）也可能是纯字符串。`md5` 避免存储大字符串到 `seen` 集合中节省内存。

**保持插入序**：`dict.fromkeys` / `if key not in seen then append` 保证第一次出现的顺序被保留——这通常是语义检索的自然排序，比打乱后再排序更合理。

## 4. 结果重排 apply_rerank（:355-:389）

LLM 重排是精度提升最大的环节：

```python
order: List[int] = json.loads(raw[s:e])       # [3, 0, 1, 2, 4]
reranked = [items[i] for i in order if 0 <= i < len(items)]
return reranked[:top_k]
```

**关键保护**：`0 <= i < len(items)` —— LLM 可能生成越界索引（比如编号 0-4 但写了个 5），过滤而非崩溃。**提前返回**（:362）：如果 `len(items) <= top_k`，不需要重排直接返回——省一次 LLM 调用。

**失败路径**（:387-:389）：JSON 解析失败 → 记录 warning → 返回原始顺序的前 top_k 项。降级是可预测的：从"最优排序"退化到"检索排序"。

## 5. 距离转相似度 distance_to_score（:125）

ChromaDB 返回的是距离（distance），值越小越相关。上层需要的是相似度（score），值越大越相关。

```python
"score": round(1.0 - dist, 4)
```

**为什么是 `1.0 - dist` 而不是其他线性变换？** ChromaDB 默认使用余弦距离，范围是 [0, 2]（0=完全相同，2=完全相反）。但对于高质量 embedding，实际距离通常在 [0, 1] 之间。`1.0 - dist` 是最直观的翻转——不用引入额外的归一化参数。

**为什么 `round(..., 4)`**？减少传输和展示的浮点噪音，三位小数足够区分度，第四位用于精细排序。这也是为了缓存 key 稳定性——同样的浮点运算产生同样的字符串表示。

## 6. Lab：提取检索优化的确定性内核

实现 `rag_tools.py`（纯标准库）：

- `chunk_text(text, chunk_size=500)` — §2 的句子边界切片
- `merge_dedupe(results, max_items)` — §3 的去重合并
- `apply_rerank(order, items, top_k)` — §4 的重排索引应用
- `distance_to_score(dist)` — §5 的距离转相似度

查询改写（LLM 环节）在 Ch5 覆盖；`search_with_rewrite()` 的完整组装是 Final 章的挑战题。
