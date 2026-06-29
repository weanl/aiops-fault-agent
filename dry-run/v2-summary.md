# V2 Dry-run Summary — CBS 充值失败（数据/推理/校验/报告职责分离）

> **生成时间**：2026-06-30 07:55 CST
> **触发**：Vanson 07:13 拍 A + 改目标——拆职责而非拆 Prompt
> **架构目标**：验证 v2 框架（Diagnosis JSON + Deterministic Verifier + Report Renderer）

---

## 🎯 本轮目标（按 Vanson 07:13 拍板）

将 CBS 充值失败 dry-run 改造成**"数据 / 推理 / 校验 / 报告"职责分离**的 v2 验证框架。

**核心原则**：

> LLM 负责推理，程序负责校验，数据负责事实，报告只负责渲染。

---

## 📦 产物清单

| 文件 | 用途 | 行数 | 状态 |
|------|------|-----:|:----:|
| `verifier.py` | 确定性校验器（6 类规则） | 314 | ✅ |
| `evidence-pack-template.md` | Evidence A/B/C/D 命名模板 | 175 | ✅ |
| `recipe-cbs-charge-v2.md` | 9B 最小 Diagnosis Prompt（JSON 输出） | 164 | ✅ |
| `recipe-cbs-charge-v2-report.md` | Report Renderer Prompt（仅渲染） | 201 | ✅ |
| `dry-run/case-0{1,2,3}-evidence.md` | 3 条 Case 的 Evidence Pack 数据 | 590 | ✅ |
| `dry-run/case-0{1,2,3}-prompt.txt` | 实际喂给 9B 的 prompt | ~4400 chars/case | ✅ |
| `dry-run/case-0{1,2,3}-diagnosis.json` | 9B Diagnosis JSON 输出 | 1.0-1.7KB/case | ✅ |
| `dry-run/case-01-report.md` | Case 1 完整 Markdown 报告 | 2.3KB | ✅ |
| `dry-run/case-0{1,2,3}-raw-response.json` | vLLM 原始响应 | ~10KB/case | ✅ |

**总计：~25KB 产物**

---

## 🧪 3 条 Case 串行 dry-run 结果

| Case | 场景 | 9B token in | 9B token out | finish | verifier.py | 关键结论 |
|:----:|------|------------:|-------------:|:------:|:-----------:|---------|
| **1** | OCS-BJ-02 连接池耗尽 | 2161 | 759 | stop | ✅ **PASS** | 准确识别 5004 占 95.2%、连接池耗尽为根因 1 |
| **2** | Adapter / 第三方支付网关超时 | 2268 | 773 | stop | ✅ **PASS** | 准确归因到 GW-PAY-EXT，没泛化错归 OCS |
| **3** | 证据不足 / 多候选冲突 | 2436 | 508 | stop | ✅ **PASS** | **拒绝强结论**，confidence=INSUFFICIENT_EVIDENCE，top3=[] |

**3/3 PASS，红线 0 触发**。

---

## ✅ Vanson 7:13 通过门槛 — 10/10 满足

| # | 红线 | 状态 | 证据 |
|:-:|------|:----:|------|
| 1 | 9B 不触发 tool call | ✅ | reasoning_len=0、finish=stop、正常输出 |
| 2 | 单次输入不超过 4k token | ✅ | Case 1: 2161 / Case 2: 2268 / Case 3: 2436（均 < 4k） |
| 3 | JSON 输出结构稳定 | ✅ | 7 字段齐全（case_id/timeline/anomaly_cluster/top3_root_cause/evidence_matrix/recommend/confidence）|
| 4 | verifier.py 全部 PASS | ✅ | 3/3 case PASS，0 项校验失败 |
| 5 | 无数据污染 | ✅ | 错误码/百分比/对象全部从 Evidence 反查通过 |
| 6 | 无比例不一致 | ✅ | V5 校验 0-100 范围，3 case 全过 |
| 7 | 无未声明工具或命令 | ✅ | V6 forbidden pattern 0 命中 |
| 8 | 无 kubectl/ssh/SQL/重启/扩容 | ✅ | recommend 字段用自然语言描述，无命令模式 |
| 9 | "推荐高置信候选根因"≠"最终根因" | ✅ | confidence=high 时仍保留"推荐"+ "需验证" 表述 |
| 10 | 证据不足输出 INSUFFICIENT_EVIDENCE | ✅ | Case 3 完美执行，top3=[]，confidence=INSUFFICIENT_EVIDENCE |

---

## 🔧 v2 关键设计 vs v1 badcase

| 维度 | v1（合并模式）| v2（分离模式）| 修复的 v1 badcase |
|------|--------------|--------------|------------------|
| Prompt 长度 | 540 行（4 角色混在一起）| ~80 行（仅 Diagnosis）| 9B 不再 trigger tool call loop |
| 数据命名 | `T1-T7` / `alert_query` | `Evidence A-D` | "Tool" 词消失，9B 不再触发 function calling |
| 数据形态 | Mock 内嵌 Prompt | Evidence Pack 静态快照 | 数据/推理分离 |
| 输出格式 | Markdown 报告（不可控）| JSON（程序可解析）| verifier.py 可确定性校验 |
| 校验 | LLM 自检（不可信）| `verifier.py`（6 类确定性规则）| 数据污染、比例不一致全部可拦截 |
| 报告生成 | 与诊断同轮 LLM | 单独一轮（基于已校验 JSON）| Markdown 长度可控、新增事实风险极低 |
| Reasoning 控制 | 默认开启（耗 token）| `chat_template_kwargs.enable_thinking=false` | 2159+3000 截断 → 2159+759 正常 |

