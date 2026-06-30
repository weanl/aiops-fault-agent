# Real Evidence Adapter Design — v2.2.1 A-mini

> **生成时间**：2026-06-30 23:00 CST
> **触发**：Vanson 22:33 拍 D → A-mini（V8 优先于真实 Evidence 接入）
> **状态**：**设计稿**（**不接真实 OpenAPI**，仅定义数据契约 / 接口 / 字段映射）
> **关联**：维度 4 准入门槛解除路径；详见 `runtime/readiness-for-real-openapi.md`

---

## 🎯 设计目标

把当前手工 YAML 的 Evidence Pack（case-XX.yaml → evidence.md）扩展为**真实数据源驱动的 Evidence Pack**，同时保持：

1. **Mock ↔ Real 共用 schema**：mock case-XX.yaml 与真实 OpenAPI 输出映射到同一 Evidence Pack 字段
2. **deterministic 验证不变**：real adapter 输出仍可被 verifier V1-V9 校验
3. **9B 推理输入不变**：9B 看到的 Evidence Pack Markdown 与 mock 完全一致
4. **数据契约优先**：先定义字段映射，再决定 API 调用方式

---

## 📊 数据模型：Evidence A/B/C/D 字段映射

### Evidence A — Alarm（告警）

| 字段 | 类型 | 来源 | 必填 | Mock 来源（YAML） | Real 来源（OpenAPI）|
|------|------|------|:----:|--------------------|----------------------|
| `alarm_id` | str | alarm 系统 | ✅ | `rows[].告警ID` | `GET /alarms?time_window=...` 返回 |
| `time` | str (HH:MM) | alarm 系统 | ✅ | `rows[].时间` | API 返回 `trigger_time` 字段 |
| `object_id` | str | alarm 系统 | ✅ | `rows[].对象` | API 返回 `target_object_id` 字段 |
| `type` | str | alarm 系统 | ✅ | `rows[].类型` | API 返回 `alarm_type` 字段 |
| `level` | str (P1/P2/P3/P4) | alarm 系统 | ✅ | `rows[].等级` | API 返回 `severity` 字段 |
| `extra` | dict | alarm 系统 | ❌ | 无 | API 返回 `metadata` 字段（告警规则 ID 等）|

**数据契约**（Evidence A Section）：
```yaml
## Evidence A — Alarm
| 告警ID | 时间 | 对象 | 类型 | 等级 |
|---|---|---|---|---|
| ALM-XXX | 22:05 | OCS-BJ-02 | 连接池超阈值 | P2 |
```

**字段映射规则**：

- `trigger_time` (ISO 8601) → `time` (HH:MM)：取 trigger_time 的 **小时:分钟** 部分，**时区归一化为 CST (UTC+8)**
- `severity` 标准化：`critical/high/medium/low/info` → `P1/P2/P3/P4/unknown`
- `target_object_id` 大写归一化（与 OBJECT_ID_RE 兼容）

---

### Evidence B — KPI（关键指标）

| 字段 | 类型 | 来源 | 必填 | Mock 来源（YAML） | Real 来源（OpenAPI）|
|------|------|------|:----:|--------------------|----------------------|
| `object_id` | str | 监控系统 | ✅ | `rows[].对象` | API 返回 `target_object_id` |
| `metric` | str | 监控系统 | ✅ | `rows[].指标` | API 返回 `metric_name` |
| `value` | float | 监控系统 | ✅ | `rows[].数值` | API 返回 `value` |
| `unit` | str | 监控系统 | ✅ | `rows[].单位` | API 返回 `unit`（%）|
| `time` | str (HH:MM) | 监控系统 | ✅ | `rows[].时间` | API 返回 `sample_time`（取 HH:MM，CST 归一）|
| `baseline` | float | 监控系统 | ❌ | 备注里写 | API 返回 `baseline_value`（用于对比）|
| `threshold` | float | 监控系统 | ❌ | 备注里写 | API 返回 `threshold_high/low`（告警阈值）|

**字段映射规则**：

- `metric_name` 中文映射表：
  ```python
  METRIC_NAME_MAP = {
      "connection_pool_usage": "连接池使用率",
      "response_time_p99": "平均响应时间",  # 简化命名
      "error_rate": "错误率",
      "success_rate": "成功率",
      "timeout_rate": "超时错误率",
  }
  ```
- `value` 单位归一化：百分比统一为 0-100（不是 0-1）
- **每个 object × metric 只保留最新一行**（取 sample_time 最大）

---

### Evidence C — Topology（拓扑）

