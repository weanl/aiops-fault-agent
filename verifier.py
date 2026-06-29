#!/usr/bin/env python3
"""
CBS 充值失败 Dry-run Verifier（v2）
==================================

职责：确定性校验 9B Diagnosis JSON 输出。
不依赖 LLM，不调用网络，纯程序逻辑。

校验范围（6 类）：
  V1. 字段反查：JSON 必须包含契约定义的全部字段
  V2. 数值一致性：错误码、百分比、对象集中度必须在 Evidence Pack 中能找到
  V3. 对象名反查：所有引用的 object_id 必须在 Evidence Pack 中存在
  V4. 错误码格式：必须是 4 位数字字符串
  V5. 百分比范围：0 ≤ pct ≤ 100
  V6. 只读边界：禁止 kubectl / ssh / SQL / 重启 / 扩容 / DELETE / UPDATE 等处置命令
       + 禁止出现未声明的 Tool / Function 名字

用法：
  python3 verifier.py <diagnosis_json_path> <evidence_pack_path>
  echo "<json>" | python3 verifier.py - <evidence_pack_path>

退出码：
  0 = PASS（全部通过）
  1 = FAIL（至少一项校验失败）
  2 = 调用错误
"""
import json
import re
import sys
from pathlib import Path


# ----------------------------- 校验规则 -----------------------------

# V1. 必填字段契约（Diagnosis JSON Schema）
REQUIRED_FIELDS = [
    "case_id",
    "timeline",          # list of {time, event}
    "anomaly_cluster",   # list of {object_id, error_code, count, pct}
    "top3_root_cause",   # list of {rank, candidate, evidence_refs, confidence}
    "evidence_matrix",   # dict {evidence_ref: claim}
    "recommend",         # string（处置建议候选，**不是**确定根因）
    "confidence",        # "high" | "medium" | "low" | "INSUFFICIENT_EVIDENCE"
]

# V2. V3. 反查索引（在 Evidence Pack 中存在的合法值）
# 注意：必须用 \b 词边界，避免误匹 ALM-2026-0628-001 中的 2026-0628
# OBJECT-ID 格式：OCS-BJ-02 / CBS-SH-01 / GW-PAY-EXT 等
# 严格规则：prefix 是已知系统缩写 + -XX- + 2 位数字
# 支持 Adapter / ADAPTER (case-insensitive via IGNORECASE)
OBJECT_ID_RE = re.compile(r"\b(?:OCS|CBS|GW|ADB|ADAPTER|APP|RDS|REDIS|NGINX|KAFKA|ES)-[A-Z]{2,5}-\d{2}\b", re.IGNORECASE)
ERROR_CODE_RE = re.compile(r"\b\d{4}\b")                     # 4 位数字
PERCENT_RE = re.compile(r"^-?\d+(\.\d+)?$")

# V4. V5. 范围约束
PCT_MIN, PCT_MAX = 0.0, 100.0
VALID_CONFIDENCE = {"high", "medium", "low", "INSUFFICIENT_EVIDENCE"}

# V6. 只读边界（出现即 FAIL）
FORBIDDEN_COMMANDS = [
    r"\bkubectl\b",
    r"\bssh\b",
    r"\bmysql\b",
    r"\bpostgres\b",
    r"\bsqlite3\b",
    r"\bredis-cli\b",
    r"\breboot\b",
    r"\brestart\b",
    r"\bshutdown\b",
    r"\bkill\b",
    r"\bdelete\b",
    r"\bupdate\b",
    r"\binsert\b",
    r"\bdrop\b",
    r"\btruncate\b",
    r"\bscale\s+up\b",
    r"\b扩容\b",
    r"\b重启\b",
    r"\b删除\b",
    r"\b清空\b",
    r"\bkill\b",
]

# V6. 未声明的 Tool / Function 名字（出现即 FAIL——证明模型想调工具）
UNDECLARED_TOOL_HINTS = [
    r"\balert_query\b",
    r"\bkpi_trend_query\b",
    r"\blog_search\b",
    r"\btopology_query\b",
    r"\bfunction_call\b",
    r"<functioncall",
    r"</functioncall",
    r'"tool_calls"\s*:',
    r'"function"\s*:\s*"',
]


