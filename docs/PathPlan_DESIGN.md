# STS2 Game Assistant — 设计文档

> 版本 v0.3 | 更新日期 2026-03-15 | **Phase 0 已完成**

---

## 1. 项目愿景

将 **Auto Painter** 从单一的"地图绘画工具"扩展为 **杀戮尖塔2 游戏助手**。  
绘画功能作为通用底层能力保留，新增"路线规划"等游戏感知功能模块，形成可持续扩展的助手平台。

**设计目标：**
- 模块化、可插拔的功能架构，每个游戏功能独立
- 核心工具层（截图、鼠标控制、路径优化）复用
- GUI 支持按功能切换标签页，易于扩展新功能

---

## 2. 现状分析（重构前历史记录）

> ⚠ 以下描述为重构**前**的旧状态，仅供参考；当前架构见第 3 节。

### 2.1 重构前的文件结构

| 模块 | 文件 | 职责 |
|------|------|------|
| 图像处理 | `image_processor.py` | 图片/文字 → Canny边缘 → 轮廓路径 |
| 路径优化 | `path_optimizer.py` | 最近邻排序、点稀疏化 |
| 鼠标控制 | `mouse_controller.py` | 倒计时、右键hold绘制 |
| GUI | `gui_app.py` | 图形界面（单文件，~660行） |
| CLI | `main.py` | 命令行入口 |

> 以上三个模块已于 2026-03-15 迁移至 `core/` 和 `features/`，旧文件存档于 `_legacy/`。

### 2.2 重构前的痛点

1. `gui_app.py` 是单体文件，所有逻辑混合
2. 根目录模块平铺，无法区分"核心工具"和"业务功能"
3. 扩展新功能需直接修改 gui_app.py 主类

---

## 3. 目标架构

### 3.1 目录结构

```
auto_painter/
├── core/                       # 📦 原子工具层（与游戏无关）✅
│   ├── __init__.py
│   ├── screen.py               # 截图、屏幕区域工具  ✅
│   ├── mouse.py                # 鼠标控制（原 mouse_controller.py）  ✅
│   └── path_opt.py             # 路径排序优化（原 path_optimizer.py）  ✅
│
├── features/                   # 📦 游戏功能层  ✅
│   ├── painter/                # 🎨 绘画功能  ✅
│   │   ├── __init__.py
│   │   └── processor.py        # 图像/文字处理（原 image_processor.py）  ✅
│   └── route_planner/          # 🗺 路线规划功能  ✅ 骨架已建立
│       ├── __init__.py
│       ├── recognizer.py       # 地图节点识别  ⏳ Phase 1 待实现
│       ├── graph.py            # 地图图结构与路径枚举  ✅
│       ├── optimizer.py        # 路线评分与推荐  ✅
│       └── drawer.py           # 路线标注（调用 core.mouse）  ⏳ Phase 3 待测试
│
├── ui/                         # 📦 界面组件层（预留）
│   └── __init__.py
│
├── assets/
│   └── node_templates/         # 节点模板图片（⏳ Phase 1 待填充）
│
├── _legacy/                    # 🗄 旧模块存档（已迁移，不再使用）✅
│   ├── image_processor.py
│   ├── path_optimizer.py
│   └── mouse_controller.py
│
├── gui_app.py                  # GUI 入口（绘画 + 路线规划双标签）  ✅
├── main.py                     # CLI 入口  ✅
├── build_exe.py                # PyInstaller 打包脚本
├── requirements.txt
├── DESIGN.md                   # 本文件
└── README.md
```

### 3.2 层级依赖规则

```
GUI (gui_app.py)
    │
    ├──▶  features/painter/     ──▶  core/
    └──▶  features/route_planner/ ──▶  core/
```

- `core` 层不依赖任何 `features` 层
- `features` 层只依赖 `core` 层，互相独立
- GUI 层可以同时使用多个 features

---

## 4. 路线规划功能设计

### 4.1 功能概述

用户在游戏地图界面截图后，程序自动：
1. 识别地图中所有节点（类型 + 位置）
2. 检测节点间的连接边
3. 根据用户偏好（最多/少火堆、精英等）评分所有可行路线
4. 展示 Top 3 推荐路线
5. 用户选择后，绘制系统在游戏地图上画出路线标记

