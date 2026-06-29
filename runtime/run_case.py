#!/usr/bin/env python3
r"""
run_case.py — AIOps Fault Agent V2 Pipeline
============================================

把单条 Case 串成完整 pipeline：

  case input (YAML)
    ↓
  evidence pack (Markdown)
    ↓
  diagnosis JSON (via 9B + Recipe v2)
    ↓
  verifier (deterministic)
    ↓
  report Markdown (via 9B + Report Renderer, ONLY if verifier PASS)

**关键约束**：
- 任一步 FAIL 立即停
- 所有输出统一到 runs/<case_id>/ 目录
- verifier 是最终验收依据
- 9B 强制 enable_thinking=false
- 不接真实 OpenAPI（默认 vLLM 本地 9B）

用法：
  python3 run_case.py --case runtime/cases/case-01.yaml
  python3 run_case.py --case runtime/cases/case-01.yaml --skip-report
  python3 run_case.py --batch case-01 case-02 case-03
"""
import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
RUNTIME = PROJECT_ROOT / "runtime"
RUNS = RUNTIME / "runs"
RECIPE_V2 = PROJECT_ROOT / "recipe-cbs-charge-v2.md"
RECIPE_REPORT = PROJECT_ROOT / "recipe-cbs-charge-v2-report.md"


