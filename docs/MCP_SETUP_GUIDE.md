# STS2 AI Agent + Codex MCP 接入指南

> 来源：https://github.com/CharTyr/STS2-Agent
> 当前版本：v0.5.2（兼容 STS2 v0.99.1）
> 状态：已技术验证，可行 ✅

---

## 1. 前置条件

- 杀戮尖塔 2（Steam）已安装
- Codex 订阅可用（CLI 版本）
- Python 3.11+ 和 `uv` 已安装（本机 uv 0.9.11 已就绪）

---

## 2. 安装 STS2AIAgent Mod

### 2.1 下载

- **GitHub（推荐）**：https://github.com/CharTyr/STS2-Agent/releases
- **NexusMods**：https://www.nexusmods.com/slaythespire2/mods/155

### 2.2 安装 Mod 文件

将 release 包中以下三个文件复制到游戏 `mods/` 目录：

```
Slay the Spire 2/
└─ mods/
   ├─ STS2AIAgent.dll
   ├─ STS2AIAgent.pck
   └─ mod_id.json
```

默认 Steam 路径：`C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2\`

### 2.3 验证 Mod 加载

启动游戏后访问（端口固定为 **8080**）：

```bash
curl http://127.0.0.1:8080/health
```

返回 200 则表示 Mod 正常运行。

---

## 3. 启动 MCP Server

MCP Server 位于 release 包的 `mcp_server/` 目录，基于 `FastMCP` 实现。

### 3.1 安装依赖

```powershell
cd <STS2-Agent 仓库路径>\mcp_server
uv sync
```

### 3.2 启动（二选一）

**方案 A：stdio 模式（推荐，Codex 默认偏好）**

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\start-mcp-stdio.ps1"
```

或直接：

```powershell
cd mcp_server
uv run sts2-mcp-server
```

**方案 B：HTTP 模式**（适合非 stdio 客户端）

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\start-mcp-network.ps1"
```

MCP HTTP 端点：`http://127.0.0.1:8765/mcp`

---

## 4. 接入 Codex

### 4.1 配置方式一：项目级配置（推荐）

本项目已预置 `.codex/config.toml`，只需将 `cwd` 改为实际路径：

```toml
[mcp_servers.sts2-ai-agent]
command = "uv"
args   = ["run", "sts2-mcp-server"]
cwd    = "D:/path/to/STS2-Agent/mcp_server"   # ← 改为实际路径

[mcp_servers.sts2-ai-agent.env]
STS2_API_BASE_URL = "http://127.0.0.1:8080"
```

### 4.2 配置方式二：CLI 命令添加

```powershell
codex mcp add sts2-ai-agent --env STS2_API_BASE_URL=http://127.0.0.1:8080 -- uv run sts2-mcp-server
```

注意：运行此命令时 working directory 必须在 `mcp_server/` 内，或在 `.codex/config.toml` 中用 `cwd` 指定。

### 4.3 配置方式三：HTTP 模式（先手动启动 MCP 网络服务器）

```toml
[mcp_servers.sts2-ai-agent-remote]
url = "http://127.0.0.1:8765/mcp"
```

### 4.4 加载 Companion Skill

`skills/sts2-mcp-player/SKILL.md` 是专为 Codex 设计的 Agent 行为规范，
强制 Codex 遵循"状态优先、按房间推进、只用可用动作"的工作流。

建议在 Codex Session 开始时加载此 Skill 文件。

---

## 5. MCP 工具清单（guided profile，默认）

| 工具 | 用途 |
|------|------|
| `health_check` | 会话开始时调用，确认 Mod 在线 |
| `get_game_state` | 每次决策前获取完整状态 |
| `get_available_actions` | 获取当前合法动作列表 |
| `act` | 执行动作（统一入口） |
| `get_relevant_game_data` | 场景感知的游戏知识查询（卡牌/遗物/怪物等） |
| `get_game_data_item` | 单实体详细信息查询 |
| `get_game_data_items` | 批量对比查询 |
| `wait_for_event` | 等待特定游戏事件 |
| `wait_until_actionable` | 等待直到可操作状态 |

**推荐决策循环**：`get_game_state` → `get_available_actions` → `act` → 重复

---

## 6. 验证检查清单

- [ ] release 包已从 GitHub 下载并解压
- [ ] `STS2AIAgent.dll` / `.pck` / `mod_id.json` 放入游戏 `mods/`
- [ ] 启动游戏，`http://127.0.0.1:8080/health` 返回 200
- [ ] `mcp_server/` 目录中 `uv sync` 完成
- [ ] MCP Server 启动无报错
- [ ] `.codex/config.toml` 中 `cwd` 已填写实际路径
- [ ] Codex 可通过 `/mcp` 命令看到 `sts2-ai-agent` 服务器
- [ ] Codex 调用 `health_check` 返回成功

---

## 7. 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `STS2_API_BASE_URL` | `http://127.0.0.1:8080` | Mod HTTP API 地址 |
| `STS2_API_TIMEOUT_SECONDS` | `10` | API 请求超时秒数 |
| `STS2_AGENT_KNOWLEDGE_DIR` | `agent_knowledge/` | 运行时知识库目录 |
| `STS2_ENABLE_DEBUG_ACTIONS` | 未设置 | `1` 启用调试工具，生产环境保持关闭 |

---

## 8. 故障排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| `/health` 无响应 | 游戏未运行或 Mod 文件路径错误 | 确认三个文件都在 `mods/` 下（非子目录） |
| MCP Server 启动失败 | `uv sync` 未执行 | 在 `mcp_server/` 下执行 `uv sync` |
| MCP 可启动但读不到状态 | 游戏未运行或端口不匹配 | 确认 `STS2_API_BASE_URL=http://127.0.0.1:8080` |
| Codex 看不到工具 | `cwd` 路径错误 | 检查 `.codex/config.toml` 中的 `cwd` 字段 |
| OS 重命名了文件 | Windows 文件名冲突 | 检查文件名未被追加 `(1)` 等后缀 |
