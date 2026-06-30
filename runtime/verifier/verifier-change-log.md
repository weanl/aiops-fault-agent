# Verifier Change Log

> **追踪 verifier.py 的所有改动 + 原因**
> **目的**：防止"verifier 改动后行为漂移"未被发现

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

### V7：错误码历史基线偏离度

- 需要 Evidence D 提供历史基线数据
- 偏离 > 2σ → 触发 confidence 降级建议
- **优先级**：中（A-mini 后下一轮）

### V8：告警与错误码时序一致性

- Evidence A 告警时间 vs Evidence D 错误码首次出现时间
- 时间差 > 5min → 标注"因果关系可疑"
- **优先级**：低

### V9：证据矩阵交叉引用

- evidence_matrix 中每个 claim 必须包含具体数值（错误码、百分比、KPI）
- 无具体数值 → 视为"空证据"
- **优先级**：中

---

## 不触发的规则

- ❌ 不修改 V1-V6 现有规则（已通过 15 项 CI 测试）
- ❌ 不引入 LLM 自检（保持纯 Python 确定性）
- ❌ 不在 verifier 里嵌入业务逻辑（verifier 只校验结构与一致性）