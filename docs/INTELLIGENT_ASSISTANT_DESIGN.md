# STS2 智能助手设计文档

> 版本：v0.3
> 日期：2026-03-23
> 状态：技术验证已通过 → 决策引擎开发中
>
> 变更历史：
> - v0.1 初始设计
> - v0.2 确认 Mod 可用，引入 Codex MCP 方案
> - v0.3 MCP 连通性已验证；精简文档；标记 Agent SDK 迁移为待办

---

## 1. 目标

将项目从"地图路线规划器"升级为**全场景自动决策的 Agent 系统**。

能力分层：**感知** → **决策** → **执行** → **学习**

---

## 2. 已验证能力与当前缺口

### 已有

| 能力 | 来源 |
|------|------|
| 自动化输入 | `core/mouse.py`, `core/screen.py` |
| 地图视觉识别 | `features/route_planner/recognizer.py` |
| 地图图搜索 + 启发式评分 | `graph.py`, `optimizer.py` |
| 路线绘制执行 | `drawer.py` |
| GUI 承载 | `gui_app.py` |

### 已验证（v0.3 新增）

| 能力 | 状态 |
|------|------|
| STS2AIAgent Mod HTTP API (端口 8080) | ✅ 已确认可用 |
| MCP Server stdio 启动 (`python -m sts2_mcp`) | ✅ 协议握手成功 |
| Codex ↔ MCP 连通 (`.codex/config.toml`) | ✅ 服务器可见 |

### 缺口

- 战斗/运营状态建模（依赖 Mod 实际返回数据对齐 schemas）
- Codex system prompt + 策略知识注入
- 规则兜底实现
- 轨迹数据采集与评估闭环

---

## 3. 架构

```text
┌─────────────── STS2 智能助手 Agent ───────────────┐
│                                                      │
│  感知层   STS2AIAgent Mod ─ HTTP API ─ MCP Server  │
│           CV 辅助（仅地图）                          │
│                    ↓                                 │
│  状态层   mod_bridge.py → schemas.py                │
│                    ↓                                 │
│  决策层   Codex (MCP) ← system prompt + 知识库     │
│           Rule Guard ← 合法性校验 + 降级决策        │
│                    ↓                                 │
│  执行层   Mod HTTP API (act) / core.mouse           │
│                    ↓                                 │
│  数据层   Trajectory Recorder → 蒸馏数据源          │
└──────────────────────────────────────────────────────┘
```

---

## 4. 决策引擎路线图

### 当前：Codex via MCP（验证 + 数据积累）

- Codex 通过 MCP 调用 `get_game_state` → `get_available_actions` → `act`
- 统一处理战斗、地图、事件、商店、休息点、奖励选择
- Rule Guard 校验合法性，异常时降级到规则决策
- 每次决策自动记录轨迹（状态 + 动作 + 推理 + 结果）

> **当前限制**：Codex 订阅仅支持 CLI/VSCode 扩展交互，无法作为 API 程序化调用。
> 当前阶段用 Codex CLI 完成 prompt 开发和决策验证。

### 待办：迁移至 Agent SDK（程序化接入）

> 🔖 **TODO — 优先级：中**

将决策引擎从 Codex CLI 迁移到 **openai-agents SDK**（或同类方案），实现：

- Python 原生调用 LLM，不再依赖 VSCode 扩展
- 完整的 agent loop 运行在本系统内
- 原生 MCP Client 支持，直接挂载 sts2-ai-agent
- 自定义记忆、多 agent 协作等高级能力

**可移植性**：当前在 Codex 上开发的 prompt、SKILL.md、MCP 工具调用流程**完全复用**，
迁移仅需替换接入层（几行代码），不影响决策逻辑和工作流。

**候选方案**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| OpenAI API + openai-agents SDK | 与 Codex 同模型，质量最高 | 按 token 计费 |
| Claude API (Anthropic) | 长上下文，推理强 | 按 token 计费 |
| Gemini API (Google) | 有免费额度 | 质量略低 |
| Ollama 本地模型 | 完全免费离线 | 需强 GPU，决策质量差距大 |

