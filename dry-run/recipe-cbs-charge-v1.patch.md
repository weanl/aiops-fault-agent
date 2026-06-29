# Recipe Patch v1.1 — CBS 充值失败 Prompt 修正

> **生成时间**：2026-06-30 00:23 CST
> **基础版本**：recipe-cbs-charge-v1.md
> **目标版本**：recipe-cbs-charge-v1.1
> **触发**：9B dry-run 5 红线 PASS，但发现 5 处可改进点（F1-F5）
> **回归测试**：必跑 9B dry-run 第二次，验证 patch 不引入新问题

---

## Patch 汇总（5 处）

| # | 问题 | 严重度 | patch 范围 |
|---|------|:------:|----------|
| F1 | Tool 6 "软跳过" | 🟡 中 | R4 prompt |
| F2 | Tool 7 "软跳过" | 🟡 中 | R4 prompt |
| F3 | 精确引用约束不足 | 🟡 中 | R1 prompt |
| F4 | 错误码笔误 | 🟢 低 | R2 prompt |
| F5 | 处理时长 Agent 自估 | 🟢 低 | 报告模板 |

**总改动**：~15 行 prompt 改动 + 1 处模板改动。

---

## F1 Patch：Tool 6 必须参考（故障模式库）

**现状**（recipe-cbs-charge-v1.md R4 prompt）：
```markdown
✅ 可以参考 `fault_pattern_library` 故障模式 + `similar_incident_retrieve` 相似案例
```

**改为**：
```markdown
✅ **必须**先调用 `fault_pattern_library(pattern="cbs_charge_fail_recent")` 获取故障模式清单
   - 故障模式是**专家经验沉淀**，是候选生成的必查输入
   - R4 的 3 个候选**至少 1 个**必须匹配故障模式库的某个 name
✅ 相似案例（Tool 7）**可参考但不强制**
```

---

## F2 Patch：Tool 7 必须参考（仅作分析路径）

**现状**：
```markdown
✅ 可以参考 `fault_pattern_library` 故障模式 + `similar_incident_retrieve` 相似案例
```

**改为**（与 F1 合并同一段）：
```markdown
✅ **必须**调用 `similar_incident_retrieve(query, time_range="-7d")` 获取相似案例
   - **红线**：相似案例只能用于**生成候选**和**参考分析路径**
   - **红线**：相似案例**绝不**直接作为根因决定证据（即不能说"上次是 X 所以这次也是 X"）
   - 候选生成后，每个候选的"分析路径参考"列要标注是否参考了相似案例
```

---

## F3 Patch：R1 精确引用约束

**现状**（recipe-cbs-charge-v1.md R1）：
```markdown
1. 调用 `alert_query_by_time_window(time_window)` 得到所有相关告警
2. 调用 `kpi_trend_query(metric="cbs_charge_success_rate", object_id, time_window)` 拿到成功率时序
3. 显式列出：告警触发时刻 / KPI 异常起止 / 错误码集中区间
4. 输出一段"时间线对齐结果"Markdown
```

**改为**（加 1 条规则）：
```markdown
1. 调用 `alert_query_by_time_window(time_window)` 得到所有相关告警
2. 调用 `kpi_trend_query(metric="cbs_charge_success_rate", object_id, time_window)` 拿到成功率时序
3. 显式列出：告警触发时刻 / KPI 异常起止 / 错误码集中区间
4. 输出一段"时间线对齐结果"Markdown

**R1 精确性约束**：
- 数字必须**严格复制** kpi_trend_query 返回的 `data_points[].value`，**不四舍五入**
- 时间必须**严格使用**告警 / KPI / 错误码返回的原始 timestamp，**不模糊**为"约 14 点"
- 错误码必须**严格使用**返回的 `code` 字段，**不省略数字**（如 `5004` 不能写 `500%` 或 `500`）
```

---

## F4 Patch：错误码格式约束

**现状**（recipe-cbs-charge-v1.md R2）：
```markdown
1. 调用 `error_code_statistic(interface="CBS-OCS", time_window)` 拿到错误码分布
2. 调用 `cmdb_object_lookup(object_id)` 确认网元类型
3. 显式列出：错误码 Top-3 + 各错误码的网元分布 + 网元的实例属性
```

**改为**（加 1 条规则）：
```markdown
1. 调用 `error_code_statistic(interface="CBS-OCS", time_window)` 拿到错误码分布
2. 调用 `cmdb_object_lookup(object_id)` 确认网元类型
3. 显式列出：错误码 Top-3 + 各错误码的网元分布 + 网元的实例属性

**R2 错误码约束**：
- 错误码是 4 位数字（如 `5004`），**必须完整引用**，不允许写成 `500%` 或省略数字
- 错误码描述必须从 `description` 字段复制（如 `OCS-CHG-FAIL-12`）
- 占比从 `percentage` 字段复制，保留小数点后 1 位
```

