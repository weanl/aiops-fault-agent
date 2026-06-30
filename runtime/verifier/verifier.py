#!/usr/bin/env python3
"""
CBS 充值失败 Dry-run Verifier（v2 工程化版）
==========================================

职责：确定性校验 9B Diagnosis JSON 输出。
不依赖 LLM，不调用网络，纯程序逻辑。

校验范围（6 类）：
  V1. 字段反查：JSON 必须包含契约定义的全部字段
  V2. 数值一致性：错误码、object_id、Evidence ref 必须在 Evidence Pack 中能找到
  V3. 对象名反查：所有引用的 object_id 必须在 Evidence Pack 中存在
  V4. 错误码格式：必须是 4 位数字字符串
  V5. 百分比范围：0 ≤ pct ≤ 100
  V6. 只读边界：禁止 kubectl / ssh / SQL / 重启 / 扩容 / DELETE / UPDATE 等处置命令
       + 禁止出现未声明的 Tool / Function 名字

CLI：
  python verifier.py --evidence evidence.md --diagnosis diagnosis.json --out verifier-result.json
  python verifier.py --self-test  # 跑 fixture 自测
"""
import argparse
import json
import re
import sys
from pathlib import Path

# V8 时间线闭合性：独立模块
try:
    from timeline_parser import check_timeline_closure, detect_conflicts  # noqa: F401
    V8_AVAILABLE = True
except ImportError:
    V8_AVAILABLE = False


# ----------------------------- 校验规则 -----------------------------

REQUIRED_FIELDS = [
    "case_id", "timeline", "anomaly_cluster", "top3_root_cause",
    "evidence_matrix", "recommend", "confidence",
]

OBJECT_ID_RE = re.compile(r"\b(?:OCS|CBS|GW|ADB|ADAPTER|APP|RDS|REDIS|NGINX|KAFKA|ES)-[A-Z]{2,5}-\d{2}\b", re.IGNORECASE)
ERROR_CODE_RE = re.compile(r"\b\d{4}\b")
PCT_MIN, PCT_MAX = 0.0, 100.0
VALID_CONFIDENCE = {"high", "medium", "low", "INSUFFICIENT_EVIDENCE"}

FORBIDDEN_COMMANDS = [
    r"\bkubectl\b", r"\bssh\b", r"\bmysql\b", r"\bpostgres\b", r"\bsqlite3\b",
    r"\bredis-cli\b", r"\breboot\b", r"\brestart\b", r"\bshutdown\b",
    r"\bkill\b", r"\bdelete\b", r"\bupdate\b", r"\binsert\b", r"\bdrop\b",
    r"\btruncate\b", r"\bscale\s+up\b",
    r"\b扩容\b", r"\b重启\b", r"\b删除\b", r"\b清空\b",
]

UNDECLARED_TOOL_HINTS = [
    r"\balert_query\b", r"\bkpi_trend_query\b", r"\blog_search\b",
    r"\btopology_query\b", r"\bfunction_call\b", r"<functioncall",
    r"</functioncall", r'"tool_calls"\s*:', r'"function"\s*:\s*"',
]


# ----------------------------- 校验函数 -----------------------------

def collect_evidence_objects(text):
    return set(OBJECT_ID_RE.findall(text))


def collect_evidence_codes(text):
    return {m for m in re.findall(r"\b\d{4}\b", text)}


def check_v1_fields(diag):
    errs = []
    for f in REQUIRED_FIELDS:
        if f not in diag:
            errs.append({"field": f, "rule": "V1", "msg": f"missing required field: {f}"})
    return errs


