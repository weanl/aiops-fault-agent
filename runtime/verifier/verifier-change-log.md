# Verifier Change Log

> **追踪 verifier.py 的所有改动 + 原因**
> **目的**：防止"verifier 改动后行为漂移"未被发现

---

## v2.2.0 → v2.2.1（2026-06-30 22:50）

### 改动 1：V8 时间线闭合性从"文档化未实现"→ 确定性实现

**触发**：Vanson 22:33 拍 D-mini，**优先级高于 A-mini（真实 OpenAPI 接入设计）**。

**问题**：v2.2.0 中 V8 时间线闭合性被记录为"文档化但未实现"。9B 在 case-09 中虽然自行降级为 medium（因为发现错误码时间戳缺失），但 verifier **没有硬约束**：如果 9B 在时间线冲突场景下输出 high confidence，verifier 不会拦截。

**改动**：

1. **新增独立模块** `runtime/verifier/timeline_parser.py`：
   - `parse_evidence_alarms(evidence_text)`：从 Evidence A 抽取 {time_minutes, object_id, level}
   - `parse_evidence_kpi_times(evidence_text)`：从 Evidence B 抽取 (time_minutes, object_id)
   - `parse_evidence_error_codes(evidence_text)`：从 Evidence D 抽取 (code, pct, object_id) —— **占比 0% 跳过**
   - `parse_topology_upstream(evidence_text)`：从 Evidence C ASCII 图解析上下游映射
   - `detect_conflicts(evidence_text, diag)`：返回 4 类冲突列表
   - `check_timeline_closure(diag, evidence_text)`：返回 verifier errors

2. **C1-C4 四类冲突检测**：
   - **C1**：拓扑下游告警早于上游 ≥ 5 分钟 → 因果倒挂
   - **C2**：错误码主要对象（pct>0%）不在告警对象集 → 沉默故障嫌疑
   - **C3**：KPI 时间 < 最早告警时间 - 5 分钟 → 因果倒挂
   - **C4**：所有错误码对象与告警对象完全不相交 → 完全沉默

3. **verifier.py 主流程接入**：
   - 新增 `check_timeline_consistency(diag, evidence_text)` 包装函数（独立 try/except 防解析异常）
   - 主 verify() 流程追加 V8 调用

4. **错误码解析 bug 修复**：
   - `parse_evidence_error_codes` 返回值从 `(code, object_id)` 改为 `(code, pct, object_id)`
   - 跳过占比 0% 的行（"主动排除"语义，不算主要对象）
   - **修复后 case-02 evidence（OCS 错误码 5004/5005 占比 0%）不再误报 C2**

5. **3 组 V8 fixture**（`runtime/verifier/fixtures/`）：
   - `v8-conflict-high-fail`：C2 命中 + high → **FAIL**（负向）
   - `v8-closed-high-pass`：时间线闭合 + high → **PASS**（正向，不误伤）
   - `v8-conflict-low-pass`：冲突 + INSUFFICIENT_EVIDENCE → **PASS**（正向，不限制 9B 自由判断）

6. **case-09 evidence 强化**：
   - 在 Evidence D 加 6001 错误码集中在 Adapter-PAY-01（不在告警对象集）→ 触发 C2
   - 9B 重跑 → 仍降级为 medium（rank 3 候选识别 Adapter 静默故障）
   - case-09 现在同时是 V8 正向样例（9B 正确识别冲突并降级）

7. **test_deterministic 加 V8 测试**：
   - `test_verifier_v8_timeline_conflict_high_fails`
   - `test_verifier_v8_timeline_closed_high_passes`
   - `test_verifier_v8_timeline_conflict_low_passes`

**测试覆盖**：

- 10 case 全量回归：10/10 PASS
- V8 fixture 三组：FAIL / PASS / PASS（符合预期）
- test_deterministic: **34/34 PASS**（v2.2.0 是 31/31，新增 3 项 V8 测试）

**不触发规则**：

- ❌ 不修改 V1-V7 现有规则
- ❌ 不调用 LLM 自检（保持纯 Python 确定性）
- ❌ 不为了 case-02 PASS 降低 C2 阈值（仅修复"占比 0% 算主要对象"的解析 bug）
- ❌ 不允许 case-09 改为简单通过（必须真实命中 V8 冲突）

---

## v2.1.0 → v2.2.0（2026-06-30 22:50）

### 改动 1：新增 V7 关键字段缺失检测

**触发**：case-10 验证（缺字段时 9B 误输出 high）

**问题**：原 verifier V1-V6 不检查 Evidence Pack 关键字段是否缺失。如果 Evidence D（Error Statistics）为空，但 9B 仍输出 high 置信，verifier 不会拦截。

**改动**：新增 `check_evidence_completeness()`：
- 拆分 evidence_text 为 4 段（## Evidence A/B/C/D）
- 检查 Evidence D 段内是否含 4 位数字错误码
- 若 Evidence D 无错误码但 diagnosis confidence=high → FAIL
- 若 Evidence D 无错误码但 top3 中任一 candidate confidence=high → FAIL

