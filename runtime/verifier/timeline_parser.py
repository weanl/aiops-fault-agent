#!/usr/bin/env python3
r"""
Timeline Closure Checker（V8）
==============================

职责：从 Evidence Pack 抽取时间线数据，判断是否存在"时间线冲突"。

V8 确定性规则的 4 类冲突检测：

C1. **上下游时间倒挂**
    - 拓扑：CBS → OCS → Adapter（A 上游 B 下游）
    - 检测：B 告警时间早于 A 告警，且无因果解释
    - 风险：判定 B 是根因但 A 应该先异常

C2. **错误码先于告警**
    - 检测：错误码主要对象 X，但 X 在时间窗口内无任何 Alarm 记录
    - 风险：错误码爆发 ≠ 故障对象（可能误判）

C3. **KPI 起点早于告警**
    - 检测：Evidence B KPI 时间 < Evidence A 最早告警时间
    - 风险：KPI 异常先于告警，但告警标注为因——逻辑倒挂

C4. **错误码对象不在告警对象集中**
    - 检测：错误码主要对象集合 ∩ Alarm 对象集合 = ∅
    - 风险：错误码集中在没人告警的对象上 → 该对象可能是"沉默故障"

V8 判定：
- 任意 C1-C4 命中 + diagnosis confidence=high → FAIL（要求降为 medium/low/INSUFFICIENT）
- 任意 C1-C4 命中 + 候选 confidence=high → FAIL（候选必降）
- 任意 C1-C4 命中 + diagnosis confidence=medium/low/INSUFFICIENT_EVIDENCE → PASS（9B 自由判断）

不修改 9B prompt，不引入 LLM 自检。
"""
import json
import re
from pathlib import Path

# 对象前缀白名单（与 V3 同步）
OBJECT_ID_RE = re.compile(r"\b(?:OCS|CBS|GW|ADB|ADAPTER|APP|RDS|REDIS|NGINX|KAFKA|ES)-[A-Z]{2,5}-\d{2}\b", re.IGNORECASE)

# 时间戳正则：HH:MM
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

# 拓扑上下游映射（基于 Evidence C 中的 ASCII 图 + 对象清单）
# 简化规则：如果在 `→` 同一行，靠左的是上游，靠右的是下游
TOPOLOGY_ARROW_RE = re.compile(r"([A-Z][A-Z0-9\-]+)\s*→\s*([A-Z][A-Z0-9\-]+)")


def parse_evidence_alarms(evidence_text):
    """从 Evidence A（Alarm）抽取 {time_minutes, object_id, level}"""
    alarms = []
    # 找到 Evidence A 段
    section = _extract_section(evidence_text, "Evidence A")
    if not section:
        return alarms
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or "时间" in cells[0] and "对象" in cells[1]:
            continue
        # 跳过表头
        if cells[0] in ("告警ID", "---"):
            continue
        time_m = TIME_RE.search(line)
        obj_m = OBJECT_ID_RE.search(line)
        if time_m and obj_m:
            h, m = int(time_m.group(1)), int(time_m.group(2))
            alarms.append({
                "time_minutes": h * 60 + m,
                "time_str": time_m.group(0),
                "object_id": obj_m.group(0).upper(),
                "level": cells[3] if len(cells) > 3 else "?",
            })
    return alarms


def parse_evidence_kpi_times(evidence_text):
    """从 Evidence B（KPI）抽取 (time_minutes, object_id)"""
    out = []
    section = _extract_section(evidence_text, "Evidence B")
    if not section:
        return out
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        if any(k in line for k in ("对象", "时间", "---")):
            continue
        time_m = TIME_RE.search(line)
        obj_m = OBJECT_ID_RE.search(line)
        if time_m and obj_m:
            h, m = int(time_m.group(1)), int(time_m.group(2))
            out.append((h * 60 + m, obj_m.group(0).upper(), time_m.group(0)))
    return out