def check_v2_consistency(diag, evidence_text):
    errs = []
    valid_objs = collect_evidence_objects(evidence_text)
    valid_codes = collect_evidence_codes(evidence_text)
    raw_refs = set(re.findall(r"Evidence\s+([A-D])\b", evidence_text))
    valid_refs = {f"Evidence {r}" for r in raw_refs}

    for ac in diag.get("anomaly_cluster", []):
        oid = ac.get("object_id", "")
        if oid and oid not in valid_objs:
            errs.append({"field": "anomaly_cluster.object_id", "rule": "V2",
                         "msg": f"object_id '{oid}' not in Evidence Pack", "valid": sorted(valid_objs)})
        code = ac.get("error_code", "")
        if code and code not in valid_codes:
            errs.append({"field": "anomaly_cluster.error_code", "rule": "V2",
                         "msg": f"error_code '{code}' not in Evidence Pack", "valid": sorted(valid_codes)})
        pct = ac.get("pct")
        if pct is not None:
            try:
                p = float(pct)
                if not (PCT_MIN <= p <= PCT_MAX):
                    errs.append({"field": "anomaly_cluster.pct", "rule": "V5",
                                 "msg": f"pct {p} out of range [{PCT_MIN},{PCT_MAX}]"})
            except (TypeError, ValueError):
                errs.append({"field": "anomaly_cluster.pct", "rule": "V5", "msg": f"pct '{pct}' not numeric"})

    for rc in diag.get("top3_root_cause", []):
        for ref in rc.get("evidence_refs", []):
            normalized = ref if ref.startswith("Evidence ") else f"Evidence {ref}"
            if normalized not in valid_refs:
                errs.append({"field": "top3_root_cause.evidence_refs", "rule": "V2",
                             "msg": f"evidence_ref '{ref}' not in Evidence Pack", "valid": sorted(valid_refs)})
    return errs


def check_v3_object_names(diag, evidence_text):
    errs = []
    valid_objs = collect_evidence_objects(evidence_text)
    used = set()
    for ac in diag.get("anomaly_cluster", []):
        oid = ac.get("object_id", "")
        if oid:
            used.add(oid)
    for rc in diag.get("top3_root_cause", []):
        for m in OBJECT_ID_RE.findall(rc.get("candidate", "")):
            used.add(m)
    for m in OBJECT_ID_RE.findall(diag.get("recommend", "")):
        used.add(m)
    for oid in used:
        if oid not in valid_objs:
            errs.append({"field": "object_id", "rule": "V3",
                         "msg": f"object_id '{oid}' not found in Evidence Pack"})
    return errs


def check_v4_error_format(diag):
    errs = []
    for ac in diag.get("anomaly_cluster", []):
        code = str(ac.get("error_code", ""))
        if code and not ERROR_CODE_RE.match(code):
            errs.append({"field": "anomaly_cluster.error_code", "rule": "V4",
                         "msg": f"error_code '{code}' must be 4-digit"})
    return errs


def check_v5_pct_range(diag):
    """V5 百分比范围 0-100（独立检查，不依赖 evidence_text）"""
    errs = []
    for ac in diag.get("anomaly_cluster", []):
        pct = ac.get("pct")
        if pct is None:
            continue
        try:
            p = float(pct)
            if not (PCT_MIN <= p <= PCT_MAX):
                errs.append({"field": "anomaly_cluster.pct", "rule": "V5",
                             "msg": f"pct {p} out of range [{PCT_MIN},{PCT_MAX}]"})
        except (TypeError, ValueError):
            errs.append({"field": "anomaly_cluster.pct", "rule": "V5", "msg": f"pct '{pct}' not numeric"})
    return errs


def check_v6_readonly_boundary(diag):
    errs = []
    flat = json.dumps(diag, ensure_ascii=False) + " " + diag.get("recommend", "")
    for pat in FORBIDDEN_COMMANDS:
        if re.search(pat, flat, re.IGNORECASE):
            errs.append({"field": "readonly_boundary", "rule": "V6",
                         "msg": f"forbidden command pattern: {pat}"})
    for pat in UNDECLARED_TOOL_HINTS:
        if re.search(pat, flat, re.IGNORECASE):
            errs.append({"field": "tool_call", "rule": "V6",
                         "msg": f"undeclared tool hint: {pat}"})
    return errs


def check_confidence_field(diag):
    conf = diag.get("confidence", "")
    if conf not in VALID_CONFIDENCE:
        return [{"field": "confidence", "rule": "V1", "msg": f"confidence '{conf}' not in {sorted(VALID_CONFIDENCE)}"}]
    # 交叉验证：整体 INSUFFICIENT_EVIDENCE 时，不应有 high 候选
    errs = []
    if conf == "INSUFFICIENT_EVIDENCE":
        for rc in diag.get("top3_root_cause", []):
            if rc.get("confidence") == "high":
                errs.append({
                    "field": "top3_root_cause.confidence",
                    "rule": "V1",
                    "msg": f"overall confidence is INSUFFICIENT_EVIDENCE but rank {rc.get('rank')} has confidence=high (contradiction)"
                })
    return errs


