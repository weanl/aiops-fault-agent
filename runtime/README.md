# AIOps Fault Agent — V2 框架（工程化骨架）

> **版本**：v2.2.1（2026-06-30 22:50 CST，V8 时间线闭合性落地）
> **范围**：CBS 用户充值失败（仅此一个场景）
> **目标**：把 v2 dry-run 产物沉淀成可复用验证框架骨架，**不接真实 OpenAPI，不建设大规模评测集，不扩展新产品**。

---

## 🎯 核心架构原则

> **LLM 负责推理，程序负责校验，数据负责事实，报告只负责渲染——三者不要混在同一次推理里。**

```
case input (YAML)
    ↓
Evidence Pack (静态数据, "Evidence A/B/C/D" 命名)
    ↓
Diagnosis Engine (9B + Recipe v2, JSON 输出)
    ↓
Deterministic Verifier (Python, 6 类规则)
    ↓
Report Renderer (9B + Report Recipe, Markdown)
```

**任何层的数据/事实必须由程序校验，LLM 只负责推理和渲染。**

---

## 🤔 三个关键设计决策

### 1. 为什么关闭 Reasoning (`chat_template_kwargs.enable_thinking=false`)?

**问题**：9B 默认 thinking 模式下，reasoning 内容会占满 `max_tokens`，导致 `content=None`（v1.1 case-01 实测：reasoning=7485 chars、content=0、finish_reason=length）。

**对策**：vLLM 启动时硬编码 `enable_thinking=true`，但 chat 请求时通过 `chat_template_kwargs.enable_thinking=false` 关闭。

**效果**（v2 实测）：
- v1.1: 64k prompt + 3000 tokens reasoning + content=0（截断）
- v2: 2161 prompt + 759 completion，content=1471 chars（正常）

**9B 适配经验**：reasoning 控制是 9B 推理的关键开关——所有 9B 委派任务第一件事 = 关 thinking。

### 2. 为什么 Evidence 不使用 Tool 命名?

**问题**：9B 看到 `Tool` / `function_call` / `T1-T7` / `alert_query` 等"可调用"暗示，会触发 function calling loop（v1.1 case-01 实测："3 tool call(s) made without visible output"）。

**对策**：用"事实标签"代替"工具命名"：
- ❌ `T1 / T2 / T3` / `alert_query_by_time_window`
- ✅ `Evidence A / B / C / D`（Alarm / KPI / Topology / Error Statistics）

**效果**：v2 case-01 实测 reasoning=0、正常输出 JSON。

### 3. 为什么 Verifier 用程序而不是 LLM?

**问题**：LLM 自检不可信——"我看起来对"≠"实际正确"。原 v1.1 badcase（"500% 全在 OCS-BJ-02"）就是因为 LLM 自检放行了数据污染。

**对策**：`verifier.py` 用纯 Python 实现 6 类确定性规则（V1 字段必填 / V2 数值反查 / V3 对象名反查 / V4 错误码格式 / V5 百分比范围 / V6 只读边界）。

**效果**：v2 case-01 即使 LLM 输出正确，verifier 仍会校验所有数字、对象、Evidence 引用是否在 Evidence Pack 中存在。

**写 verifier 第一件事 = 准备 1 个 good fixture + 1 个 bad fixture**。

---

## 📁 目录结构

```
runtime/
├── README.md                 # 本文件
├── run_case.py               # Pipeline 串起器（CLI）
├── cases/                    # Case 输入（YAML）
│   ├── case-01.yaml          # OCS-BJ-02 连接池耗尽
│   ├── case-02.yaml          # Adapter 第三方支付超时
│   └── case-03.yaml          # 证据不足 / 多候选冲突
├── evidence/                 # Step 1: Evidence Pack 生成器
│   └── evidence_builder.py
├── diagnosis/                # Step 2: Diagnosis Runner
│   └── diagnosis_runner.py
├── verifier/                 # Step 3: Verifier（最终验收依据）
│   └── verifier.py
├── report/                   # Step 4: Report Renderer
│   └── report_renderer.py
└── runs/                     # 每次 run 的产物
    └── <case_id>/
        ├── evidence.md
        ├── diagnosis.json
        ├── verifier-result.json
        ├── report.md
        └── run-summary.md
```

---

## 🚀 快速开始

### 单条 Case

```bash
cd project/aiops-fault-agent
python3 runtime/run_case.py --case runtime/cases/case-01.yaml
```

### 批量跑 3 条 Case

```bash
python3 runtime/run_case.py --batch case-01 case-02 case-03
```

### 跳过 Report（仅诊断 + 校验）

```bash
python3 runtime/run_case.py --case runtime/cases/case-01.yaml --skip-report
```

### 单独使用某一步

