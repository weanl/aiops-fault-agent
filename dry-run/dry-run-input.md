# CBS 充值失败诊断 — Mock 输入

> **场景**：CBS 用户充值失败（mock 数据，不接真实 OpenAPI）
> **生成时间**：2026-06-30 00:18 CST
> **目的**：在 9B 上 dry-run `recipe-cbs-charge-v1.md`

---

## 输入（标准 JSON 格式）

```json
{
  "scenario": "cbs_charge_fail",
  "scenario_version": "v1",
  "recipe_file": "recipe-cbs-charge-v1.md",
  
  "time_window": "2026-06-30 14:00:00 to 2026-06-30 14:30:00",
  "object_id": "CBS-BJ-03",
  "alert_id": "CBS-CHARGE-FAIL-ALERT-202606301425",
  "user_query": "某局点（北京，CBS-BJ-03）最近 30 分钟充值失败是否异常？可能原因是什么？",
  
  "context": {
    "scenario": "CBS 平台用户充值失败诊断",
    "system_role": "Recipe-driven Agent",
    "recipe_steps": ["R1 时间线对齐", "R2 异常聚类", "R3 传播链追踪", "R4 根因候选生成", "R5 证据矩阵填充"],
    "available_tools": [
      "alert_query_by_time_window",
      "kpi_trend_query",
      "error_code_statistic",
      "topology_upstream_downstream",
      "cmdb_object_lookup",
      "fault_pattern_library",
      "similar_incident_retrieve"
    ],
    "red_lines": [
      "不在范围的问题明确拒绝",
      "5 步 Recipe 不可跳步",
      "历史案例不直接决定根因",
      "不自动执行处置",
      "所有结论绑定证据"
    ]
  }
}
```

---

## Mock 数据预设（9B 跑时使用）

### Mock 工具调用结果（每个 tool 的预设返回）

#### Tool 1: alert_query_by_time_window(time_window="2026-06-30 14:00:00 to 14:30:00")
**返回**（mock）:
```json
{
  "alerts": [
    {
      "alert_id": "CBS-CHARGE-FAIL-ALERT-202606301425",
      "trigger_time": "2026-06-30 14:25:00",
      "severity": "major",
      "object_id": "CBS-BJ-03",
      "description": "CBS 充值失败率超过阈值（>2%）",
      "metric_value": "失败率 3.5%",
      "related_alerts": [
        {"alert_id": "OCS-BJ-02-CONN-POOL-HIGH-202606301420", "trigger_time": "2026-06-30 14:20:00", "severity": "minor"},
        {"alert_id": "CBS-BJ-03-LATENCY-HIGH-202606301422", "trigger_time": "2026-06-30 14:22:00", "severity": "minor"}
      ]
    }
  ],
  "total_count": 1
}
```

#### Tool 2: kpi_trend_query(metric="cbs_charge_success_rate", object_id="CBS-BJ-03", time_window="2026-06-30 14:00:00 to 14:30:00")
**返回**（mock）:
```json
{
  "metric": "cbs_charge_success_rate",
  "object_id": "CBS-BJ-03",
  "data_points": [
    {"timestamp": "14:00", "value": 99.2},
    {"timestamp": "14:10", "value": 99.1},
    {"timestamp": "14:15", "value": 99.0},
    {"timestamp": "14:20", "value": 98.5},
    {"timestamp": "14:25", "value": 96.5},
    {"timestamp": "14:30", "value": 96.3}
  ],
  "baseline": 99.1,
  "anomaly_window": "14:20-14:30"
}
```

#### Tool 3: error_code_statistic(interface="CBS-OCS", time_window="2026-06-30 14:00:00 to 14:30:00")
**返回**（mock）:
```json
{
  "interface": "CBS-OCS",
  "total_errors": 1247,
  "distribution": [
    {"code": "5004", "description": "OCS-CHG-FAIL-12", "count": 1085, "percentage": 87.0, "object_distribution": [{"object_id": "OCS-BJ-02", "count": 1085}]},
    {"code": "5005", "description": "OCS-TIMEOUT", "count": 120, "percentage": 9.6, "object_distribution": [{"object_id": "OCS-BJ-02", "count": 80}, {"object_id": "OCS-BJ-01", "count": 40}]},
    {"code": "5009", "description": "OCS-INTERNAL-ERR", "count": 42, "percentage": 3.4, "object_distribution": [{"object_id": "OCS-SH-01", "count": 42}]}
  ]
}
```

