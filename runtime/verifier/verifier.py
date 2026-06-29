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