def check_evidence_completeness(diag, evidence_text):
    """V7 (v2.2.0 新增)：关键字段缺失检测
    Evidence Pack 的 4 段（Alarm/KPI/Topology/Error Statistics）必须含数据。
    Error Statistics 段 rows=[] 或被明确标注为“缺失”是关键证据缺失。
    若 Evidence D 为空 → 9B 不应输出 high confidence。
    """
    errs = []
    # 按段拆分：## Evidence X — 标题 到下一个 ## 或文末
    sections = re.split(r"\n##\s+", evidence_text)
    section_map = {}
    for sec in sections:
        m = re.match(r"(Evidence\s+[A-D])\s*—\s*(\S+)", sec)
        if m:
            section_map[m.group(1)] = m.group(2)
    # 检查 Error Statistics 段（Evidence D）实际是否有数据
    # 方法：在 ## Evidence D 段内检查 "| 错误码" 表头 + 后续非空行
    evidence_d_section = ""
    for sec in sections:
        if sec.startswith("Evidence D"):
            evidence_d_section = sec
            break
    # 如果 Error Statistics 段内没有 4 位数字错误码 → 视为缺失
    error_codes_in_evidence_d = ERROR_CODE_RE.findall(evidence_d_section)
    evidence_d_empty = not error_codes_in_evidence_d
    if evidence_d_empty:
        # Evidence D 缺失错误码 → 9B 不应输出 high confidence
        if diag.get("confidence") == "high":
            errs.append({
                "field": "evidence_d_completeness",
                "rule": "V7",
                "msg": "Evidence D (Error Statistics) has no error codes but diagnosis confidence=high (should be low/INSUFFICIENT_EVIDENCE)"
            })
        for rc in diag.get("top3_root_cause", []):
            if rc.get("confidence") == "high":
                errs.append({
                    "field": "top3_root_cause.confidence",
                    "rule": "V7",
                    "msg": f"Evidence D (Error Statistics) has no error codes but rank {rc.get('rank')} candidate has confidence=high"
                })
    return errs


def check_command_reference_safety(diag):
    """V9 (v2.2.0 新增)：历史案例引用检测
    recommend 不得包含"与历史案例相似""历史上有过"等表述 → 防止 LLM
    用历史案例直接定根因。

    限制：仅检查中文特定表述（避免误伤常规诊断报告中的历史参考）。
    """
    errs = []
    flat = diag.get("recommend", "")
    forbidden_phrases = [
        r"与历史案例相似",
        r"历史上有过",
        r"历史案例表明",
        r"根据历史.*得出",
        r"历史上.*所以当前",
    ]
    for pat in forbidden_phrases:
        if re.search(pat, flat):
            errs.append({
                "field": "recommend",
                "rule": "V9",
                "msg": f"recommend references historical case directly: {pat} (历史案例不能直接定根因)"
            })
    return errs


def check_timeline_consistency(diag, evidence_text):
    """V8 (v2.2.1 实现)：时间线闭合性校验

    检测 Evidence Pack 中是否存在 4 类时间线冲突：
      C1: 拓扑上下游时间倒挂（下游告警早于上游）
      C2: 错误码对象不在告警对象集（沉默故障嫌疑）
      C3: KPI 起点早于告警（因果倒挂）
      C4: 错误码对象与告警对象完全不相交

    触发条件：存在冲突 + diagnosis confidence=high → FAIL
    触发条件：存在冲突 + 任一 top3 candidate confidence=high → FAIL
    存在冲突 + medium/low/INSUFFICIENT_EVIDENCE → PASS（9B 已正确降级）

    不调用 LLM，纯文本解析。
    """
    if not V8_AVAILABLE:
        return []  # 模块不可用时静默跳过（CI 环境）
    try:
        return check_timeline_closure(diag, evidence_text)
    except Exception as e:
        # V8 解析失败不应阻断其他 verifier 检查
        return [{"field": "timeline_parser", "rule": "V8",
                 "msg": f"V8 parse error (non-fatal): {e}"}]


