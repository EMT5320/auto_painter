# STS2 智能助手升级设计

> 版本：v0.1  
> 日期：2026-03-18  
> 状态：方案设计

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

### 3.1 不建议以“小参数量 LLM 微调”作为主决策引擎

原因：

1. 战斗决策是高约束、强数值、强合法性校验的问题，不是自然语言生成问题
2. 小 LLM 容易产生非法动作、漏算伤害、忽略状态层数与资源约束
3. 地图和战斗都更适合结构化输入，而不是长文本 Prompt
4. 本地推理虽然可行，但稳定性和样本效率都不理想

小 LLM 更适合做：

- 文本事件解释
- 决策理由生成
- 调试日志总结
- 玩家交互问答

### 3.2 推荐主路线：专用结构化模型 + 搜索 + 规则兜底

最合理的核心架构：

1. 规则系统负责合法性与安全边界
2. 专用策略模型负责快速给出候选动作
3. 价值模型负责评估中长期收益
4. 搜索器负责在关键节点做短程展开和纠错

这是一个混合系统，而不是单一模型系统。

---

## 4. 总体架构图

```text
┌────────────────────────────────────────────────────────────┐
│                        STS2 智能助手                        │
└────────────────────────────────────────────────────────────┘

          ┌──────────────────── 感知层 ────────────────────┐
          │                                                │
          │  Screen Capture / OCR / Template / Mod Bridge  │
          │                                                │
          │  地图状态   战斗状态   运营状态   运行日志       │
          └──────────────────────┬─────────────────────────┘
                                 │
                                 v
          ┌──────────────────── 状态层 ────────────────────┐
          │                                                │
          │  MapState   BattleState   RunState   ActionSet │
          │                                                │
          │  统一结构化状态、合法动作集合、特征编码         │
          └──────────────────────┬─────────────────────────┘
                                 │
                                 v
      ┌──────────────────────── 决策层 ─────────────────────────┐
      │                                                        │
      │  Route Agent   Battle Agent   Event Agent   Shop Agent │
      │                                                        │
      │  Policy Net + Value Net + Search + Rule Guard          │
      └──────────────────────┬─────────────────────────────────┘
                             │
                             v
          ┌──────────────────── 执行层 ────────────────────┐
          │                                                │
          │  Mouse / Scroll / Click / Draw / Key Input     │
          │                                                │
          │  使用现有 core.mouse / core.screen 复用执行能力 │
          └──────────────────────┬─────────────────────────┘
                                 │
                                 v
          ┌──────────────────── 学习层 ────────────────────┐
          │                                                │
          │  Data Collector / Replay / Offline Training    │
          │  Evaluation / Model Registry / A-B Testing     │
          │                                                │
          └────────────────────────────────────────────────┘
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
│  ├─ game_bridge/          # 新增：状态获取
│  │  ├─ __init__.py
│  │  ├─ base.py
│  │  ├─ screen_reader.py
│  │  ├─ mod_bridge.py
│  │  ├─ memory_reader.py
│  │  └─ schemas.py
│  ├─ agent/                # 新增：智能决策
│  │  ├─ __init__.py
│  │  ├─ coordinator.py
│  │  ├─ route_agent.py
│  │  ├─ battle_agent.py
│  │  ├─ event_agent.py
│  │  ├─ shop_agent.py
│  │  ├─ rest_agent.py
│  │  ├─ policy.py
│  │  ├─ value.py
│  │  ├─ search.py
│  │  └─ rule_guard.py
│  └─ telemetry/            # 新增：数据记录
│     ├─ __init__.py
│     ├─ recorder.py
│     ├─ serializer.py
│     └─ replay_loader.py
├─ training/                # 新增：训练与评测
│  ├─ __init__.py
│  ├─ dataset_builder.py
│  ├─ train_bc.py
│  ├─ train_value.py
│  ├─ train_rl.py
│  ├─ evaluate.py
│  └─ export_model.py
├─ models/                  # 新增：模型文件
├─ data/                    # 新增：轨迹数据
└─ INTELLIGENT_ASSISTANT_DESIGN.md
```

