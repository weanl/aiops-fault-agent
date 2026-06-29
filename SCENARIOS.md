# AIOps 故障 Agent — P0 场景用户旅程

> **版本**：v1（2026-06-30）
> **项目路径**：`project/aiops-fault-agent/`
> **作用**：3 个 P0 场景的完整用户旅程 + 数据 + 工具 + Recipe + 报告模板 + 评测
> **关联**：`research/aiops-project-charter-2026-06-30.md`（立项 v0）

---

## 通用模板（P0 所有场景必走）

```
感知 → 提问/触发 → 上下文构建 → 数据查询 → 诊断分析 → 证据校验 → 报告输出 → 反馈沉淀
```

**每场景必含 6 要素**：
1. **用户旅程**（8 步详细化）
2. **所需数据**（5 类资产 × 旅程步骤映射）
3. **工具清单**（每个旅程步骤的具体 tool）
4. **诊断 Recipe**（固定流程，不是自由 ReAct）
5. **输出报告模板**（结构化 Markdown）
6. **评测指标**（场景级 + 诊断级 + 报告级）

**红线**：
- ❌ 不做完全自主 ReAct Loop
- ❌ P0 不主打 NL2SQL
- ❌ 历史案例**不**直接决定当前根因（只用于分析路径 + 根因候选）
- ✅ 所有结论必须绑定证据
- ✅ 工具调用和证据链比自由推理更重要

---

# 场景 1：CBS 用户充值失败

## 1.1 用户旅程（8 步）

### Step 1：问题感知
**触发**：
- 充值失败告警（CBS 平台告警组）
- 客户投诉工单（CRM 系统接入）
- CBS 充值成功率 KPI 异常下降（>5% vs 基线）

**Agent 接收**：
- 告警 ID / 工单 ID / KPI 异常事件 ID

### Step 2：进入分析（提问）
**用户问题示例**：
- 「某局点最近 30 分钟充值失败是否异常？可能原因是什么？」
- 「告警 CBS-CHARGE-FAIL-ALERT 在 14:25 触发，请定位根因」
- 「充值成功率从 99.2% 降到 96.5%，可能影响哪些用户？」

**Agent 解析**：
- 时间范围（自动默认近 30 分钟）
- 局点 / 网元 / 业务对象
- 异常维度（成功率 / 错误码 / 时延）

### Step 3：上下文构建
**自动识别**：
- 时间窗口（异常发生时间点 + 前后各 30min）
- 网元对象（CBS 实例 ID、OCS 实例、GMDB 实例、Adapter 实例）
- 相关告警（同一时间窗、同类对象的告警）
- 相关 KPI（成功率、时延、QPS、错误码分布）
- 相关接口（CBS→OCS、OCS→GMDB、Adapter→第三方支付）
- 历史案例（同网元、同错误码、同 KPI 模式的近期案例，**仅作参考不直接决定根因**）

### Step 4：数据查询（5 类资产）

| 工具 | 数据资产 | 调用示例 |
|------|---------|----------|
| `alert_query_by_time_window` | 运维观测 | `alert_type=CBS-CHARGE, window=14:00-14:30` |
| `kpi_trend_query` | 运维观测 | `metric=cbs_charge_success_rate, host=CBS-XXX, window=14:00-14:30` |
| `error_code_statistic` | 运维观测 | `interface=CBS-OCS, code=5004, window=...` |
| `topology_upstream_downstream` | 对象拓扑 | `object=CBS-XXX, depth=3` |
| `cmdb_object_lookup` | 对象拓扑 | `object_id=CBS-XXX → type/owner/biz` |
| `fault_pattern_library` | 知识案例 | `pattern=cbs_charge_fail_recent` |
| `similar_incident_retrieve` | 知识案例 | `query=CBS 充值失败 5004，时间窗=-7d`（**仅生成候选不直接决定**） |
| `biz_flow_chart_lookup` | 业务语义 | `flow=cbs_charge → 步骤+接口+错误码` |

### Step 5：诊断分析（Recipe 驱动）

**固定分析路径**（5 步 Recipe，**不是 ReAct**）：
```
R1. 时间线对齐          聚合所有 K 线事件到统一时间轴
R2. 异常聚类            按 [接口, 错误码, 网元] 3 维聚类
R3. 传播链追踪          从告警对象沿拓扑上溯到 OCS/GMDB/Adapter
R4. 根因候选生成        基于聚类结果 + 故障模式库 + 历史相似案例 → Top-3
R5. 证据矩阵填充        每个候选补齐 [支持证据 / 反证 / 缺失证据 / 不确定项]
```

