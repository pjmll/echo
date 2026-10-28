# 源码导读：监控与路由降权闭环

## 核心文件：`monitor/performance_monitor.py`

### AnomalyDetector（:61-:100）

- 初始化（:67-:70）：`window=60`（滑动窗口大小），`sensitivity=2.5`（Z-score 阈值）。
- `_history`（:70）：`defaultdict(lambda: deque(maxlen=window))` ——每个 metric 独立维护一个固定长度的双端队列。
- `record()`（:72-:95）：
  - 追加数据点（:74）：`buf.append(value)`。
  - 数据不足保护（:76-:77）：`len(buf) < window // 2` 时返回 None。
  - 计算均值和标准差（:79-:81）：`statistics.mean(buf)` 和 `statistics.stdev(buf)`。
  - 零标准差保护（:82-:83）：`stdev == 0` 时返回 None。
  - Z-score 计算（:85）：`z = abs(value - mean) / stdev`。
  - 异常判定（:86-:94）：`z > sensitivity` 时返回异常信息字典，包含 metric、value、mean、z_score（保留 2 位小数）、severity（high/medium）。

### _routing_penalty（:244-:251）

```python
@staticmethod
def _routing_penalty(success_rate: float, avg_ms: float) -> float:
    penalty = 0.0
    if success_rate < 0.90:
        penalty += min(0.5, (0.90 - success_rate) * 2)
    if avg_ms > 3000:
        penalty += min(0.4, (avg_ms - 3000) / 10000)
    return min(penalty, 0.9)
```

- 成功率惩罚（:247-:248）：低于 0.90 时，每下降 0.05 增加 0.1 penalty，上限 0.5。
- 延迟惩罚（:249-:250）：高于 3000ms 时，每增加 1000ms 增加 0.1 penalty，上限 0.4。
- 总上限（:251）：`min(penalty, 0.9)` ——保留 10% 路由权重。

### _check_threshold（:253-:270）

- THRESHOLDS 字典（:110-:115）：定义每个 metric 的阈值、严重级别、比较操作符。
- 触发判定（:258-:260）：根据 operator 是 "less_than" 还是 "greater_than" 判断是否超阈值。
- 告警生成（:261-:268）：创建 Alert 对象，追加到 `_alerts` 列表，记录日志，可选发送 Webhook。

### _collect（:190-:230）

- 采集 Agent 统计（:192）：`agent_stats = self._orchestrator.get_stats()`。
- 遍历每个 Agent（:195-:214）：
  - 异常检测（:199-:203）：对 success_rate 和 avg_ms 分别调用 `_detector.record()`。
  - 阈值告警（:206-:207）：调用 `_check_threshold()`。
  - 计算降权（:214）：`routing_penalties[agent_key] = self._routing_penalty(sr, ms)`。
- 写回 Orchestrator（:228-:230）：`updater(routing_penalties)` ——这是闭环的关键。

### 反馈闭环的体现

Monitor 不直接修改路由逻辑，而是通过 `update_routing_penalties` 把 penalty 系数传递给 Orchestrator。Orchestrator 的 `routing_score()`（Ch2）使用这个 penalty 调整评分：

```python
# Ch2 的 routing_score 公式
score = (success_rate * 0.7 + latency_score * 0.3) * (1.0 - penalty)
```

penalty 越大，score 越低，`_best_agent()` 越不会选择该 Agent。恢复后 penalty 下降，score 回升，自动重新启用。