| 字段 | 类型 | 来源 | 必填 | Mock 来源（YAML） | Real 来源（CMDB API）|
|------|------|------|:----:|--------------------|----------------------|
| `graph` | str (ASCII) | CMDB | ✅ | `graph` 字段 | API 返回 `topology_edges[]` 转 ASCII |
| `objects[].id` | str | CMDB | ✅ | `objects[].id` | API 返回 `component_id` |
| `objects[].role` | str | CMDB | ✅ | `objects[].role` | API 返回 `component_role` |
| `direction` | str | CMDB | ❌ | 隐含 | API 返回 `call_direction`（upstream/downstream）|
| `latency_ms` | float | CMDB | ❌ | 无 | API 返回 `avg_latency_ms` |

**字段映射规则**：

- `topology_edges[]`（结构化列表）→ ASCII 图：
  ```python
  edges = [("CBS-SH-01", "OCS-BJ-02"), ("OCS-BJ-02", "Adapter-PAY-01")]
  graph = " → ".join([e[0] for e in edges[:-1]] + [edges[-1][1]])
  # 输出: "CBS-SH-01 → OCS-BJ-02 → Adapter-PAY-01"
  ```
- **只保留故障相关的子图**（深度 2-3 层），不画全网拓扑
- 对象命名归一化为大写（与 OBJECT_ID_RE 兼容）

---

### Evidence D — Error Statistics（错误码统计）

| 字段 | 类型 | 来源 | 必填 | Mock 来源（YAML） | Real 来源（日志系统 API）|
|------|------|------|:----:|--------------------|----------------------|
| `error_code` | str (4 位) | 日志系统 | ✅ | `rows[].错误码` | API 返回 `error_code` |
| `count` | int | 日志系统 | ✅ | `rows[].次数` | API 返回 `count` |
| `pct` | float (0-100) | 日志系统 | ✅ | `rows[].占比` | API 返回 `percentage` |
| `main_object_id` | str | 日志系统 | ✅ | `rows[].主要对象` | API 返回 `primary_target_id` |
| `first_seen_time` | str (HH:MM) | 日志系统 | ❌ | **缺失**（关键缺口）| API 返回 `first_observed_time` |
| `last_seen_time` | str (HH:MM) | 日志系统 | ❌ | **缺失**（关键缺口）| API 返回 `last_observed_time` |

**字段映射规则**：

- `percentage`（0-1 小数）→ `pct`（0-100）：`pct = percentage * 100`
- `pct < 0.5` 的行跳过（占位/噪声）
- **first_seen_time / last_seen_time 必须从 API 拿**——V8 时间线闭合性高度依赖这两个字段
- 如果 API 不返回，verifier V7 会 FAIL（视为关键字段缺失）

---

## 🔌 接口契约：`evidence_adapter_interface.py`