```bash
# 1. Evidence Pack
python3 runtime/evidence/evidence_builder.py runtime/cases/case-01.yaml > /tmp/ev.md
python3 runtime/evidence/evidence_builder.py runtime/cases/case-01.yaml --validate

# 2. Diagnosis Runner
python3 runtime/diagnosis/diagnosis_runner.py \
  --recipe recipe-cbs-charge-v2.md \
  --evidence /tmp/ev.md \
  --out /tmp/diag.json \
  --token-budget 4000

# 3. Verifier
python3 runtime/verifier/verifier.py run \
  --evidence /tmp/ev.md \
  --diagnosis /tmp/diag.json \
  --out /tmp/v.json

# 4. Report Renderer（仅 verifier PASS 后）
python3 runtime/report/report_renderer.py \
  --recipe recipe-cbs-charge-v2-report.md \
  --diagnosis /tmp/diag.json \
  --out /tmp/report.md
```

---

## ✅ 验收标准（Vanson 7:31 拍板）

| # | 标准 | 状态 |
|:-:|------|:----:|
| 1 | 现有 3 条 case 可通过 `run_case.py` 串行跑通 | ✅ |
| 2 | 3 条 case 仍然全部 PASS | ✅ |
| 3 | 9B 不触发 tool call | ✅（reasoning=0、finish=stop）|
| 4 | `enable_thinking=false` 固化在 runner 中 | ✅（diagnosis_runner.py / report_renderer.py）|
| 5 | verifier 作为最终验收依据 | ✅（V1-V6 6 类规则）|
| 6 | report 只在 verifier PASS 后生成 | ✅（pipeline 任一 FAIL 立即停）|
| 7 | 所有输出可追溯到 runs 目录 | ✅（runs/<case_id>/{evidence.md, diagnosis.json, verifier-result.json, report.md, run-summary.md}）|
| 8 | 不接真实 OpenAPI | ✅（vLLM 本地 9B 即可）|
| 9 | 不扩展 Mobile Money | ✅（仅 CBS 充值失败）|
| 10 | 不建设 50 条评测集 | ✅（仅 3 条 mock case）|
| 11 | 不启动 P0 阶段 1 | ✅（v2 框架工程化，不接真实数据）|

---

## 🚧 Vanson 7:31 禁止事项 — 全部遵守

- ❌ 不进入真实 OpenAPI 接入
- ❌ 不建设 50 条评测集
- ❌ 不扩展 Mobile Money
- ❌ 不启动 P0 阶段 1
- ❌ 不继续堆长 prompt
- ❌ 不把 verifier 交给 LLM 做

---

## 🧪 实施中修复的 3 个 Bug（教训）

| # | Bug | 触发场景 | 修复 |
|:-:|-----|---------|------|
| 1 | `OBJECT_ID_RE` 用 `^...$` 行首行尾 → 表格行内 object_id 漏判 | v2 dry-run 第一次跑时 | 改 `\b...\b` 词边界正则 |
| 2 | `Evidence A` 归一化（接受 "Evidence A" 和 "A" 两种写法） | v2 dry-run Case 1 PASS 后 Case 2 FAIL | 归一化为 `f"Evidence {ref}"` |
| 3 | OBJECT_ID 中间段 2 字母 → 2-5 字母 + IGNORECASE | Case 2 Adapter-PAY-01 匹不到 | 改 `[A-Z]{2,5}` + IGNORECASE |
| 4 | `verifier.py` 的 `check_v5_pct_range(diag)` 内部调 `check_v2_consistency(diag, "")` 传空 evidence_text → V2 在空文本里找不到任何 obj 报 FAIL | v2 工程化第一次跑 | 把 V5 独立实现（不依赖 evidence_text）|
| 5 | requests 库默认走 http_proxy → 9B 502 Bad Gateway | diagnosis_runner.py / report_renderer.py 调 vLLM | 在 os.environ 设 no_proxy=localhost |

**教训**：**verifier 自己写 + fixture 双向验证 + 跨模块独立测试**，bug 不会自己暴露。

---

## 🚦 进入 P0 阶段 1 的准入门槛

> 当以下条件**全部满足**时，可拍板进入 P0（接真实 OpenAPI + 建设评测集）：

| # | 门槛 | 当前状态 |
|:-:|------|:-------:|
| 1 | v2 框架在 ≥ 10 条 mock case 上全 PASS | ⏳ 3/3 PASS（待扩到 10+）|
| 2 | Verifier 6 类规则覆盖 ≥ 90% 失败场景 | ⏳ 需扩 fixture 库 |
| 3 | Report Renderer 不新增事实的稳定性验证 ≥ 10 条 | ⏳ 3/3（待扩到 10+）|
| 4 | Evidence Pack 生成器可对接真实监控 / 告警系统 | ❌ 仍为手工 YAML |
| 5 | 9B Reasoning 控制稳定（不需要为不同 case 调参）| ✅ 经验固化在 runner |
| 6 | 9B Prompt token 预算稳定 < 4k | ✅ 当前 2142-2264 |

