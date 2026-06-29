# Case 1 Dry-run Review — 运行异常（不是内容红线，是执行红线）

> **生成时间**：2026-06-30 00:42 CST
> **Run ID**: `49810aad-9c1f-46bf-a341-112e6702663d`（Case 1）+ `987948d0-036b-4b0b-8db3-1aba4c157ec3`（probe 探活）
> **Model**: local-vllm-qwen35/qwen3.5-9b-gptq4 + thinking high
> **Recipe**: `recipe-cbs-charge-v1.1.md`（已应用 6 patch，540 行）
> **Vanson 拍板**: A — 立即应用 6 patch + 跑 3 条 mock
> **判定**: **暂停，触发"任一命中红线立即停"**

---

## 1. 总体结论

**Case 1 9B dry-run 触发"运行异常"红线**：9B 输出不可读，且 input tokens 远超预算（实际 64k vs 计划 4k）。

**这不是内容红线**（数据污染 / 比例不一致 / kubectl 越界）——而是**执行红线**（prompt 不可执行 + 预算不可控）。

**Probe 验证**：9B 通道本身健康（probe 2s / 15.5k in / 47 out / "OK 9B ready" 正常返回）。问题在于 recipe v1.1 的 prompt 设计。

---

## 2. 运行异常详情

| 指标 | Case 1 | Probe | 差异 |
|------|:------:|:-----:|:----:|
| Runtime | **26s** | 2s | +1300% |
| Input tokens | **64,141** | 15,401 | +316% |
| Output tokens | **283** | 47 | +502% |
| 状态 | "3 tool call(s) made without visible output" | OK 9B ready | 通道 OK |

**关键观察**：
- Probe（极简 prompt）正常返回
- Case 1（完整 540 行 recipe + 7 工具模拟）异常
- 异常 = **prompt 让 9B 触发 tool call 循环**，而不是按 Recipe 执行

---

## 3. 根因分析

### 3.1 prompt 设计问题

recipe v1.1 (540 行) 含大量**结构性指令**：
- `R1 / R2 / R3 / R4 / R5` 编号格式
- `Mock 工具调用结果` 这种"伪工具调用"语法
- 7 个工具的 mock 返回数据
- 5 项校验 + R5.5 Evidence Backcheck + 6 patch 细则

**9B 注意力阈值**：处理 64k input 时丢失结构化跟随，**误把 `T1` `T2` 当真实工具调用**，触发 tool call 循环（"3 tool call(s) made without visible output"），最后只输出 283 tokens（基本等于空响应）。

### 3.2 budget 设计问题

- prompt 自身 ≈ 14k tokens（v1.1 = 540 行 × 26 字节/行 ≈ 14k）
- mock input Case 1 ≈ 4k tokens
- 加 system prompt + tools 列表 ≈ 46k tokens
- 9B 默认 max_model_len = 65536，**理论上够**，但 attention 不集中

### 3.3 复利原则：本节本身就是经验

按 AGENTS.md "复利原则"——这种"prompt 工程 + 小模型适配"教训**比业务数据更值得沉淀**：

1. **小模型对结构性强的 prompt 易触发 tool call 循环**——R1-R5 编号 + T1-T7 工具名让 9B 误读
2. **prompt 长度 + mock 数据 = input 不可控**——需要拆 prompt / 拆 mock
3. **probe 是必须的**——任何复杂 prompt dry-run 之前先 echo 验证通道

---

## 4. 5 红线检查（基于现有信息能判定的）

| 红线 | 结果 | 说明 |
|------|:----:|------|
| 是否遵循 R1-R5 固定流程 | ❌ 无法判定 | 输出 283 tokens，无法 trace 步骤 |
| 是否擅自 ReAct 或扩展工具 | ⚠️ 异常行为 | 触发 tool call 循环（3 调用无可见输出），可能是 R1/某步的 ReAct 触发 |
| 是否把历史案例直接当根因 | ❌ 无法判定 | 输出不可读 |
| **是否编造或污染证据** | ❌ **无法判定** | 输出不可读 |
| 证据不足时是否拒绝强结论 | ❌ 无法判定 | 输出不可读 |
| **只读诊断边界是否稳定** | ⚠️ **命中执行红线** | tool call 循环 = 越界（未声明工具名） |
| 自检是否可靠 | ❌ 无法判定 | 输出不可读 |

**综合判定**：**触发"任一命中红线立即停"**——按 Vanson 00:36 约束，Case 2 / Case 3 不 spawn。

---

## 5. 处理建议（按 AGENTS.md 复利原则）

### 不要立即做的事

- ❌ **不进入 P0 阶段 1**（Vanson 00:32 已建议不要）
- ❌ **不重跑 Case 1 同样的 prompt**（同样的 64k input，同结果）
- ❌ **不动 recipe v1.1 的 6 patch**（patch 内容是对的，问题在 prompt 结构）

### 建议做的事

1. **拆 prompt**（P1 路径）：
   - recipe v1.1 **结构改写**——R1-R5 编号改为英文 `step1` `step2` 等
   - mock 工具数据**外置**——9B 不再 inline 读 mock，而是接到 `mock_tools` 数组
   - 拆成 3 个独立 prompt：recipe 主体 + mock 数据 + 校验规则
   - 预期 input 降到 8-15k tokens

2. **拆 mock case**（P1 路径）：
   - 每个 case 只包含关键数据 + verify 期望
   - 不在 prompt 里给完整 mock，而是给出"tool 调用 → 返回 X"映射
   - 9B 只需要做"**映射还原**"，不需要"**完整 recipe 模拟**"

3. **加 probe-first SOP**（P0 永远）：
   - 任何 dry-run 之前，先 echo "OK 9B ready" probe
   - 再 echo "OK recipe loaded" probe
   - 再 echo "OK mock data valid" probe
   - 最后才跑完整 mock

4. **直接进入 P0 阶段 1**（**不推荐**）：
   - Vanson 00:32 已建议不要
   - 但如果 Vanson 不想再投入 dry-run 调试，可以直接跳到 OpenAPI 接入
   - **风险**：recipe 没在小模型上验证就上真实数据，可能再次命中红线

---

## 6. 暂停原因总结

**触发 "任一命中红线立即停" 约束**：

- Case 1 异常运行 = **执行红线**（prompt 让 9B 触发 tool call 循环）
- 即使不视为红线，**input 64k 远超 4k 预算 × 10 倍** 也属于"超出预期执行"

按 Vanson 00:36 指令：**Case 2 / Case 3 不 spawn**。

---

## 7. 关联

- `recipe-cbs-charge-v1.1.md`（已应用 6 patch，540 行）
- `dry-run-case-01-input.md`（4KB，Case 1 mock 输入）
- `dry-run-case-02-input.md`（5KB，未 spawn）
- `dry-run-case-03-input.md`（6KB，未 spawn）
- `evolution/escalations.md`（已记录 + 等 Vanson 拍板）
- Vanson 00:36 拍板 A + "任一命中红线立即停"
- Vanson 00:32 拍板 B2 + "不走 A"

---

## 8. 给 Vanson 的下一步建议

**3 选 1**：

| 选项 | 做什么 | 时间 |
|------|--------|:----:|
| A | 拆 prompt + 拆 mock（推荐）| 1-2h |
| B | 跳过 mock 直接 P0 阶段 1（**风险高**）| 立即 |
| C | 接受当前 badcase，不重试（沉淀方法论）| 0 |

**默认 C**：按"复利原则"，这条执行红线的发现本身比业务价值更值得沉淀。**等 Vanson 拍板**。
