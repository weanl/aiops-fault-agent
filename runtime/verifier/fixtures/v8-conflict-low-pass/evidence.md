# Evidence Pack — Fixture V8-Conflict-Low-PASS

> **目的**：V8 时间线闭合性正向测试 —— 当 Evidence 存在冲突（C2 沉默对象）时，
> 9B 正确降级为 INSUFFICIENT_EVIDENCE，verifier 必须 PASS（V8 不强制要求 medium/low）。

---

## Evidence A — Alarm

**说明**：时间窗口内的告警快照。

| 告警ID | 时间 | 对象 | 类型 | 等级 |
|---|---|---|---|---|
| ALM-FIX-201 | 16:00 | CBS-SH-01 | 充值成功率下降 | P3 |

**备注**：仅 CBS 一条告警

---

## Evidence B — KPI

**说明**：KPI 快照。

| 对象 | 指标 | 数值 | 单位 | 时间 |
|---|---|---|---|---|
| CBS-SH-01 | 充值成功率 | 75.0 | % | 16:30 |
| OCS-BJ-02 | 连接池使用率 | 70.0 | % | 16:30 |

**备注**：OCS 指标正常，CBS 略低

---

## Evidence C — Topology

**说明**：拓扑关系。

```
CBS-SH-01 (充值入口) → OCS-BJ-02 (在线计费) → Adapter-PAY-01 (第三方支付)
```

**对象清单**：
- CBS-SH-01
- OCS-BJ-02
- Adapter-PAY-01

---

## Evidence D — Error Statistics

**说明**：错误码分布。

| 错误码 | 次数 | 占比 | 主要对象 |
|---|---|---|---|
| 5004 | 30 | 30.0 | **OCS-BJ-02** |

**备注**：
- 5004 集中在 OCS-BJ-02（30%）—— **但 OCS 在告警对象集中不存在**
- 典型 C2 沉默对象信号

---