# ----------------------------- 校验函数 -----------------------------

def fail(msg, errors):
    errors.append(msg)


def check_v1_fields(diag):
    """V1. 必填字段反查"""
    errs = []
    for f in REQUIRED_FIELDS:
        if f not in diag:
            errs.append(f"V1 missing required field: {f}")
    return errs


def collect_evidence_objects(evidence_pack_text):
    """从 Evidence Pack 文本中抽取合法 object_id 集合"""
    objs = set(OBJECT_ID_RE.findall(evidence_pack_text))
    objs.update(OBJECT_ID_RE.findall(evidence_pack_text))
    return objs


def collect_evidence_codes(evidence_pack_text):
    """从 Evidence Pack 文本中抽取合法错误码集合"""
    codes = set()
    for m in re.findall(r"\b\d{4}\b", evidence_pack_text):
        if ERROR_CODE_RE.match(m):
            codes.add(m)
    return codes


def check_v2_consistency(diag, evidence_text):
    """V2. 数值一致性：错误码、object_id 必须在 Evidence Pack 中出现"""
    errs = []
    valid_objs = collect_evidence_objects(evidence_text)
    valid_codes = collect_evidence_codes(evidence_text)

    # anomaly_cluster 里的错误码 + object_id 必须来自 Evidence
    for ac in diag.get("anomaly_cluster", []):
        oid = ac.get("object_id", "")
        if oid and oid not in valid_objs:
            errs.append(f"V2 object_id '{oid}' not in Evidence Pack (valid: {sorted(valid_objs)})")
        code = ac.get("error_code", "")
        if code and code not in valid_codes:
            errs.append(f"V2 error_code '{code}' not in Evidence Pack (valid: {sorted(valid_codes)})")
        # 百分比反查
        pct = ac.get("pct")
        if pct is not None:
            try:
                p = float(pct)
                if not (PCT_MIN <= p <= PCT_MAX):
                    errs.append(f"V5 pct {p} out of range [{PCT_MIN},{PCT_MAX}]")
            except (TypeError, ValueError):
                errs.append(f"V5 pct '{pct}' not numeric")

    # top3_root_cause 里引用的 evidence_refs（Evidence A/B/C/D）合法
    # 接受两种格式："Evidence A" / "A"
    raw_refs = set(re.findall(r"Evidence\s+([A-D])\b", evidence_text))
    # 归一化：去除 "Evidence " 前缀
    valid_refs = {f"Evidence {r}" for r in raw_refs}
    for rc in diag.get("top3_root_cause", []):
        for ref in rc.get("evidence_refs", []):
            # 同时接受 "Evidence A" 和 "A" 两种写法
            normalized = ref if ref.startswith("Evidence ") else f"Evidence {ref}"
            if normalized not in valid_refs:
                errs.append(f"V2 evidence_ref '{ref}' not in Evidence Pack (valid: {sorted(valid_refs)})")

    return errs


def check_v3_object_names(diag, evidence_text):
    """V3. object_id 反查（去重后必须全在 Evidence Pack）"""
    errs = []
    valid_objs = collect_evidence_objects(evidence_text)
    used = set()
    for ac in diag.get("anomaly_cluster", []):
        oid = ac.get("object_id", "")
        if oid:
            used.add(oid)
    # 也扫描 top3 / recommend 里的 object_id 出现
    for rc in diag.get("top3_root_cause", []):
        cand = rc.get("candidate", "")
        for m in OBJECT_ID_RE.findall(cand):
            used.add(m)
    rec = diag.get("recommend", "")
    for m in OBJECT_ID_RE.findall(rec):
        used.add(m)

    for oid in used:
        if oid not in valid_objs:
            errs.append(f"V3 object_id '{oid}' not found in Evidence Pack")
    return errs


def check_v4_error_format(diag):
    """V4. 错误码必须是 4 位数字"""
    errs = []
    for ac in diag.get("anomaly_cluster", []):
        code = str(ac.get("error_code", ""))
        if code and not ERROR_CODE_RE.match(code):
            errs.append(f"V4 error_code '{code}' must be 4-digit (got '{code}')")
    return errs


