# Readiness for Real OpenAPI — P0 阶段 1 真实接入 Checklist

> **生成时间**：2026-06-30 23:00 CST
> **触发**：Vanson 22:33 拍 D → A-mini（V8 优先于真实 OpenAPI 接入）
> **目的**：明确 P0 阶段 1 真实 Evidence Pack 接入需要哪些接口 / 权限 / 样例 / 字段映射 / 数据质量要求
> **状态**：**未启动 P0 阶段 1**；本 checklist 用于启动前对照检查
> **关联**：`real-evidence-adapter-design.md` + `evidence_adapter_interface.py`

---

## 🎯 启动门槛（5 项全绿才可启动 P0）

| # | 门槛 | 状态 | 阻塞点 |
|:-:|------|:----:|--------|
| 1 | 真实 API 接口清单 + 文档地址 | ❌ | 需用户提供 4 类 API endpoint + 文档 |
| 2 | API 访问权限（OAuth / API Key）| ❌ | 需申请 read-only 权限 |
| 3 | 数据样例（≥10 个真实告警的完整 Evidence Pack）| ❌ | 需用户提供脱敏样本 |
| 4 | 字段映射文档（API 字段 → Evidence 字段）| ⏸ A-mini 设计稿 | 待用户提供 API 字段名 |
| 5 | 数据质量验证（覆盖率 / 字段缺失率 / 时间一致性）| ❌ | 需跑通真实样例 |

**5/5 阻塞**——启动 P0 前必须全部解除。

---

## 📋 需要的真实 API 接口清单

### 接口 1：告警系统 API（→ Evidence A）

| 项 | 详情 |
|----|------|
| **用途** | 拉取时间窗口内的告警列表 |
| **Endpoint** | ❓ 需用户提供（候选：`GET /api/v1/alarms`）|
| **认证** | ❓ 需用户提供（候选：OAuth2 / API Key）|
| **时间窗口参数** | `?start_time=&end_time=` 或 `?time_window=30m` |
| **返回示例字段** | ❓ 需用户提供 |
| **必含字段** | `alarm_id` / `trigger_time` / `target_object_id` / `alarm_type` / `severity` |
| **可选字段** | `metadata` / `rule_id` / `recovery_time` |
| **时间格式** | ❓ ISO 8601 / Unix timestamp？ |
| **时区** | ❓ UTC / CST？ |

---

### 接口 2：监控系统 API（→ Evidence B）

| 项 | 详情 |
|----|------|
| **用途** | 拉取指定对象的关键 KPI 快照 |
| **Endpoint** | ❓ 需用户提供 |
| **认证** | ❓ |
| **参数** | `?object_ids=&metrics=&time_window=` |
| **必含字段** | `target_object_id` / `metric_name` / `value` / `unit` / `sample_time` |
| **可选字段** | `baseline_value` / `threshold_high/low` |
| **metric_name 列表** | ❓ 需用户提供支持的指标名清单 |
| **value 范围** | ❓ 0-100 / 0-1？百分比是否已归一化？ |

---

### 接口 3：CMDB API（→ Evidence C）

| 项 | 详情 |
|----|------|
| **用途** | 拉取对象相关的拓扑子图 |
| **Endpoint** | ❓ 需用户提供 |
| **认证** | ❓ |
| **参数** | `?root_object_ids=&depth=2` |
| **必含字段** | `component_id` / `component_role` / `edges[].from/to` |
| **可选字段** | `call_direction` / `avg_latency_ms` |
| **拓扑深度** | ❓ 最多支持几层？默认 2-3 层 |
| **节点数上限** | ❓ 单次最多返回多少节点？避免返回全网拓扑 |

---

### 接口 4：日志系统 API（→ Evidence D）

| 项 | 详情 |
|----|------|
| **用途** | 拉取时间窗口内的错误码统计 |
| **Endpoint** | ❓ 需用户提供 |
| **认证** | ❓ |
| **参数** | `?time_window=&object_ids=&min_count=10` |
| **必含字段** | `error_code` / `count` / `percentage` / `primary_target_id` |
| **可选字段** | `first_observed_time` / `last_observed_time` |
| **error_code 格式** | ❓ 是否统一 4 位数字？ |
| **percentage 单位** | ❓ 0-1 / 0-100？ |
| **first_observed_time 是否可用** | ❓ **V8 时间线闭合性的关键字段**，必须返回 |

---

## 🔐 权限与认证

### 最小权限清单

