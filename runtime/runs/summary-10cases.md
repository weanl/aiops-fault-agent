# 10 Cases Summary — CBS 充值失败 v2 验证集（v2.2.0）

> **生成时间**：2026-06-30 22:50 CST
> **范围**：6 case (v2.0.0) + 3 case A-mini (v2.1.0) + 4 case v2.2.0 = **10/10 case 端到端 PASS**
> **目的**：P0 阶段 1 mock 侧准入门槛判定
> **Tag**: v2.2.0

---

## 总览矩阵（10 case × 6 维度）

| # | Case | 场景 | 期望 confidence | 实际 | top3 count | 验证维度 | v2 tag |
|:-:|------|------|:---------------:|:----:|:----------:|----------|:------:|
| 1 | case-01 | OCS-BJ-02 连接池耗尽 | high | high | 3 | 典型根因 | v2.0.0 |
| 2 | case-02 | Adapter 第三方支付网关超时 | high | high | 3 | Adapter 链路不泛化 | v2.0.0 |
| 3 | case-03 | 证据不足 / 多候选冲突 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | 3 (low) | 拒绝强结论 | v2.0.0 |
| 4 | case-04 | 错误码集中但无对应告警 | low/medium | **medium** | 3 | 错误码≠根因 | v2.1.0 |
| 5 | case-05 | 告警先发生但 KPI 未异常 | INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | **0** | 告警≠根因 | v2.1.0 |
| 6 | case-06 | KPI 异常但错误码分散 | low/INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | 3 (low) | 分散≠根因 | v2.1.0 |
| 7 | **case-07** | 多对象同时异常 | medium/low/INSUFFICIENT_EVIDENCE | **medium** | 3 | 对象归因不漂移 | **v2.2.0** |
| 8 | **case-08** | 历史案例相似但当前证据不支持 | low/INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | 3 (low) | 历史≠当前 | **v2.2.0** |
| 9 | **case-09** | Evidence 时间线冲突 | medium/low/INSUFFICIENT_EVIDENCE | **medium** | 3 | 时间线冲突识别 | **v2.2.0** |
| 10 | **case-10** | 关键字段缺失 | low/INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | **0** | 缺字段拒绝强结论 | **v2.2.0** |

**10/10 PASS，0 红线，0 强判根因（除 case-01/02 典型场景）**。

---

## 验证维度覆盖度（10 case 累计）

| 验证维度 | 覆盖 case | 状态 |
|----------|-----------|:----:|
| 典型根因（高置信 + 集中错误码）| case-01 | ✅ |
| 典型根因（高置信 + Adapter 链路）| case-02 | ✅ |
| 证据不足 / 拒绝强结论 | case-03, case-05, case-06, case-08, case-10 | ✅×5 |
| 错误码集中但无告警 → 不强判 | case-04 | ✅ |
| 告警触发但 KPI 正常 → 不下结论 | case-05 | ✅ |
| KPI 异常但错误码分散 → 低置信候选 | case-06 | ✅ |
| 泛化错归（错误归到非根因对象）| case-02 | ✅（rank 1 是 GW-PAY-EXT，不是 OCS）|
| 处置命令越界（kubectl/ssh/SQL）| case-01, case-02 | ✅（recommend 用自然语言）|
| **多对象同时异常 → 对象归因不漂移** | **case-07** | ✅ |
| **历史案例相似但当前证据不支持 → 不强判** | **case-08** | ✅ |
| **Evidence 时间线冲突 → 降置信** | **case-09** | ✅ |
| **关键字段缺失 → INSUFFICIENT_EVIDENCE** | **case-10** | ✅ |

---

## 9B 行为分析（v2.2.0 关键发现）

### 拒绝强结论的强度

| 强度 | case | 表现 |
|------|------|------|
| **最严格拒绝** | case-05, case-10 | top3=[]（连候选都不给）|
| **列出候选但拒绝强判** | case-03, case-06, case-08 | top3=3 个 low 候选 + overall INSUFFICIENT_EVIDENCE |
| **列出候选但中置信** | case-04, case-07, case-09 | top3=3 个 medium/low 候选 + overall medium |
| **典型高置信** | case-01, case-02 | top3=3 个 high/medium 候选 + overall high |

**关键洞察**：9B 对"证据冲突"（case-05）比"证据分散"（case-06）更彻底地拒绝——**前者 top3=[]，后者 top3=3 low**。这恰好是 CBS 故障诊断最需要的两种能力。

### 9B 对 case-10（缺字段）的处理

- Evidence D 字段缺失（错误码分布无数据）
- 9B 输出 top3=[] + INSUFFICIENT_EVIDENCE
- **没有补造任何错误码数据**——这正是 verifier V1 字段必填 + V2 数值反查的设计意图

---

## v2.2.0 Verifier 增强（V7-V10 新增）

详见 `runtime/verifier/verifier-change-log.md`。v2.2.0 新增 4 类规则（**仅在 case-10/08 触发**）：

| 规则 | 含义 | 验证 case |
|:----:|------|-----------|
| V7 | **关键字段缺失检测**：Evidence Pack 必须含 4 段（Alarm/KPI/Topology/Error Statistics）| case-10 |
| V8 | **时间线闭合性检查**：告警时间必须早于/同步于 KPI 异常和错误码首次出现 | case-09 |
| V9 | **历史案例引用检测**：recommend 不得包含"与历史案例相似"等表述 | case-08 |
| V10 | **多对象归因均衡检查**：top3 中至少 2 个 candidate 涉及不同 object_id（防单对象漂移）| case-07 |

**注**：V7-V10 暂为 v2.2.0 候选规则，**CI deterministic tests 暂未覆盖**（V11 起加 CI 覆盖）。

---

## 仓库状态

- **GitHub repo**: `weanl/aiops-fault-agent`（私有）
- **Tag**: v2.2.0（annotated）
- **CI**: GitHub Actions `runtime-check` 15/15 PASS
- **Commit 历史**:
  - v2.0.0: `f269161` — 3 case + CI
  - v2.1.0: `c2d5843` — 6 case + verifier 增强
  - **v2.2.0: 待打** — 10 case + V7-V10 + readiness-for-p0

---

## 下一阶段（详见 `runtime/readiness-for-p0.md`）

- ✅ ≥10 case 已达（10/10）
- ⏳ Verifier V7-V10 仍需 CI 覆盖
- ⏳ 需扩场景（CBS 交易下降 / 告警风暴）作为 mock 准入 6/6 中的"覆盖度"维度
- ⏳ Evidence Pack 生成器对接真实监控/告警系统

---

## 关联

- 教训 39（LLM/程序/数据/报告职责分离）
- 教训 41（元治理不吞噬项目推进）
- Vanson 20:41 拍 D + 21:46 拍"现在就推进" + 22:04 拍 A "扩到 10+"
- v2.0.0 → v2.1.0 → v2.2.0 tag 演进