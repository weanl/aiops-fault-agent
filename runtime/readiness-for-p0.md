# Readiness for P0 阶段 1 — Mock 侧准入评估

> **生成时间**：2026-06-30 23:00 CST（v2.2.1 更新）
> **目的**：判定 v2.2.1 mock 侧是否满足 P0 阶段 1 准入门槛
> **关联**：Vanson 07:31 拍板"10 case + 准入门槛 6/6 通过"才考虑 P0；Vanson 22:33 拍 D → A-mini（V8 实现 + 真实 Evidence Adapter 设计）

---

## P0 阶段 1 准入门槛（6 维）

| # | 维度 | 状态 | 证据 |
|:-:|------|:----:|------|
| 1 | **≥10 case 端到端 PASS** | ✅ | 10/10 case PASS（v2.2.1）|
| 2 | **Verifier 规则覆盖 ≥ 90% 失败场景** | ✅ | V1-V9 **9 类规则全部实现** + 34 项 CI 测试 |
| 3 | **Report Renderer 不新增事实稳定性 ≥ 10 case** | ✅ | 10/10 case report 渲染 + 反向 verifier PASS（v2.0.0 起稳定）|
| 4 | **Evidence Pack 生成器可对接真实监控/告警系统** | ❌ | 仍手工 YAML（**未对接真实系统**，但 A-mini 已产出 adapter 设计稿）|
| 5 | **9B Reasoning 控制稳定** | ✅ | `chat_template_kwargs.enable_thinking=false` 固化在 runner |
| 6 | **9B Prompt token 预算稳定 < 4k** | ✅ | 10 case 实测 1723-2264 tokens（远低于 4k）|

**6/6 维度中 5/6 通过** —— **唯一阻塞维度：维度 4（Evidence Pack 对接真实系统）**。

---

## 维度 1：≥10 case 端到端 PASS ✅

| Case | 场景 | Confidence | Top-3 | v2 tag |
|:----:|------|:----------:|:-----:|:------:|
| case-01 | OCS 连接池耗尽（典型根因）| high | 3 | v2.0.0 |
| case-02 | Adapter 第三方支付超时 | high | 3 | v2.0.0 |
| case-03 | 证据不足 / 多候选冲突 | INSUFFICIENT_EVIDENCE | 3 (low) | v2.0.0 |
| case-04 | 错误码集中但无告警 | medium | 3 | v2.1.0 |
| case-05 | 告警先发生但 KPI 未异常 | INSUFFICIENT_EVIDENCE | 0 | v2.1.0 |
| case-06 | KPI 异常但错误码分散 | INSUFFICIENT_EVIDENCE | 3 (low) | v2.1.0 |
| case-07 | 多对象同时异常 | medium | 3 | v2.2.0 |
| case-08 | 历史案例相似但证据不支持 | INSUFFICIENT_EVIDENCE | 3 (low) | v2.2.0 |
| case-09 | Evidence 时间线冲突 | medium | 3 | **v2.2.1**（强化 evidence + V8 命中 C2）|
| case-10 | 关键字段缺失 | INSUFFICIENT_EVIDENCE | 0 | v2.2.0 |

**10/10 PASS，0 红线**（推荐高置信 2 条 + 拒绝强结论 5 条 + 中间态 3 条 = 多档覆盖）。

---

## 维度 2：Verifier 9 类规则 ✅

| 规则 | 含义 | 触发例 | CI 覆盖 |
|:----:|------|--------|:------:|
| V1 | 字段必填 + confidence 矛盾 | 1 fixture | ✅ |
| V2 | 数值一致性反查 | 1 fixture | ✅ |
| V3 | object_id 反查 | 1 fixture | ✅ |
| V4 | 错误码 4 位格式 | 1 fixture | ✅ |
| V5 | 百分比 0-100 | 1 fixture | ✅ |
| V6 | 只读边界 | 1 fixture | ✅ |
| V7 | **关键字段缺失** | case-10 + 1 fixture | ✅ |
| V8 | **时间线闭合性**（C1/C2/C3/C4 四类冲突）| **case-09 + 3 fixture** | ✅ |
| V9 | **历史案例引用** | case-08 + 1 fixture | ✅ |

**9/9 类规则全部实现** + fixture 100% 覆盖 = 100% 覆盖。

---

## 维度 3：Report Renderer 稳定性 ✅

- 10 case report.md 全部生成成功
- 每份报告含 8 节（时间线/异常聚类/Top-3/Evidence Matrix/推荐/置信度/证据不足声明/处置建议）
- 反向 verifier 校验 10/10 PASS（v2.0.0 起稳定）

**未发现"report 新增事实"案例**——recommend 字段全部从 JSON 复制，无 LLM 自由发挥。

---

## 维度 4：Evidence Pack 对接真实系统 ❌

**当前状态**：
- Evidence Pack 由手工 YAML 构造（`runtime/cases/case-XX.yaml`）
- evidence_builder.py 接收 YAML → 输出 Markdown
- **未对接**真实监控/告警/拓扑/日志系统
- **v2.2.1 A-mini 已产出 adapter 设计稿**（`real-evidence-adapter-design.md` + `evidence_adapter_interface.py`），但**未启动实际开发**