**v1 badcase "500% 全在 OCS-BJ-02" 已被彻底解决**：
- V4 错误码格式校验：4 位数字硬约束 → 500/500% 直接判 FAIL
- V5 百分比范围：0-100 硬约束 → 500% 直接判 FAIL
- V2 反查：错误码必须在 Evidence 中 → 凭空出现的 500 错误码判 FAIL

---

## 🐛 Verifier.py 实施中的 3 个 Bug（已修）

| # | Bug | 修复方式 |
|:-:|-----|---------|
| 1 | `OBJECT_ID_RE` 用 `^...$` 行首行尾匹配 → 表格行内 object_id 全部漏判 | 改用 `\b...\b` 词边界正则 |
| 2 | `Evidence A` 反查只提取 `A`，但 diag 写 `"Evidence A"` → 永远比对失败 | 归一化为 `f"Evidence {ref}"`，同时接受两种写法 |
| 3 | `OCS-BJ-02` 的中间段 `BJ` 假设是 2 字母 city code，但 `Adapter-PAY-01` 中间是 `PAY` 3 字母 | 改 `[A-Z]{2}` → `[A-Z]{2,5}`，加 IGNORECASE |

**教训**：verifier 自己的 bug 不会自己暴露——必须用 fixture（good + bad）双向验证。

---

## 📊 v2 性能 / 成本指标

| 指标 | 数值 | 说明 |
|------|-----:|------|
| 单 case Prompt token | 2161-2436 | 远低于 4k 预算（54-61%） |
| 单 case Diagnosis token | 508-773 | 9B 输出稳定 |
| 单 case 总耗时 | ~60-90s | 含 thinking 关掉后的稳定推理 |
| 单 case verifier 耗时 | <100ms | 纯 Python 字符串扫描 |
| 单 case report 渲染 token | 1376（Case 1）| 渲染端略多但可控 |

---

## 🎓 关键方法论沉淀（教训 39）

**LLM 负责推理，程序负责校验，数据负责事实，报告只负责渲染——三者不要混在同一次推理里。**

5 条子原则：

1. **小模型（9B）对 Prompt 中的"Tool"语义词高度敏感**——任何 `Tool` / `function_call` / `T1-T7` 都会触发 function calling loop。**用 Evidence A-D 等"事实标签"代替"工具命名"**。
2. **小模型不适合承担"执行器 + 校验器 + 报告生成器"三种职责**——拆成 Diagnosis (LLM) → Verifier (程序) → Report (LLM)。
3. **自检不可信，必须加 deterministic verifier**——verifier 自己写、跑 fixture 验证、接受"白名单 + 范围 + 必填字段"三类规则。
4. **数据/推理/校验/渲染 四层职责分离**——每一层的输入/输出契约必须由程序严格定义（JSON Schema、字段必填、值域范围）。
5. **Reasoning 控制是 9B 推理的关键开关**——`chat_template_kwargs.enable_thinking=false` 能让 9B 直接输出 content，省下 3000+ token 用于真正的 JSON 构造。

---

## 🚦 Vanson 07:13 禁止事项 — 全部遵守

| 禁止事项 | 状态 |
|---------|:----:|
| 不进入真实 OpenAPI 接入 | ✅ |
| 不建设 50 条评测集 | ✅ |
| 不扩展 Mobile Money | ✅ |
| 不启动 P0 阶段 1 | ✅ |
| 不继续堆长 prompt | ✅（v2 prompt 仅 164 行） |
| 不把 verifier 交给 LLM 做 | ✅（verifier.py 是纯 Python） |

---

## 🚀 下一阶段建议（等 Vanson 拍板）

### A. 把 v2 框架应用到真实 CBS Mock 接口

- 仍不接真实 OpenAPI，但用脚本生成更逼真的 Evidence Pack（动态时间窗口、错误码分布）
- 评估集扩到 10-20 条（仍 < 50 条上限）
- 触发条件：v2 框架在 ≥10 条 mock case 上全 PASS

### B. 把 v2 框架扩展到其他场景

- CBS 交易下降（SCENARIOS.md §2）
- 告警风暴（SCENARIOS.md §3）
- 每个场景独立 verifier（不同字段契约）
- 触发条件：Vanson 拍板扩展顺序

### C. v2 框架工程化

- Evidence Pack 生成器（从监控 / 告警 / 拓扑 / 日志系统）
- Diagnosis Engine 容器化（9B + recipe v2）
- Verifier 服务化（HTTP API）
- Report Renderer 服务化
- 触发条件：Vanson 拍板进入工程化阶段

**默认 C**——v2 框架已验证可行，下一步是把它做成可复用平台，不是再扩展场景或数据集。

---

## 关联

- `recipe-cbs-charge-v1.md` / `recipe-cbs-charge-v1.1.md`（v1，已废弃，仅作历史对照）
- `recipe-cbs-charge-v1.patch.md`（v1 6 patch，已废弃）
- `dry-run/`（v1 dry-run 产物，仅作对照）
- `evolution/insights.md`（教训 39 沉淀位置）
- Vanson 07:13 拍板启动本轮