**当前不建议进入 P0**：v2 框架在 3 条 case 上验证可行，但**未达到 10+ 门槛**。

---

## 🧪 CI / Local E2E Test

### CI（云端 hosted runner）

GitHub Actions 跑 **deterministic 回归护栏**（不调 9B / 不连 vLLM）：

```yaml
# .github/workflows/runtime-check.yml
on: push / pull_request
runs-on: ubuntu-latest
- python runtime/tests/test_deterministic.py
```

**CI 覆盖**（15 项）：

| 层级 | 测试 | 说明 |
|------|------|------|
| Verifier | good fixture PASS | 正向验证 |
| Verifier | bad fixture FAIL | 反向验证 |
| Verifier | v1 badcase 拦截 ≥ 4 类 | 500%/500 错误码 + kubectl 越界 |
| Verifier | confidence 矛盾检测 | INSUFFICIENT_EVIDENCE + high 候选 |
| Evidence Builder | 3 case YAML --validate | 4 段命名 + 禁止词 + 字段 |
| Evidence Builder | 渲染包含 4 段 | 输出 Markdown 结构 |
| Evidence Builder | 无 Tool 语义词 | 防止 9B trigger loop |
| 存档诊断 | 3 case 存档 diagnosis.json 反向 PASS | v2.0.0 端到端产物可重放 |
| CLI 化 | verifier run / evidence_builder | 端到端可调用 |

### Local E2E Test（本地 + 9B）

**全链路 E2E 依赖本地 vLLM 9B**，**GitHub hosted runner 跑不了**（访问不到 localhost:8000，也不需要 GPU 跑 9B）。

**前置条件**：

```bash
# 1. 本地 vLLM 9B 在线（:8000 端口）
curl http://localhost:8000/v1/models

# 2. Python 依赖
pip install pyyaml requests
```

**跑全链路**：

```bash
cd project/aiops-fault-agent

# 单条 case
python3 runtime/run_case.py --case runtime/cases/case-01.yaml

# 3 条 case 串行
python3 runtime/run_case.py --batch case-01 case-02 case-03

# 跳过 Report（仅诊断 + 校验）
python3 runtime/run_case.py --case runtime/cases/case-01.yaml --skip-report
```

**期望输出**：

```
============================================================
  Case: case-01  (OCS-BJ-02 连接池耗尽)
============================================================
[STEP 1] Evidence Builder: ... → evidence.md
[OK] evidence.md (1670 chars)
[STEP 2] Diagnosis Runner: ... → diagnosis.json
[runner] PASS: prompt_tokens=2142 completion_tokens=705
[STEP 3] Verifier: ... → verifier-result.json
[STEP 4] Report Renderer: ... → report.md
[SUMMARY] run-summary.md (4/4 PASS)
```

### Self-hosted Runner（如需要）

如果未来 P0 阶段 1 启动，需要 CI 也跑 full E2E（含 9B）：

1. 配置 GitHub self-hosted runner（带 GPU + vLLM）
2. workflow 加 `runs-on: self-hosted`
3. workflow 加 step: `pip install vllm` + 启动 9B 服务
4. **不推荐在 v2.0.0 阶段做**（增加维护成本，且 3/3 mock 验证不需要）

---

## 🎓 方法论沉淀

参见 `evolution/insights.md` 教训 39：

> **LLM 负责推理，程序负责校验，数据负责事实，报告只负责渲染——三者不要混在同一次推理里。**

5 条子原则：

1. 小模型对"Tool"语义词高度敏感 → 用 Evidence A-D 代替
2. 小模型不适合承担"执行器+校验器+报告生成器"三种职责 → 拆成 3 个独立环节
3. 自检不可信，必须加 deterministic verifier
4. 数据/推理/校验/渲染 四层职责分离
5. Reasoning 控制是 9B 推理的关键开关

---

## 🔗 关联

- `recipe-cbs-charge-v2.md`（Diagnosis Prompt，9B 最小）
- `recipe-cbs-charge-v2-report.md`（Report Renderer Prompt）
- `verifier.py`（原始版本，runtime/verifier/verifier.py 是 CLI 化版）
- `evolution/insights.md` 教训 39（方法论）
- `dry-run/v2-summary.md`（v2 dry-run 总结，3 case 验证记录）
- Vanson 7:13 拍板启动 v2 重构 / Vanson 7:31 拍板启动 C-mini 工程化

---

## 📊 当前状态