| 系统 | 权限范围 | 理由 |
|------|---------|------|
| 告警系统 | `read:alarms` | 只读，不允许修改告警状态 |
| 监控系统 | `read:metrics` | 只读历史快照，不允许写入 |
| CMDB | `read:topology` | 只读，不允许修改组件关系 |
| 日志系统 | `read:error_stats` | 只读聚合数据，不允许读原始日志 |

### 认证方式

- ❓ **OAuth2 client_credentials**：token 有效期？刷新策略？
- ❓ **API Key**：放在 header / query param？
- ❓ **mTLS**：是否需要双向证书？

### 限流策略

| 系统 | QPS 限制 | 超限处理 |
|------|---------|----------|
| 告警系统 | ❓ | 需 adapter 加 retry + 指数退避 |
| 监控系统 | ❓ | 同上 |
| CMDB | ❓ | CMDB 通常低频，可缓存 |
| 日志系统 | ❓ | 聚合 API 通常限流严，需提前申请 |

---

## 📦 数据样例要求

**最少 10 个完整 Evidence Pack**（脱敏后）：

| # | 场景 | 必含证据 |
|:-:|------|----------|
| 1 | OCS 连接池耗尽 | 4 段完整 + 所有字段 |
| 2 | Adapter 第三方支付超时 | 同上 |
| 3 | 证据不足（INSUFFICIENT）| Evidence D 错误码少 |
| 4 | 错误码集中但无告警 | C2 沉默对象 |
| 5 | 告警先发生但 KPI 未异常 | 缺 KPI 数据 |
| 6 | KPI 异常但错误码分散 | 错误码散落 |
| 7 | 多对象同时异常 | 拓扑多点故障 |
| 8 | 历史案例相似但证据不支持 | 历史数据不能直接定根因 |
| 9 | **时间线冲突**（V8 核心样例）| C2 沉默对象 / C1 倒挂 |
| 10 | **关键字段缺失**（V7 触发）| Evidence D 无错误码 |

**脱敏要求**：

- ❌ 真实告警 ID → 用 `ALM-REAL-XXX` 替换
- ❌ 真实 object_id → 用通用占位符（如 `OCS-REAL-NN`）
- ❌ 真实错误码 → 保留数字（用于 verifier V4 校验）
- ❌ 真实时间戳 → 保留相对时间，日期脱敏

---

## 🗺️ 字段映射文档

> **当前状态**：A-mini 设计稿已定义 mock YAML → Evidence 字段映射。
> **缺**：真实 API 字段 → Evidence 字段映射。

### 待用户提供

| Evidence 字段 | 真实 API 字段 | 数据类型 | 备注 |
|---------------|---------------|----------|------|
| alarm_id | ❓ | str | API 返回什么名字？ |
| trigger_time | ❓ | ISO 8601 / Unix ts | 时区？ |
| target_object_id | ❓ | str | 大小写规则？ |
| alarm_type | ❓ | str | 枚举值？ |
| severity | ❓ | enum | 怎么映射到 P1-P4？ |
| metric_name | ❓ | str | 支持哪些指标？ |
| value | ❓ | float | 单位归一化？ |
| sample_time | ❓ | ISO 8601 | 同 trigger_time |
| error_code | ❓ | str | 是否统一 4 位？ |
| first_observed_time | ❓ | ISO 8601 | **必须返回**（V8 关键） |

---

## ✅ 数据质量验证（启动前必跑）

### 维度 1：字段覆盖率

| Evidence 段 | 必填字段 | 期望覆盖率 | 实际覆盖率 |
|-------------|---------|----------|----------|
| A | alarm_id / time / object_id / type / level | ≥ 99% | ❓ 待测 |
| B | object_id / metric / value / unit / time | ≥ 95% | ❓ |
| C | graph / objects[].id | 100% | ❓ |
| D | error_code / count / pct / main_object_id | ≥ 95% | ❓ |
| D (关键) | **first_seen_time** | **≥ 80%**（缺失会被 V7 拦截）| ❓ **必测** |

### 维度 2：时间一致性

- 告警 `trigger_time` 与 KPI `sample_time` 时区一致 ✅
- 错误码 `first_observed_time` ≥ 告警最早时间 - 5min ✅
- 拓扑对象 ID 与告警对象 ID 大小写一致 ✅

### 维度 3：对象 ID 命名规范

- 必须符合 OBJECT_ID_RE 正则：`\b(?:OCS|CBS|GW|ADB|ADAPTER|APP|RDS|REDIS|NGINX|KAFKA|ES)-[A-Z]{2,5}-\d{2}\b`
- 不符合的对象 → adapter 报 SKIPPED，不参与推理