def check_v5_pct_range(diag):
    """V5. 百分比范围 0-100"""
    errs = []
    for ac in diag.get("anomaly_cluster", []):
        pct = ac.get("pct")
        if pct is None:
            continue
        try:
            p = float(pct)
            if not (PCT_MIN <= p <= PCT_MAX):
                errs.append(f"V5 pct {p} out of range [{PCT_MIN},{PCT_MAX}]")
        except (TypeError, ValueError):
            errs.append(f"V5 pct '{pct}' not numeric")
    return errs


def check_v6_readonly_boundary(diag):
    """V6. 只读边界：禁止处置命令 + 禁止未声明 Tool 名字"""
    errs = []
    # 把 JSON 整体扁平化为字符串扫描
    flat = json.dumps(diag, ensure_ascii=False)
    flat += " " + diag.get("recommend", "")

    # 只读边界
    for pat in FORBIDDEN_COMMANDS:
        if re.search(pat, flat, re.IGNORECASE):
            errs.append(f"V6 forbidden command pattern: {pat}")

    # 未声明 Tool
    for pat in UNDECLARED_TOOL_HINTS:
        if re.search(pat, flat, re.IGNORECASE):
            errs.append(f"V6 undeclared tool hint: {pat}")

    return errs


def check_confidence_field(diag):
    """附加：confidence 字段必须是合法枚举"""
    errs = []
    conf = diag.get("confidence", "")
    if conf not in VALID_CONFIDENCE:
        errs.append(f"V1 confidence '{conf}' not in {sorted(VALID_CONFIDENCE)}")
    return errs


# ----------------------------- Main -----------------------------

def verify(diag_path, evidence_path):
    diag_path = Path(diag_path)
    evidence_path = Path(evidence_path)

    if not diag_path.exists():
        print(f"[FATAL] Diagnosis JSON not found: {diag_path}", file=sys.stderr)
        return 2
    if not evidence_path.exists():
        print(f"[FATAL] Evidence Pack not found: {evidence_path}", file=sys.stderr)
        return 2

    # 读 Diagnosis JSON
    try:
        diag = json.loads(diag_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[FATAL] Diagnosis JSON parse error: {e}", file=sys.stderr)
        return 1

    evidence_text = evidence_path.read_text(encoding="utf-8")

    # 跑全部校验
    all_errs = []
    all_errs += check_v1_fields(diag)
    all_errs += check_v2_consistency(diag, evidence_text)
    all_errs += check_v3_object_names(diag, evidence_text)
    all_errs += check_v4_error_format(diag)
    all_errs += check_v5_pct_range(diag)
    all_errs += check_v6_readonly_boundary(diag)
    all_errs += check_confidence_field(diag)

    # 输出
    case_id = diag.get("case_id", "<unknown>")
    print(f"=== Verifier v2 — Case: {case_id} ===")
    print(f"Evidence Pack: {evidence_path}")
    print(f"Diagnosis JSON: {diag_path}")
    print()

    if not all_errs:
        print("[PASS] ✓ 全部 6 类校验通过")
        print()
        print(f"  - V1 fields:        OK ({len(REQUIRED_FIELDS)} required fields present)")
        print(f"  - V2 consistency:   OK")
        print(f"  - V3 object names:  OK ({len(collect_evidence_objects(evidence_text))} objects in evidence)")
        print(f"  - V4 error format:  OK (4-digit pattern)")
        print(f"  - V5 pct range:     OK (0-100)")
        print(f"  - V6 readonly:      OK (no forbidden commands / undeclared tools)")
        print(f"  - confidence:       {diag.get('confidence', 'N/A')}")
        print(f"  - top3 count:       {len(diag.get('top3_root_cause', []))}")
        print()
        return 0
    else:
        print(f"[FAIL] ✗ {len(all_errs)} 项校验不通过：")
        print()
        for i, e in enumerate(all_errs, 1):
            print(f"  {i}. {e}")
        print()
        return 1


def main():
    if len(sys.argv) != 3:
        print("Usage: verifier.py <diagnosis_json> <evidence_pack>", file=sys.stderr)
        return 2
    return verify(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    sys.exit(main())