| 项 | 状态 |
|---|:----:|
| 4 个核心模块（evidence / diagnosis / verifier / report）| ✅ |
| 1 个 pipeline 串起器（run_case.py）| ✅ |
| **10 条 mock case 端到端 PASS** | ✅（v2.2.1） |
| **Verifier V1-V9 全部实现** | ✅（v2.2.1） |
| README | ✅ |
| **下一阶段建议** | 等 Vanson 拍板：<br/>A. 接真实 OpenAPI（见 readiness-for-real-openapi.md）<br/>B. 扩场景（CBS 交易下降 / 告警风暴）<br/>C. 扩到 20+ mock case |

---

## 📜 版本演进

| 版本 | 日期 | 关键变更 |
|------|------|----------|
| **v2.2.1** | 2026-06-30 22:50 | **V8 时间线闭合性落地**（C1-C4 四类冲突检测）+ 3 个 fixture + case-09 evidence 强化 + test_deterministic 34 项 PASS |
| v2.2.0 | 2026-06-30 22:50 | V7 关键字段缺失 + V9 历史案例引用检测 + 4 case (case-07/08/09/10) + 31/31 PASS |
| v2.1.0 | 2026-06-30 22:00 | V1 confidence 矛盾检测 + runner_meta 兼容 + 3 case (case-04/05/06) |
| v2.0.0 | 2026-06-30 20:30 | 框架骨架（4 模块 + pipeline + 3 case PASS）|

---

## 🛡️ Verifier V1-V9 规则状态（v2.2.1 全部实现）

| 规则 | 名称 | 触发条件 | 实现版本 |
|------|------|---------|:--------:|
| **V1** | 字段必填 | 必填字段缺失 / confidence 矛盾 | v2.0.0 |
| **V2** | 数值一致性 | 错误码/对象/Evidence ref 不在 evidence | v2.0.0 |
| **V3** | 对象名反查 | 引用的 object_id 不在 evidence | v2.0.0 |
| **V4** | 错误码格式 | 错误码非 4 位数字 | v2.0.0 |
| **V5** | 百分比范围 | pct 不在 [0,100] | v2.0.0 |
| **V6** | 只读边界 | 出现 kubectl/ssh/DELETE 等命令 | v2.0.0 |
| **V7** | 关键字段缺失 | Evidence D 无错误码 + high confidence | v2.2.0 |
| **V8** | 时间线闭合性 | C1 拓扑倒挂 / C2 沉默对象 / C3 KPI 早于告警 / C4 错误码/告警对象不相交 + high confidence | **v2.2.1** |
| **V9** | 历史案例引用 | recommend 出现"与历史案例相似"等表述 | v2.2.0 |

**V8 详细规则**：

- **C1** 拓扑上下游时间倒挂：拓扑 A → B，B 告警早于 A ≥ 5 分钟 → 倒挂
- **C2** 错误码对象脱离告警对象集：Evidence D 占比 > 0% 的错误码对象不在 Evidence A 告警对象集中 → 沉默故障嫌疑
- **C3** KPI 起点早于告警：Evidence B KPI 时间 < Evidence A 最早告警时间 ≥ 5 分钟 → 因果倒挂
- **C4** 错误码对象与告警对象完全不相交：所有错误码对象都不在告警对象集 → 完全沉默

**V8 判定**：

- 任意 C1-C4 命中 + diagnosis confidence=high → **FAIL**
- 任意 C1-C4 命中 + top3 任一 candidate confidence=high → **FAIL**
- 任意 C1-C4 命中 + medium/low/INSUFFICIENT_EVIDENCE → **PASS**（9B 已正确降级）

**V8 实现位置**：`runtime/verifier/timeline_parser.py`（独立模块）+ `runtime/verifier/verifier.py` `check_timeline_consistency()`。

**V8 fixture**（3 组）：

- `v8-conflict-high-fail` — 时间线冲突 + diagnosis high → FAIL
- `v8-closed-high-pass` — 时间线闭合 + diagnosis high → PASS（不误伤）
- `v8-conflict-low-pass` — 时间线冲突 + INSUFFICIENT_EVIDENCE → PASS（不限制 9B 自由判断）

---

## 🧪 V8 fixture 测试结果（v2.2.1）

```
✅ verifier: V8 冲突+high = FAIL — verdict=FAIL hit=['V8']
✅ verifier: V8 闭合+high = PASS — verdict=PASS conf=high
✅ verifier: V8 冲突+INSUFFICIENT = PASS — verdict=PASS conf=INSUFFICIENT_EVIDENCE
```

---

## 🧪 test_deterministic 测试覆盖（v2.2.1: 34/34 PASS）

| 层级 | 测试项 | 数量 |
|------|--------|:----:|
| Verifier | good/bad fixture + v1 badcase + confidence 矛盾 + V7/V8/V9 | 9 |
| Evidence Builder | 10 case YAML validate + 4 段渲染 + 无 Tool 词 | 12 |
| 存档诊断 | 10 case 反向 verifier PASS | 10 |
| CLI 端到端 | verifier run + evidence_builder 输出 | 3 |