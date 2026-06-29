#!/usr/bin/env python3
r"""
Evidence Pack Builder
=====================

职责：从结构化 case 输入（YAML / JSON）生成标准 Evidence Pack Markdown。
不调用 LLM，不调用网络，纯程序。

输入格式（YAML 或 JSON）：
  case_id: case-01
  case_name: OCS-BJ-02 连接池耗尽
  time_window: 最近 30 分钟
  evidence:
    - label: Evidence A
      type: Alarm
      rows:
        - {time: "14:25", object_id: "OCS-BJ-02", ...}
      notes: ...
    - label: Evidence B
      type: KPI
      rows: [...]
      notes: ...

输出：标准 Evidence Pack Markdown（Evidence A/B/C/D 命名）

**关键约束**：
- 禁止生成包含 Tool / T1-T7 / alert_query / kpi_trend_query 等词的 Evidence
- 所有 object_id 必须符合 [A-Z]{2,5}-[A-Z]{2,5}-<digits> 格式
- 错误码必须是 4 位数字

用法：
  python3 evidence_builder.py case.yaml > evidence.md
  python3 evidence_builder.py --validate case.yaml  # 校验不输出
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml  # 需要 PyYAML

# Evidence A/B/C/D 4 类（按 Vanson 拍板的命名规则）
EVIDENCE_TYPES = ["Alarm", "KPI", "Topology", "Error Statistics"]
EVIDENCE_LABELS = ["Evidence A", "Evidence B", "Evidence C", "Evidence D"]

# 禁止词清单（出现即 FAIL）
FORBIDDEN_WORDS = [
    "Tool", "Tools", "tool",
    "T1", "T2", "T3", "T4", "T5", "T6", "T7",
    "alert_query", "kpi_trend_query", "log_search", "topology_query",
    "function_call", "<functioncall>", "tool_calls",
]

OBJECT_ID_RE = re.compile(r"^[A-Z]{2,5}-[A-Z]{2,5}-\d{2}$")
ERROR_CODE_RE = re.compile(r"^\d{4}$")


def validate_case(case):
    """校验 case 结构 + 禁止词"""
    errs = []

    # 必填字段
    for f in ["case_id", "case_name", "time_window", "evidence"]:
        if f not in case:
            errs.append(f"missing required field: {f}")

    # evidence 必须是 4 段（A/B/C/D）
    evidence = case.get("evidence", [])
    if len(evidence) != 4:
        errs.append(f"evidence must have exactly 4 sections (A/B/C/D), got {len(evidence)}")

    # 校验每段
    for i, ev in enumerate(evidence):
        expected_label = EVIDENCE_LABELS[i]
        if ev.get("label") != expected_label:
            errs.append(f"evidence[{i}].label must be '{expected_label}', got '{ev.get('label')}'")
        if ev.get("type") != EVIDENCE_TYPES[i]:
            errs.append(f"evidence[{i}].type must be '{EVIDENCE_TYPES[i]}', got '{ev.get('type')}'")
        if "rows" not in ev and ev.get("type") != "Topology":
            errs.append(f"evidence[{i}] missing 'rows' (except Topology)")

    # 校验禁止词（递归检查所有字符串值）
    case_str = json.dumps(case, ensure_ascii=False, default=str)
    for word in FORBIDDEN_WORDS:
        if word in case_str:
            errs.append(f"forbidden word found: '{word}' (会触发 9B tool call loop)")

    return errs


def render_topology(topology_text, objects):
    """渲染 Topology 段为 ASCII 图"""
    lines = []
    lines.append("```")
    lines.append(topology_text)
    lines.append("```")
    lines.append("")
    lines.append("**对象清单**：")
    for obj in objects:
        lines.append(f"- {obj.get('id')}: {obj.get('role', '')}")
    return "\n".join(lines)


def render_table(rows, columns):
    """渲染 Markdown 表格"""
    if not rows:
        return "（无数据）"
    lines = []
    # 表头
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("|" + "|".join(["---"] * len(columns)) + "|")
    # 数据行
    for row in rows:
        cells = [str(row.get(col, "")) for col in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_evidence_pack(case):
    """渲染标准 Evidence Pack Markdown"""
    lines = []
    lines.append(f"# Evidence Pack — Case {case['case_id'].replace('case-', '')}: {case['case_name']}")
    lines.append("")
    lines.append(f"> **生成时间**：{case.get('generate_time', '<待定>')}")
    lines.append(f"> **时间窗口**：{case['time_window']}")
    lines.append("> **查询状态**：已查询完成（静态快照，不可调用）")
    lines.append(f"> **关联场景**：{case.get('scenario', 'CBS 用户充值失败')}")
    if case.get("expected_verify"):
        lines.append(f"> **期望验证**：{case['expected_verify']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for ev in case["evidence"]:
        label = ev["label"]
        ev_type = ev["type"]
        lines.append(f"## {label} — {ev_type}")
        lines.append("")
        if "description" in ev:
            lines.append(f"**说明**：{ev['description']}")
            lines.append("")

        if ev_type == "Topology":
            # 拓扑用 ASCII 图
            lines.append("```")
            lines.append(ev.get("graph", ""))
            lines.append("```")
            lines.append("")
            lines.append("**对象清单**：")
            for obj in ev.get("objects", []):
                lines.append(f"- {obj.get('id')}: {obj.get('role', '')}")
            if "notes" in ev:
                lines.append("")
                lines.append("**备注**：")
                for note in ev["notes"].split("\n"):
                    lines.append(f"- {note}")
        else:
            # Alarm / KPI / Error Statistics 用表格
            columns = ev.get("columns", [])
            if not columns and ev.get("rows"):
                columns = list(ev["rows"][0].keys())
            lines.append(render_table(ev.get("rows", []), columns))
            if "notes" in ev:
                lines.append("")
                lines.append("**备注**：")
                for note in ev["notes"].split("\n"):
                    lines.append(f"- {note}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Evidence Pack Builder")
    parser.add_argument("case_file", help="Case input file (YAML or JSON)")
    parser.add_argument("--validate", action="store_true", help="Only validate, no output")
    args = parser.parse_args()

    case_path = Path(args.case_file)
    if not case_path.exists():
        print(f"[FATAL] case file not found: {case_path}", file=sys.stderr)
        return 2

    # 读 case
    content = case_path.read_text(encoding="utf-8")
    if case_path.suffix in [".yaml", ".yml"]:
        case = yaml.safe_load(content)
    else:
        case = json.loads(content)

    # 校验
    errs = validate_case(case)
    if errs:
        print(f"[FAIL] {len(errs)} 项校验不通过：", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if args.validate:
        print(f"[PASS] Case {case.get('case_id', '?')} 校验通过（4 段 Evidence 命名合法，无禁止词）")
        return 0

    # 渲染
    print(render_evidence_pack(case))
    return 0


if __name__ == "__main__":
    sys.exit(main())