### 4.2 节点类型

```python
class NodeType(Enum):
    MONSTER  = "monster"   # 敌人 👾
    ELITE    = "elite"     # 精英 👹
    REST     = "rest"      # 休息/营火 🔥
    MERCHANT = "merchant"  # 商人 🏪
    UNKNOWN  = "unknown"   # 未知 ❓
    TREASURE = "treasure"  # 宝箱 🗝
    BOSS     = "boss"      # Boss（终点）
```

### 4.3 地图图结构

STS2 地图是一个有向无环图（DAG），从起点（底部）到 Boss（顶部）。

```python
@dataclass
class MapNode:
    node_id:   int
    node_type: NodeType
    position:  tuple[int, int]  # 屏幕坐标（像素）或拼接画布坐标
    screen_pos: tuple[int, int] # 原始屏幕坐标（用于点击）
    scroll_step: int            # 点击前需滚动到的步骤
    layer:     int              # 所在层数（0 = 起点层，越大越靠近 Boss）

@dataclass
class MapGraph:
    nodes: dict[int, MapNode]
    edges: list[tuple[int, int]]   # (from_id, to_id)
```

**START / BOSS 节点采用拓扑推断，不依赖模板**（见 §4.7 起点/终点识别）：
- `NodeType.START`：入度 = 0 的节点，路线从此分叉
- `NodeType.BOSS`：出度 = 0 的节点，路线在此收束

### 4.4 识别流水线

```
倒计时后最小化 GUI
    │
    ▼
滚动采集（pyautogui.scroll + screenshot）
    │  ├─ 先滚到底部（起点可见）
    │  ├─ 自适应滚轮量（基于相邻帧相似度动态放大/缩小）
    │  └─ 连续多次激进滚动无变化 → 判定到达 Boss 顶部
    ▼
多帧拼接（根据重叠区域计算 y_offset）
    │
    ▼
预处理（灰度化、缩放归一化）
    │
    ▼
节点检测（cv2.matchTemplate 模板匹配 × 6 种节点类型）
    │  ├─ 对每类节点使用对应模板图
    │  ├─ 多尺度匹配（应对不同游戏分辨率）
    │  ├─ 同类型 NMS 去重（IoU 阈值 0.5）
    │  └─ 跨模板/跨尺度空间聚类去重（同一真实节点合并）
    ▼
边检测（虚线识别）
    │  ├─ 仅在相邻层节点对之间检测
    │  ├─ 沿两节点连线采样像素亮度
    │  └─ 暗色虚线占比超过阈值 → 视为相连
    ▼
图净化
    │  ├─ 去掉重复边 / 自环
    │  ├─ 保留最大弱连通分量
    │  └─ 重新编号节点并重新分层
    ▼
层次划分（Y 坐标分组确定 layer）
    │
    ▼
构建 MapGraph
```

#### 模板匹配细节

- 每种节点类型需要 **1-3 张**参考截图作为模板（从游戏中截取）
- 存放在 `assets/node_templates/<type>/` 目录下
- 使用 `cv2.TM_CCOEFF_NORMED`，阈值 ≥ 0.75 视为匹配
- 多尺度：缩放系数 [0.8, 0.9, 1.0, 1.1, 1.2]，处理不同分辨率

```python
# recognizer.py 核心逻辑示例
def detect_nodes_by_template(screenshot_gray, templates_dir) -> list[MapNode]:
    results = []
    for node_type in NodeType:
        tmpl_dir = os.path.join(templates_dir, node_type.value)
        templates = load_templates(tmpl_dir)
        for scale in [0.8, 0.9, 1.0, 1.1, 1.2]:
            for tmpl in templates:
                scaled = cv2.resize(tmpl, None, fx=scale, fy=scale)
                res = cv2.matchTemplate(screenshot_gray, scaled, cv2.TM_CCOEFF_NORMED)
                locs = np.where(res >= MATCH_THRESHOLD)
                for pt in zip(*locs[::-1]):
                    results.append(RawMatch(node_type, pt, res[pt[1], pt[0]], scale))
    return nms_deduplicate(results)
```

