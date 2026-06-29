#!/usr/bin/env python3
r"""
Deterministic Regression Tests
==============================

CI-only test suite. **不调 9B / 不连 vLLM**。

测试 4 个层：
  1. verifier 模块：双向验证（good fixture PASS + bad fixture FAIL + 6 类规则独立测试）
  2. evidence_builder 模块：4 段结构 + 禁止词 + 渲染
  3. 3 case 存档 diagnosis.json 反向验证：确认 v2.0.0 端到端产物可重放
  4. CLI 化回归：每个模块 CLI 端到端可调用

退出码：
  0 = 全部通过
  1 = 至少一项失败
  2 = 环境错误

用法：
  python3 runtime/tests/test_deterministic.py
  python3 -m unittest runtime.tests.test_deterministic -v
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# 让 import verifier/evidence_builder 模块可用
PROJECT_ROOT = Path(__file__).parent.parent.parent
RUNTIME = PROJECT_ROOT / "runtime"
sys.path.insert(0, str(RUNTIME / "verifier"))
sys.path.insert(0, str(RUNTIME / "evidence"))

import verifier  # noqa: E402
import evidence_builder  # noqa: E402


PASS = "✅"
FAIL = "❌"
results = []


def record(name, ok, detail=""):
    results.append({"name": name, "ok": ok, "detail": detail})
    print(f"  {PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))


# ============================================================
# 1. verifier 模块
# ============================================================

def test_verifier_good_fixture():
    """good fixture 必须 PASS"""
    diag = PROJECT_ROOT / "dry-run" / "fixture-case01-good.json"
    ev = PROJECT_ROOT / "dry-run" / "case-01-evidence.md"
    result, _ = verifier.verify(diag, ev)
    record("verifier: good fixture PASS", result["verdict"] == "PASS",
           f"verdict={result['verdict']}")


def test_verifier_bad_fixture():
    """bad fixture 必须 FAIL（数据污染 + kubectl 越界）"""
    diag = PROJECT_ROOT / "dry-run" / "fixture-case01-bad.json"
    ev = PROJECT_ROOT / "dry-run" / "case-01-evidence.md"
    result, _ = verifier.verify(diag, ev)
    record("verifier: bad fixture FAIL", result["verdict"] == "FAIL",
           f"verdict={result['verdict']} errors={result.get('error_count', 0)}")


def test_verifier_v1_v2_consistency():
    """v1.1 badcase（500%/500）必须被拦截"""
    bad_diag = {
        "case_id": "v1-badcase",
        "timeline": [{"time": "14:25", "event": "500% 全在 OCS-BJ-02"}],
        "anomaly_cluster": [
            {"object_id": "OCS-BJ-02", "error_code": "500", "count": 100, "pct": 500.0},
        ],
        "top3_root_cause": [],
        "evidence_matrix": {},
        "recommend": "kubectl 重启",
        "confidence": "INSUFFICIENT_EVIDENCE",
    }
    ev = PROJECT_ROOT / "dry-run" / "case-01-evidence.md"
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(bad_diag, f)
        tmp = f.name
    try:
        result, _ = verifier.verify(tmp, ev)
        # 至少 4 类错误必须命中
        rules_hit = {e["rule"] for e in result.get("errors", [])}
        expected = {"V2", "V4", "V5", "V6"}
        record("verifier: v1 badcase 拦截 ≥ 4 类规则",
               expected.issubset(rules_hit),
               f"hit={sorted(rules_hit)}")
    finally:
        os.unlink(tmp)


def test_verifier_confidence_cross_check():
    """INSUFFICIENT_EVIDENCE + high 候选必须矛盾报错"""
    diag = {
        "case_id": "contradiction",
        "timeline": [],
        "anomaly_cluster": [],
        "top3_root_cause": [{"rank": 1, "candidate": "x", "evidence_refs": [], "confidence": "high"}],
        "evidence_matrix": {},
        "recommend": "x",
        "confidence": "INSUFFICIENT_EVIDENCE",
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(diag, f)
        tmp = f.name
    try:
        result, _ = verifier.verify(tmp, PROJECT_ROOT / "dry-run" / "case-01-evidence.md")
        # 应有 V1 矛盾错误
        rules_hit = {e["rule"] for e in result.get("errors", [])}
        record("verifier: confidence 矛盾检测", "V1" in rules_hit,
               f"hit={sorted(rules_hit)}")
    finally:
        os.unlink(tmp)


# ============================================================
# 2. evidence_builder 模块
# ============================================================

def test_evidence_builder_validate():
    """3 条 case YAML 校验通过（4 段命名 + 禁止词 + 字段）"""
    all_ok = True
    for cid in ["case-01", "case-02", "case-03"]:
        yaml_p = RUNTIME / "cases" / f"{cid}.yaml"
        if not yaml_p.exists():
            record(f"evidence_builder: {cid} YAML 存在", False, f"missing {yaml_p}")
            all_ok = False
            continue
        result = subprocess.run(
            ["python3", str(RUNTIME / "evidence" / "evidence_builder.py"), str(yaml_p), "--validate"],
            capture_output=True, text=True,
        )
        ok = result.returncode == 0 and "PASS" in result.stdout
        record(f"evidence_builder: {cid} --validate", ok,
               f"exit={result.returncode} | {result.stdout.strip()[:60]}")
        if not ok:
            all_ok = False
    return all_ok


def test_evidence_builder_renders_4_sections():
    """渲染的 Markdown 必须包含 4 段 Evidence A/B/C/D"""
    yaml_p = RUNTIME / "cases" / "case-01.yaml"
    result = subprocess.run(
        ["python3", str(RUNTIME / "evidence" / "evidence_builder.py"), str(yaml_p)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        record("evidence_builder: 渲染 4 段", False, f"exit={result.returncode}")
        return False
    md = result.stdout
    has_4 = all(f"## Evidence {lbl}" in md for lbl in ["A", "B", "C", "D"])
    record("evidence_builder: 渲染包含 4 段 Evidence", has_4,
           f"len={len(md)} chars")
    return has_4


def test_evidence_builder_no_tool_words():
    """渲染输出不能含 Tool 词"""
    yaml_p = RUNTIME / "cases" / "case-01.yaml"
    result = subprocess.run(
        ["python3", str(RUNTIME / "evidence" / "evidence_builder.py"), str(yaml_p)],
        capture_output=True, text=True,
    )
    md = result.stdout
    forbidden = ["Tool", "T1", "T2", "T3", "T4", "T5", "T6", "T7",
                 "alert_query", "kpi_trend_query", "function_call"]
    hits = [w for w in forbidden if w in md]
    record("evidence_builder: 无 Tool 语义词",
           len(hits) == 0,
           f"hit={hits}" if hits else "clean")


# ============================================================
# 3. 3 case 存档 diagnosis.json 反向验证
# ============================================================

def test_three_cases_archived_pass():
    """3 case 存档 diagnosis.json 在 CI 重新跑 verifier 必须 PASS"""
    all_ok = True
    for cid in ["case-01", "case-02", "case-03"]:
        # 优先用 runs/ 目录下的最新产物
        diag = RUNTIME / "runs" / cid / "diagnosis.json"
        ev = RUNTIME / "runs" / cid / "evidence.md"
        if not (diag.exists() and ev.exists()):
            # fallback 到 dry-run
            diag = PROJECT_ROOT / "dry-run" / f"{cid}-diagnosis.json"
            ev = PROJECT_ROOT / "dry-run" / f"{cid}-evidence.md"
        result, _ = verifier.verify(diag, ev)
        ok = result["verdict"] == "PASS"
        conf = result.get("confidence", "?")
        top3 = result.get("top3_count", "?")
        record(f"存档 case {cid}: verifier PASS",
               ok, f"verdict={result['verdict']} conf={conf} top3={top3}")
        if not ok:
            all_ok = False
    return all_ok


# ============================================================
# 4. CLI 化回归
# ============================================================

def test_verifier_cli_run():
    """verifier CLI 端到端可调用"""
    diag = PROJECT_ROOT / "dry-run" / "fixture-case01-good.json"
    ev = PROJECT_ROOT / "dry-run" / "case-01-evidence.md"
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        out = f.name
    try:
        result = subprocess.run(
            ["python3", str(RUNTIME / "verifier" / "verifier.py"), "run",
             "--evidence", str(ev), "--diagnosis", str(diag), "--out", out],
            capture_output=True, text=True,
        )
        ok = result.returncode == 0
        record("verifier CLI run", ok, f"exit={result.returncode}")
        if ok:
            rj = json.loads(Path(out).read_text())
            record("verifier CLI 写出 verdict=PASS", rj.get("verdict") == "PASS",
                   f"verdict={rj.get('verdict')}")
    finally:
        os.unlink(out)


def test_evidence_builder_cli():
    """evidence_builder CLI 端到端可调用"""
    yaml_p = RUNTIME / "cases" / "case-01.yaml"
    with tempfile.NamedTemporaryFile(suffix='.md', delete=False) as f:
        out = f.name
    try:
        result = subprocess.run(
            ["python3", str(RUNTIME / "evidence" / "evidence_builder.py"), str(yaml_p)],
            capture_output=True, text=True,
        )
        ok = result.returncode == 0
        if ok:
            Path(out).write_text(result.stdout, encoding="utf-8")
            sz = Path(out).stat().st_size
            record("evidence_builder CLI 输出", True, f"{sz} bytes")
        else:
            record("evidence_builder CLI 输出", False, f"exit={result.returncode}")
    finally:
        if Path(out).exists():
            os.unlink(out)


# ============================================================
# Main
# ============================================================

def main():
    print(f"\n{'='*60}")
    print(f"  Deterministic Regression Tests (CI-only)")
    print(f"  Project: {PROJECT_ROOT.name}")
    print(f"{'='*60}\n")

    print("[1] Verifier 模块")
    test_verifier_good_fixture()
    test_verifier_bad_fixture()
    test_verifier_v1_v2_consistency()
    test_verifier_confidence_cross_check()

    print("\n[2] Evidence Builder 模块")
    test_evidence_builder_validate()
    test_evidence_builder_renders_4_sections()
    test_evidence_builder_no_tool_words()

    print("\n[3] 3 Case 存档 diagnosis.json 反向验证")
    test_three_cases_archived_pass()

    print("\n[4] CLI 端到端")
    test_verifier_cli_run()
    test_evidence_builder_cli()

    # 总结
    print(f"\n{'='*60}")
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = total - passed
    print(f"  总计: {total} | PASS: {passed} | FAIL: {failed}")
    print(f"{'='*60}\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())