def step1_evidence(case_yaml, run_dir):
    """Step 1: case YAML → evidence.md"""
    out = run_dir / "evidence.md"
    print(f"\n[STEP 1] Evidence Builder: {case_yaml} -> {out}")
    result = subprocess.run(
        ["python3", str(RUNTIME / "evidence" / "evidence_builder.py"), str(case_yaml)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[FAIL] evidence_builder exit {result.returncode}")
        print(result.stderr)
        return False, None
    out.write_text(result.stdout, encoding="utf-8")
    print(f"[OK] evidence.md ({len(result.stdout)} chars)")
    return True, out


def step2_diagnosis(evidence_md, run_dir):
    """Step 2: evidence.md → diagnosis.json (via 9B)"""
    out = run_dir / "diagnosis.json"
    print(f"\n[STEP 2] Diagnosis Runner: {evidence_md} -> {out}")
    result = subprocess.run(
        [
            "python3", str(RUNTIME / "diagnosis" / "diagnosis_runner.py"),
            "--recipe", str(RECIPE_V2),
            "--evidence", str(evidence_md),
            "--out", str(out),
            "--token-budget", "4000",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[FAIL] diagnosis_runner exit {result.returncode}")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        return False, None
    print(result.stdout)
    return True, out


def step3_verifier(evidence_md, diagnosis_json, run_dir):
    """Step 3: diagnosis.json + evidence.md → verifier-result.json"""
    out = run_dir / "verifier-result.json"
    print(f"\n[STEP 3] Verifier: {diagnosis_json} + {evidence_md} -> {out}")
    result = subprocess.run(
        [
            "python3", str(RUNTIME / "verifier" / "verifier.py"), "run",
            "--evidence", str(evidence_md),
            "--diagnosis", str(diagnosis_json),
            "--out", str(out),
        ],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"[FAIL] verifier exit {result.returncode}")
        print(result.stderr)
        return False, out
    return True, out


def step4_report(verifier_result, diagnosis_json, run_dir):
    """Step 4: ONLY if verifier PASS → report.md"""
    out = run_dir / "report.md"
    print(f"\n[STEP 4] Report Renderer: {diagnosis_json} -> {out}")
    result = subprocess.run(
        [
            "python3", str(RUNTIME / "report" / "report_renderer.py"),
            "--recipe", str(RECIPE_REPORT),
            "--diagnosis", str(diagnosis_json),
            "--out", str(out),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[FAIL] report_renderer exit {result.returncode}")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        return False, None
    print(result.stdout)
    return True, out


def run_summary(case_id, run_dir, results, total_elapsed):
    """Step 5: 写 run-summary.md"""
    out = run_dir / "run-summary.md"
    lines = []
    lines.append(f"# Run Summary — {case_id}")
    lines.append("")
    lines.append(f"> **生成时间**：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> **总耗时**：{round(total_elapsed, 2)}s")
    lines.append(f"> **V2 框架**：数据/推理/校验/报告 职责分离")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Pipeline 结果")
    lines.append("")
    lines.append("| Step | 工具 | 状态 | 产物 |")
    lines.append("|------|------|:----:|------|")

    step_names = ["Step 1: Evidence", "Step 2: Diagnosis", "Step 3: Verifier", "Step 4: Report"]
    artifacts = ["evidence.md", "diagnosis.json", "verifier-result.json", "report.md"]
    for i, (name, ok) in enumerate(zip(step_names, results["steps"])):
        status = "✅ PASS" if ok else ("⏭️ SKIP" if results["steps"][i] is None and i == 3 else "❌ FAIL")
        lines.append(f"| {name} | (see code) | {status} | {artifacts[i]} |")
    lines.append("")

    lines.append("## 最终判定")
    lines.append("")
    final = "**PASS**" if results["verifier_passed"] else "**FAIL**"
    lines.append(f"- **Verifier verdict**: {final}")
    if results["verifier_result_path"]:
        try:
            v = json.loads(Path(results["verifier_result_path"]).read_text(encoding="utf-8"))
            if v.get("verdict") == "PASS":
                lines.append(f"- **Confidence**: {v.get('confidence', 'N/A')}")
                lines.append(f"- **Top-3 count**: {v.get('top3_count', 0)}")
            else:
                lines.append(f"- **Error count**: {v.get('error_count', 0)}")
                if v.get("errors"):
                    lines.append("")
                    lines.append("### 失败字段")
                    for e in v["errors"][:5]:  # 只列前 5 个
                        lines.append(f"- [{e.get('rule','?')}] {e.get('field','?')}: {e.get('msg','?')}")
        except Exception as e:
            lines.append(f"  (verifier result parse error: {e})")
    lines.append("")

    lines.append("## 产物清单")
    lines.append("")
    for f in run_dir.iterdir():
        lines.append(f"- `{f.relative_to(PROJECT_ROOT)}` ({f.stat().st_size} bytes)")
    lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[SUMMARY] {out}")
    return out


def run_case(case_yaml, skip_report=False):
    """串起一条 case 的完整 pipeline"""
    case_yaml = Path(case_yaml)
    if not case_yaml.exists():
        print(f"[FATAL] case file not found: {case_yaml}")
        return 1

    # 读 case_id
    import yaml
    case = yaml.safe_load(case_yaml.read_text(encoding="utf-8"))
    case_id = case.get("case_id", case_yaml.stem)

    # 准备 runs/<case_id>/
    run_dir = RUNS / case_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # 清空旧产物
    for f in run_dir.iterdir():
        f.unlink()

    print(f"\n{'='*60}")
    print(f"  Case: {case_id}  ({case.get('case_name', '?')})")
    print(f"  Run dir: {run_dir}")
    print(f"{'='*60}")

    results = {"steps": [False, False, False, None], "verifier_passed": False, "verifier_result_path": None}
    t0 = time.time()

    # Step 1: Evidence
    ok, evidence_md = step1_evidence(case_yaml, run_dir)
    results["steps"][0] = ok
    if not ok:
        return run_summary_and_exit(case_id, run_dir, results, time.time() - t0)

    # Step 2: Diagnosis
    ok, diagnosis_json = step2_diagnosis(evidence_md, run_dir)
    results["steps"][1] = ok
    if not ok:
        return run_summary_and_exit(case_id, run_dir, results, time.time() - t0)

    # Step 3: Verifier
    ok, verifier_result = step3_verifier(evidence_md, diagnosis_json, run_dir)
    results["steps"][2] = ok
    results["verifier_result_path"] = str(verifier_result)
    # 读 verifier verdict
    try:
        v = json.loads(Path(verifier_result).read_text(encoding="utf-8"))
        results["verifier_passed"] = (v.get("verdict") == "PASS")
    except Exception:
        results["verifier_passed"] = False
    if not ok or not results["verifier_passed"]:
        return run_summary_and_exit(case_id, run_dir, results, time.time() - t0)

    # Step 4: Report（仅 verifier PASS 时）
    if skip_report:
        print("\n[STEP 4] SKIPPED (--skip-report)")
    else:
        ok, report_md = step4_report(verifier_result, diagnosis_json, run_dir)
        results["steps"][3] = ok

    return run_summary_and_exit(case_id, run_dir, results, time.time() - t0)


def run_summary_and_exit(case_id, run_dir, results, elapsed):
    run_summary(case_id, run_dir, results, elapsed)
    return 0 if all(s in (True, None) for s in results["steps"]) else 1


def main():
    parser = argparse.ArgumentParser(description="AIOps Fault Agent V2 Pipeline Runner")
    parser.add_argument("--case", help="Single case YAML file")
    parser.add_argument("--batch", nargs="+", help="Batch run by case_id (without .yaml)")
    parser.add_argument("--skip-report", action="store_true", help="Skip Step 4 (report)")
    args = parser.parse_args()

    if args.case:
        return run_case(args.case, skip_report=args.skip_report)

    if args.batch:
        # 串行跑多条 case
        results = []
        for cid in args.batch:
            case_path = RUNTIME / "cases" / f"{cid}.yaml"
            if not case_path.exists():
                print(f"[FATAL] case not found: {case_path}")
                results.append((cid, 2))
                continue
            code = run_case(case_path, skip_report=args.skip_report)
            results.append((cid, code))
        # 总结
        print(f"\n{'='*60}")
        print(f"  Batch Run Summary ({len(results)} cases)")
        print(f"{'='*60}")
        for cid, code in results:
            print(f"  {cid}: {'PASS' if code == 0 else 'FAIL'} (exit {code})")
        return 0 if all(c == 0 for _, c in results) else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())