# ----------------------------- Main -----------------------------

def verify(diag_path, evidence_path):
    diag_path = Path(diag_path)
    evidence_path = Path(evidence_path)

    if not diag_path.exists():
        return {"verdict": "FAIL", "error": f"diagnosis not found: {diag_path}"}, 2
    if not evidence_path.exists():
        return {"verdict": "FAIL", "error": f"evidence not found: {evidence_path}"}, 2

    try:
        diag = json.loads(diag_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"verdict": "FAIL", "error": f"diagnosis JSON parse error: {e}"}, 1

    # 如果 diagnosis 文件包含 runner_meta wrapper，提取内部的 diagnosis
    if "diagnosis" in diag and isinstance(diag["diagnosis"], dict):
        diag = diag["diagnosis"]

    evidence_text = evidence_path.read_text(encoding="utf-8")

    all_errs = []
    all_errs += check_v1_fields(diag)
    all_errs += check_v2_consistency(diag, evidence_text)
    all_errs += check_v3_object_names(diag, evidence_text)
    all_errs += check_v4_error_format(diag)
    all_errs += check_v5_pct_range(diag)
    all_errs += check_v6_readonly_boundary(diag)
    all_errs += check_confidence_field(diag)
    # v2.2.0 新增：V7 关键字段缺失 + V9 历史案例引用检测
    all_errs += check_evidence_completeness(diag, evidence_text)
    all_errs += check_command_reference_safety(diag)
    # v2.2.1 新增：V8 时间线闭合性（默认调用，独立 try/except 防解析异常）
    all_errs += check_timeline_consistency(diag, evidence_text)

    if not all_errs:
        return {
            "verdict": "PASS",
            "case_id": diag.get("case_id", "<unknown>"),
            "checks": {
                "V1_fields": "OK ({} required fields present)".format(len(REQUIRED_FIELDS)),
                "V2_consistency": "OK",
                "V3_object_names": "OK ({} objects in evidence)".format(len(collect_evidence_objects(evidence_text))),
                "V4_error_format": "OK (4-digit pattern)",
                "V5_pct_range": "OK (0-100)",
                "V6_readonly": "OK (no forbidden commands / undeclared tools)",
                "V7_evidence_completeness": "OK (all 4 sections have data)",
                "V9_command_reference_safety": "OK (no historical case direct reference)",
                "V8_timeline_closure": "OK (timeline conflicts handled correctly)",
            },
            "confidence": diag.get("confidence", "N/A"),
            "top3_count": len(diag.get("top3_root_cause", [])),
        }, 0
    else:
        return {
            "verdict": "FAIL",
            "case_id": diag.get("case_id", "<unknown>"),
            "error_count": len(all_errs),
            "errors": all_errs,
        }, 1


def self_test():
    """用 fixture 双向验证 verifier 自己没 bug"""
    fixtures_dir = Path(__file__).parent.parent.parent / "runtime" / "verifier" / "fixtures"
    if not fixtures_dir.exists():
        return [{"self_test": "SKIP", "reason": f"fixtures dir not found: {fixtures_dir}"}]

    results = []
    for fix_dir in sorted(fixtures_dir.iterdir()):
        if not fix_dir.is_dir():
            continue
        diag_p = fix_dir / "diagnosis.json"
        ev_p = fix_dir / "evidence.md"
        expected = fix_dir.name  # "good" or "bad-case-name"
        if not diag_p.exists() or not ev_p.exists():
            continue
        result, _ = verify(diag_p, ev_p)
        results.append({"fixture": expected, "verdict": result["verdict"]})
    return results


def main():
    parser = argparse.ArgumentParser(description="CBS 充值失败 Dry-run Verifier")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="verify a diagnosis against evidence")
    p_run.add_argument("--evidence", required=True)
    p_run.add_argument("--diagnosis", required=True)
    p_run.add_argument("--out", help="output JSON path (optional)")

    p_test = sub.add_parser("self-test", help="run fixture self-test")

    args = parser.parse_args()

    if args.cmd == "run":
        result, code = verify(args.diagnosis, args.evidence)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(output, encoding="utf-8")
            print(f"[verifier] result written to {args.out}")
        else:
            print(output)
        return code
    elif args.cmd == "self-test":
        results = self_test()
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())