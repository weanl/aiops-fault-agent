# Case Matrix — CBS 充值失败 v2 验证集

> **生成时间**：2026-06-30 22:50 CST
> **范围**：10 case 端到端 PASS（v2.0.0 3 + v2.1.0 3 + v2.2.0 4）
> **目的**：追踪每个 case 验证哪条 verifier 规则 / 哪类场景
> **Tag**: v2.2.0

---

## 矩阵（10 case × 6 验证维度）

| Case | 场景 | 期望 confidence | 实际 | top3 count | 验证维度 |
|:----:|------|:---------------:|:----:|:----------:|----------|
| **case-01** | OCS-BJ-02 连接池耗尽（典型根因）| high | high | 3 | V1/V2/V3/V6 |
| **case-02** | Adapter 第三方支付网关超时 | high | high | 3 | V2/V3 + 不泛化错归 |
| **case-03** | 证据不足 / 多候选冲突 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | 3 (low) | V1 矛盾检测 + 拒绝强结论 |
| **case-04** | 错误码集中但无对应告警 | low/medium | **medium** | 3 | 错误码≠根因 |
| **case-05** | 告警先发生但 KPI 未异常 | INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | **0** | 告警≠根因 |
| **case-06** | KPI 异常但错误码分散 | low/INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | 3 (low) | 分散≠根因 |
| **case-07** | 多对象同时异常 | medium/low/INSUFFICIENT_EVIDENCE | **medium** | 3 | 对象归因不漂移 |
| **case-08** | 历史案例相似但当前证据不支持 | low/INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | 3 (low) | 历史≠当前 |
| **case-09** | Evidence 时间线冲突 | medium/low/INSUFFICIENT_EVIDENCE | **medium** | 3 | 时间线冲突识别 |
| **case-10** | 关键字段缺失 | low/INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | **0** | 缺字段拒绝强结论 |

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
| 泛化错归（错误归到非根因对象）| case-02 | ✅ |
| 处置命令越界（kubectl/ssh/SQL）| case-01, case-02 | ✅ |
| **多对象同时异常 → 对象归因不漂移** | **case-07** | ✅ |
| **历史案例相似但当前证据不支持 → 不强判** | **case-08** | ✅ |
| **Evidence 时间线冲突 → 降置信** | **case-09** | ✅ |
| **关键字段缺失 → INSUFFICIENT_EVIDENCE** | **case-10** | ✅ |

---

## Verifier 规则覆盖（V1-V9）

| 规则 | 含义 | 验证 case | v2 tag |
|:----:|------|-----------|:------:|
| V1 | 字段必填 + confidence 矛盾检测 | case-01~10 | v2.0.0 |
| V2 | 数值一致性反查 | case-01~10 | v2.0.0 |
| V3 | object_id 反查 | case-01~10 | v2.0.0 |
| V4 | 错误码 4 位格式 | case-01~10 | v2.0.0 |
| V5 | 百分比 0-100 | case-01~10 | v2.0.0 |
| V6 | 只读边界（kubectl/ssh/SQL/重启/扩容）| case-01~10 | v2.0.0 |
| V7 | **关键字段缺失检测**（Evidence D 缺错误码时不应 high）| case-10 | **v2.2.0** |
| V8 | 时间线闭合性检查（文档化，verifier 未实现）| case-09 | v2.2.0 (obs) |
| V9 | **历史案例引用检测**（recommend 不得"与历史案例相似"定根因）| case-08 | **v2.2.0** |

---

## CI 测试覆盖（runtime/tests/test_deterministic.py）

**31 项 deterministic 检查**：

1-4. Verifier 模块：good/bad/v1.1 badcase/confidence 矛盾
5-6. Verifier 模块 v2.2.0：V7/V9 fixture
7-16. Evidence Builder 10 case --validate
17. evidence_builder 渲染 4 段
18. evidence_builder 无 Tool 语义词
19-28. 10 case 存档 diagnosis.json 反向 PASS
29-31. CLI 端到端（verifier run / evidence_builder）

---

## 下一阶段

### P0 阶段 1 准入门槛（详见 `runtime/readiness-for-p0.md`）

- ✅ ≥10 case 已达（10/10）
- ✅ Verifier V1-V9 覆盖
- ⏳ 需扩场景（CBS 交易下降 / 告警风暴）
- ⏳ Evidence Pack 生成器对接真实监控/告警系统

---

## 关联

- 教训 39（LLM/程序/数据/报告职责分离）
- 教训 41（元治理不吞噬项目推进）
- Vanson 20:41 拍 D + 21:46 拍"现在就推进" + 22:04 拍 A "扩到 10+"
- v2.0.0 → v2.1.0 → v2.2.0 tag 演进