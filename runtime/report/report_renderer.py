#!/usr/bin/env python3
"""
Report Renderer
===============

职责：把已经通过 verifier 的 Diagnosis JSON 渲染成 Markdown 报告。

**关键约束**：
- 只在 verifier PASS 后执行
- 不允许新增事实、数字、对象、命令、处置动作
- 所有内容必须来自输入 JSON

输入：diagnosis.json（包含 runner_meta 的 wrapper）
输出：report.md
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

# 避免 requests 走 http_proxy 拦截本地 vLLM
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_MODEL = "qwen3.5-9b-gptq4"
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TOP_P = 0.95


def extract_report_prompt_template(recipe_md):
    """从 Report Renderer recipe 中提取 Prompt 模板"""
    m = re.search(r"````markdown\n(.*?)\n````", recipe_md, re.DOTALL)
    if not m:
        raise ValueError("no report prompt template found")
    return m.group(1)


def call_vllm(prompt, base_url, model, max_tokens, temperature, top_p, timeout):
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def extract_markdown(response):
    if "choices" not in response or not response["choices"]:
        raise ValueError("vLLM response has no choices")
    msg = response["choices"][0]["message"]
    content = msg.get("content") or ""
    if not content.strip():
        raise ValueError(f"empty content, finish_reason={response['choices'][0].get('finish_reason')}")
    return content


def render_report(recipe_path, diagnosis_path, output_path, base_url, model,
                  max_tokens, temperature, top_p, timeout):
    """主流程：读 Report Recipe + Diagnosis JSON → 调 9B → 写 Markdown"""
    recipe_md = Path(recipe_path).read_text(encoding="utf-8")
    template = extract_report_prompt_template(recipe_md)

    diag_data = json.loads(Path(diagnosis_path).read_text(encoding="utf-8"))
    # 如果有 runner_meta wrapper，提取内部 diagnosis
    if "diagnosis" in diag_data and isinstance(diag_data["diagnosis"], dict):
        diag = diag_data["diagnosis"]
        meta = diag_data.get("runner_meta", {})
    else:
        diag = diag_data
        meta = {}

    # 拼 prompt
    prompt = template.replace("{paste verified_diagnosis_json_here}", json.dumps(diag, ensure_ascii=False, indent=2))

    print(f"[report] prompt chars: {len(prompt)}, est_tokens: {len(prompt)//4}")
    print(f"[report] calling 9B (thinking=false)...")
    t0 = time.time()
    try:
        response = call_vllm(prompt, base_url, model, max_tokens, temperature, top_p, timeout)
    except requests.exceptions.RequestException as e:
        print(f"[FATAL] vLLM call failed: {e}", file=sys.stderr)
        return 2
    elapsed = time.time() - t0

    try:
        markdown = extract_markdown(response)
    except ValueError as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 1

    # 写入
    header = f"<!-- 报告生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -->\n"
    header += f"<!-- Diagnosis 来源: {diagnosis_path} -->\n"
    header += f"<!-- 渲染耗时: {round(elapsed, 2)}s -->\n"
    header += f"<!-- 用量: {response.get('usage', {})} -->\n\n"
    Path(output_path).write_text(header + markdown, encoding="utf-8")
    print(f"[report] PASS: report written to {output_path}")
    print(f"  - elapsed: {round(elapsed, 2)}s")
    print(f"  - content chars: {len(markdown)}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Report Renderer (9B Markdown)")
    parser.add_argument("--recipe", required=True, help="Report Renderer recipe path")
    parser.add_argument("--diagnosis", required=True, help="Diagnosis JSON path (verified)")
    parser.add_argument("--out", required=True, help="Output report markdown path")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--top-p", type=float, default=DEFAULT_TOP_P)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    return render_report(
        args.recipe, args.diagnosis, args.out,
        args.base_url, args.model, args.max_tokens, args.temperature, args.top_p, args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())