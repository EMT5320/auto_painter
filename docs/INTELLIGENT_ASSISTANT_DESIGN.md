# STS2 智能助手升级设计

> 版本：v0.2  
> 日期：2026-03-20  
> 状态：方案设计 → 技术验证
>
> v0.2 变更摘要：
> - 确认 STS2 Mod 生态可用，采用 STS2AIAgent Mod (HTTP API) 作为主状态来源
> - 决策引擎从"本地专用模型"调整为"Codex 大模型 (MCP) + 规则兜底"
> - 移除内存读取方案，CV 仅保留用于地图识别
> - 训练路线调整为：先用 Codex 积累数据，后期蒸馏专用模型

---

## 1. 目标

将当前项目从“绘画工具 + 地图路线规划器”升级为“可感知游戏状态、可规划地图路线、可执行战斗决策、可持续学习优化”的智能游戏助手。

目标能力分为四层：

1. 感知层：稳定获取地图、战斗、运营相关的结构化状态
2. 决策层：在地图、事件、商店、休息点、战斗中选择高价值动作
3. 执行层：将决策转化为点击、滚动、绘制、按键等自动化操作
4. 学习层：通过数据采集、离线训练和评测持续提升策略质量

---

## 2. 当前项目现状

现有代码已经具备一个很好的雏形：

- [core/screen.py](/d:/Games/script/auto_painter/core/screen.py)：截图、滚动、拼接采集
- [core/mouse.py](/d:/Games/script/auto_painter/core/mouse.py)：鼠标控制与自动执行
- [features/route_planner/recognizer.py](/d:/Games/script/auto_painter/features/route_planner/recognizer.py)：地图节点识别
- [features/route_planner/graph.py](/d:/Games/script/auto_painter/features/route_planner/graph.py)：地图图结构与路径枚举
- [features/route_planner/optimizer.py](/d:/Games/script/auto_painter/features/route_planner/optimizer.py)：启发式路线评分
- [features/route_planner/drawer.py](/d:/Games/script/auto_painter/features/route_planner/drawer.py)：路线绘制执行

这说明当前项目已经有：

- 自动化输入能力
- 地图感知能力
- 规则图搜索能力
- GUI 承载能力

当前缺失的核心能力是：

- 战斗状态建模
- 运营状态建模
- 面向长期收益的策略模型
- 训练数据闭环
- 可量化的策略评测体系

---

## 3. 方案结论

### 3.1 主决策引擎：Codex 大模型 (MCP 接入)

**v0.2 重大调整：** 放弃 v0.1 中“本地小模型微调”的方案，改用 Codex 作为主决策引擎。

采用这一方案的原因：

1. STS2 已有 STS2AIAgent Mod 将游戏状态暴露为本地 HTTP API，并包装为 MCP Server
2. Codex 订阅配额充足，可以支撑高频次决策调用
3. 大模型在理解游戏规则、策略推理、事件文本解析方面远强于小模型
4. 无需前期训练投入，即刻可用，快速验证整个流程
5. Codex 决策过程自然产出高质量标注数据，为后期蒸馏专用模型积累数据

**架构路线：**

```text
第一阶段（当前）：Codex via MCP 作为主决策引擎
  └─ 规则系统兜底（合法性校验、安全边界）
  └─ 每次决策自动记录轨迹数据

第二阶段（数据充分后）：蒸馏专用小模型
  └─ 用 Codex 决策轨迹做行为克隆
  └─ 小模型本地推理，降低延迟和成本
  └─ Codex 不确定时做 fallback
```

### 3.2 为什么不直接训练/微调小模型

v0.1 中的分析仍然有效，但结论调整为“先不做，而不是不做”：

1. 战斗决策是高约束、强数值问题，小模型容易产生非法动作
2. 没有充分数据就训练，效果很差
3. Codex 先跑起来积累数据，种子数据质量更高
4. 后期蒸馏时有明确的数据分布和评估基准

小模型的定位调整为“第二阶段蒸馏目标”，而非当前重点。

### 3.3 规则系统仍然必须保留