### 远期：蒸馏专用小模型

启动条件：200+ 局高质量对局、Codex 通关率 ≥ 50%

- 行为克隆（BC）：模仿 Codex 决策分布
- 导出 ONNX，本地推理
- 混合模式：常规走小模型，关键决策 fallback 到大模型

---

## 5. 模块结构

```text
auto_painter/
├─ core/                     # 通用工具（不引入 AI 逻辑）
├─ features/
│  ├─ route_planner/         # 已有：地图识别 + 评分 + 绘制
│  ├─ game_bridge/           # 状态获取
│  │  ├─ base.py             # 抽象接口
│  │  ├─ mod_bridge.py       # ★ Mod HTTP API 客户端
│  │  ├─ screen_reader.py    # CV 降级（仅地图）
│  │  └─ schemas.py          # 状态/动作数据模型
│  ├─ agent/                 # 决策协调
│  │  ├─ coordinator.py      # 场景调度 → Codex/Rule Guard
│  │  └─ rule_guard.py       # 合法性校验 + 降级规则
│  └─ telemetry/             # 数据记录
│     ├─ recorder.py         # 轨迹自动记录
│     └─ replay_loader.py    # 回放与分析
├─ training/                 # 远期：蒸馏（数据充分后启动）
├─ data/                     # 决策轨迹数据
├─ mcp/                      # STS2-Agent MCP Server（外部依赖）
└─ docs/
```

设计原则：
- `game_bridge/` 只取状态，不决策
- `agent/` 调度 + 兜底，真正决策由 LLM (MCP) 完成
- `training/` 与运行时解耦
- 状态 Schema 字段用 `Optional`，缺失时降级而非崩溃

---

## 6. 在线决策流程

```text
主流程：
  Mod 运行 → get_game_state → get_available_actions
  → Codex 推理 → rule_guard 校验 → act → recorder 记录 → 循环

降级流程（Codex 不可用）：
  rule_guard 接管 → 地图用 optimizer.py / 战斗用基础规则 / 其它安全默认
```

---

## 7. 实施计划

| 阶段 | 目标 | 验收标准 |
|------|------|---------|
| **A: 状态管道** | Mod HTTP API → Python 结构化状态 | 能打印战斗状态 JSON + 记录一局日志 |
| **B: 决策引擎** | Codex MCP 全场景自动决策 | 自动完成一局游戏 + 轨迹存储 |
| **C: 策略优化** | prompt 迭代 + 数据积累 | 通关率 ≥ 50% + 200 局数据 |
| **D: Agent SDK 迁移** | 程序化 LLM 接入 | 脱离 Codex CLI 独立运行 |
| **E: 蒸馏** | 本地小模型 | 与 Codex 一致率 > 70% |

当前位置：**A 已完成大部分（骨架代码就绪），B 进行中（MCP 已通，待 prompt 开发）**

---

## 8. 风险与对策

| 风险 | 对策 |
|------|------|
| Mod 版本不兼容 | 抽象接口可切换实现 + 社区跟进 + CV 降级 |
| Codex/LLM 延迟 | 回合制可接受 + 批量规划 + 蒸馏后本地推理 |
| LLM 产生非法动作 | rule_guard 校验 + MCP tool 约束 + 自动重试 |
| 数据质量不足 | 先确保通关率再蒸馏 + 按结果加权 + 过滤低质量 |
| API 配额/中断 | 规则兜底独立运行 + 本地模型替代 |

---

## 9. 与现有代码的衔接

**保留复用**：`core/screen.py`、`core/mouse.py`、`route_planner/*`、`gui_app.py`

**升级**：`optimizer.py`（静态权重 → 状态感知评分），以"可切换模式"并行接入：
- 经典模式：启发式评分
- 智能模式：LLM 结合 RunState 评估

