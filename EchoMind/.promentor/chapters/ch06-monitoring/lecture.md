# Ch 6: 监控与路由降权闭环

本章学什么：**当 Agent 在线表现变差时，系统如何自动发现、自动降权、自动恢复？**

难度：mid。涉及统计方法（Z-score）、反馈闭环设计、阈值告警——都是生产级监控系统的核心模式。

## 1. 为什么需要监控闭环

静态路由（Ch2）基于历史统计选择 Agent，但无法应对运行时突发故障：

- Agent A 突然开始超时（依赖服务挂了）
- Agent B 成功率骤降（LLM 返回格式异常）
- 工具 C 连续失败（数据库连接池耗尽）

**没有监控闭环**：Orchestrator 继续把请求路由给故障 Agent，用户体验恶化，直到人工介入。

**有监控闭环**：Monitor 实时采集 → 发现异常 → 计算降权系数 → 写回 Orchestrator → `_best_agent()` 自动绕开故障 Agent → 恢复后自动回升权重。

## 2. Z-score 异常检测（:61-:100）

```python
class AnomalyDetector:
    def __init__(self, window: int = 60, sensitivity: float = 2.5):
        self._window      = window
        self._sensitivity = sensitivity
        self._history: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=window))

    def record(self, metric: str, value: float) -> Optional[Dict[str, Any]]:
        buf = self._history[metric]
        buf.append(value)

        if len(buf) < self._window // 2:
            return None  # 数据不足，不检测

        mean  = statistics.mean(buf)
        stdev = statistics.stdev(buf) if len(buf) > 1 else 0.0
        if stdev == 0:
            return None

        z = abs(value - mean) / stdev
        if z > self._sensitivity:
            return {
                "metric":   metric,
                "value":    value,
                "mean":     mean,
                "z_score":  round(z, 2),
                "severity": "high" if z > self._sensitivity * 1.5 else "medium",
            }
        return None
```

**设计决策：为什么用 Z-score 而不是固定阈值？**

- **固定阈值**：`success_rate < 0.9` 触发告警。问题：不同 Agent 的基线不同——Agent A 平时 0.95，降到 0.91 已经是异常；Agent B 平时 0.85，0.91 反而是好转。
- **Z-score**：比较当前值与**自身历史均值**的偏离程度。`z = |value - mean| / stdev`，超过 2.5 倍标准差判定为异常。这是统计过程控制（SPC）的标准方法。

**滑动窗口**：`deque(maxlen=60)` 只保留最近 60 个数据点。太长的窗口会让历史噪音稀释近期突变；太短的窗口统计不稳定。60 是经验值（约 10 分钟 @ 10s 采集间隔）。

**数据不足保护**（:78-:79）：`len(buf) < window // 2` 时不检测——样本太少，均值和标准差不可靠。

**零标准差保护**（:83-:84）：所有历史值相同时 `stdev == 0`，除法会崩溃。直接返回 None（无异常）。

## 3. 路由降权系数（:244-:251）

```python
@staticmethod
def _routing_penalty(success_rate: float, avg_ms: float) -> float:
    """把在线表现转成 0-0.9 的路由降权系数。"""
    penalty = 0.0
    if success_rate < 0.90:
        penalty += min(0.5, (0.90 - success_rate) * 2)
    if avg_ms > 3000:
        penalty += min(0.4, (avg_ms - 3000) / 10000)
    return min(penalty, 0.9)
```

**设计决策：为什么是线性惩罚而不是阶梯式？**

- **阶梯式**：`success_rate < 0.9 → penalty = 0.5`。问题：0.89 和 0.5 的惩罚相同，但后者明显更严重。
- **线性**：`(0.90 - success_rate) * 2`。成功率每下降 0.05，penalty 增加 0.1。平滑过渡，避免路由抖动。