即使 Codex 能力很强，规则兜底仍不可缺：

1. 规则系统负责合法性与安全边界（动作 mask、资源约束等）
2. Codex 返回非法动作时，规则层拦截并修正
3. 网络异常或 API 超时时，规则系统可以独立完成基础决策

---

## 4. 总体架构图

```text
┌────────────────────────────────────────────────────────────┐
│                        STS2 智能助手                        │
└────────────────────────────────────────────────────────────┘

      ┌────────────────── 感知层（状态获取）──────────────────┐
      │                                                        │
      │  STS2AIAgent Mod (C# Harmony)                         │
      │    │─ 本地 HTTP API ── 游戏状态 JSON                 │
      │    └─ MCP Server  ── AI 客户端直接调用              │
      │                                                        │
      │  CV 辅助（仅地图）：模板匹配 / 拼接 / 路线绘制          │
      └───────────────────────┬──────────────────────────────┘
                                │
                                v
      ┌────────────────── 状态层（结构化）──────────────────┐
      │                                                        │
      │  game_bridge/mod_bridge.py ── HTTP → Python 对象     │
      │  game_bridge/schemas.py    ── RunState / BattleState  │
      │                               MapState / ActionSet    │
      └───────────────────────┬──────────────────────────────┘
                                │
                                v
      ┌────────────────── 决策层（智能体）──────────────────┐
      │                                                        │
      │  Codex (via MCP) ── 主决策引擎                      │
      │    ├─ 战斗决策    ├─ 地图路线    ├─ 事件/商店     │
      │                                                        │
      │  Rule Guard ── 合法性校验 / 安全兜底 / 降级决策       │
      └───────────────────────┬──────────────────────────────┘
                                │
                                v
      ┌────────────────── 执行层（操控）──────────────────┐
      │                                                        │
      │  STS2AIAgent Mod HTTP API ── 游戏内操作指令           │
      │  core.mouse / core.screen  ── 地图绘制 / 截图          │
      └───────────────────────┬──────────────────────────────┘
                                │
                                v
      ┌────────────────── 数据层（积累）──────────────────┐
      │                                                        │
      │  Trajectory Recorder ── 每次决策自动记录             │
      │  Replay / Evaluation ── 离线评测与分析               │
      │  Distillation Data   ── 后期蒸馏小模型的数据源         │
      └──────────────────────────────────────────────────────┘
```

---

## 5. 面向当前仓库的模块设计

建议新增目录：

```text
auto_painter/
├─ core/
├─ features/
│  ├─ painter/
│  ├─ route_planner/
│  ├─ game_bridge/          # 新增：状态获取（Mod 为主，CV 为辅）
│  │  ├─ __init__.py
│  │  ├─ base.py            # 抽象接口，定义状态获取契约
│  │  ├─ mod_bridge.py      # ★ 主实现：通过 STS2AIAgent HTTP API 获取状态
│  │  ├─ screen_reader.py   # 辅助/降级：仅用于地图 CV 识别
│  │  └─ schemas.py         # RunState / BattleState / MapState / ActionSet
│  ├─ agent/                # 新增：决策协调与规则兜底
│  │  ├─ __init__.py
│  │  ├─ coordinator.py     # 场景调度：识别当前场景，分发给 Codex
│  │  └─ rule_guard.py      # 合法性校验 + 安全兜底 + 降级规则
│  └─ telemetry/            # 新增：数据记录
│     ├─ __init__.py
│     ├─ recorder.py        # 决策轨迹自动记录
│     └─ replay_loader.py   # 轨迹回放与分析
├─ training/                # ★ 第二阶段：蒸馏专用模型（数据充分后再启动）
│  ├─ __init__.py
│  ├─ dataset_builder.py   # 从轨迹数据构建训练集
│  ├─ train_bc.py          # 行为克隆（模仿 Codex 决策）
│  ├─ evaluate.py          # 离线评测
│  └─ export_model.py      # 导出 ONNX / TorchScript
├─ data/                    # 新增：Codex 决策轨迹数据
└─ docs/
```