**影响**：
- case-10 反向验证：Evidence D 缺，9B 输出 INSUFFICIENT_EVIDENCE + top3=[] → 通过
- 新增 test_verifier_v7_evidence_d_missing fixture：模拟 case-10 误输出 high → FAIL
- V7 触发例：1 项
- 6 个老 case + case-07/09 不触发（它们 Evidence D 都有数据）

**测试覆盖**：`runtime/tests/test_deterministic.py` test_verifier_v7_evidence_d_missing

---

### 改动 2：新增 V9 历史案例引用检测

**触发**：case-08 验证（"与历史案例相似"陷阱）

**问题**：9B 可能被诱导用历史案例直接定根因，例如："与历史案例相似，所以当前根因是 OCS"。这种表述即使 confidence 标注为 medium/low，仍是**不严谨的诊断结论**。

**改动**：新增 `check_command_reference_safety()`：
- 检查 `recommend` 字段中是否含"与历史案例相似""历史上有过""历史案例表明""根据历史.*得出""历史上.*所以当前"等表述
- 任一命中 → FAIL

**影响**：
- case-08 反向验证：recommend 未引用历史 → 通过
- 新增 test_verifier_v9_historical_reference fixture：模拟"与历史案例相似" → FAIL

**测试覆盖**：`runtime/tests/test_deterministic.py` test_verifier_v9_historical_reference

---

### 改动 3：V8 时间线闭合性检查（**v2.2.1 已实现**）

**v2.2.0 状态**：文档化但未实现，依赖 9B 自行判断。

**v2.2.1 落地**：见上方 v2.2.0 → v2.2.1 章节的 7 项改动。

---

## v2.0.0 → v2.1.0（2026-06-30 22:00）

### 改动 1：新增 `confidence_cross_check`（V1 扩展）

**触发**：A-mini case-04 验证

**问题**：原 V1 只检查 overall confidence 字段是否在合法枚举（high/medium/low/INSUFFICIENT_EVIDENCE），**未检查 overall confidence 与 top3 candidates confidence 的一致性**。

**风险场景**：overall confidence=INSUFFICIENT_EVIDENCE 时，9B 仍可能在 top3 里给出 high 候选 —— 这是**逻辑矛盾**。

**改动**：check_confidence_field 加交叉检查：
```python
if conf == "INSUFFICIENT_EVIDENCE":
    for rc in top3_root_cause:
        if rc.get("confidence") == "high":
            errs.append({...})  # 矛盾
```

**影响**：
- case-03 反向验证：3 low candidates + overall INSUFFICIENT_EVIDENCE → 通过（无矛盾）
- case-06 反向验证：3 low/medium + overall INSUFFICIENT_EVIDENCE → 通过
- 任何未来 case 出现矛盾 → FAIL

**测试覆盖**：`runtime/tests/test_deterministic.py` test_verifier_confidence_cross_check

---

## v2.0.0 → v2.1.0（2026-06-30 22:00）

### 改动 2：verifier runner_meta 兼容

**触发**：诊断 runner 输出格式升级（增加 `runner_meta` wrapper）

**问题**：v2.0.0 verifier 期望 diagnosis 文件直接是 JSON 对象。v2.1.0 runner 输出 `{diagnosis: {...}, runner_meta: {...}}` 格式。

**改动**：verify() 函数加 unwrap 逻辑：
```python
if "diagnosis" in diag and isinstance(diag["diagnosis"], dict):
    diag = diag["diagnosis"]
```

**影响**：v2.0.0 存档的 case-01/02/03 diagnosis.json 仍能被新 verifier 验证（向后兼容）

---

## 未来可能改动（**待 Vanson 拍板**）

### V10：多对象归因均衡检查

- 状态：v2.2.0 文档化但未实现
- 设计意图：top3 中至少 2 个 candidate 涉及不同 object_id（防单对象漂移）
- 风险：可能误伤 case-01（典型单对象根因）
- 未来路径：仅在 top3_root_cause 长度 ≥ 2 时检查，且 overall confidence != high 时跳过

### V11：告警数量 vs 错误码量交叉

- 多告警 + 少错误码 → 可能是告警风暴/误报
- 少告警 + 多错误码 → 可能是静默故障
- 状态：v2.2.0 未涉及

---

## 不触发的规则

- ❌ 不修改 V1-V6 现有规则（已通过 31 项 CI 测试）
- ❌ 不引入 LLM 自检（保持纯 Python 确定性）
- ❌ 不在 verifier 里嵌入业务逻辑（verifier 只校验结构与一致性）
- ❌ 不强制要求 evidence_matrix 含时间线分析（V8 暂文档化）
- ❌ 不强制要求 top3 多对象均衡（V10 暂文档化）