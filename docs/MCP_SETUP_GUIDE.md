# STS2AIAgent Mod + Codex MCP 接入指南

> 日期：2026-03-20
> 状态：技术验证阶段

---

## 1. 前置条件

- 杀戮尖塔 2 已安装（Steam）
- Codex 订阅可用
- Python 3.x + `uv` 包管理器已安装

---

## 2. 安装 STS2AIAgent Mod

### 2.1 下载

从 NexusMods 下载：https://www.nexusmods.com/slaythespire2/mods/155

### 2.2 安装 Mod

1. 找到 STS2 安装目录：
   ```
   C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2\
   ```
   （也可通过 Steam → 右键游戏 → 管理 → 浏览本地文件）

2. 在安装目录下创建 `mods` 文件夹（如果不存在）

3. 将以下文件复制到 `mods/` 目录：
   ```
   mods/
   ├─ STS2AIAgent.dll
   ├─ STS2AIAgent.pck
   └─ mod_id.json
   ```

### 2.3 验证 Mod 加载

1. 启动杀戮尖塔 2
2. Mod 加载后会在游戏内启动一个本地 HTTP Server
3. 用浏览器或 curl 访问验证：
   ```bash
   curl http://localhost:58000/health
   ```
   （端口号以实际为准，查看 Mod 文档或游戏日志确认）

---

## 3. 安装 MCP Server

STS2AIAgent 自带 MCP Server 包装层，位于下载包的 `mcp_server/` 目录。

### 3.1 安装依赖

```bash
cd mcp_server
uv sync
```

### 3.2 测试 MCP Server

stdio 模式（推荐，桌面 AI 客户端偏好）：
```bash
uv run sts2-mcp-server
```

HTTP 模式：
```bash
uv run sts2-mcp-server --http
```

---

## 4. 接入 Codex

### 4.1 方案 A：Codex 直接通过 MCP 连接

如果 Codex 支持 MCP stdio 模式启动：

在 Codex MCP 配置中添加：
```json
{
  "mcpServers": {
    "sts2-agent": {
      "command": "uv",
      "args": ["run", "sts2-mcp-server"],
      "cwd": "<path-to-mcp_server-directory>"
    }
  }
}
```

### 4.2 方案 B：通过 HTTP MCP 连接

如果客户端偏好 HTTP 方式：

1. 先启动 HTTP MCP Server
2. 配置 Codex 连接到 HTTP 端点

### 4.3 验证连接

Codex 应能通过 MCP tools 进行以下操作：

- 获取游戏状态（场景类型、战斗状态、地图状态等）
- 执行游戏操作（打牌、选择路线、选择奖励等）

---

## 5. 验证检查清单

- [ ] STS2AIAgent Mod 文件已放入游戏 mods/ 目录
- [ ] 启动游戏后 Mod 加载成功
- [ ] HTTP API 健康检查通过 (`/health`)
- [ ] MCP Server 能正常启动
- [ ] Codex 能通过 MCP 获取游戏状态
- [ ] Codex 能通过 MCP 执行游戏操作

---

## 6. 已知注意事项

- 开启 Mod 后游戏会切换到 Modded 存档模式，原存档需手动复制
- STS2 版本更新可能导致 Mod 需要更新
- Mod 的 HTTP API 端口号需要在实际安装后确认
- 联机模式下其他玩家也需要安装相同版本的 Mod

---

## 7. 故障排查

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| Mod 不加载 | 文件路径不对 | 确认文件在 `mods/` 下，非子目录 |
| HTTP API 无响应 | Mod 未启动或端口冲突 | 查看游戏日志确认端口 |
| MCP Server 启动失败 | uv 未安装或依赖缺失 | 运行 `uv sync` 安装依赖 |
| Codex 连接失败 | MCP 配置错误 | 检查 cwd 路径和命令参数 |
