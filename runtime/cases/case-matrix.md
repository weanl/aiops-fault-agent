# Case Matrix — CBS 充值失败 v2 验证集

> **生成时间**：2026-06-30 21:50 CST
> **范围**：6 case 端到端 PASS（v2.0.0 3 case + A-mini 3 case）
> **目的**：追踪每个 case 验证哪条 verifier 规则 / 哪类场景

---

## 矩阵（6 case × 6 验证维度）

| Case | 场景 | 期望 confidence | 实际 | top3 count | 验证维度 |
|:----:|------|:---------------:|:----:|:----------:|----------|
| **case-01** | OCS-BJ-02 连接池耗尽（典型根因）| high | high | 3 | V1/V2/V3 数值反查 + V6 只读边界 |
| **case-02** | Adapter 第三方支付网关超时 | high | high | 3 | V2/V3 数值反查 + 不泛化错归 |
| **case-03** | 证据不足 / 多候选冲突 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | 3 (low) | confidence 矛盾检测 + 拒绝强结论 |
| **case-04** | 错误码集中但无对应告警 | low/medium | **medium** | 3 | 不强判根因（错误码占比≠根因）|
| **case-05** | 告警先发生但 KPI 未异常 | INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | **0** | 不只凭告警定根因 |
| **case-06** | KPI 异常但错误码分散 | low/INSUFFICIENT_EVIDENCE | **INSUFFICIENT_EVIDENCE** | 3 (low) | 错误码分散不构成高置信 |

---

## 验证维度覆盖度

| 维度 | 覆盖 case | 状态 |
|------|-----------|:----:|
| **典型根因（高置信 + 集中错误码）** | case-01 | ✅ |
| **典型根因（高置信 + Adapter 链路）** | case-02 | ✅ |
| **证据不足 / 拒绝强结论** | case-03, case-05, case-06 | ✅ |
| **错误码集中但无告警 → 不强判** | case-04 | ✅ |
| **告警触发但 KPI 正常 → 不下结论** | case-05 | ✅ |
| **KPI 异常但错误码分散 → 低置信候选** | case-06 | ✅ |
| **泛化错归（错误归到非根因对象）** | case-02 | ✅（rank 1 是 GW-PAY-EXT，不是 OCS）|
| **处置命令越界（kubectl/ssh/SQL）** | case-01, case-02 | ✅（recommend 用自然语言）|

---

## Verifier 规则覆盖（V1-V6）

| 规则 | 含义 | 验证 case |
|:----:|------|-----------|
| V1 | 字段必填 + confidence 矛盾检测 | case-01~06 全跑 |
| V2 | 数值一致性反查 | case-01~06 全跑 |
| V3 | object_id 反查 | case-01~06 全跑 |
| V4 | 错误码 4 位格式 | case-01~06 全跑 |
| V5 | 百分比 0-100 | case-01~06 全跑 |
| V6 | 只读边界（kubectl/ssh/SQL/重启/扩容）| case-01~06 全跑 |

---

## CI 测试覆盖（runtime/tests/test_deterministic.py）

15 项 deterministic 检查：

1. verifier good fixture PASS
2. verifier bad fixture FAIL
3. verifier v1 badcase 拦截 ≥ 4 类
4. verifier confidence 矛盾检测
5-7. evidence_builder 3 case --validate
8. evidence_builder 渲染包含 4 段
9. evidence_builder 无 Tool 语义词
10-12. 3 case 存档 diagnosis.json 反向 PASS
13. verifier CLI run
14. evidence_builder CLI
15. (总数 = 15)

---

## 下一阶段扩 case 方向（Vanson 20:41 拍 D 后）

### B 路径：扩展场景（SCENARIOS.md）

- CBS 交易下降（独立故障类型）
- 告警风暴（关联告警聚合）
- 多区域同故障（跨节点关联）
- 第三方支付商户侧问题（链路下移）

### C 路径：扩 verifier 规则

- V7：错误码历史基线偏离度（与 Evidence D 占比交叉）
- V8：告警与错误码时序一致性（Evidence A 时间 vs Evidence D 触发时间）
- V9：证据矩阵交叉引用（evidence_matrix 中 claim 必须包含具体数值）

### P0 阶段 1 准入门槛（当前进度）

- 3/10 边界 ✅（已 6 条）
- 需扩到 10+ 条 → **再写 4-6 条**才达准入

---

## 关联

- 教训 39（LLM/程序/数据/报告 四职责分离）
- 教训 41（元治理不吞噬项目推进）
- `evolution/insights.md` 教训 41 段
- Vanson 07:13 拍板 v2 重构 + 07:31 拍板 C-mini + 07:48 拍板先 CI 后 tag + 20:41 拍 D 复盘