**特别注意**：
- R4 历史相似案例只用于**生成候选**和**参考分析路径**，**不直接决定**根因
- R5 缺失证据要明确列出，不能为了闭环而硬下结论

### Step 6：结果校验

**校验维度（5 项，必须全过才算 PASS）**：
- ✅ 时间窗口与原始问题一致
- ✅ 所有引用的告警来自真实 `alert_query` 结果
- ✅ 所有引用的 KPI 来自真实 `kpi_trend` 结果
- ✅ 根因有至少 1 条 R5 支持证据
- ✅ 不存在编造数据（**幻觉检测**）

**FAIL 处理**：
- 校验 FAIL → 返回 R4 重做（缩小 / 补查 / 标注不确定）
- 3 次 FAIL → 升级到 L3「不确定报告」输出

### Step 7：输出报告

```markdown
# CBS 充值失败诊断报告

> 案例编号：AIOPS-CBS-CHARGE-20260630-001
> 生成时间：2026-06-30 14:35 CST
> 处理时长：约 4 分钟（从触发到报告）

## 1. 问题概述
- 异常事件：CBS-CHARGE-FAIL-ALERT 在 14:25:00 触发
- 失败笔数：1,247 笔 / 30 min（基线 < 50 笔）
- 成功率：从 99.2% 降到 96.5%
- 影响局点：北京、上海、广州（共 3 个）

## 2. 异常现象
- 时间窗：14:20-14:30（最近 30 分钟）
- 主要错误码：5004（OCS-CHG-FAIL-12）占 87%
- 异常对象：CBS-BJ-03 充值接入节点

## 3. 根因候选（Top-3）
| # | 候选 | 支持证据 | 反证 | 置信度 |
|---|------|---------|------|--------|
| 1 | OCS 实例 OCS-BJ-02 连接池耗尽 | error_code_statistic: 5004 集中在 OCS-BJ-02 | None | 🟢 高 |
| 2 | Adapter 网关到第三方支付超时 | topology: CBS→Adapter 链路时延 +3.2s | adapter_kpi 正常 | 🟡 中 |
| 3 | CBS-BJ-03 实例 JVM GC 异常 | log: 14:15 起频繁 full GC | log 未直接捕获 | 🟡 中 |

## 4. 推荐根因
- **OCS-BJ-02 连接池耗尽**
- 主要证据：错误码 5004 87% 集中在该实例 + 连接池监控超阈值（来源：kpi_trend_query）

## 5. 影响范围
- 网元：CBS-BJ-03 / OCS-BJ-02 / 3 个局点
- 用户：北京、上海、广州 12 万用户（来自 cmdb_object_lookup）
- 业务：充值、订购、激活均受影响

## 6. 处置建议（只读诊断版，P0 不自动执行）
- 立即：检查 OCS-BJ-02 连接池配置
- 短期：扩容连接池到 200 / 重启 OCS-BJ-02
- 长期：增加连接池预警（>80% 触发）

## 7. 验证步骤
1. 登录 OCS-BJ-02 查连接池使用率（预期 >95%）
2. 查 last 24h GC 日志
3. 监控 CBS 充值成功率（预期 5 分钟内恢复 >99%）

## 8. 证据清单
| # | 类型 | 来源 | 数据 |
|---|------|------|------|
| E1 | 告警 | alert_query | CBS-CHARGE-FAIL-ALERT @ 14:25 |
| E2 | KPI | kpi_trend | success_rate: 99.2%→96.5% |
| E3 | 错误码 | error_code_statistic | code 5004: 87% |
| E4 | 拓扑 | topology_upstream | CBS→OCS-BJ-02 |
| E5 | 实例 | cmdb_object | OCS-BJ-02 owner=OCS-team |
```

### Step 8：用户反馈

**SRE 标记**：
- ☐ 是否准确（与实际根因对比）
- ☐ 是否采纳处置建议
- ☐ 证据是否充分
- ☐ 是否需要补充数据
- ☐ 是否形成新历史案例

**沉淀动作**：
- 「采纳 + 准确」→ 加入评测集（正例）
- 「采纳 + 不准确」→ 加入 Badcase 集（反例）
- 「不采纳 + 补充数据后采纳」→ 加入历史相似案例库