def parse_evidence_error_codes(evidence_text):
    """从 Evidence D（Error Statistics）抽取 (error_code, pct, object_id)

    返回: list of (code: str, pct: float, object_id: str)
    跳过占比 0% 的行（主动排除的语义，不算主要对象）。
    """
    out = []
    section = _extract_section(evidence_text, "Evidence D")
    if not section:
        return out
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        if any(k in line for k in ("错误码", "次数", "---")):
            continue
        code_m = re.search(r"\b(\d{4})\b", line)
        obj_m = OBJECT_ID_RE.search(line)
        if not (code_m and obj_m):
            continue
        # 解析占比列（Evidence D 表头是 [错误码, 次数, 占比, 主要对象]）
        pct = 0.0
        cells = [c.strip() for c in line.strip("|").split("|")]
        # 找到含 "X.X" 或 "X" 的浮点单元格
        for c in cells:
            c_clean = c.replace("%", "").strip()
            try:
                p = float(c_clean)
                # 占比应在 0-100 之间，且不是错误码本身（4 位数）
                if 0 <= p <= 100 and len(c_clean) <= 6:
                    pct = p
                    break
            except ValueError:
                continue
        # 跳过占比为 0 的行（主动排除，本就不算主要对象）
        if pct <= 0.0:
            continue
        out.append((code_m.group(1), pct, obj_m.group(0).upper()))
    return out


def parse_topology_upstream(evidence_text):
    """从 Evidence C（Topology）解析上下游映射
    返回 dict: {downstream_object: upstream_object}
    """
    section = _extract_section(evidence_text, "Evidence C")
    if not section:
        return {}
    upstream = {}
    # 解析 ASCII 图中的 → 链
    for line in section.splitlines():
        if "→" not in line:
            continue
        # 处理单链 A → B
        m = re.search(r"([A-Z][A-Z0-9\-]+)\s*→\s*([A-Z][A-Z0-9\-]+)", line)
        if m:
            # 同时找 object_id 的精确匹配
            up_candidates = OBJECT_ID_RE.findall(line)
            up_ids = [o.upper() for o in up_candidates]
            for i in range(len(up_ids) - 1):
                upstream[up_ids[i + 1]] = up_ids[i]
    return upstream


def _extract_section(text, label):
    """提取 ## label 段内容"""
    parts = re.split(r"\n##\s+", text)
    for p in parts:
        if p.startswith(label):
            return p
    return ""