设计原则：

- `core/` 保持通用工具层，不引入模型逻辑
- `features/game_bridge/` 只负责取状态，不负责决策
- `features/agent/` 只负责决策，不直接操作底层截图细节
- `training/` 与运行时逻辑解耦，便于实验迭代

---

## 6. 关键设计决策

### 6.1 优先建设 `game_bridge`

如果没有可靠的结构化状态，后续模型训练价值很低。

状态来源优先级建议：

1. 游戏 Mod / 调试接口 / 导出日志
2. 内存读取
3. 截图识别 + OCR

推荐优先级的原因：

- 地图识别还比较适合 CV
- 战斗状态如果全靠图像识别，复杂度和脆弱性都会非常高
- 一旦能拿到结构化状态，训练、回放、评测都会容易很多

### 6.2 地图和战斗必须拆开建模

不要一开始就追求“一个大模型统治所有场景”。

建议拆成：

- 地图代理：决定下一层走哪条边
- 战斗代理：每回合、每步选择具体动作
- 运营代理：休息点、商店、事件、奖励选择

这样做的好处：

- 每个任务动作空间更清晰
- 数据格式更稳定
- 更便于逐步上线

### 6.3 搜索必须保留

即使引入模型，也不应彻底放弃搜索。

推荐：

- 地图决策：枚举可行路径 + 价值评估
- 战斗决策：Beam Search 或 MCTS 做短视展开
- 关键动作使用规则兜底，避免模型发散

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

## 8. 模型方案

### 8.1 地图决策模型

目标：

- 输入当前 `RunState + MapState`
- 输出每个可选下一节点的价值分数

推荐模型：

- 初期：特征工程 + MLP
- 中期：图结构编码器 + MLP
- 后期：轻量 GNN 或 Transformer Encoder

为什么地图模型可以先轻量：

- 动作空间小
- 可行路径可枚举
- 有大量规则特征可直接利用

### 8.2 战斗决策模型

目标：

- 输入当前 `BattleState`
- 输出合法动作分布 `policy`
- 同时输出状态价值 `value`

推荐模型：

- 实体编码器 + Transformer
- 或者分桶特征 + MLP 作为最初版本

输出：

- `policy_logits[action_id]`
- `state_value`

要求：

- 必须支持合法动作 mask
- 必须支持目标选择
- 必须能表达多敌人和状态层数

### 8.3 是否需要 LLM

建议定位为辅助模块，而非主决策模块。

可以保留一个可选本地小 LLM，用于：

- 解析事件文本
- 生成“为什么这样决策”的解释
- 汇总对局日志

但不要将其放入高频战斗回合主环路。

---

## 9. 训练路线

### 9.1 第一阶段：规则与专家数据采集

先不直接训练最强模型，先把数据采起来。

数据来源建议：

1. 当前启发式路线规划器产生地图决策
2. 人工游玩记录
3. 可编写的简单规则战斗器
4. 后续搜索器生成的高质量样本

采集内容：

- 完整状态
- 合法动作集合
- 最终选择动作
- 后续结果
- 战斗结果 / 掉血 / 奖励

### 9.2 第二阶段：行为克隆

目标：

- 先学会模仿已有高质量决策
- 让模型稳定输出合法动作

优点：

- 开发快
- 容易看到效果
- 可作为 RL 或搜索蒸馏的初始化

### 9.3 第三阶段：价值学习

训练价值网络预测：

- 当前地图选择的长期收益
- 当前战斗状态的胜率 / 掉血期望 / 资源代价

### 9.4 第四阶段：搜索蒸馏或强化学习

条件成熟后再做：

- 离线强化学习
- 搜索生成伪标签
- 自博弈或模拟器强化训练

不建议一开始就直接上 RL。

原因：

- 环境构建复杂
- 样本消耗大
- 调试难度高

---

## 10. 在线推理流程

### 10.1 地图决策流程

```text
识别地图
  -> 构建图结构
  -> 枚举可行路径
  -> 提取路径特征
  -> 地图价值模型评分
  -> 规则过滤
  -> 选择最优下一步
  -> 执行点击 / 绘制
```

