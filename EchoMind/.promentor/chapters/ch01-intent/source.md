# 源码导读：三路融合意图识别

## 核心文件：`core/intent_recognizer.py`

### 意图分类体系（:29-:122）

- `IntentCategory`（:29-:48）：19 个类别。注意细分意图（order_status/logistics/refund/invoice/payment_issue/account_security/technical_login/technical_crash/human_handoff）与大类的并存。
- `_TEMPLATES`（:71-:90）：Few-shot 模板，**同时**用于 LLM 提示词示例和 Embedding 相似度匹配——一份数据两处消费，`learn()`（:223-:230）在线新增样本后两路同时受益。
- `_SPECIFIC_INTENTS`/`_GENERIC_INTENTS`/`_INTENT_GROUPS`（:92-:122）：细粒度修正和意图归组所需的两张集合 + 一张映射表。

### recognize 主流程（:172-:221）

```python
llm_task = asyncio.create_task(self._llm_recognize(message, history))     # :191
emb_task = asyncio.create_task(self._embedding_recognize(message)) ...    # :192
pat      = self._pattern_recognize(message)                               # :193 同步，零延迟
if emb_task:
    llm, emb = await asyncio.gather(llm_task, emb_task)                   # :196 并行等待
```

**关键点：pattern 路是同步执行的**（:193），在等待两个异步任务时它已经完成。三路真正的总延迟 = max(LLM, Embedding)，不是三者之和。

:182-:186 是 MD5 缓存键（`_cache_key`，:453-:464）：message 截断 200 字 + 最近 3 轮 history，命中直接返回。:217-:219 是简易 LRU：超 1000 条删前 500。

### _vote 加权投票（:338-:371）

- :340-:344 先记录三路原始分到 `source_scores`（可观测性：API 响应里能看到每一路说了什么）。
- :345-:350 LLM failed 分支：Embedding → Pattern → other 逐级兜底。
- :352-:355 权重选择：Embedding 可用时 0.7/0.2/0.1，不可用时 0.85/0.15（**权重和始终为 1**，保证置信度可比）。
- :356-:363 按类别累加 `w * conf`，取最大。
- :364-:368 **细粒度修正**：`best in _GENERIC_INTENTS and pat_intent in _SPECIFIC_INTENTS and pat_conf >= 0.5 and best_score < 0.8` 四个条件同时成立才覆盖。为什么加 `best_score < 0.8`？加权分已经很高说明三路一致，不需要 pattern 来"纠偏"。
- :369-:370 阈值降级到 other。

### _pattern_recognize（:304-:334）+ _best_pattern_match（:471-:484）

:306 `msg = message.lower()` —— 匹配前统一小写。
:329-:331 先 specific 后 generic，specific 命中即返回。
:481 打分：`score = min(1.0, 0.5 + 0.25 * (hits - 1))`。

### _local_embedding（:423-:440）+ _cosine（:132-:137）

- :413-:419 `_embed_text` 先探测客户端有无 `embeddings` 资源（远端向量），没有才落到本地哈希向量。**接口探测式降级**，不写死。
- :429-:431 1/2/3-gram 字符切片：`tokens.update(normalized[i:i+n] ...)`，set 去重。
- :436-:439 MD5 → 前 4 字节取模定位，第 5 字节奇偶定符号。
- `_cosine` :137 零向量防护。

### _extract_entities（:375-:387）

四组正则。注意 error_code 是**两次 findall 相加**（:383-:386）：先带前缀的精确匹配（`error_code: 401`），再裸的 `\b([45]\d{2})\b`——4xx/5xx 才可能是 HTTP 错误码，避免把 "200 元" 误判。`_unique`（:466-:468）用 `dict.fromkeys` 保序去重。

### _urgency（:442-:451）

关键词表 :125-:129 按 CRITICAL→HIGH→MEDIUM 顺序检查（dict 有序），命中即返回；无关键词按意图给默认值。

## 辅助文件：`core/llm_utils.py`

`extract_text_content`（:5-:22）：兼容 Anthropic SDK 返回的多种 block 形态（对象/dict/裸字符串），所有 LLM 调用共用。Lab 不涉及。