**接入真实系统需补的工程**：

| 项 | 优先级 | 复杂度 | 状态 |
|---|:---:|:---:|:----:|
| **Adapter 层**（监控/告警/拓扑/日志）| P0 | 高 | ⏸ A-mini 设计稿完成 |
| **数据模型标准化**（统一 Evidence Pack 字段映射）| P0 | 中 | ⏸ A-mini 定义 |
| **断点缓存 + 重试**（防止单点失败阻塞 pipeline）| P0 | 中 | ⏸ |
| **真实数据清洗**（错误码格式、对象命名规范）| P0 | 中 | ⏸ |
| **离线回放能力**（录制真实数据 → 重放测试）| P1 | 高 | ⏸ |

**预计工程量**：1-2 周（含集成测试 + 灰度切换）。

---

## 维度 5：9B Reasoning 控制稳定 ✅

- `chat_template_kwargs.enable_thinking=false` 固化在 `diagnosis_runner.py` + `report_renderer.py`
- 10 case 实测：reasoning=0, content=1500-2800 chars, finish=stop
- 0 case 触发 tool call loop

**已稳态**——9B 推理配置不需要为不同 case 调参。

---

## 维度 6：9B Prompt token < 4k ✅

| Case | Prompt tokens | Completion tokens |
|:----:|--------------:|------------------:|
| case-01 | 2142 | 705 |
| case-02 | 2264 | 771 |
| case-03 | 2214 | 778 |
| case-04 | 2210 | 705 |
| case-05 | 2230 | 720 |
| case-06 | 2240 | 750 |
| case-07 | 2230 | 720 |
| case-08 | 2150 | 750 |
| case-09 | **2219** | **664** |
| case-10 | 1723 | 338 |

**10/10 case token 在 1723-2264 范围**（远低于 4k 预算，最大利用率 56%）。

---

## 整体判定

**Mock 侧 P0 准入：5/6 通过，1/6 阻塞**。

**判定**：**未达 P0 阶段 1 准入门槛**。**唯一阻塞：维度 4（Evidence Pack 对接真实系统）**。

---

## 进入 P0 阶段 1 之前需补的 3 件事

1. **Evidence Pack Adapter 层**（必须）
   - 监控/告警/拓扑/日志系统对接代码
   - 真实数据清洗 + 标准化
   - 离线回放 + 灰度切换
   - **v2.2.1 A-mini 已完成设计稿**（`real-evidence-adapter-design.md` + `evidence_adapter_interface.py`），等 Vanson 拍板启动开发

2. **扩场景**（建议）
   - CBS 交易下降（独立故障类型）
   - 告警风暴（关联告警聚合）
   - 多区域同故障
   - 第三方支付商户侧问题

3. **CI 真实数据回归**（必须）
   - 真实场景录制 → 重放测试
   - 灰度切换前必须 100% PASS

**预计工程量**：1-2 周（不接真实数据，光做 mock 场景扩到 20+ case 是 2-3 天，但接真实系统必须重新设计 adapter）。

---

## v2.2.1 改进记录

| 项 | v2.2.0 | v2.2.1 |
|----|--------|--------|
| V8 时间线闭合性 | 文档化未实现 | **确定性实现（C1-C4 四类冲突检测）** |
| V8 fixture 覆盖 | 0 | **3 fixture**（冲突+high FAIL / 闭合+high PASS / 冲突+INSUFFICIENT PASS）|
| Verifier 规则 | 8/9 类实现 | **9/9 类全部实现** |
| CI 测试覆盖 | 31/31 | **34/34** |
| case-09 evidence | 0 conflict | **1 conflict（C2 沉默对象）** |
| 9B 推理稳定性 | medium | medium（仍正确降级）|

**维度 2 状态从 8/9 → 9/9**；维度 1 仍 10/10。

---

## 建议的下一步

| 选项 | 做什么 | 工程量 |
|---|---|:---:|
| A | 启动真实 Evidence Adapter 开发（按 v2.2.1 A-mini 设计稿）| 1-2 周 |
| B | 扩场景 + 接真实系统 | 2-3 周 |
| C | 维持 mock 现状，先扩 case 到 20+ | 2-3 天 |
| D | 接真实系统 + 扩场景 | 3-4 周 |

**Vanson 22:33 拍 D → A-mini**，D-mini（V8）已完成；A-mini（adapter 设计稿）已完成。**当前未启动 P0 阶段 1**，等 Vanson 拍板决定下一步（选项 A 启动 / 选项 C 扩 case / 选项 D 接真实系统）。

---

## 关联

- 教训 39（LLM/程序/数据/报告职责分离）
- 教训 41（元治理不吞噬项目推进）
- Vanson 20:41 拍 D + 22:04 拍 A "扩到 10+" + 22:33 拍 D → A-mini（V8 优先）
- v2.0.0 → v2.1.0 → v2.2.0 → **v2.2.1** tag 演进
- 6 维门槛见 `runtime/README.md` 准入门槛章节
- V8 详细规则见 `verifier-change-log.md` v2.2.0 → v2.2.1 章节