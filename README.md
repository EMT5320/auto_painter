# ⚔ STS2 Game Assistant — 杀戮尖塔2 游戏助手

杀戮尖塔2 游戏助手，集成 AI 决策引擎、地图路线规划和自动绘画功能。

**当前功能：**
- 🤖 **AI 智能助手** — LLM 驱动的自动决策引擎，通过 MCP 与游戏交互（核心功能，可用）
- 🎨 **自动绘画** — 将图片或文字绘制到地图画布上（完整可用）
- 🗺 **路线规划** — 识别地图节点，按偏好计算最优路线（开发中）

---

## 安装依赖

```bash
pip install -r requirements.txt
```

> 决策引擎依赖 `openai-agents` 和 `openai`，已包含在 `requirements.txt` 中。

## 启动

### 🤖 AI 智能助手（CLI）

需要先启动游戏并加载 STS2AIAgent Mod（HTTP API 监听 `127.0.0.1:8080`），然后：

```bash
# Agent SDK 模式 — LLM 通过 MCP 自主读状态 + 执行（推荐）
python run_agent.py --engine agent_sdk --api-key "sk-xxx"

# Direct LLM 模式 — 直接 API 调用，不启动 MCP 子进程（轻量调试用）
python run_agent.py --engine direct_llm --api-key "sk-xxx"

# 指定模型 / 提供商
python run_agent.py --provider anthropic --model claude-sonnet-4-20250514
python run_agent.py --model gpt-4o-mini

# 查看完整参数
python run_agent.py --help
```

也可以通过环境变量传入 API Key：
```bash
set OPENAI_API_KEY=sk-xxx
python run_agent.py
```

### 图形界面版（绘画 + 路线规划）

```bash
python gui_app.py
```

### 命令行版（仅绘画功能）

```bash
python main.py
```

### 打包为 .exe

```bash
python build_exe.py
```

---

## 功能说明

### 🤖 AI 智能助手

基于 LLM 的全自动游戏决策引擎，支持战斗、地图选路、事件、商店、营地、奖励等所有场景。

**两种引擎模式：**

| 模式 | 原理 | 适用场景 |
|------|------|---------|
| `agent_sdk` | LLM 通过 MCP 自主读状态 + 查知识库 + 执行动作 | 正式游玩，推荐 |
| `direct_llm` | Coordinator 读取状态后发给 LLM，解析 JSON 执行 | prompt 调试、轻量测试 |

**支持的模型提供商：** OpenAI / Anthropic / Google / Ollama

**决策轨迹**会自动记录到 `data/trajectories/` 目录（JSONL 格式），可用于后续分析。

**依赖：**
- STS2AIAgent Mod 已安装并运行（提供 HTTP API）
- MCP Server 位于 `mcp/sts2-ai-agent-v0.5.2-windows/`（随项目附带）

### 🎨 绘画功能

在游戏地图界面，按住右键可以自由绘画。本工具自动模拟这个过程，将**文字或图片**绘制到画面上。

1. 切换到「🎨 绘画」标签页
2. 选择「图片模式」或「文字模式」
3. 调整参数后点击「开始绘制」
4. 在倒计时内切换到游戏地图界面

> 在「🤖 AI 素描模式」中，已新增路径优化算法切换：  
> `经典最近邻`（旧版） / `增强路径优化`（新算法，带短线过滤与前瞻排序），可直接做 A/B 对比。

### 🗺 路线规划（开发中）

根据节点偏好自动计算最优路线，并在游戏地图上标注。

**实现进度：**
- Phase 0 (完成)：架构重构，骨架模块建立
- Phase 1 (进行中)：节点模板匹配识别
- Phase 2 (待开始)：图构建 + 路线评分
- Phase 3 (待开始)：路线绘制集成

**使用节点模板：**  
将各节点类型的截图放入 `assets/node_templates/<类型>/` 目录：
```
assets/node_templates/
  elite/     *.png   ← 精英节点图标
  rest/      *.png   ← 营火节点图标
  merchant/  *.png   ← 商人节点图标
  unknown/   *.png   ← 未知节点图标
  treasure/  *.png   ← 宝箱节点图标
  monster/   *.png   ← 敌人节点图标
```

> ⚡ **紧急停止**：把鼠标移到屏幕**左上角**立即中断任何绘制操作

---

## 项目结构

```
auto_painter/
├── run_agent.py              # AI 助手入口（CLI）
├── gui_app.py                # GUI 入口（绘画 + 路线规划）
├── main.py                   # CLI 入口（仅绘画）
├── mcp/                      # MCP Server（STS2AIAgent 工具包装）
│   └── sts2-ai-agent-v0.5.2-windows/
├── features/
│   ├── agent/                # AI 决策引擎
│   │   ├── config.py         # 引擎配置（模型、提供商、模式）
│   │   ├── engine.py         # EngineBase 抽象接口
│   │   ├── sdk_engine.py     # Agent SDK 引擎（MCP 集成）
│   │   ├── direct_engine.py  # Direct LLM 引擎
│   │   ├── prompts.py        # 场景专属系统 prompt
│   │   ├── coordinator.py    # 主循环协调器
│   │   └── rule_guard.py     # 规则校验 + 降级决策
│   ├── game_bridge/          # 游戏状态获取
│   │   ├── mod_bridge.py     # Mod HTTP API 客户端
│   │   └── schemas.py        # 游戏状态数据模型
│   ├── telemetry/            # 决策轨迹记录
│   │   └── recorder.py       # JSONL 轨迹写入
│   ├── painter/              # 绘画功能
│   └── route_planner/        # 路线规划功能
├── core/                     # 原子工具层（截图/鼠标/路径优化）
├── assets/
│   └── node_templates/       # 节点模板图片
└── requirements.txt
```

