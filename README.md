# ⚔ STS2 Game Assistant — 杀戮尖塔2 游戏助手

杀戮尖塔2 游戏助手，帮助你在地图界面完成更多操作。

**当前功能：**
- 🎨 **自动绘画** — 将图片或文字绘制到地图画布上（完整可用）
- 🗺 **路线规划** — 识别地图节点，按偏好计算最优路线（开发中）

---

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动

### 图形界面版（推荐）

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
├── core/                     # 原子工具层
│   ├── screen.py             # 截图工具
│   ├── mouse.py              # 鼠标控制
│   └── path_opt.py           # 路径优化
├── features/                 # 游戏功能层
│   ├── painter/              # 绘画功能
│   │   └── processor.py      # 图像/文字处理
│   └── route_planner/        # 路线规划功能
│       ├── recognizer.py     # 节点识别
│       ├── graph.py          # 地图图结构
│       ├── optimizer.py      # 路线评分
│       └── drawer.py         # 路线绘制
├── assets/
│   └── node_templates/       # 节点模板图片
├── gui_app.py                # GUI 入口
├── main.py                   # CLI 入口
├── build_exe.py              # 打包脚本
├── DESIGN.md                 # 详细设计文档
└── requirements.txt
```

详细设计请参阅 [DESIGN.md](DESIGN.md)。