### 10.2 战斗决策流程

```text
读取 BattleState
  -> 生成合法动作集合
  -> 策略网络给出 Top-K 候选
  -> 搜索器展开未来若干步
  -> 价值网络评估叶子状态
  -> 规则层做安全校验
  -> 执行动作
  -> 记录轨迹
```

---

## 11. 分阶段实施计划

### Phase A：状态管道打通

目标：

- 从“能看图”升级到“能拿结构化状态”

交付：

- `features/game_bridge/schemas.py`
- `RunState / MapState / BattleState` 定义
- 至少一种稳定状态来源
- 轨迹记录器

验收标准：

- 能把一局游戏关键节点完整记录成结构化日志

### Phase B：智能地图代理

目标：

- 替换当前 [features/route_planner/optimizer.py](/d:/Games/script/auto_painter/features/route_planner/optimizer.py) 的纯静态权重评分

交付：

- `route_agent.py`
- 地图特征提取器
- 初版地图价值模型
- 与现有 `recognizer + graph` 集成

验收标准：

- 路线选择开始考虑血量、金币、遗物、卡组形态，而不是只看节点偏好

### Phase C：战斗代理 MVP

目标：

- 在受限场景下实现自动战斗

范围建议：

- 先只支持一个角色
- 先只支持基础卡池
- 先只支持普通战斗

交付：

- `battle_agent.py`
- 合法动作生成器
- 行为克隆策略模型
- 简单搜索器

验收标准：

- 在限定场景中稳定完成基础战斗

### Phase D：运营代理

目标：

- 处理事件、商店、营火、奖励选择

交付：

- `event_agent.py`
- `shop_agent.py`
- `rest_agent.py`

### Phase E：学习闭环

目标：

- 持续采集、训练、评测、替换模型

交付：

- 数据清洗流程
- 离线评测脚本
- 模型版本管理
- A/B 测试接口

---

## 12. 推荐的 MVP 路线

为了尽快做出“真的会变聪明”的版本，推荐按下面顺序推进：

1. 保留当前地图识别与自动执行能力
2. 新增结构化 `RunState`
3. 先把路线评分升级为“状态感知的地图价值模型”
4. 只做一个很小范围的战斗代理 MVP
5. 最后再考虑通用化和全局最优

这条路线的优点是：

- 可以快速看到智能增量
- 不需要一次性重构整个项目
- 能复用现有代码最多

---

## 13. 风险与对策

### 风险 1：战斗状态无法稳定获取

对策：

- 优先寻找 Mod / 调试接口
- 只有在无法获得结构化状态时，才退回 OCR + CV

### 风险 2：数据量不足

对策：

- 先做人类演示数据
- 再用规则与搜索生成伪专家数据

### 风险 3：模型会做出非法动作

对策：

- 动作空间离散化
- 合法动作 mask
- `rule_guard` 强校验

### 风险 4：一步局部最优导致整局崩盘

对策：

- 加入价值模型
- 在地图与运营决策中引入长期收益目标

### 风险 5：推理太慢

对策：

- 地图模型轻量化
- 战斗只对 Top-K 动作做搜索
- 保持本地模型小型化

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
- 智能模式：使用 `route_agent`

---

## 15. 最终建议

最终推荐路线可以概括为一句话：

> 先做状态桥接，再做结构化专用模型，配合搜索和规则兜底，逐步替代当前静态启发式逻辑。

不推荐的路线：

- 直接把小 LLM 微调成主决策器
- 一上来就做全场景统一大模型
- 在没有结构化状态前就投入大量训练成本

推荐的路线：

1. 打通结构化状态采集
2. 地图决策模型先行
3. 战斗代理做小范围 MVP
4. 建立训练和评测闭环
5. 最后再考虑更复杂的统一智能体

---

## 16. 下一步建议

文档落地后，建议紧接着做两件事：

1. 编写 `game_bridge` 接口设计文档
2. 编写训练数据 schema 文档

这两份文档会直接决定后续实现是否顺利。

