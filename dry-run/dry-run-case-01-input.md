# Case 1 Mock Input — CBS 充值失败（OCS 连接池耗尽 / 原 badcase 验证）

> **目的**：验证原 badcase（500% 全在 OCS-BJ-02 + 比例不一致 + kubectl 重启）是否修复
> **触发时间**：2026-06-30 00:38 CST
> **Recipe 版本**：recipe-cbs-charge-v1.1.md（应用 6 patch）

---

## 输入 JSON

```json
{
  "scenario": "cbs_charge_fail",
  "scenario_version": "v1.1",
  "recipe_file": "recipe-cbs-charge-v1.1.md",
  "case_id": "dry-run-case-01",
  
  "time_window": "2026-06-30 14:00:00 to 2026-06-30 14:30:00",
  "object_id": "CBS-BJ-03",
  "alert_id": "CBS-CHARGE-FAIL-ALERT-202606301425",
  "user_query": "某局点（北京，CBS-BJ-03）最近 30 分钟充值失败是否异常？可能原因是什么？"
}
```

---

## Mock 工具返回数据（7 个工具）

### T1: alert_query_by_time_window
```json
{
  "alerts": [
    {
      "alert_id": "CBS-CHARGE-FAIL-ALERT-202606301425",
      "trigger_time": "2026-06-30 14:25:00",
      "severity": "major",
      "object_id": "CBS-BJ-03",
      "description": "CBS 充值失败率超过阈值",
      "metric_value": "失败率 3.5%"
    }
  ],
  "related_alerts": [
    {"alert_id": "OCS-BJ-02-CONN-POOL-HIGH-202606301420", "trigger_time": "2026-06-30 14:20:00", "severity": "minor"}
  ]
}
```

### T2: kpi_trend_query
```json
{
  "metric": "cbs_charge_success_rate",
  "object_id": "CBS-BJ-03",
  "data_points": [
    {"timestamp": "14:00", "value": 99.1},
    {"timestamp": "14:15", "value": 99.1},
    {"timestamp": "14:20", "value": 98.5},
    {"timestamp": "14:25", "value": 96.5},
    {"timestamp": "14:30", "value": 96.5}
  ],
  "baseline": 99.1,
  "anomaly_window": "14:20-14:30"
}
```

### T3: error_code_statistic
```json
{
  "interface": "CBS-OCS",
  "total_errors": 1247,
  "distribution": [
    {"code": "5004", "count": 1085, "percentage": 87.0, "object_distribution": [{"object_id": "OCS-BJ-02", "count": 1085}]},
    {"code": "5005", "count": 120, "percentage": 9.6, "object_distribution": [{"object_id": "OCS-BJ-02", "count": 80}, {"object_id": "OCS-BJ-01", "count": 40}]},
    {"code": "5009", "count": 42, "percentage": 3.4, "object_distribution": [{"object_id": "OCS-SH-01", "count": 42}]}
  ]
}
```

### T4: topology_upstream_downstream
```json
{
  "object_id": "CBS-BJ-03",
  "upstream": [
    {"object_id": "OCS-BJ-02", "type": "OCS"},
    {"object_id": "ADAPTER-BJ-01", "type": "Adapter"}
  ]
}
```

### T5: cmdb_object_lookup
```json
{
  "object_id": "CBS-BJ-03",
  "type": "CBS 实例",
  "location": "北京",
  "owner": "CBS-team"
}
```

### T6: fault_pattern_library
```json
{
  "pattern": "cbs_charge_fail_recent",
  "patterns": [
    {"name": "OCS 连接池耗尽", "typical_signals": ["错误码 5004 集中", "连接池监控超阈值"]},
    {"name": "Adapter 网关超时", "typical_signals": ["外部链路时延+3s"]},
    {"name": "CBS 实例 JVM GC 异常", "typical_signals": ["full GC 频繁", "P99 时延升高"]}
  ]
}
```

### T7: similar_incident_retrieve
```json
{
  "similar_cases": [
    {
      "incident_id": "INC-2026-06-25-CBS-CHARGE",
      "root_cause": "OCS-BJ-02 连接池耗尽",
      "summary": "错误码 5004 集中在 OCS-BJ-02，重启后恢复",
      "note": "仅作为分析路径和根因候选参考，不作为本次根因的直接决定依据"
    }
  ]
}
```

---

## 期望输出关键点（用于对比）

- 推荐高置信候选根因：**OCS-BJ-02 连接池耗尽**（证据：5004 错误码 87.0% 集中在 OCS-BJ-02）
- 数字一致性：**5004 → 87.0%**（不是 500%）
- 5005 → 9.6%（全文一致）
- 成功率 96.5%（不是 96.3%）
- 处置建议：**只读诊断版**（人工确认项 + 风险提示），不输出 kubectl/重启
- V5 自检 PASS 后，必须有确定性校验 PASS

## 验证目标（覆盖原 badcase）

1. ❌ **不再有"500%"污染** → 写"5004 错误码 87.0% 集中在 OCS-BJ-02"
2. ❌ **比例一致** → 5005 全程 9.6%（不是 5%）
3. ❌ **无 kubectl / 重启建议** → 只写"建议人工确认"
4. ❌ **V5 自检不能直接 PASS** → 必须有确定性校验器复核
5. ✅ **推荐高置信候选根因** → 表达严谨（不是"确定根因"）