#### Tool 4: topology_upstream_downstream(object_id="CBS-BJ-03", depth=3)
**返回**（mock）:
```json
{
  "object_id": "CBS-BJ-03",
  "upstream": [
    {"object_id": "OCS-BJ-02", "type": "OCS", "relation": "CBS→OCS 充值接口"},
    {"object_id": "GMDB-BJ-01", "type": "GMDB", "relation": "OCS→GMDB 余额查询"},
    {"object_id": "ADAPTER-BJ-01", "type": "Adapter", "relation": "CBS→Adapter 第三方支付"}
  ],
  "downstream": [
    {"object_id": "USER-BJ-NEW", "type": "User Group", "relation": "影响用户群"}
  ]
}
```

#### Tool 5: cmdb_object_lookup(object_id="CBS-BJ-03")
**返回**（mock）:
```json
{
  "object_id": "CBS-BJ-03",
  "type": "CBS 实例",
  "location": "北京",
  "owner": "CBS-team",
  "biz_line": "充值",
  "attributes": {
    "version": "v8.5.2",
    "deploy_date": "2026-05-15",
    "last_change": "2026-06-25 11:00:00 配置更新"
  }
}
```

#### Tool 6: fault_pattern_library(pattern="cbs_charge_fail_recent")
**返回**（mock）:
```json
{
  "pattern": "cbs_charge_fail_recent",
  "patterns": [
    {
      "name": "OCS 连接池耗尽导致 CBS 充值失败",
      "frequency": "中",
      "typical_signals": ["错误码 5004 集中", "OCS 连接池监控超阈值", "成功率断崖式下降"],
      "typical_objects": ["OCS 实例"]
    },
    {
      "name": "Adapter 网关到第三方支付超时",
      "frequency": "中",
      "typical_signals": ["外部链路时延升高", "Adapter→第三方时延+3s+"],
      "typical_objects": ["Adapter 实例"]
    },
    {
      "name": "CBS 实例 JVM GC 异常",
      "frequency": "低",
      "typical_signals": ["GC 日志 full GC 频繁", "CBS 实例 P99 时延升高"],
      "typical_objects": ["CBS 实例"]
    }
  ]
}
```

#### Tool 7: similar_incident_retrieve(query="CBS 充值失败 5004 错误码集中", time_range="-7d")
**返回**（mock，**只参考不直接决定**）:
```json
{
  "similar_cases": [
    {
      "incident_id": "INC-2026-06-25-CBS-CHARGE",
      "date": "2026-06-25",
      "root_cause": "OCS-BJ-02 连接池耗尽",
      "summary": "类似错误码 5004 集中，集中在 OCS-BJ-02，重启后恢复",
      "outcome": "已解决"
    },
    {
      "incident_id": "INC-2026-06-18-CHARGE-TIMEOUT",
      "date": "2026-06-18",
      "root_cause": "Adapter 网关超时",
      "summary": "第三方支付网关超时导致充值失败",
      "outcome": "已解决"
    }
  ],
  "note": "以上案例仅作为分析路径和根因候选参考，不作为本次根因的直接决定依据"
}
```

---

## 期望输出（仅作评测参考）

### 期望报告关键字段
- 推荐根因：**OCS-BJ-02 连接池耗尽**（基于 Tool 3 错误码 87% 集中在该实例 + Tool 1 关联告警）
- 置信度：**高**
- 关键证据：1085/1247（87%）错误集中在 OCS-BJ-02
- 反证：Adapter 链路暂无明显异常
- 缺失证据：OCS-BJ-02 连接池监控值（应该有但 mock 没给）

### 5 红线检查清单
- [ ] R1-R5 全部执行（**5 步不能跳步**）
- [ ] 不擅自 ReAct（**没用未列出工具**）
- [ ] 历史案例不直接决定根因（**没有"上次是这样所以这次也是"**）
- [ ] 不编造数据（**所有引用都来自 mock tools**）
- [ ] 报告结构完整（**8 节模板**）
- [ ] 证据不足时拒绝下结论（R6 触发判断，**不强推根因**）
