# Ch 1: 三路融合意图识别

本章学什么：**如何把"用户到底想干什么"从一个模糊的自然语言问题变成一个带置信度的结构化决策**。这是整条流水线的信息提纯步骤，Ch2 的路由、RAG 门控、评测全部消费它的输出。

难度：hard。难点不在单个算法，而在于**三个不完美的信号源如何合成一个可信赖的决策**。

## 1. 为什么是三路，而不是一路 LLM

单用 LLM 做意图识别有三个问题：延迟高（每次 300ms+）、成本高、偶发失败（网络/限流）时整个系统失明。EchoMind 的答案是三路融合：

| 路 | 权重 | 特点 | 失败模式 |
|----|------|------|---------|
| LLM Few-shot 语义理解 | 70% | 理解复杂语义和上下文，主力 | 慢、贵、会挂 |
| Embedding 向量相似度 | 20% | 快速匹配常见表达 | 对新颖表达弱 |
| 关键词模式匹配 | 10% | 零延迟、永不失败 | 无语义理解 |

三路**并行**调用（`asyncio.gather`），LLM 挂了还有两路兜底。这是"消除特殊情况"的第一个例子：不存在"LLM 失败怎么办"的 if/else 补丁，投票机制天然处理了它。

## 2. 加权投票 `_vote`（intent_recognizer.py:338-371）

核心是一个按类别累加的打分循环：

```python
weights = [(llm, 0.7), (emb, 0.2), (pat, 0.1)]
scores: Dict[IntentCategory, float] = {}
for result, w in weights:
    cat  = result.get("intent", IntentCategory.OTHER)
    conf = result.get("confidence", 0.0)
    scores[cat] = scores.get(cat, 0.0) + w * conf
best = max(scores, key=scores.get)
```

**设计决策：为什么是加权累加而不是多数投票？**
多数投票丢失置信度信息。LLM 说 refund(0.95)、Embedding 说 billing(0.4)、Pattern 说 refund(0.5)——多数投票是 refund，但如果 LLM 只有 0.3 的把握呢？加权累加让高置信度信号有更大话语权。

投票之后还有两个精妙的后处理：

1. **细粒度修正**（:366-:368）：如果加权结果是宽泛大类（如 `billing`），但模式匹配命中了高置信的细粒度意图（如 `refund`，conf ≥ 0.5）且加权分不足 0.8，就用细粒度意图覆盖。原因：LLM 倾向输出大类，而业务需要 `refund`/`invoice` 这种可以直接路由的细分意图。
2. **阈值降级**（:369-:370）：融合分 < 0.5 → 直接返回 `other`，交给 Ch2 的澄清逻辑。**宁可承认不知道，不可错误地自信**。

LLM 失败时（`llm["failed"] == True`）走独立分支（:345-:350）：依次尝试 Embedding → Pattern → other。

## 3. 关键词模式匹配 `_pattern_recognize`（:304-:334）

两级模式表：`specific_patterns`（细粒度业务意图）和 `generic_patterns`(大类)。**先查 specific，命中即返回；未命中才查 generic**。

打分公式（`_best_pattern_match`，:471-:484）：

```python
hits = sum(1 for kw in kws if kw in message)
score = min(1.0, 0.5 + 0.25 * (hits - 1))
```

单个关键词命中给 0.5，每多命中一个 +0.25，封顶 1.0。为什么起点是 0.5？因为 0.5 恰好等于投票阈值——单个明确业务词就值得信任，但不配拿到更高话语权。

## 4. 本地哈希向量 `_local_embedding`（:423-:440）

Embedding 路不依赖外部向量服务：把文本切成 1/2/3-gram 字符片段，每个片段 MD5 哈希后映射到 256 维向量的某一维，符号由哈希字节奇偶决定：

```python
for token in tokens:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    idx = int.from_bytes(digest[:4], "big") % dims
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    vec[idx] += sign
```

这叫 **hashing trick**（特征哈希）。它不懂语义——"退款"和"退货"在向量空间里的接近程度只来自字符重叠——但对客服场景的模板化表达（"我要退款"/"申请退款"）足够产生可用的相似度信号。而且：确定性、零依赖、永不失败。

配套 `_cosine`（:132-:137）是纯 Python 余弦相似度，注意零向量防护：`return dot / (na * nb) if na and nb else 0.0`。

## 5. 实体提取 `_extract_entities`（:375-:387）

用正则而不是 LLM 提取高价值实体——order_id、date、amount、error_code。设计理由写在 docstring 里："避免每次识别都额外调用 LLM"。实体格式是稳定的（订单号、金额、HTTP 状态码），正则是这种场景的最优解：**结构化、稳定的信息用规则；模糊、开放的信息才用模型**。

这些实体随后被 Ch2 的 `_domain_scores` 消费：有 error_code 给 technical +0.2 分，有 amount 给 billing +0.15 分。

## 6. 紧急度 `_urgency`（:442-:451）

关键词优先（"紧急"→CRITICAL、"今天/马上"→HIGH、"这周"→MEDIUM），无关键词时按意图给默认值（escalation/human_handoff→HIGH，complaint→MEDIUM，其余→LOW）。CRITICAL 会在 Ch2 直接触发升级路由，跳过一切打分。

## 7. Lab：重写意图识别的确定性内核

LLM 调用路（`_llm_recognize`）不可离线测试，Lab 覆盖其余全部确定性逻辑。实现 `intent.py`：

- `CATEGORIES` —— 19 个意图字符串常量（含 "other"），顺序见 lab.json。
- `cosine(a, b)` —— 余弦相似度，零向量返回 0.0。
- `local_embedding(text, dims=256)` —— hashing trick 向量。
- `pattern_recognize(message, specific_patterns, generic_patterns)` —— 两级模式匹配 + 打分公式。
- `vote(llm, emb, pat, threshold=0.5)` —— 加权投票 + failed 兜底 + 阈值降级（细粒度修正作为挑战题，见 lab.json notes）。
- `extract_entities(message)` —— 四类实体的正则提取。
- `urgency(message, intent)` —— 返回 1-4 整数。

对应讲义概念：§2→vote，§3→pattern_recognize，§4→cosine/local_embedding，§5→extract_entities，§6→urgency。
