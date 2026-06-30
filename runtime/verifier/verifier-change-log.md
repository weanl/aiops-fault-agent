# Verifier Change Log

> **追踪 verifier.py 的所有改动 + 原因**
> **目的**：防止"verifier 改动后行为漂移"未被发现

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

### 改动 3：V8 时间线闭合性检查（**文档化但未实现**）

**触发**：case-09 验证（时间线冲突）

**观察**：9B 在 case-09 中将 confidence 降至 medium，并在 evidence_matrix 中标注了"时间线冲突"——但 verifier **未做硬约束**。

**当前实现**：verifier 不强制要求 evidence_matrix 必须提到"时间线"——这是 9B 的判断空间。

**未实现原因**：时间线闭合性涉及复杂语义判断（如"22:05 OCS 告警后 22:25 CBS 告警"是否算"不闭合"？），V8 规则需要更多 case 验证才能定型。

**未来路径**：v2.3.0 起加 V8 fixture（要求 evidence_matrix 中至少 1 个 claim 包含"时间线"或"先后"或"因果"等关键词）。

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

### V8：时间线闭合性检查

- 状态：v2.2.0 文档化但未实现
- 未来路径：v2.3.0 起加 fixture + verifier 强制要求

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