# Evidence Pack Template — CBS 充值失败 Dry-run

> **项目路径**：`project/aiops-fault-agent/`
> **版本**：v2（2026-06-30）
> **目的**：为 9B Diagnosis Agent 提供**静态、可追溯的事实**。
> **关键原则**：Evidence ≠ Tool。Evidence 是"已查询完成的快照"，不是"可调用函数"。

---

## ⚠️ 命名红线（9B 适配）

**禁止使用以下词汇**（会触发 9B tool call 循环）：

- ❌ `Tool` / `Tools` / `tool`
- ❌ `T1` / `T2` / `T3` / `T4` / `T5` / `T6` / `T7`
- ❌ `alert_query` / `kpi_trend_query` / `log_search` / `topology_query` 等动词_名词结构
- ❌ `function_call` / `<functioncall>` / `tool_calls`
- ❌ 任何"可调用"的暗示

**必须使用**：

- ✅ `Evidence A` / `Evidence B` / `Evidence C` / `Evidence D`（命名固定字母顺序）
- ✅ `Alarm` / `KPI` / `Topology` / `Error Statistics`（数据类型描述）
- ✅ `已查询完成` / `静态快照` / `查询结果`（状态描述）

---

## 📋 模板（每条 Case 复制此结构）

```markdown
# Evidence Pack — Case {N}: {case_name}

> **生成时间**：{YYYY-MM-DD HH:MM}
> **时间窗口**：{time_window}
> **查询状态**：已查询完成（静态快照，不可调用）
> **关联场景**：CBS 用户充值失败

---

## Evidence A — Alarm

**说明**：时间窗口内的告警快照（已从告警系统查询完成）。

| 告警 ID | 时间 | 对象 | 类型 | 等级 |
|---------|------|------|------|------|
| ALM-2026-{xxx} | HH:MM | {OBJECT-ID} | {alarm_type} | P{0-3} |

**备注**：
- {可选：告警趋势 / 关联说明}

---

## Evidence B — KPI

**说明**：相关网元的 KPI 快照（已从监控系统查询完成）。

| 对象 | 指标 | 数值 | 单位 | 时间 |
|------|------|------|------|------|
| {OBJECT-ID} | {metric_name} | {value} | {unit} | HH:MM |

**备注**：
- {可选：阈值 / 同比 / 环比}

---

## Evidence C — Topology

**说明**：相关网元的拓扑关系（已从 CMDB 查询完成）。

```
{OBJECT-A} → {OBJECT-B} → {OBJECT-C}
```

**对象清单**：
- {OBJECT-A}：{role}
- {OBJECT-B}：{role}
- {OBJECT-C}：{role}

---

## Evidence D — Error Statistics

**说明**：错误码分布统计（已从日志系统查询完成）。

| 错误码 | 次数 | 占比 | 主要对象 |
|--------|------|------|----------|
| {4位数字} | {count} | {pct}% | {OBJECT-ID} |

**备注**：
- {可选：错误码含义 / 历史基线}

---
```

---

## 📝 填写示例（Case 1 — OCS 连接池耗尽）

> ⚠️ 真实 Case 数据见 `dry-run-case-01-input.md`。这里只展示命名规范。

```markdown
# Evidence Pack — Case 1: OCS-BJ-02 连接池耗尽

> **生成时间**：2026-06-30 07:30 CST
> **时间窗口**：最近 30 分钟
> **查询状态**：已查询完成（静态快照，不可调用）

---

## Evidence A — Alarm

| 告警 ID | 时间 | 对象 | 类型 | 等级 |
|---------|------|------|------|------|
| ALM-2026-0628-001 | 14:25 | OCS-BJ-02 | 连接池使用率超阈值 | P2 |
| ALM-2026-0628-002 | 14:28 | OCS-BJ-02 | 充值错误率突增 | P1 |

## Evidence B — KPI

| 对象 | 指标 | 数值 | 单位 | 时间 |
|------|------|------|------|------|
| OCS-BJ-02 | 连接池使用率 | 98.5 | % | 14:30 |
| OCS-BJ-02 | 充值 TPS | 120 | req/s | 14:30 |
| OCS-BJ-02 | 平均响应时间 | 1850 | ms | 14:30 |

## Evidence C — Topology

```
CBS-SH-01 (入口) → OCS-BJ-02 (在线计费) → Adapter-PAY-01 (第三方支付)
```

- CBS-SH-01：充值入口网关
- OCS-BJ-02：在线计费系统（北京节点）
- Adapter-PAY-01：第三方支付适配器

## Evidence D — Error Statistics

| 错误码 | 次数 | 占比 | 主要对象 |
|--------|------|------|----------|
| 5004 | 4280 | 95.2 | OCS-BJ-02 |
| 5005 | 215 | 4.8 | OCS-BJ-02 |

**错误码说明**：
- 5004：连接池获取超时
- 5005：数据库写入超时
```

---

## ✅ Verifier 反查清单（程序会用这些做校验）

Evidence Pack 文本中出现的内容，**Verifier 会抽取作为合法值**：

1. **object_id**：匹配正则 `^[A-Z]{2,5}-[A-Z]{2}-\d{2}$`（如 `OCS-BJ-02`）
2. **错误码**：匹配正则 `^\d{4}$`（如 `5004`）
3. **Evidence 标签**：`Evidence A` / `Evidence B` / `Evidence C` / `Evidence D`
4. **百分比**：手动反查数值（Verifer 会校验 0-100 范围）

如果 Diagnosis JSON 里引用了 Evidence Pack 中**不存在**的值，Verifier 会判 FAIL。

---

## 🚫 不要做的事

- ❌ 在 Evidence Pack 中加"查询接口"或"调用方式"描述
- ❌ 用动词命名（`alert_query` / `get_kpi` 等）——会触发 9B tool loop
- ❌ 留空字段或写"TBD"——Verifier 会判字段缺失
- ❌ 加"未来可扩展"说明——这是静态快照，不是模板

---

## 关联

- `recipe-cbs-charge-v2.md`（9B Diagnosis Prompt）
- `recipe-cbs-charge-v2-report.md`（Report Rendering Prompt）
- `verifier.py`（确定性校验器）
- 3 条 Case 数据：`dry-run-case-0{1,2,3}-input.md`