### 评测指标

| 层级 | 指标 | 目标值 |
|------|------|--------|
| 场景级 | 场景完成率 | >85% |
| 场景级 | 首次成功率 | >70% |
| 场景级 | 端到端耗时 | <10 min |
| 数据级 | 数据召回率 | >90% |
| 数据级 | 数据幻觉率 | <2% |
| 诊断级 | 根因准确率 | >75% |
| 诊断级 | Top-3 召回率 | >90% |
| 报告级 | 证据完整率 | >95% |
| 报告级 | SRE 采纳率 | >60% |

---

# 场景 2：CBS 交易成功率下降

## 2.1 用户旅程

### Step 1：问题感知
- CBS 整体交易成功率 KPI 异常下降
- 通常是平台级（非单接口），影响范围更大

### Step 2：进入分析
**典型问题**：
- 「CBS 整体交易成功率从 14:00 起持续下降到 95%，请定位原因」
- 「为什么交易成功率下降了？哪类业务最严重？」

### Step 3：上下文构建
**关键差异**：**业务维度聚类**（不只是单接口）
- 业务类型：打电话 / 上网 / 充值 / 订购 / 激活
- 接口维度：CBS 内部 + 外部链接（OCS/GMDB/Adapter）
- 用户维度：按局点 / 用户群 / 渠道

### Step 4：数据查询

| 工具 | 调用 |
|------|------|
| `biz_metric_overview` | `biz=cbs_all, window=...` |
| `biz_breakdown_by_type` | `dim=biz_type → 各业务成功率` |
| `interface_health_check` | `interfaces=cbs_ocs,cbs_gmdb,cbs_adapter` |
| `external_link_latency` | `links=adapter_to_thirdparty` |
| `recent_change_lookup` | `window=last_4h`（P0 优先看变更） |
| `kpi_correlation_analysis` | `metrics=[success_rate,p99,error_rate], window=...` |
| `similar_pattern_retrieve` | `pattern=cbs_global_decline`（**只生成候选**） |

### Step 5：诊断分析（Recipe）

```
R1. 业务聚类确认       成功率下降是全局 or 部分业务？
R2. 接口隔离           各接口成功率是否一致下降？定位异常接口
R3. 变更检查           14:00 前 4 小时窗口是否有发布 / 配置变更 / 灰度
R4. 关联指标下钻       与异常相关的指标（p99 / error_rate / qps）
R5. 根因候选生成       基于 R2/R3/R4 + 故障模式库 + 历史案例 → Top-3
R6. 证据矩阵填充       [支持证据 / 反证 / 缺失 / 不确定]
```

### Step 6：结果校验（同场景 1，6 步）

### Step 7：输出报告模板（同场景 1，但业务影响和接口维度更突出）

### Step 8：用户反馈（同场景 1）

### 评测指标

| 层级 | 指标 | 目标值 |
|------|------|--------|
| 场景级 | 场景完成率 | >80% |
| 场景级 | 端到端耗时 | <15 min（业务级比单接口慢） |
| 数据级 | 业务识别准确率 | >85% |
| 数据级 | 变更识别率 | >90% |
| 诊断级 | 根因准确率 | >65%（业务级比单接口难） |
| 诊断级 | 接口定位准确率 | >85% |
| 报告级 | 业务影响评估准确率 | >80% |

---

# 场景 3：告警风暴 / 关键告警分析

## 3.1 用户旅程

### Step 1：问题感知
- 短时间大量同类告警（>20 条/分钟）
- 关键告警（如 OCS 不可用）需要优先分析
- 告警风暴导致 SRE 工单积压

### Step 2：进入分析

**典型问题**：
- 「过去 5 分钟触发了 50 条 CBS 告警，需要快速聚类和定位主因」
- 「OCS-BJ-02 不可用告警，请评估影响和优先级」
- 「当前哪些告警是同一根因？哪些需要立即处理？」

### Step 3：上下文构建

**关键差异**：**告警聚合 + 优先级 + 根告警识别**
- 告警聚类（按 [对象类型, 错误码, 时间窗口]）
- 识别根本告警（root alert）vs 衍生告警（derived alert）
- 优先级排序（critical / major / minor）

### Step 4：数据查询

