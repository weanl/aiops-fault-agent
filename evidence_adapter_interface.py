#!/usr/bin/env python3
r"""
Real Evidence Adapter Interface — v2.2.1 A-mini
================================================

**职责**：定义 Evidence Adapter 抽象接口 + 标准数据结构。
**约束**：
  - 仅定义接口 + 数据契约，不接真实 OpenAPI
  - Mock adapter 和未来 Real adapter 共用同一 schema
  - 输出与 case-XX.yaml 1:1 对应 → 喂给 evidence_builder → Markdown

**4 个核心方法**：
  1. fetch_alarms    → Evidence A
  2. fetch_kpis      → Evidence B
  3. fetch_topology  → Evidence C
  4. fetch_error_stats → Evidence D

**3 个标准 dataclass**：
  - AlarmRecord / KpiRecord / TopologyGraph / ErrorCodeRecord
  - TimeWindow（统一时间窗口）

**2 个 adapter 实现**：
  - MockYamlAdapter（已实现，读 case-XX.yaml）
  - RealOpenAPIAdapter（骨架占位，NotImplementedError）

**1 个转换函数**：
  - adapter_to_evidence_pack(adapter, time_window, ...) → Markdown 字符串

用法：
    from evidence_adapter_interface import MockYamlAdapter, adapter_to_evidence_pack
    from datetime import datetime

    adapter = MockYamlAdapter("runtime/cases/case-09.yaml")
    window = TimeWindow(start=datetime(2026, 6, 30, 22, 0), duration_minutes=30)
    markdown = adapter_to_evidence_pack(adapter, window, ["OCS-BJ-02", "CBS-SH-01"])
    print(markdown)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# ============================================================
# 标准数据结构（与 mock YAML 1:1 对应）
# ============================================================

@dataclass
class AlarmRecord:
    """Evidence A — Alarm 一条记录"""
    alarm_id: str
    time: str  # HH:MM (CST, UTC+8)
    object_id: str
    type: str
    level: str  # P1/P2/P3/P4
    extra: dict = field(default_factory=dict)


@dataclass
class KpiRecord:
    """Evidence B — KPI 一条记录"""
    object_id: str
    metric: str
    value: float
    unit: str
    time: str  # HH:MM (CST)
    baseline: Optional[float] = None
    threshold: Optional[float] = None


@dataclass
class TopologyObject:
    """Evidence C — Topology 对象清单中的一项"""
    id: str
    role: str


@dataclass
class TopologyGraph:
    """Evidence C — Topology 子图"""
    graph: str  # ASCII "A → B → C"
    objects: List[TopologyObject] = field(default_factory=list)


@dataclass
class ErrorCodeRecord:
    """Evidence D — Error Statistics 一条记录"""
    error_code: str  # 4 位数字
    count: int
    pct: float  # 0-100
    main_object_id: str
    first_seen_time: Optional[str] = None  # HH:MM (CST) — V8 时间线关键字段
    last_seen_time: Optional[str] = None


@dataclass
class TimeWindow:
    """统一时间窗口：起点 + 时长 + 时区"""
    start: datetime
    duration_minutes: int = 30
    tz: str = "Asia/Shanghai"


# ============================================================
# 抽象接口
# ============================================================

class EvidenceAdapter(ABC):
    """Evidence Pack 数据源抽象接口
    
    所有 adapter 必须实现 4 个方法。
    返回值类型与 mock YAML 1:1 对应。
    """
    
    @abstractmethod
    def fetch_alarms(self, time_window: TimeWindow) -> List[AlarmRecord]:
        """拉取时间窗口内的告警列表 → Evidence A"""
        ...
    
    @abstractmethod
    def fetch_kpis(self, time_window: TimeWindow,
                   object_ids: List[str]) -> List[KpiRecord]:
        """拉取指定对象的 KPI 快照 → Evidence B"""
        ...
    
    @abstractmethod
    def fetch_topology(self, object_ids: List[str]) -> TopologyGraph:
        """拉取对象相关的拓扑子图 → Evidence C"""
        ...
    
    @abstractmethod
    def fetch_error_stats(self, time_window: TimeWindow,
                          object_ids: List[str]) -> List[ErrorCodeRecord]:
        """拉取时间窗口内的错误码统计 → Evidence D"""
        ...


# ============================================================
# Mock Adapter（已实现）
# ============================================================

class MockYamlAdapter(EvidenceAdapter):
    """读取 runtime/cases/case-XX.yaml 的 mock adapter
    
    用于：
      1. CI 单元测试（不连真实 OpenAPI）
      2. 离线回归（用录制数据替代真实数据）
      3. 9B 推理稳定性验证（保证 evidence schema 一致）
    """
    
    def __init__(self, yaml_path: str):
        import yaml
        self.case = yaml.safe_load(open(yaml_path, encoding="utf-8"))
    
    def fetch_alarms(self, time_window: TimeWindow) -> List[AlarmRecord]:
        out = []
        for ev in self.case.get("evidence", []):
            if ev.get("label") != "Evidence A":
                continue
            for row in ev.get("rows", []):
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
        for ev in self.case.get("evidence", []):
            if ev.get("label") != "Evidence B":
                continue
            for row in ev.get("rows", []):
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
        for ev in self.case.get("evidence", []):
            if ev.get("label") != "Evidence C":
                continue
            objs = [TopologyObject(id=o["id"], role=o["role"]) for o in ev.get("objects", [])]
            return TopologyGraph(graph=ev["graph"].strip(), objects=objs)
        return TopologyGraph(graph="")
    
    def fetch_error_stats(self, time_window: TimeWindow,
                          object_ids: List[str]) -> List[ErrorCodeRecord]:
        out = []
        for ev in self.case.get("evidence", []):
            if ev.get("label") != "Evidence D":
                continue
            for row in ev.get("rows", []):
                if row.get("占比", 0.0) <= 0.0:  # 跳过主动排除（V8 边界）
                    continue
                out.append(ErrorCodeRecord(
                    error_code=row["错误码"],
                    count=row["次数"],
                    pct=row["占比"],
                    main_object_id=row["主要对象"],
                ))
        return out


# ============================================================
# Real Adapter 骨架（v2.3.0+ 实现）
# ============================================================

class RealOpenAPIAdapter(EvidenceAdapter):
    """真实 OpenAPI adapter 骨架 —— v2.3.0+ 实现
    
    **当前 v2.2.1 不实现**，仅保留接口签名。
    实现时需：
      1. 申请 4 类 API 访问权限（Alarm / Monitor / CMDB / Log）
      2. 实现 OAuth / API Key 认证
      3. 处理 4 类错误（429 / 5xx / timeout / 字段缺失）
      4. 实现 first_seen_time 字段拉取（V8 关键）
      5. 时区归一化（API 返回 UTC → CST）
    """
    
    def __init__(self, config: dict):
        # config 期望字段：
        #   base_url: str
        #   auth_token: str
        #   endpoints: {alarms, kpis, topology, error_stats}
        #   timeout_seconds: int (默认 10)
        #   retry_count: int (默认 3)
        raise NotImplementedError(
            "RealOpenAPIAdapter not implemented in v2.2.1 A-mini. "
            "Use MockYamlAdapter for now. See real-evidence-adapter-design.md."
        )
    
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


# ============================================================
# 转换器：adapter → evidence.md (Markdown)
# ============================================================

def adapter_to_evidence_pack(adapter: EvidenceAdapter,
                             time_window: TimeWindow,
                             candidate_object_ids: List[str]) -> str:
    """把 adapter 输出转成 evidence_builder.py 兼容的 Markdown
    
    与 case-XX.yaml 的渲染产物格式完全一致
    → 9B / verifier 不需要感知数据源差异。
    
    Args:
        adapter: EvidenceAdapter 实例（Mock / Real）
        time_window: 时间窗口
        candidate_object_ids: 候选对象 ID 列表（用于 KPI / Topology 过滤）
    
    Returns:
        Markdown 字符串，可直接写入 evidence.md
    """
    alarms = adapter.fetch_alarms(time_window)
    kpis = adapter.fetch_kpis(time_window, candidate_object_ids)
    topology = adapter.fetch_topology(candidate_object_ids)
    err_stats = adapter.fetch_error_stats(time_window, candidate_object_ids)
    
    lines = [
        f"# Evidence Pack — {type(adapter).__name__} Output",
        f"> 时间窗口: {time_window.start.isoformat()} +{time_window.duration_minutes}min ({time_window.tz})",
        f"> 候选对象: {', '.join(candidate_object_ids)}",
        f"> 来源: {type(adapter).__name__}",
        "",
        "---",
        "",
        "## Evidence A — Alarm",
        "",
        "**说明**：时间窗口内的告警快照。",
        "",
        "| 告警ID | 时间 | 对象 | 类型 | 等级 |",
        "|---|---|---|---|---|",
    ]
    for a in alarms:
        lines.append(f"| {a.alarm_id} | {a.time} | {a.object_id} | {a.type} | {a.level} |")
    
    lines += [
        "",
        "---",
        "",
        "## Evidence B — KPI",
        "",
        "**说明**：相关网元的 KPI 快照。",
        "",
        "| 对象 | 指标 | 数值 | 单位 | 时间 |",
        "|---|---|---|---|---|",
    ]
    for k in kpis:
        lines.append(f"| {k.object_id} | {k.metric} | {k.value} | {k.unit} | {k.time} |")
    
    lines += [
        "",
        "---",
        "",
        "## Evidence C — Topology",
        "",
        "**说明**：相关网元的拓扑关系。",
        "",
        "```",
        topology.graph,
        "```",
        "",
        "**对象清单**：",
    ]
    for o in topology.objects:
        lines.append(f"- {o.id}: {o.role}")
    
    lines += [
        "",
        "---",
        "",
        "## Evidence D — Error Statistics",
        "",
        "**说明**：错误码分布统计。",
        "",
        "| 错误码 | 次数 | 占比 | 主要对象 |",
        "|---|---|---|---|",
    ]
    for e in err_stats:
        lines.append(f"| {e.error_code} | {e.count} | {e.pct} | {e.main_object_id} |")
    
    return "\n".join(lines) + "\n"


# ============================================================
# CLI 自检（不连真实 API）
# ============================================================

def _self_check():
    """Mock adapter → Markdown 端到端 smoke test"""
    import sys
    from pathlib import Path
    
    project_root = Path(__file__).parent
    yaml_path = project_root / "runtime" / "cases" / "case-01.yaml"
    if not yaml_path.exists():
        print(f"[SKIP] {yaml_path} not found")
        return 0
    
    adapter = MockYamlAdapter(str(yaml_path))
    window = TimeWindow(
        start=datetime(2026, 6, 28, 14, 0),
        duration_minutes=30,
        tz="Asia/Shanghai",
    )
    candidate_ids = ["OCS-BJ-02", "CBS-SH-01", "Adapter-PAY-01"]
    
    md = adapter_to_evidence_pack(adapter, window, candidate_ids)
    print(md)
    
    # 简单结构校验
    required_sections = [
        "## Evidence A — Alarm",
        "## Evidence B — KPI",
        "## Evidence C — Topology",
        "## Evidence D — Error Statistics",
    ]
    missing = [s for s in required_sections if s not in md]
    if missing:
        print(f"[FAIL] missing sections: {missing}")
        return 1
    print(f"[PASS] all 4 evidence sections present ({len(md)} chars)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_self_check())