```python
#!/usr/bin/env python3
"""
Real Evidence Adapter Interface — v2.2.1 A-mini

**不接真实 OpenAPI**。仅定义接口签名 + 数据契约。

约定：
- 所有 adapter 必须实现 4 个方法（fetch_alarms / fetch_kpis / fetch_topology / fetch_error_stats）
- 所有方法返回标准化结构（与 mock YAML 1:1 对应）
- mock adapter 和 future real adapter 共用同一 schema
- 不在接口层做错误恢复（交给 pipeline 层处理）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


# ----------------------------- 标准数据结构 -----------------------------

@dataclass
class AlarmRecord:
    alarm_id: str
    time: str  # HH:MM (CST)
    object_id: str
    type: str
    level: str  # P1/P2/P3/P4
    extra: dict = field(default_factory=dict)


@dataclass
class KpiRecord:
    object_id: str
    metric: str
    value: float
    unit: str
    time: str  # HH:MM (CST)
    baseline: Optional[float] = None
    threshold: Optional[float] = None


@dataclass
class TopologyObject:
    id: str
    role: str


@dataclass
class TopologyGraph:
    graph: str  # ASCII "A → B → C"
    objects: List[TopologyObject] = field(default_factory=list)


@dataclass
class ErrorCodeRecord:
    error_code: str  # 4 digits
    count: int
    pct: float  # 0-100
    main_object_id: str
    first_seen_time: Optional[str] = None  # HH:MM (CST)
    last_seen_time: Optional[str] = None


@dataclass
class TimeWindow:
    """时间窗口：起点 + 时长 + 时区"""
    start: datetime  # CST
    duration_minutes: int = 30
    tz: str = "Asia/Shanghai"


# ----------------------------- 接口契约 -----------------------------

class EvidenceAdapter(ABC):
    """Evidence Pack 数据源抽象接口
    
    所有 adapter（mock / real / recording）必须实现 4 个方法。
    返回值与 YAML schema 1:1 对应，可直接喂给 evidence_builder.py。
    """
    
    @abstractmethod
    def fetch_alarms(self, time_window: TimeWindow) -> List[AlarmRecord]:
        """拉取时间窗口内的告警列表"""
        ...
    
    @abstractmethod
    def fetch_kpis(self, time_window: TimeWindow, 
                   object_ids: List[str]) -> List[KpiRecord]:
        """拉取指定对象的 KPI 快照"""
        ...
    
    @abstractmethod
    def fetch_topology(self, object_ids: List[str]) -> TopologyGraph:
        """拉取对象相关的拓扑子图"""
        ...
    
    @abstractmethod
    def fetch_error_stats(self, time_window: TimeWindow,
                         object_ids: List[str]) -> List[ErrorCodeRecord]:
        """拉取时间窗口内的错误码统计"""
        ...


# ----------------------------- Mock Adapter 示例 -----------------------------

class MockYamlAdapter(EvidenceAdapter):
    """读取 runtime/cases/case-XX.yaml 的 mock adapter
    
    用于：
    1. CI 单元测试（不连真实 OpenAPI）
    2. 离线回归（用录制数据替代真实数据）
    3. 9B 推理稳定性验证（保证 evidence schema 一致）
    """
    
    def __init__(self, yaml_path: str):
        import yaml
        self.case = yaml.safe_load(open(yaml_path))
    
    def fetch_alarms(self, time_window: TimeWindow) -> List[AlarmRecord]:
        out = []
        for ev in self.case["evidence"]:
            if ev["label"] != "Evidence A":
                continue
            for row in ev["rows"]:
                out.append(AlarmRecord(
                    alarm_id=row["告警ID"],
                    time=row["时间"],
                    object_id=row["对象"],
                    type=row["类型"],
                    level=row["等级"],
                ))
        return out
    
    def fetch_kpis(self, time_window: TimeWindow,
                   object_ids: List[str]) -> List[KpiRecord]:
        out = []
        for ev in self.case["evidence"]:
            if ev["label"] != "Evidence B":
                continue
            for row in ev["rows"]:
                if row["对象"] not in object_ids:
                    continue
                out.append(KpiRecord(
                    object_id=row["对象"],
                    metric=row["指标"],
                    value=float(row["数值"]),
                    unit=row["单位"],
                    time=row["时间"],
                ))
        return out
    
    def fetch_topology(self, object_ids: List[str]) -> TopologyGraph:
        for ev in self.case["evidence"]:
            if ev["label"] != "Evidence C":
                continue
            objs = [TopologyObject(id=o["id"], role=o["role"]) for o in ev["objects"]]
            return TopologyGraph(graph=ev["graph"].strip(), objects=objs)
        return TopologyGraph(graph="")
    
    def fetch_error_stats(self, time_window: TimeWindow,
                          object_ids: List[str]) -> List[ErrorCodeRecord]:
        out = []
        for ev in self.case["evidence"]:
            if ev["label"] != "Evidence D":
                continue
            for row in ev["rows"]:
                if row["占比"] <= 0.0:  # 跳过主动排除
                    continue
                out.append(ErrorCodeRecord(
                    error_code=row["错误码"],
                    count=row["次数"],
                    pct=row["占比"],
                    main_object_id=row["主要对象"],
                ))
        return out


# ----------------------------- Real Adapter 骨架（待实现） -----------------------------

class RealOpenAPIAdapter(EvidenceAdapter):
    """真实 OpenAPI adapter 骨架 —— v2.3.0+ 实现
    
    当前 v2.2.1 A-mini **不实现**，仅保留接口签名。
    实现时需要：
    1. 申请 4 个 API 的访问权限（Alarm / Monitor / CMDB / Log）
    2. 实现 OAuth / API Key 认证
    3. 处理 4 类错误（429 / 5xx / timeout / 字段缺失）
    4. 写入 readiness-for-real-openapi.md 列出的所有必填字段
    """
    
    def __init__(self, config: dict):
        # config 包含 base_url / auth_token / endpoint_paths
        raise NotImplementedError("Real adapter not implemented in v2.2.1 A-mini")
    
    def fetch_alarms(self, time_window: TimeWindow) -> List[AlarmRecord]:
        raise NotImplementedError
    
    def fetch_kpis(self, time_window: TimeWindow,
                   object_ids: List[str]) -> List[KpiRecord]:
        raise NotImplementedError
    
    def fetch_topology(self, object_ids: List[str]) -> TopologyGraph:
        raise NotImplementedError
    
    def fetch_error_stats(self, time_window: TimeWindow,
                          object_ids: List[str]) -> List[ErrorCodeRecord]:
        raise NotImplementedError


# ----------------------------- 转换器：adapter → evidence.md -----------------------------

def adapter_to_evidence_pack(adapter: EvidenceAdapter,
                             time_window: TimeWindow,
                             candidate_object_ids: List[str]) -> str:
    """把 adapter 输出转成 evidence_builder.py 兼容的 Markdown
    
    与 case-XX.yaml 的渲染产物格式完全一致 → 9B / verifier 不需要感知数据源差异。
    """
    alarms = adapter.fetch_alarms(time_window)
    kpis = adapter.fetch_kpis(time_window, candidate_object_ids)
    topology = adapter.fetch_topology(candidate_object_ids)
    err_stats = adapter.fetch_error_stats(time_window, candidate_object_ids)
    
    lines = [
        f"# Evidence Pack — Real Adapter Output",
        f"> 时间窗口: {time_window.start} +{time_window.duration_minutes}min",
        f"> 来源: {type(adapter).__name__}",
        "",
        "## Evidence A — Alarm",
        "| 告警ID | 时间 | 对象 | 类型 | 等级 |",
        "|---|---|---|---|---|",
    ]
    for a in alarms:
        lines.append(f"| {a.alarm_id} | {a.time} | {a.object_id} | {a.type} | {a.level} |")
    
    lines += [
        "",
        "## Evidence B — KPI",
        "| 对象 | 指标 | 数值 | 单位 | 时间 |",
        "|---|---|---|---|---|",
    ]
    for k in kpis:
        lines.append(f"| {k.object_id} | {k.metric} | {k.value} | {k.unit} | {k.time} |")
    
    lines += [
        "",
        "## Evidence C — Topology",
        "```",
        topology.graph,
        "```",
        "**对象清单**:",
    ]
    for o in topology.objects:
        lines.append(f"- {o.id}: {o.role}")
    
    lines += [
        "",
        "## Evidence D — Error Statistics",
        "| 错误码 | 次数 | 占比 | 主要对象 |",
        "|---|---|---|---|",
    ]
    for e in err_stats:
        lines.append(f"| {e.error_code} | {e.count} | {e.pct} | {e.main_object_id} |")
    
    return "\n".join(lines)