**上限保护**：
- 成功率惩罚上限 0.5：即使 success_rate = 0，penalty 也不会超过 0.5。
- 延迟惩罚上限 0.4：即使 avg_ms = 13000，penalty 也不会超过 0.4。
- 总 penalty 上限 0.9：保留 10% 的路由权重，避免完全隔离（可能只是临时故障）。

**为什么 penalty 上限是 0.9 而不是 1.0？** 完全隔离（penalty = 1.0）意味着该 Agent 永远不会被选中。如果故障恢复，需要人工干预才能重新启用。0.9 保留一线生机——恢复后自动回升。

## 4. 阈值告警（:253-:270）

```python
THRESHOLDS = {
    "agent_success_rate":  (0.90, Severity.ERROR,   "less_than"),
    "tool_success_rate":   (0.95, Severity.WARNING, "less_than"),
    "agent_avg_ms":        (3000, Severity.WARNING, "greater_than"),
    "tool_avg_ms":         (5000, Severity.ERROR,   "greater_than"),
}

def _check_threshold(self, metric: str, value: float, label: str) -> None:
    if metric not in self.THRESHOLDS:
        return
    threshold, severity, operator = self.THRESHOLDS[metric]
    triggered = (operator == "less_than" and value < threshold) or \
                (operator == "greater_than" and value > threshold)
    if triggered:
        alert = Alert(severity=severity, metric=f"{metric}:{label}", ...)
        self._alerts.append(alert)
        logger.warning(f"[{severity.value.upper()}] {alert.message}")
```

**Z-score vs 阈值告警的分工**：
- **Z-score**：发现"相对于自身历史的突变"——适合检测渐进式恶化或突发异常。
- **阈值告警**：发现"绝对不可接受的状态"——success_rate < 0.9 无论历史如何都是问题。

两者互补：Z-score 捕捉早期信号，阈值告警捕捉严重状态。

## 5. 反馈闭环（:190-:230）

```python
async def _collect(self) -> None:
    agent_stats = self._orchestrator.get_stats()
    routing_penalties: Dict[str, float] = {}

    for agent_key, s in agent_stats.items():
        sr = s["success_rate"]
        ms = s["avg_ms"]
        
        # 异常检测
        for metric, value in [("agent_success_rate", sr), ("agent_avg_ms", ms)]:
            anomaly = self._detector.record(f"{metric}:{agent_key}", value)
            if anomaly:
                logger.warning(f"异常检测 [{agent_key}] {metric}={value:.3f} z={anomaly['z_score']}")
        
        # 阈值告警
        self._check_threshold("agent_success_rate", sr, agent_key)
        self._check_threshold("agent_avg_ms", ms, agent_key)
        
        # 计算降权
        routing_penalties[agent_key] = self._routing_penalty(sr, ms)

    # 写回 Orchestrator
    updater = getattr(self._orchestrator, "update_routing_penalties", None)
    if updater:
        updater(routing_penalties)
```

**闭环的关键**：`update_routing_penalties` 把 Monitor 计算的 penalty 写回 Orchestrator。Orchestrator 的 `routing_score()`（Ch2）会用这个 penalty 调整评分：

```python
# Ch2 的 routing_score
score = (success_rate * 0.7 + latency_score * 0.3) * (1.0 - penalty)
```

penalty = 0.5 → score 减半 → `_best_agent()` 自动选择其他 Agent。

**恢复机制**：Agent 恢复正常后，success_rate 回升 → penalty 下降 → score 回升 → 重新被选中。无需人工干预。

## 6. Lab：提取监控的确定性内核

实现 `monitor_tools.py`（纯标准库）：

- `z_score(values, current)` — §2 的 Z-score 计算
- `routing_penalty(success_rate, avg_ms)` — §3 的降权系数
- `check_threshold(metric, value, thresholds)` — §4 的阈值检查

异常检测的滑动窗口管理、Prometheus 集成、Webhook 发送在 Final 章覆盖；本章聚焦核心计算逻辑。
