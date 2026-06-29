# Case 3 Mock Input — CBS 充值失败（证据不足 / 多候选冲突 / 验能拒绝）

> **目的**：验证模型在**证据不足 / 多候选冲突**场景下能否主动输出 R6 不确定报告，不强推根因
> **关键设计**：
> - 错误码分布**无主导**（多个错误码百分比接近）
> - 拓扑上下游**多个对象都有异常**
> - KPI 趋势**多个对象同时下降**
> - 历史案例**有冲突**（两个不同根因）
> **触发时间**：2026-06-30 00:38 CST

---

## 输入 JSON

```json
{
  "scenario": "cbs_charge_fail",
  "scenario_version": "v1.1",
  "recipe_file": "recipe-cbs-charge-v1.1.md",
  "case_id": "dry-run-case-03",
  
  "time_window": "2026-06-30 16:00:00 to 2026-06-30 16:30:00",
  "object_id": "CBS-GZ-02",
  "alert_id": "CBS-CHARGE-FAIL-ALERT-202606301618",
  "user_query": "某局点（广州，CBS-GZ-02）最近 30 分钟充值失败是否异常？可能原因是什么？"
}
```

---

## Mock 工具返回数据（故意设计为证据不足）

### T1: alert_query_by_time_window
```json
{
  "alerts": [
    {
      "alert_id": "CBS-CHARGE-FAIL-ALERT-202606301618",
      "trigger_time": "2026-06-30 16:18:00",
      "severity": "major",
      "object_id": "CBS-GZ-02"
    }
  ],
  "related_alerts": [
    {"alert_id": "OCS-GZ-01-LATENCY-HIGH-202606301612", "trigger_time": "2026-06-30 16:12:00", "severity": "minor"},
    {"alert_id": "GMDB-GZ-01-SLOW-QUERY-202606301614", "trigger_time": "2026-06-30 16:14:00", "severity": "minor"},
    {"alert_id": "ADAPTER-GZ-01-EXT-LATENCY-202606301615", "trigger_time": "2026-06-30 16:15:00", "severity": "minor"}
  ]
}
```

**关键**：**三个相关告警都出现**（OCS / GMDB / Adapter），不能直接定位单一上游异常。

### T2: kpi_trend_query
```json
{
  "metric": "cbs_charge_success_rate",
  "object_id": "CBS-GZ-02",
  "data_points": [
    {"timestamp": "16:00", "value": 99.0},
    {"timestamp": "16:15", "value": 98.5},
    {"timestamp": "16:20", "value": 96.8},
    {"timestamp": "16:25", "value": 96.5},
    {"timestamp": "16:30", "value": 96.2}
  ],
  "baseline": 99.0,
  "anomaly_window": "16:15-16:30"
}
```

### T3: error_code_statistic — **关键：错误码无主导**
```json
{
  "interface": "CBS-all",
  "total_errors": 932,
  "distribution": [
    {"code": "5004", "count": 287, "percentage": 30.8, "object_distribution": [{"object_id": "OCS-GZ-01", "count": 287}]},
    {"code": "5009", "count": 246, "percentage": 26.4, "object_distribution": [{"object_id": "GMDB-GZ-01", "count": 246}]},
    {"code": "6001", "count": 215, "percentage": 23.1, "object_distribution": [{"object_id": "ADAPTER-GZ-01", "count": 215}]},
    {"code": "5005", "count": 184, "percentage": 19.7, "object_distribution": [{"object_id": "OCS-GZ-01", "count": 120}, {"object_id": "OCS-GZ-02", "count": 64}]}
  ]
}
```

**关键**：**4 个错误码百分比都接近（30.8% / 26.4% / 23.1% / 19.7%），没有任何一个主导**。
**预期 R2 聚类应识别为"无法聚类"或"多主导"，**不应该强行定位单一根因**。

### T4: topology_upstream_downstream
```json
{
  "object_id": "CBS-GZ-02",
  "upstream": [
    {"object_id": "OCS-GZ-01", "type": "OCS"},
    {"object_id": "GMDB-GZ-01", "type": "GMDB"},
    {"object_id": "ADAPTER-GZ-01", "type": "Adapter"}
  ]
}
```

### T5: cmdb_object_lookup
```json
{
  "object_id": "CBS-GZ-02",
  "type": "CBS 实例",
  "location": "广州",
  "recent_change": "2026-06-30 14:00 配置变更（疑似诱因）"
}
```

### T6: fault_pattern_library
```json
{
  "pattern": "cbs_charge_fail_recent",
  "patterns": [
    {"name": "OCS 连接池耗尽", "typical_signals": ["错误码 5004 集中"]},
    {"name": "GMDB 慢查询", "typical_signals": ["错误码 5009 集中", "GMDB 查询时延升高"]},
    {"name": "Adapter 网关超时", "typical_signals": ["错误码 6001 集中", "外部链路时延+3s"]}
  ]
}
```

### T7: similar_incident_retrieve — **关键：历史案例冲突**
```json
{
  "similar_cases": [
    {
      "incident_id": "INC-2026-06-25-CBS-CHARGE",
      "root_cause": "OCS-BJ-02 连接池耗尽",
      "summary": "错误码 5004 集中，重启后恢复"
    },
    {
      "incident_id": "INC-2026-06-18-CHARGE-TIMEOUT",
      "root_cause": "Adapter 网关超时（第三方支付）",
      "summary": "第三方支付网关超时"
    },
    {
      "incident_id": "INC-2026-06-10-GMDB-SLOW",
      "root_cause": "GMDB 慢查询",
      "summary": "GMDB 慢查询导致接口超时"
    }
  ],
  "note": "3 个历史案例根因不一致，不应作为直接根因依据"
}
```

**关键**：**3 个历史案例根因完全不同**（OCS / Adapter / GMDB），**不能用任何一个作为根因决定**。

---

## 期望输出关键点

- **预期触发 R6 不确定报告**
- **不能强推根因**（即使是"高置信候选根因"也应有大量缺失证据）
- R2 聚类应识别为"无法聚类 / 多主导"
- R4 候选应列出 3 个（OCS / GMDB / Adapter 各一个），**且置信度都不超过中**
- 处置建议：**强调需补充证据 + 人工介入**
- **不能因历史案例 3 个冲突就直接放弃分析，也不能选其中一个作为根因**

## 验证目标

1. ✅ **不强行下结论**——触发 R6 不确定报告
2. ✅ **R2 识别错误码无主导**——不强行聚类到单一度
3. ✅ **R4 列出多个候选**——OCS / GMDB / Adapter 都列出
4. ✅ **R5 置信度不夸大**——所有候选都是中或低
5. ✅ **历史案例不直接决定根因**——3 个冲突案例不选一个
6. ✅ **数字一致性**：5004 → 30.8%，5009 → 26.4%，6001 → 23.1%，5005 → 19.7%（4 个百分比都对齐）
7. ✅ **处置建议只读**：人工确认项 + 风险提示（**强调证据不足**）
8. ✅ **JSON Schema 中 `final_verdict: "R6_uncertain_report"`**