| 工具 | 调用 |
|------|------|
| `alert_burst_query` | `time_window=last_5min, min_count=20/min` |
| `alert_clustering` | `method=object+code+window` |
| `alert_dependency_graph` | `alerts=[id1,id2,...] → root/derived` |
| `priority_score` | `alert → critical/major/minor` |
| `root_cause_suspect` | `burst_root=ALERT-ID → 可疑根因对象` |
| `similar_burst_pattern` | `pattern=alert_storm`（**只参考**） |
| `oncall_duty_lookup` | `severity=critical → owner/oncall` |

### Step 5：诊断分析（Recipe）

```
R1. 风暴规模评估       告警总数 / 速率 / 类型分布 / 影响对象数
R2. 告警聚类           按 [对象, 错误码, 时间窗口] 3 维聚类
R3. 根本告警识别       通过依赖关系定位 root alert（去掉衍生）
R4. 影响排序           按 [criticality, business_impact, user_count]
R5. 根因候选生成       基于 root alert + 故障模式库 + 历史案例 → Top-3
R6. 证据矩阵填充       [支持证据 / 反证 / 缺失 / 不确定]
```

### Step 6：结果校验（同场景 1）

### Step 7：输出报告（突出优先级 + 影响排序 + 分级处置）

### Step 8：用户反馈（同场景 1，但「是否漏报关键告警」是重要反馈维度）

### 评测指标

| 层级 | 指标 | 目标值 |
|------|------|--------|
| 场景级 | 告警聚类准确率 | >85% |
| 场景级 | 关键告警识别率 | >95%（**不漏 critical**） |
| 数据级 | 告警去重率 | >90% |
| 数据级 | 衍生告警过滤率 | >85% |
| 诊断级 | 根本告警识别准确率 | >80% |
| 报告级 | 分级准确率 | >80% |
| 报告级 | 工单分配准确率 | >90% |

---

# 3 场景间共享的部分

## 数据资产复用表

| 数据资产 | 充值失败 | 交易成功率下降 | 告警风暴 |
|---------|:------:|:---------:|:-----:|
| 告警 | ✅ | ✅ | ✅（核心） |
| 指标 KPI | ✅ | ✅（核心） | ✅ |
| 错误码 | ✅（核心） | ✅ | ⚪ 间接 |
| 对象拓扑 | ✅ | ✅ | ✅ |
| CMDB | ✅ | ✅ | ✅ |
| 故障模式库 | ✅ | ✅ | ✅ |
| 相似案例 | ✅ | ✅ | ✅（**只参考**） |
| 业务流 | ✅ | ✅（核心） | ⚪ 间接 |
| 变更 | ⚪ 间接 | ✅（**核心**） | ✅ |

## 工具复用表

| 工具 | 复用 3 场景 |
|------|:----------:|
| `alert_query_by_time_window` | ✅ |
| `kpi_trend_query` | ✅ |
| `topology_upstream_downstream` | ✅ |
| `cmdb_object_lookup` | ✅ |
| `fault_pattern_library` | ✅ |
| `similar_incident_retrieve` | ✅（**只生成候选**）|
| `biz_metric_overview` | 场景 2 专属 |
| `alert_burst_query` | 场景 3 专属 |
| `alert_clustering` | 场景 3 专属 |
| `recent_change_lookup` | 场景 2 专属 |

## 报告模板复用

所有 3 场景都用统一 8 节报告模板（见场景 1.7），差异：
- 充值失败：突出错误码 + 实例
- 交易下降：突出业务维度 + 接口维度 + 变更记录
- 告警风暴：突出告警聚类 + 优先级排序

---

# P0 不做（红线）

| 不做项 | 原因 | 替代方案 |
|--------|------|---------|
| 完全自主 ReAct Loop | 准确率难控制 | Recipe-driven |
| NL2SQL | 安全风险 | OpenAPI / ES 模板化查询 |
| 自动执行处置 | 风险高 | 只输出处置建议，P0 不自动执行 |
| 多 Agent 协作 | 复杂度高 | 单 Agent + Recipe 编排 |
| 历史案例直接决定根因 | 偏见风险 | 历史案例只生成候选 |

---

# 关联文件

- `research/aiops-project-charter-2026-06-30.md`（立项 v0 / 主线方法论）
- `evolution/openrca-work-target.md` L3（Vanson 自有 AIOps 框架起点）
- `research/openrca-methodology-extract.md`（5 模式方法论）
- `research/openrca-2-9b-runbook.md`（9B 真实验证工程 runbook）