### 4.5 路线评分系统

用户偏好使用 **权重滑块**（-2 到 +2），代表对某类节点的厌恶/偏好程度。

```python
@dataclass
class RoutePreferences:
    weights: dict[NodeType, float]
    # 示例: {NodeType.ELITE: +2.0, NodeType.REST: +1.0, NodeType.MONSTER: -1.0}
```

路线评分算法：

```
score(route) = Σ weight[node.type] for node in route
             + bonus_diversity        # 路线经过多种节点类型奖励
             + penalty_consecutive_monsters  # 连续怪物惩罚
```

找出所有从起点到 Boss 的路径（DFS），按得分降序排列，返回 Top 3。

由于路径数通常 < 数千条（STS2 地图约 5-7 层，每层 3-5 个节点），全枚举可行。

### 4.6 路线绘制方案

选定路线后，将路线节点坐标转换为鼠标绘制指令：

```python
def draw_route(path: list[int], graph: MapGraph, style: DrawStyle):
    """
    1. 从 graph 获取 path 中各节点的 screen position
    2. 在相邻节点间生成连线点序列（interpolate）
    3. 调用 core.mouse.draw_strokes 按住右键绘制
    4. 在每个节点位置画圆点（小圆圈）突出显示
    """
```

绘制风格选项：
- **路径线**：连接各节点的粗线段
- **节点标记**：在选中节点处画圆圈
- **起点终点**：起点画三角，终点画星形

### 4.7 地图超屏滚动与全图拼接

#### 问题背景

STS2 地图的高度**超过单个屏幕**，需要滚动才能看到完整路线。  
地图结构为**单根单叶有向树**：  
- **唯一起点**（地图底部，单个入口节点）→ 多条分岔路 → **唯一终点**（Boss，地图顶部）

#### 双坐标系设计

| 坐标系 | 说明 | 用途 |
|--------|------|------|
| **拼接画布坐标** (`position`) | 完整游戏地图的绝对像素坐标，Y 轴向下 | 层次划分、路径分析 |
| **屏幕坐标** (`screen_pos`) | 节点在被截图那一帧中的实际屏幕像素坐标 | 点击操作、路线标注 |

每个 `MapNode` 同时存储两套坐标。

#### 滚动采集流程

```
1. 将鼠标移至地图区域中心
2. 向下滚动到底（起点可见）
   └── scroll_to_map_bottom(map_center)
3. 循环 num_steps 次：
   ├── 截图当前视口 → frames[step]
   ├── 记录 scroll_step = step
   └── 向上滚动 scroll_clicks_per_step 格
4. 返回 frames[(screenshot, scroll_step), ...]
```

#### 截图拼接算法

相邻两帧之间存在**重叠区域**（上方帧的底部 = 下方帧的顶部，在地图空间内）：

```
地图全图（垂直展开）：
  ┌──────────────┐  ← Boss（顶部）
  │  frame[N]    │  scroll_step=N（镜头最高）
  │  ┄┄┄┄┄┄┄┄┄┄  │  ← 重叠区 N/N-1
  │  frame[N-1]  │
  │  ┄┄┄┄┄┄┄┄┄┄  │  ← 重叠区 1/0
  │  frame[0]    │  scroll_step=0（镜头最低）
  └──────────────┘  ← 起点（底部）
```

**重叠检测**：  
- 取 `frame[i]`（下方帧）顶部 30% 作为模板  
- 在 `frame[i+1]`（上方帧）底部 60% 中用 `cv2.matchTemplate` 搜索  
- 匹配位置确定像素偏移，从而精确计算每帧在拼接画布中的 Y 偏移量

**拼接公式**：
```
y_offset[0]   = total_height - frame_h          # frame[0] 贴在画布底部
y_offset[i+1] = y_offset[i] - step_size[i]      # step_size = frame_h - overlap
total_height  = frame_h + Σ step_sizes
```

#### 起点 / 终点识别

> **设计决策**：START 和 BOSS 节点**不使用模板匹配**，改用图拓扑结构推断。  
> 原因：STS2 的 Boss 图标每局随机（骷髅骑士、守望者等），起点图标同样不固定，无法维护可靠模板库。