---

## F5 Patch：处理时长不允许 Agent 自估

**现状**（recipe-cbs-charge-v1.md Final Output）：
```markdown
> 案例编号：AIOPS-CBS-CHARGE-<YYYYMMDD>-<NNN>
> 生成时间：<time>
> 处理时长：<minutes>
```

**改为**：
```markdown
> 案例编号：AIOPS-CBS-CHARGE-<YYYYMMDD>-<NNN>
> 生成时间：<time>
> 处理时长：<input_from_caller_or_omit>（不允许 Agent 自己估算）
```

---

## 完整 patch diff（可直接 apply 到 v1）

```diff
--- a/recipe-cbs-charge-v1.md
+++ b/recipe-cbs-charge-v1.md
@@ -R4-section-1 @@
- ✅ 可以参考 `fault_pattern_library` 故障模式 + `similar_incident_retrieve` 相似案例
+ ✅ **必须**先调用 `fault_pattern_library(pattern="cbs_charge_fail_recent")` 获取故障模式清单
+    - 故障模式是**专家经验沉淀**，是候选生成的必查输入
+    - R4 的 3 个候选**至少 1 个**必须匹配故障模式库的某个 name
+ ✅ **必须**调用 `similar_incident_retrieve(query, time_range="-7d")` 获取相似案例
+    - **红线**：相似案例只能用于**生成候选**和**参考分析路径**
+    - **红线**：相似案例**绝不**直接作为根因决定证据（即不能说"上次是 X 所以这次也是 X"）

@@ -R1-section-2 @@
- 4. 输出一段"时间线对齐结果"Markdown
+ 4. 输出一段"时间线对齐结果"Markdown
+
+ **R1 精确性约束**：
+ - 数字必须**严格复制** kpi_trend_query 返回的 `data_points[].value`，**不四舍五入**
+ - 时间必须**严格使用**告警 / KPI / 错误码返回的原始 timestamp，**不模糊**为"约 14 点"
+ - 错误码必须**严格使用**返回的 `code` 字段，**不省略数字**（如 `5004` 不能写 `500%` 或 `500`）

@@ -R2-section-3 @@
- 3. 显式列出：错误码 Top-3 + 各错误码的网元分布 + 网元的实例属性
+ 3. 显式列出：错误码 Top-3 + 各错误码的网元分布 + 网元的实例属性
+
+ **R2 错误码约束**：
+ - 错误码是 4 位数字（如 `5004`），**必须完整引用**，不允许写成 `500%` 或省略数字
+ - 错误码描述必须从 `description` 字段复制（如 `OCS-CHG-FAIL-12`）
+ - 占比从 `percentage` 字段复制，保留小数点后 1 位

@@ -Final-Output @@
--> 处理时长：<minutes>
+> 处理时长：<input_from_caller_or_omit>（不允许 Agent 自己估算）
```

---

## 回归测试计划

### 测试项（最小集，验证 patch 有效性）

| # | 测试项 | 期望 |
|---|--------|------|
| RT1 | 重跑 dry-run-input.md | R4 必须调用 Tool 6 |
| RT2 | 重跑 dry-run-input.md | R4 必须调用 Tool 7（且标注"仅参考"）|
| RT3 | 重跑 dry-run-input.md | R1 数字精确（99.1% 而非 99.0%）|
| RT4 | 重跑 dry-run-input.md | 错误码写 `5004` 而非 `500%` |
| RT5 | 重跑 dry-run-input.md | 处理时长字段为 `<input_from_caller>` 或不写 |

### 验证后

- ✅ **5 项全过** → 应用 patch 到 v1（升级到 v1.1）
- ⚠️ **1-2 项 FAIL** → 重新调整 patch
- ❌ **3+ 项 FAIL** → 回滚 patch，保留 v1（dry-run 已 OK，不需要 patch）

---

## 状态

- ⏳ **patch 待应用**——等你拍板
- 拍板项：
  - **A. 应用 patch + 跑回归测试**（2 次 9B 调用）
  - **B. 仅应用 patch，不跑回归测试**（节省 token）
  - **C. 暂不应用 patch，保留 v1**（dry-run 已 OK）

**默认 B**——按复利原则不主动造 token。如果 v1 dry-run 已通过 P0 目标，patch 是"锦上添花"而非必需。