def detect_conflicts(evidence_text, diag):
    """检测 4 类时间线冲突
    返回: list of {"rule": "C1|C2|C3|C4", "msg": str}
    """
    conflicts = []
    alarms = parse_evidence_alarms(evidence_text)
    kpis = parse_evidence_kpi_times(evidence_text)
    error_codes = parse_evidence_error_codes(evidence_text)
    upstream_map = parse_topology_upstream(evidence_text)

    # C1: 上下游时间倒挂
    if len(alarms) >= 2 and upstream_map:
        # 按对象聚合最早告警时间
        earliest_by_obj = {}
        for a in alarms:
            obj = a["object_id"]
            t = a["time_minutes"]
            if obj not in earliest_by_obj or t < earliest_by_obj[obj]:
                earliest_by_obj[obj] = t
        for downstream, upstream in upstream_map.items():
            if downstream in earliest_by_obj and upstream in earliest_by_obj:
                d_t = earliest_by_obj[downstream]
                u_t = earliest_by_obj[upstream]
                # 下游告警早于上游 ≥ 5 分钟 → 倒挂
                if d_t < u_t - 5:
                    h_d = f"{d_t // 60:02d}:{d_t % 60:02d}"
                    h_u = f"{u_t // 60:02d}:{u_t % 60:02d}"
                    conflicts.append({
                        "rule": "C1",
                        "msg": f"topology downstream '{downstream}' ({h_d}) alarm earlier than upstream '{upstream}' ({h_u}) by {u_t - d_t}min (causal inversion?)"
                    })

    # C2: 错误码先于告警—— 错误码主要对象不在告警对象集中
    #     只看占比 > 0% 的对象（占比 0% 已在 parse_evidence_error_codes 过滤）
    alarm_objs = {a["object_id"] for a in alarms}
    code_objs = {o for _, _, o in error_codes}
    if error_codes and alarms:
        # 错误码对象里有没有任何一个没有任何告警的对象？
        silent_objs = code_objs - alarm_objs
        if silent_objs:
            for o in silent_objs:
                obj_codes = [(c, p) for c, p, obj in error_codes if obj == o]
                total_pct = sum(p for _, p in obj_codes)
                if total_pct > 0:
                    conflicts.append({
                        "rule": "C2",
                        "msg": f"error code object '{o}' has no alarm in Evidence A but appears in Evidence D with {total_pct:.1f}% (silent fault or false alarm?)"
                    })

    # C3: KPI 起点早于告警
    if kpis and alarms:
        earliest_alarm = min(a["time_minutes"] for a in alarms)
        # KPI 时间 < earliest_alarm 且差异 ≥ 5 分钟
        early_kpis = [k for k in kpis if k[0] < earliest_alarm - 5]
        if early_kpis:
            t = min(k[0] for k in early_kpis)
            h_t = f"{t // 60:02d}:{t % 60:02d}"
            h_alarm = f"{earliest_alarm // 60:02d}:{earliest_alarm % 60:02d}"
            conflicts.append({
                "rule": "C3",
                "msg": f"KPI earliest time ({h_t}) earlier than earliest alarm ({h_alarm}) (KPI triggers before alert?)"
            })

    # C4: 错误码对象完全没任何 evidence（更严格的 C2）
    # 如果 error_codes 全部集中在某些对象，但 alarm_objs 完全不重叠
    if error_codes and code_objs and alarm_objs:
        if code_objs and alarm_objs.isdisjoint(code_objs):
            conflicts.append({
                "rule": "C4",
                "msg": f"error code objects {code_objs} disjoint from alarm objects {alarm_objs}"
            })

    return conflicts


def check_timeline_closure(diag, evidence_text):
    """V8 主函数：检测诊断输出与时间线冲突的一致性
    若存在冲突 + confidence=high → FAIL
    """
    conflicts = detect_conflicts(evidence_text, diag)
    errs = []
    if not conflicts:
        return errs
    # 存在冲突时，confidence 必须 ≤ medium
    overall_conf = diag.get("confidence", "")
    if overall_conf == "high":
        msgs = "; ".join(c["msg"] for c in conflicts)
        errs.append({
            "field": "timeline_closure",
            "rule": "V8",
            "msg": f"overall confidence=high but timeline conflict detected: {msgs} (should be medium/low/INSUFFICIENT_EVIDENCE)"
        })
    # 任何候选 confidence=high 也要 FAIL
    for rc in diag.get("top3_root_cause", []):
        if rc.get("confidence") == "high":
            msgs = "; ".join(c["msg"] for c in conflicts)
            errs.append({
                "field": "top3_root_cause.confidence",
                "rule": "V8",
                "msg": f"rank {rc.get('rank')} candidate confidence=high but timeline conflict: {msgs}"
            })
    return errs


if __name__ == "__main__":
    # CLI 自检
    import sys
    if len(sys.argv) >= 3:
        diag_p = Path(sys.argv[1])
        ev_p = Path(sys.argv[2])
        diag = json.loads(diag_p.read_text())
        if "diagnosis" in diag:
            diag = diag["diagnosis"]
        ev = ev_p.read_text()
        conflicts = detect_conflicts(ev, diag)
        print(f"Detected {len(conflicts)} conflicts:")
        for c in conflicts:
            print(f"  [{c['rule']}] {c['msg']}")
        if check_timeline_closure(diag, ev):
            print("V8 FAIL")
        else:
            print("V8 PASS")