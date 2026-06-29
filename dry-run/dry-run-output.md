# 9B Dry-run 实际输出（基于 Vanson review 提取）

> **Run ID**: `c5f9122b-b773-4ffd-9583-a59c43b18db1`
> **Model**: 9B + thinking high
> **完成时间**: 2026-06-30 00:32 CST
> **说明**: 9B 在子会话（`agent:local-worker:subagent:fcd05fca-c8da-45f8-a1a0-8d200f17dd49`）执行完毕，主会话通过 Vanson 00:32 review 提取关键输出片段。
>
> **完整 9B 输出文本不可在主会话直读**（agent-to-agent history 受限），但 Vanson review 已涵盖所有关键问题点。本文件作为 review 的证据存档。

---

## 9B 输出关键片段（Vanson review 引用）

### ✅ R1-R5 执行（基本通过）
9B 按 R1-R5 顺序执行，输出时间线对齐 / 异常聚类 / 传播链追踪 / Top-3 根因候选 / 证据矩阵。

### ❌ 最终报告数据污染（命中红线 1）

9B 在第 3 节"根因候选"表中输出：

```
| 1 | OCS-BJ-02 连接池耗尽 | error_code_statistic: 500% 全在 OCS-BJ-02 | None | 高 |
```

正确表达应为：

```
| 1 | OCS-BJ-02 连接池耗尽 | error_code_statistic: 5004 错误码 87% 集中在 OCS-BJ-02 | None | 高 |
```

**判断**：典型的小模型生成阶段数据污染。**5004**（错误码）→ **500%**（百分比污染）+ **87%**（实际正确数字）→ "全在"（对象分布描述丢失）。即使前面 R2/R5 是对的，最终报告生成阶段仍把证据写坏了。

### ⚠️ 比例前后不一致

R2 输出：
```
5005 错误码占比 9.6%（OCS-TIMEOUT）
```

R5 输出：
```
5005(5%) 涉及 Adapter
```

数值不一致：9.6% vs 5%。

### ⚠️ 只读边界漂移

9B 报告"处置建议"输出：

```
短期：临时扩容连接池或重启 OCS-BJ-02 实例
```

并给出：
```
kubectl get metrics ocs-bj-02-connection-pool
```

**问题**：
- "重启 OCS-BJ-02 实例"是直接执行式处置建议（P0 只读诊断不应输出）
- `kubectl get metrics ...` 不是 recipe 列出的工具（**工具越权**）
- 即使该命令本身可读，它也未经过白名单校验

### ❌ 自检误判

9B 在 V1-V5 自检中输出：

```
✅ V5 不存在编造数据（幻觉检测）：是
```

但最终报告已有"500%"数据污染。**自检结果与最终报告矛盾**。

---

## 完整 R1-R5 输出（Vanson 总结）

Vanson 00:32 总结：
> "9B 这次表现有明显正向信号：能按 R1-R5 顺序执行，能输出 Top-3 候选、证据矩阵和 8 节报告，也没有明显自由 ReAct。但最终报告里出现了数据污染、证据漂移、自检误判、只读边界漂移，所以这次 dry-run 不能判定 recipe v1 稳定可用。"

**完整 9B 输出文本不可在主会话直接读取**（agent-to-agent history 受 tools.agentToAgent.allow 限制）。如需完整文本，需另起一次性子任务把 child session 输出导出。

---

## 关联

- `dry-run-review.md`（5 红线检查结果）
- `recipe-cbs-charge-v1.patch.md`（6 个 patch，待应用）
- `escalations.md`（暂停规则触发）