```

**接口设计原则**：

1. **Mock ↔ Real 共用 schema**：`MockYamlAdapter` 和未来 `RealOpenAPIAdapter` 返回值类型一致
2. **verifier 不变**：adapter 输出喂给 evidence_builder → Markdown → verifier V1-V9 不变
3. **9B 不感知**：9B 看到的 evidence.md 与 mock 形态一致
4. **失败隔离**：单 API 失败 → 返回空 + 记录到 extra，不阻塞其他 API

---

## 🕒 时间窗口规则

| 维度 | 规则 |
|------|------|
| **窗口长度** | 默认 30 分钟（与 mock case 一致）|
| **窗口起点** | 用户指定或当前时间向前对齐到 30 分钟边界 |
| **时区** | 全部归一化为 `Asia/Shanghai` (CST, UTC+8) |
| **API 返回** | 如果 OpenAPI 返回 UTC → adapter 内转换 |
| **HH:MM 截断** | evidence.md 只显示 HH:MM（精确到分钟），秒数丢弃 |

---

## 🔗 P0 真实接入最小字段清单

| 段 | 必填字段 | 可选字段 | 缺失处理 |
|----|---------|---------|----------|
| **Evidence A** | alarm_id / time / object_id / type / level | extra | 任一缺失 → adapter 报 SKIPPED，不输出 evidence |
| **Evidence B** | object_id / metric / value / unit / time | baseline / threshold | metric / value 缺失 → 跳过该行 |
| **Evidence C** | graph / objects[].id | objects[].role / direction | graph 为空 → 9B 报 INSUFFICIENT_EVIDENCE |
| **Evidence D** | error_code / count / pct / main_object_id | first_seen_time / last_seen_time | first_seen_time 缺失 → V7 视为关键字段缺失 |

**`KnowledgeNotes` / `HistoricalCases`（可选）**：

- 9B 当前 4 段不引用历史案例（V9 拦截"与历史案例相似"）
- 因此 history 数据**不进 Evidence Pack**
- 如未来启用，需新增 Evidence E 段

---

## 🚦 P0 阶段 1 启动条件（来自 readiness-for-real-openapi.md）

**v2.2.1 A-mini 设计稿完成** ✅
**未启动 P0 阶段 1**——等 Vanson 拍板：
- A. 启动真实 Evidence Adapter 开发（按本设计稿）
- B. 维持 mock 现状，扩 case 到 20+
- C. 接真实系统 + 扩场景

**默认建议 A**（Vanson 22:33 拍 D → A-mini 暗示优先做真实接入）。

---

## 关联

- `evidence_adapter_interface.py` — 接口契约代码
- `readiness-for-real-openapi.md` — P0 准入 checklist
- `runtime/verifier/verifier.py` — 9 类规则不变
- `runtime/evidence/evidence_builder.py` — Markdown 渲染器不变
- 维度 4 阻塞解除路径（`runtime/readiness-for-p0.md`）