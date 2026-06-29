#!/usr/bin/env python3
"""
Diagnosis Runner
================

职责：调用 9B 执行 Recipe v2，输出 Diagnosis JSON。

**关键约束（Vanson 拍板固化）**：
- 强制 `chat_template_kwargs.enable_thinking=false`（reasoning 占 token 太多）
- 限制输入 token 预算（默认 4000）
- 不允许 tool call（Recipe v2 Prompt 已经是 Offline Dry-run Mode）
- 失败立即返回，不重试

输入：recipe-cbs-charge-v2.md 模板 + evidence.md
输出：diagnosis.json
"""
import argparse
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

# 9B vLLM 配置
DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_MODEL = "qwen3.5-9b-gptq4"
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TOP_P = 0.95
# 4k token 预算（Vanson 7:13 红线）
DEFAULT_TOKEN_BUDGET = 4000


def extract_prompt_template(recipe_md):
    """从 Recipe v2 Markdown 中提取 Prompt 模板（````markdown ... ````）"""
    m = re.search(r"````markdown\n(.*?)\n````", recipe_md, re.DOTALL)
    if not m:
        raise ValueError("no prompt template found in recipe markdown")
    return m.group(1)


def build_prompt(recipe_md, evidence_md):
    """拼装完整 prompt = 模板 + 注入 Evidence Pack"""
    template = extract_prompt_template(recipe_md)
    return template.replace("{paste evidence_pack_content_here}", evidence_md)


def call_vllm(prompt, base_url, model, max_tokens, temperature, top_p, timeout):
    """调用 vLLM chat completions"""
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "chat_template_kwargs": {"enable_thinking": False},  # **固化红线**
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def extract_diagnosis_json(response):
    """从 vLLM 响应中提取 JSON content"""
    if "choices" not in response or not response["choices"]:
        raise ValueError(f"vLLM response has no choices: {json.dumps(response, ensure_ascii=False)[:300]}")
    msg = response["choices"][0]["message"]
    content = msg.get("content") or ""
    if not content.strip():
        raise ValueError(f"vLLM returned empty content (reasoning may have consumed all tokens). finish_reason={response['choices'][0].get('finish_reason')}")
    return content


def parse_json(content):
    """尝试从 content 中提取 JSON（容错：去掉 markdown 代码块标记）"""
    content = content.strip()
    # 去掉 ```json ... ```
    if content.startswith("```"):
        content = re.sub(r"^```\w*\n", "", content)
        content = re.sub(r"\n```$", "", content)
    return json.loads(content)


def check_token_budget(usage, budget):
    """校验输入 token 不超预算"""
    prompt_tokens = usage.get("prompt_tokens", 0)
    if prompt_tokens > budget:
        return False, f"prompt_tokens={prompt_tokens} exceeds budget={budget}"
    return True, f"prompt_tokens={prompt_tokens} within budget={budget}"


def run_diagnosis(recipe_path, evidence_path, output_path, base_url, model,
                  max_tokens, temperature, top_p, token_budget, timeout):
    """主流程：读 recipe + evidence → 拼 prompt → 调 9B → 写 JSON"""
    recipe_md = Path(recipe_path).read_text(encoding="utf-8")
    evidence_md = Path(evidence_path).read_text(encoding="utf-8")
    prompt = build_prompt(recipe_md, evidence_md)

    est_tokens = len(prompt) // 4
    print(f"[runner] prompt chars: {len(prompt)}, est_tokens: {est_tokens}")
    if est_tokens > token_budget:
        print(f"[FATAL] estimated tokens {est_tokens} exceeds budget {token_budget} (would also be rejected by vLLM)", file=sys.stderr)
        return 2

    print(f"[runner] calling 9B (thinking=false)...")
    t0 = time.time()
    try:
        response = call_vllm(prompt, base_url, model, max_tokens, temperature, top_p, timeout)
    except requests.exceptions.RequestException as e:
        print(f"[FATAL] vLLM call failed: {e}", file=sys.stderr)
        return 2
    elapsed = time.time() - t0

    # 提取 JSON
    try:
        content = extract_diagnosis_json(response)
    except ValueError as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 1

    try:
        diagnosis = parse_json(content)
    except json.JSONDecodeError as e:
        print(f"[FATAL] diagnosis JSON parse error: {e}\ncontent:\n{content[:500]}", file=sys.stderr)
        return 1

    # Token 预算校验
    usage = response.get("usage", {})
    ok, msg = check_token_budget(usage, token_budget)
    if not ok:
        print(f"[FATAL] {msg}", file=sys.stderr)
        return 1

    # 写输出
    output = {
        "diagnosis": diagnosis,
        "runner_meta": {
            "model": model,
            "elapsed_seconds": round(elapsed, 2),
            "usage": usage,
            "token_budget": token_budget,
            "token_budget_check": msg,
            "thinking_disabled": True,  # **强制声明**
            "tool_call_disabled": True,
        },
    }
    Path(output_path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[runner] PASS: diagnosis written to {output_path}")
    print(f"  - prompt_tokens: {usage.get('prompt_tokens', '?')}")
    print(f"  - completion_tokens: {usage.get('completion_tokens', '?')}")
    print(f"  - elapsed: {round(elapsed, 2)}s")
    print(f"  - token_budget: {token_budget} ({msg})")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Diagnosis Runner (9B Recipe v2)")
    parser.add_argument("--recipe", required=True, help="Recipe v2 markdown path")
    parser.add_argument("--evidence", required=True, help="Evidence Pack markdown path")
    parser.add_argument("--out", required=True, help="Output diagnosis JSON path")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--top-p", type=float, default=DEFAULT_TOP_P)
    parser.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    return run_diagnosis(
        args.recipe, args.evidence, args.out,
        args.base_url, args.model, args.max_tokens, args.temperature, args.top_p,
        args.token_budget, args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())