**拓扑推断规则（`graph.mark_structural_nodes`）：**

| 角色 | 拓扑特征 | 含义 |
|------|---------|------|
| `NodeType.START` | 入度 = 0，出度 > 0 | "路线开始分叉的地方"——无任何前驱节点 |
| `NodeType.BOSS`  | 出度 = 0，入度 > 0 | "分叉路线的收束点"——无任何后继节点 |

**流程**：
1. 模板匹配阶段**跳过** START 和 BOSS（见 `_STRUCTURAL_NODE_TYPES`）
2. 对所有中间节点（MONSTER/ELITE/REST 等）正常识别
3. `build_map_graph` 构图后自动调用 `mark_structural_nodes`，根据入出度打标

这样无论 Boss 图标如何变化，只要图结构正确（路线在顶部唯一收束），就能准确识别喵～

#### 点击时的坐标还原

路线绘制时，需按 `scroll_step` 分组执行：

```python
for node in route:
    scroll_to_step(node.scroll_step)   # 先滚到对应步骤
    click(node.screen_pos)             # 再用屏幕坐标点击
```

### 4.8 当前实现状态（2026-03-15 上午）

今天上午已完成以下关键改动：

- 路线规划 GUI 从"截图 / 分析 / 绘制"三步操作，改为**倒计时后自动接管**的一体化流程
- GUI 在倒计时结束后自动 `iconify()` 最小化，避免把助手窗口截进地图截图中
- `core/screen.py` 新增**自适应滚动截图**逻辑：
    - 相邻帧相似度高 → 逐步放大滚轮量
    - 相邻帧变化过大 → 逐步减小滚轮量
    - 多次激进滚动后仍几乎无变化 → 判定滚动到地图顶部（Boss 可见）
- `recognizer.py` 的边检测从"位置推断"改为**真实虚线检测**，避免不相连节点被错误连边
- `recognizer.py` 新增两阶段去重：
    - **同类型 NMS 去重**：去掉同一模板/尺度的重复命中
    - **跨模板空间聚类去重**：去掉不同模板/尺度命中的同一真实节点
- `recognizer.py` 新增图净化：重复边去重、保留最大弱连通分量、重新编号节点
- 路线绘制阶段不再使用单一固定滚轮量，而是复现采集阶段的**逐步滚动计划**，减少滚动错位

当前实际状态：

- 滚动采集与全图拼接：**可用**
- 模板加载与节点识别：**可用，但重复命中较多**
- 虚线边检测：**基本可用**
- 自动路线规划：**已接入 GUI**
- 自动路线绘制：**已接入 GUI**

当前主要问题：

- 某些实际地图中，模板匹配会产生大量重复节点（例如曾出现 **333 个节点** 的异常结果）
- 新增的图净化在某些情况下又**过于激进**，可能把真实节点一并合并掉，当前曾压缩到仅 **9 个节点 / 8 条边**
- 因此，当前瓶颈已从"能不能滚动识别"转移到"**如何从重复命中中恢复出真实树状地图**"

下一步应重点收敛：

1. 调整空间去重阈值（按层内间距、节点图标尺寸、模板尺度做自适应）
2. 将去重从"全局距离聚类"改为"先分层、后做层内去重"
3. 用树状图约束（每层节点数、入出度分布、路径连续性）辅助恢复真实地图
4. 在 GUI 预览图上叠加去重前/去重后的节点框，便于人工观察误差来源

---

## 5. 实现计划

### Phase 0 — 架构重构 ✅ 已完成（2026-03-15）

**交付内容：**