### 维度 4：错误码格式

- 必须 4 位数字字符串（verifier V4 强制）
- 字符串类型（不是 int）

---

## 🧪 启动前必跑的 5 项验证

| # | 验证 | 方法 | 通过标准 |
|:-:|------|------|---------|
| 1 | Mock ↔ Real schema 一致性 | 用同一 case YAML 和真实数据分别喂 adapter，对比 evidence.md 输出 | 字段名 / 列顺序完全一致 |
| 2 | 真实数据回放 | 把 10 个真实样本喂给 run_case.py | 10/10 case 端到端 PASS 或 known-fail |
| 3 | Verifier V1-V9 在真实数据上 PASS | 用真实数据跑 test_deterministic.py | 34/34 PASS |
| 4 | 9B 在真实数据上不输出 high when 不应该 | 比对 9B 输出 vs 期望 confidence | 错误率 < 10% |
| 5 | 离线回放稳定性 | 同一份真实数据连跑 3 次 | 输出完全一致 |

---

## 🚦 启动 P0 阶段 1 的 SOP

### Step 1：用户提供真实 API 信息（1-2 天）

- [ ] 4 个 API endpoint + 认证方式
- [ ] 字段映射表（API 字段 → Evidence 字段）
- [ ] 10 个脱敏样例 Evidence Pack

### Step 2：实现 RealOpenAPIAdapter（2-3 天）

- [ ] 4 个 fetch_* 方法
- [ ] 错误处理（429 / 5xx / timeout）
- [ ] 时区归一化（UTC → CST）
- [ ] 字段命名归一化（大写 + OBJECT_ID_RE 校验）

### Step 3：数据质量验证（1-2 天）

- [ ] 字段覆盖率（5 段 × N 字段）
- [ ] 时间一致性检查
- [ ] 对象 ID 命名规范检查
- [ ] 错误码格式检查

### Step 4：双轨运行（3-5 天）

- [ ] Mock + Real 并行跑 10 case
- [ ] 对比 evidence.md 输出差异
- [ ] 对比 diagnosis.json 差异
- [ ] 灰度切换比例：10% → 50% → 100%

### Step 5：v2.3.0 tag

- [ ] 10/10 case PASS（real adapter）
- [ ] 34/34 test_deterministic PASS
- [ ] CI 真实数据回归（self-hosted runner）

---

## 📊 工程量估算

| 阶段 | 工作量 | 依赖 |
|------|--------|------|
| 用户提供 API 信息 | 1-2 天 | 用户 |
| RealOpenAPIAdapter 实现 | 2-3 天 | API 信息 |
| 数据质量验证 | 1-2 天 | RealOpenAPIAdapter |
| 双轨运行 | 3-5 天 | 数据质量达标 |
| v2.3.0 tag | 1 天 | 双轨稳定 |
| **总计** | **8-13 天（1.5-2.5 周）** | — |

---

## 🚧 启动前 3 个阻塞点

1. **真实 API 文档 + 权限**（用户责任）—— 无文档无法实现 adapter
2. **数据样例脱敏**（用户责任）—— 无样例无法做字段映射
3. **生产环境访问**（用户责任）—— 无访问权无法跑双轨

**OpenClaw / OpenCode 侧可独立完成**：adapter 代码实现 / 数据质量校验 / 双轨对比逻辑。

---

## ⚠️ 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 真实 API 限流严 | 拉取超时 | adapter retry + 指数退避 |
| first_seen_time API 不返回 | V7 触发大量 FAIL | 与日志系统 owner 协商加字段 |
| 时区不一致 | 时间线冲突误判 | adapter 强制 UTC→CST |
| 对象 ID 命名不规范 | OBJECT_ID_RE 不匹配 | adapter 加命名归一化层 |
| 错误码格式不统一 | V4 报错 | adapter 加格式校验 + 修复 |

---

## 关联

- `real-evidence-adapter-design.md` — 数据模型 + 接口契约 + 字段映射
- `evidence_adapter_interface.py` — 接口代码（已实现 Mock，Real 占位）
- `runtime/readiness-for-p0.md` — Mock 侧 6 维门槛（5/6 通过，1/6 阻塞）
- `runtime/verifier/verifier.py` — 9 类规则不变
- Vanson 22:33 拍 D → A-mini（D-mini 已完成，A-mini 设计稿完成）