**v0.2 模块调整说明：**

- **移除 `memory_reader.py`**：内存读取风险高、维护成本大、版本敏感，有 Mod 后无必要
- **精简 `agent/`**：战斗/地图/事件/商店的决策由 Codex 统一处理，不再拆分独立 agent 文件
- **精简 `training/`**：移除 `train_value.py`、`train_rl.py`，第一阶段只做行为克隆
- **保留 `telemetry/`**：轨迹数据是蒸馏的基础，从第一天就开始积累

设计原则：

- `core/` 保持通用工具层，不引入 AI 逻辑
- `features/game_bridge/` 只负责取状态，不负责决策
- `features/agent/` 负责场景调度和规则兜底，真正的决策由 Codex (MCP) 完成
- `training/` 与运行时解耦，仅在第二阶段启用

---

## 6. 关键设计决策

### 6.1 状态获取：STS2AIAgent Mod (HTTP API)

**v0.2 已确认可行。**

STS2 基于 Godot 4.5.1 (C#/.NET)，官方已内置 Mod 支持，游戏代码未混淆，可用 Harmony Patch 钩取任意游戏内方法。

社区已有的关键 Mod：

| Mod | 能力 | 与本项目的关系 |
|-----|------|---------------|
| **STS2AIAgent** (NexusMods #155) | 游戏状态 HTTP API + MCP Server | **核心依赖：感知层 + 执行层** |
| Qu'est-ce Spire (sts2-advisor) | 实时读取卡牌/遗物/牌组 | 参考实现：状态读取的 Harmony Patch 写法 |
| BaseLib-StS2 | 标准化 Mod 基座 | 若自研 Mod 可依赖 |

状态来源优先级（已确认）：

1. **STS2AIAgent Mod HTTP API**：战斗状态、运营状态、动作执行（主要）
2. **CV 截图 + 模板匹配**：地图视觉布局、路线绘制（辅助）
3. ~~内存读取~~：已移除，风险高且无必要

### 6.2 决策引擎：Codex via MCP

Codex 通过 MCP 协议连接 STS2AIAgent Mod，统一处理所有场景的决策：

- **战斗决策**：读取 BattleState，分析手牌/敌人/buff，输出打牌序列
- **地图路线**：结合 RunState + MapState，选择最优路径
- **事件/商店/休息点**：理解文本与数值，做出运营决策
- **奖励选择**：基于当前牌组、遗物、构筑方向评估

为什么 Codex 比拆分独立 agent 更合适：

- STS2 的决策场景本身就需要跨场景的全局理解（打牌时要考虑路线，选卡时要考虑整局构筑）
- Codex 天然具备这种跨场景推理能力
- 可以用 system prompt 载入游戏知识库，无需训练

### 6.3 规则兜底仍然必须保留

规则系统的职责在 Codex 架构下变为：

- **合法性 mask**：确保 Codex 输出的动作在当前状态下合法
- **安全边界**：血量过低时强制防御优先、资源约束等
- **降级决策**：Codex API 超时或异常时，规则系统独立完成基础决策
- **地图路线**：现有启发式评分作为 Codex 不可用时的 fallback

---

## 7. 数据与状态建模

### 7.1 状态对象

建议统一成三套 schema：

```python
MapState
BattleState
RunState
```

#### `RunState`

表示整局上下文：

- 角色
- 当前章节
- 楼层
- 当前血量 / 最大血量
- 金币
- 药水
- 遗物列表
- 卡组摘要
- 已升级卡牌
- 当前路线历史

#### `MapState`

表示地图决策上下文：

- 当前可见地图图结构
- 当前节点位置
- 各候选分支未来节点序列
- 章节危险度
- 精英分布
- 营火分布
- 商店分布
- 目标 Boss 信息
- 与当前 `RunState` 结合后的路径特征

#### `BattleState`

表示战斗内状态：

- 手牌
- 抽牌堆 / 弃牌堆
- 能量
- 玩家状态层数
- 各敌人血量
- 各敌人意图
- 敌我 buff/debuff
- 回合数
- 战斗阶段信息
- 合法动作列表

### 7.2 动作定义

动作必须是离散、可校验、可回放的。

地图动作：

- `choose_next_node(node_id)`

战斗动作：

- `play_card(card_id, target_id)`
- `use_potion(potion_id, target_id)`
- `end_turn()`

运营动作：

- `rest()`
- `upgrade(card_id)`
- `buy(item_id)`
- `skip_reward()`
- `take_reward(reward_id)`

### 7.3 奖励定义

不能只看“当前一步收益”，必须考虑长期收益。

建议定义多层奖励：

- 局部奖励：本场战斗掉血少、击杀快、资源使用合理
- 中期奖励：拿到关键遗物、卡组变强、路线风险控制
- 全局奖励：通关率、章节存活率、最终评价

示例：

```text
reward =
  + 通关奖励
  + 小节胜利奖励
  - 掉血惩罚
  - 非必要资源浪费惩罚
  + 高价值构筑成型奖励
```

---

## 8. 决策方案

### 8.1 第一阶段：Codex 主决策（当前）

Codex 通过 MCP 直接连接 STS2AIAgent Mod，作为唯一的智能决策引擎。

**输入：** Mod 暴露的游戏状态 JSON（通过 MCP tools 调用）

**输出：** 具体操作指令（通过 MCP tools 执行）

**优势：**

- 无需训练，即刻可用
- 天然理解游戏规则、卡牌文本、事件文本
- 可以通过 system prompt 注入策略知识
- 每次决策的推理过程自然产出可解释的轨迹数据

**局限：**

- 网络延迟（每次决策需要 API 调用）
- API 配额消耗（当前 Codex 订阅配额充足，不构成问题）
- 可能产生非法动作（通过 rule_guard 兜底）

### 8.2 第二阶段：蒸馏专用小模型（数据充分后）

待 Codex 积累足够决策轨迹后，蒸馏本地专用模型：

- **训练数据**：Codex 的决策轨迹（状态 → 动作 对）
- **训练方法**：行为克隆（BC），直接模仿 Codex 的决策分布
- **模型架构**：轻量级（MLP 或小 Transformer），支持本地 CPU/GPU 推理
- **部署方式**：导出 ONNX，本地推理，降低延迟和成本

**启动条件（建议）：**

- 至少 200+ 局完整对局数据
- Codex 在目标难度下的通关率稳定在 50%+
- 有明确的评估基准（Codex 决策质量作为 upper bound）

### 8.3 混合模式（过渡期）

蒸馏模型上线后，可采用混合策略：

- 常规决策：本地小模型快速推理
- 关键决策（精英战、Boss 战、商店、事件）：仍调用 Codex
- 不确定时：本地模型置信度低于阈值时 fallback 到 Codex

---

## 9. 数据积累与蒸馏路线

### 9.1 第一阶段：Codex 决策 + 自动轨迹采集（当前）

Codex 作为主决策引擎的同时，自动记录每次决策的完整轨迹。

采集内容：

- 完整游戏状态快照（来自 Mod HTTP API）
- Codex 的决策输出（动作 + 推理过程）
- 动作执行结果（状态变化、掉血、奖励等）
- 对局结果（通关/死亡、层数、评价）

采集优势：

- Codex 决策自然产出高质量标注，无需人工标注
- 每局游戏都是有效数据，无论胜负
- 推理过程可以作为“思维链”数据用于后期训练

### 9.2 第二阶段：行为克隆蒸馏（数据充分后）

目标：训练本地小模型模仿 Codex 的决策分布。

- 输入：结构化游戏状态
- 输出：动作分布
- 损失函数：交叉熵 + 合法动作 mask
- 评估指标：与 Codex 决策的一致率、独立跑局通关率

### 9.3 第三阶段：进阶优化（可选）

待行为克隆模型稳定后，可考虑：

- 价值网络：预测长期收益，用于地图和运营决策
- 搜索蒸馏：用 Codex 做 tree search 生成更高质量样本
- 离线 RL：基于积累数据做离线强化学习

此阶段不是当前重点，视第二阶段效果决定是否启动。

---

## 10. 在线决策流程

### 10.1 Codex MCP 决策主流程

```text
STS2AIAgent Mod 运行中，游戏状态实时暴露为 HTTP API
                    │
                    v
Codex (via MCP) 调用 get_game_state tool
  -> 获取当前场景类型（地图 / 战斗 / 事件 / 商店 / 休息点 / 奖励）
  -> 获取完整状态 JSON（RunState + 场景状态）
  -> Codex 分析状态、推理策略、输出决策
  -> rule_guard 校验合法性
  -> Codex 调用 perform_action tool 执行操作
  -> telemetry 自动记录轨迹
  -> 循环直到场景结束
```

### 10.2 降级流程（Codex 不可用时）

```text
Codex API 超时 / 异常
  -> rule_guard 接管决策
  -> 地图：使用现有启发式评分 (optimizer.py)
  -> 战斗：基础规则（优先防御、过回合）
  -> 其它：安全默认选择
```

---

## 11. 分阶段实施计划

### Phase A：Mod 桥接验证 + 状态管道打通

目标：确认 STS2AIAgent Mod 可用，Python 端能稳定获取结构化状态

交付：

- STS2AIAgent Mod 安装与验证
- `features/game_bridge/mod_bridge.py` —— HTTP API 对接
- `features/game_bridge/schemas.py` —— RunState / BattleState / MapState
- `features/telemetry/recorder.py` —— 轨迹记录器

验收标准：

- Python 端能实时打印战斗状态 JSON
- 能记录一局游戏的完整结构化日志

### Phase B：Codex MCP 接入 + 全场景决策

目标：Codex 通过 MCP 连接 STS2AIAgent，实现全场景自动决策

交付：

- STS2AIAgent MCP Server 配置与接入
- `features/agent/coordinator.py` —— 场景调度
- `features/agent/rule_guard.py` —— 合法性校验 + 降级规则
- Codex system prompt 设计（游戏知识、策略指南）

验收标准：

- Codex 能自动完成一局游戏（包括地图选择、战斗、事件、商店等）
- 轨迹数据自动记录并存储

### Phase C：策略优化 + 数据积累

目标：提升 Codex 决策质量，积累蒸馏数据

交付：

- system prompt 迭代优化（基于对局分析）
- 地图路线增强（注入 RunState 到现有 route_planner）
- 轨迹数据分析工具
- 目标：200+ 局高质量对局数据

验收标准：

- Codex 在目标难度下通关率稳定在 50%+
- 路线选择考虑血量、金币、遗物、卡组

### Phase D：蒸馏专用模型（数据充分后）

目标：用 Codex 决策轨迹蒸馏本地小模型

交付：

- `training/dataset_builder.py` —— 构建训练集
- `training/train_bc.py` —— 行为克隆训练
- `training/evaluate.py` —— 离线评测
- `training/export_model.py` —— 导出 ONNX

验收标准：

- 本地模型与 Codex 决策一致率 > 70%
- 本地模型独立跑局能通过 Act 1

---

## 12. 推荐的 MVP 路线

**v0.2 重大调整：** 得益于 STS2AIAgent Mod + Codex MCP 的组合，MVP 可以直接跳到“全场景自动决策”，而不需要按场景逐步建设。

推荐顺序：

1. 安装 STS2AIAgent Mod，验证 HTTP API 可用
2. 将 STS2AIAgent MCP Server 接入 Codex
3. Codex 直接通过 MCP 操控游戏，实现全流程自动玩
4. 迭代优化 system prompt 和规则兜底
5. 积累数据后考虑蒸馏本地模型

这条路线的优点：

- **极快的验证速度**：不需要训练任何模型，安装 Mod + 配置 MCP 即可开始
- **全场景覆盖**：Codex 天然支持所有决策场景，无需逐个开发
- **数据自然积累**：每次游玩都是高质量训练数据
- **完全复用现有代码**：地图 CV、鼠标控制、GUI 等不受影响

---

## 13. 风险与对策

### 风险 1：STS2 版本更新导致 Mod 失效

STS2 处于 EA 阶段，频繁更新可能导致 Harmony Patch 点变化。

对策：

- `game_bridge/base.py` 设计为抽象接口，`mod_bridge.py` 和 `screen_reader.py` 可切换
- 状态 Schema 字段用 `Optional`，缺失时降级而非崩溃
- 关注 STS2AIAgent / BaseLib 社区更新
- Mod 不可用时自动降级到 CV + 规则兜底

### 风险 2：Codex API 延迟影响游戏体验

每次决策需要等待 API 响应，可能会有明显延迟。

对策：

- STS2 是回合制游戏，对实时性要求不高，延迟可接受
- 第二阶段蒸馏本地模型后延迟将大幅降低
- 战斗中可批量规划整个回合的动作序列，减少调用次数

### 风险 3：Codex 产生非法动作

大模型可能输出当前状态下不合法的动作。

对策：

- `rule_guard` 强制校验每个动作的合法性
- MCP tool 描述中明确合法动作约束
- 非法动作时自动重试或降级到规则决策

### 风险 4：数据质量不足以支撑蒸馏

如果 Codex 决策质量不高，蒸馏出的模型也会很差。

对策：

- 先确保 Codex 通关率稳定后再启动蒸馏
- 轨迹数据按对局结果加权（通关局 > 失败局）
- 定期评估数据分布，过滤低质量样本

### 风险 5：Codex API 配额耗尽或服务中断

对策：

- 规则兜底系统可独立运行
- 战斗中按回合批量规划，减少 API 调用
- 过渡到本地模型后不再依赖 API

---

## 14. 与当前代码的衔接方式

以下模块建议保留并复用：

- [core/screen.py](/d:/Games/script/auto_painter/core/screen.py)
- [core/mouse.py](/d:/Games/script/auto_painter/core/mouse.py)
- [features/route_planner/recognizer.py](/d:/Games/script/auto_painter/features/route_planner/recognizer.py)
- [features/route_planner/graph.py](/d:/Games/script/auto_painter/features/route_planner/graph.py)
- [gui_app.py](/d:/Games/script/auto_painter/gui_app.py)

以下模块建议逐步替换或升级：

- [features/route_planner/optimizer.py](/d:/Games/script/auto_painter/features/route_planner/optimizer.py)
  原因：当前只支持静态节点权重，无法表达整局运营状态

新增的智能代理层不应该直接改坏原有路线规划器，而应该以“可切换模式”的方式并行接入：

- 经典模式：继续使用当前启发式路线评分
- 智能模式：Codex 结合 RunState 进行状态感知评分

---

## 15. 最终建议

最终推荐路线可以概括为一句话：

> 先做 Mod 状态桥接，用 Codex (MCP) 作为主决策引擎快速验证全流程，配合规则兜底，同时自动积累数据，待数据充分后蒸馏本地专用模型。

不推荐的路线：

- 直接微调/训练小模型（没有数据基础）
- 纯图像识别方案做战斗状态（复杂度太高）
- 内存读取方案（风险高且无必要）
- 在没有结构化状态前投入训练成本

推荐的路线：

1. 安装 STS2AIAgent Mod，打通状态管道
2. 将 MCP Server 接入 Codex，实现全场景自动决策
3. 迭代优化 system prompt + 规则兜底
4. 自动积累决策轨迹数据
5. 数据充分后蒸馏本地小模型

---

## 16. 下一步建议

文档更新后，立即执行：

1. **下载并安装 STS2AIAgent Mod**，启动游戏验证 HTTP API 可用性
2. **尝试将 STS2AIAgent MCP Server 接入 Codex**，验证 MCP 调用链路
3. **编写 `game_bridge/schemas.py`**，定义 RunState / BattleState / MapState
4. **编写 `game_bridge/mod_bridge.py`**，对接 HTTP API

前两步是技术验证，确认可行后再推进代码实现。