- [x] 分析现有代码，识别痛点
- [x] 创建 `core/`、`features/` 目录结构与 `__init__.py`
- [x] 迁移 `mouse_controller.py` → `core/mouse.py`
- [x] 迁移 `path_optimizer.py` → `core/path_opt.py`
- [x] 迁移 `image_processor.py` → `features/painter/processor.py`
- [x] 新增 `core/screen.py`（截图与屏幕区域工具）
- [x] `gui_app.py` 重构：标题更名 + 顶层功能 TabView（🎨 绘画 / 🗺 路线规划）
- [x] `gui_app.py` 路线规划骨架 UI（节点偏好滑块 × 6、截图按钮、路线列表区）
- [x] 创建 `features/route_planner/` 完整骨架模块（4 个子模块 + `__init__.py`）
- [x] 实现 `graph.py`：`MapGraph`、`build_map_graph`、`find_all_routes`（DFS 枚举，已测试）
- [x] 实现 `optimizer.py`：`RoutePreferences`、`rank_routes`、`describe_route`（已测试）
- [x] 实现 `drawer.py` 骨架：`route_to_strokes`、`draw_route_on_screen`
- [x] 更新 `main.py` / `requirements.txt` 使用新导入路径
- [x] 旧模块存档至 `_legacy/`，根目录整洁
- [x] 更新 `README.md` 反映新项目定位
- [x] 编写 `DESIGN.md` 设计文档

**测试验证：**
```
所有核心模块导入: OK
DFS 路径枚举（3条路径）: OK
路线评分排序: OK（精英权重+2时正确选出精英路线）
```

### Phase 1 — 节点模板采集 + 识别 ⏳ 待开始

**前置条件：** 从游戏中截取各类节点图标，放入 `assets/node_templates/<类型>/` 多张 PNG。

**节点识别：**
- [x] 收集各节点类型截图，整理到 `assets/node_templates/`（已放入 monster / elite / rest / merchant / unknown / treasure）
- [x] 放弃 `start` / `boss` 模板方案，改为图拓扑推断起点与终点
- [x] 完善 `recognizer.py` 的 `detect_nodes`（模板匹配、多尺度、NMS 已接入）
- [x] 实现真实虚线边检测（已替代原 `_detect_edges_by_proximity` 设想）
- [ ] 调优模板阈值、尺度组合与跨模板去重策略
- [ ] 恢复真实地图节点数（当前仍存在"重复过多"与"净化过猛"两种极端情况）

**地图滚动与全图采集（新增）：**
- [x] `core/screen.py` 新增 `scroll_map`、`scroll_to_map_bottom`、`capture_scrolled_map`
- [x] `recognizer.py` 新增 `NodeType.START`，`MapNode` 扩展 `scroll_step`/`screen_pos` 字段
- [x] `recognizer.py` 新增 `_detect_frame_overlap`（帧间重叠检测）
- [x] `recognizer.py` 新增 `stitch_screenshots`（多帧拼接）
- [x] `recognizer.py` 新增 `recognize_full_map_scrolled`（滚动采集 + 拼接 + 识别一体化）
- [x] 滚动策略升级为**自适应滚轮量**，基于相邻帧相似度动态调整
- [x] GUI 接入：倒计时 → 最小化窗口 → 自动滚动采集 → 拼接 → 识别 → 规划 → 绘制
- [ ] 实测校准：确认不同分辨率 / DPI 下，自适应滚动能稳定覆盖整张地图
- [ ] GUI 预览：叠加显示节点框、边、去重前后对比，辅助调试

### Phase 2 — 图构建与路线计算 ⏳ 待开始

> `graph.py` 和 `optimizer.py` 核心算法已在 Phase 0 实现，本阶段主要做 GUI 集成。

- [x] `graph.py`：`MapGraph`、`build_map_graph`、`find_all_routes` DFS 枚举（Phase 0 完成）
- [x] `optimizer.py`：`rank_routes` 加权评分（Phase 0 完成）
- [x] GUI：识别结果 → 构建 MapGraph → 调用 `rank_routes`
- [x] GUI：路线列表展示候选路线（用于日志/预览）
- [x] 规划与绘制合并：自动选择最高分路线；若有多条并列最高分则随机选择一条
- [ ] 在地图预览图上高亮最终选中的路径，便于肉眼核对

### Phase 3 — 路线绘制集成 ⏳ 待开始

> `drawer.py` 骨架已在 Phase 0 实现，待 Phase 1/2 完成后接入测试。

- [x] `drawer.py` 骨架：圆圈标记 + 连线笔画生成（Phase 0 完成）
- [x] GUI 已接入自动绘制流程（倒计时 + 接管 + 绘制）
- [x] 绘制阶段按 `scroll_step` 和 `scroll_plan` 分步滚动后再绘制，避免滚动错位
- [ ] 在不同游戏分辨率下测试 `screen_pos` 映射精度
- [ ] 调优圆圈大小和连线粗细
- [ ] 解决跨帧节点去重后，绘制坐标可能随代表帧变化而抖动的问题

### Phase 4（可选扩展）

- [ ] 支持手动标注模式（用户点击地图截图标注节点）
- [ ] 支持 YOLO 模型替代模板匹配（提升识别泛化性）
- [ ] 添加更多游戏功能（如牌库建议等）

---

## 6. 技术选型

| 技术 | 用途 | 理由 |
|------|------|------|
| OpenCV `cv2.matchTemplate` | 节点识别 | 无需训练，轻量级，支持多尺度 |
| OpenCV `HoughLinesP` | 连线检测 | 适合检测直线段连接 |
| NetworkX（可选） | 图算法 | 路径枚举；也可自实现 DFS 避免额外依赖 |
| customtkinter | GUI | 现有基础，保持一致 |
| pyautogui | 截图 + 鼠标 | 现有依赖 |

> **NetworkX 的取舍**：STS2 地图图规模小（< 50节点），自实现 DFS 即可，无需引入 NetworkX。  
> 若未来需要更复杂的图算法（最短路、连通分量），再考虑引入。

---

## 7. 已知难点与对策

### 7.1 游戏分辨率多样性

**问题**：玩家屏幕分辨率（1080p/1440p/4K）不同，节点图标大小不一致。  
**对策**：多尺度模板匹配（resize 模板至 5 个尺度）+ 记忆用户上次成功的缩放系数。

### 7.2 地图区域检测

**问题**：截图包含游戏外的内容（任务栏、其他窗口）。  
**对策**：让用户拖动框选地图区域，或检测游戏窗口句柄（`win32gui.FindWindow`）自动裁剪。

### 7.3 虚线连线检测难度

**问题**：STS2 地图连线是虚线（间断性），Hough 变换容易漏检。  
**对策**：
1. 先对截图做形态学膨胀（`cv2.dilate`）将虚线补全为实线
2. 再做直线检测
3. 备选：直接用节点间距离 + 角度阈值推断连接关系（对于层次结构地图较准确）

### 7.4 节点遮挡

**问题**：节点可能相互重叠（罕见但存在）。  
**对策**：NMS 时保留置信度更高者；允许用户手动修正。

### 7.5 地图高度超出屏幕

**问题**：STS2 地图纵向超过单屏，无法一次截图获取全部节点；起点在屏幕底部，Boss 在顶部。  
**对策**：
1. 先用 `scroll_to_map_bottom` 滚到最底部，保证起点可见
2. 以固定步长向上滚动，每步调用 `capture_region` 截图
3. 用 `_detect_frame_overlap`（`cv2.matchTemplate` 匹配相邻帧重叠区）精确计算帧间偏移
4. `stitch_screenshots` 将所有帧拼合为完整地图画布
5. 同时为每个节点存储 `screen_pos`（原始屏幕坐标）和 `scroll_step`（对应的滚动步骤），用于后续点击

**滚动步数估计**：以 1080p 分辨率为基准，地图约 1.5~2 屏高，建议 `num_steps=6, scroll_clicks_per_step=5`；  
4K 分辨率图标变大，需相应增大 `scroll_clicks_per_step`。

### 7.6 重复节点与过度净化

**问题**：模板匹配在真实游戏截图中会产生大量重复命中；但如果去重阈值设得过大，又会把相邻真实节点错误合并。  
典型现象：
1. 去重不足时，曾出现 **333 个节点** 的异常识别结果
2. 净化过猛时，又可能只剩 **9 个节点 / 8 条边**，导致无法恢复完整路线

**当前对策：**
1. 先做同类型 NMS 去重，再做跨模板空间聚类去重
2. 用最大弱连通分量去掉孤立噪声节点
3. 用树状图约束（起点唯一、Boss 唯一、相邻层连边）作为后验过滤

**仍待优化：**
1. 目前空间去重仍是全局阈值，缺乏按层/按图标尺寸的自适应能力
2. 需要引入"层内最小间距"约束，避免同层真实节点被误合并
3. 需要在预览图上显示去重前后结果，便于观察误差来源

### 7.7 自适应滚动仍需实测校准

**问题**：不同分辨率、DPI 缩放、窗口模式下，同样的鼠标滚轮格数对应的地图位移差异很大。  
**当前对策**：基于相邻帧相似度，动态放大/缩小滚轮量；多次激进滚动无变化时停止。  
**仍待优化**：后续可记录一轮成功滚动的 `scroll_plan`，并在相同环境下缓存复用，减少每次启动时的试探成本。

---

## 8. 接口契约

### 8.1 `features/route_planner/recognizer.py`

```python
def recognize_map(
    screenshot: PIL.Image.Image,
    templates_dir: str,
    match_threshold: float = 0.75
) -> tuple[list[MapNode], list[tuple[int, int]]]:
    """单张截图识别（用于已有截图或测试）"""

def recognize_full_map_scrolled(
    map_region: tuple[int, int, int, int],
    templates_dir: str,
    num_scroll_steps: int = 6,
    scroll_clicks_per_step: int = 5,
    match_threshold: float = 0.75,
) -> tuple[list[MapNode], list[tuple[int, int]], PIL.Image.Image]:
    """
    全图滚动采集 + 拼接 + 识别一体化接口。
    输入：地图屏幕区域 (x,y,w,h) + 模板目录
    输出：(节点列表, 边列表, 拼接全图)
    节点的 position  = 拼接画布坐标（用于分层、路径分析）
    节点的 screen_pos = 原始屏幕坐标（用于点击操作）
    节点的 scroll_step = 点击前应滚动到的步骤
    """

def stitch_screenshots(
    frames: list[PIL.Image.Image],
) -> tuple[PIL.Image.Image, list[int]]:
    """
    拼接多张滚动截图，自动检测帧间重叠。
    frames[0] = scroll_step=0（最底部/起点），frames[-1] = 最顶部（Boss）
    返回 (stitched_image, y_offsets)，y_offsets[i] 为帧 i 在拼接图中的 Y 起始坐标
    """
```

### 8.2 `features/route_planner/graph.py`

```python
def build_map_graph(
    nodes: list[MapNode],
    edges: list[tuple[int, int]]
) -> MapGraph:
    """从识别结果构建 MapGraph"""

def find_all_routes(graph: MapGraph) -> list[list[int]]:
    """DFS 枚举所有从起点到终点的路径"""
```

### 8.3 `features/route_planner/optimizer.py`

```python
def rank_routes(
    routes: list[list[int]],
    graph: MapGraph,
    prefs: RoutePreferences
) -> list[tuple[float, list[int]]]:
    """
    输入：所有可行路径 + 图 + 用户偏好
    输出：按得分降序排列的 (score, path) 列表
    """
```

### 8.4 `features/route_planner/drawer.py`

```python
def draw_route_on_screen(
    route: list[int],
    graph: MapGraph,
    draw_speed: float = 0.0004,
    stop_event: threading.Event = None
) -> None:
    """将选定路线通过鼠标绘制到游戏地图上"""
```

### 8.5 `core/screen.py`（新增）

```python
def scroll_map(clicks: int, x: int, y: int) -> None:
    """在指定坐标滚动鼠标滚轮（正数向上/朝Boss方向）"""

def scroll_to_map_bottom(cx: int, cy: int, max_scrolls: int = 30) -> None:
    """将地图滚动到最底部（起点可见）"""

def capture_scrolled_map(
    region: tuple[int, int, int, int],
    num_steps: int,
    scroll_clicks_per_step: int,
    map_center: tuple[int, int],
    step_delay: float = 0.3,
) -> list[tuple[PIL.Image.Image, int]]:
    """
    从地图底部逐步向上滚动截图。
    返回 [(screenshot, scroll_step), ...]，scroll_step=0 为最底部
    """
```

---

*本文档最后更新：2026-03-15 上午，已补充自适应滚动、虚线边检测、一体化规划绘制、节点去重与当前问题记录（4.4 / 4.8 / 7.6 / 7.7）。*
