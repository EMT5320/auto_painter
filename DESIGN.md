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
    position:  tuple[int, int]  # 屏幕坐标（像素）
    layer:     int              # 所在层数（0 = 起点层，越大越靠近 Boss）

@dataclass
class MapGraph:
    nodes: dict[int, MapNode]
    edges: list[tuple[int, int]]   # (from_id, to_id)
```

### 4.4 识别流水线

```
截图（pyautogui.screenshot）
    │
    ▼
预处理（灰度化、缩放归一化）
    │
    ▼
节点检测（cv2.matchTemplate 模板匹配 × 6 种节点类型）
    │  ├─ 对每类节点使用对应模板图
    │  ├─ 多尺度匹配（应对不同游戏分辨率）
    │  └─ NMS 去重（IoU 阈值 0.5）
    ▼
边检测（连线识别）
    │  ├─ 提取图像中的虚线段（灰度+Canny+Hough）
    │  └─ 匹配线段端点与节点坐标（最近邻）
    ▼
层次划分（Y 坐标 K-Means 聚类确定 layer）
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

- [ ] 收集各节点类型截图，整理到 `assets/node_templates/`（**需要游戏截图**）
- [ ] 完善 `recognizer.py` 的 `detect_nodes`（模板匹配骨架已有，需调优阈值）
- [ ] 实现 `_detect_edges_by_proximity` 边检测（虚线膨胀 + 采样判断）
- [ ] GUI 接入：截图 → 调用识别 → 在预览图上绘制标注框 → 允许手动修正节点

### Phase 2 — 图构建与路线计算 ⏳ 待开始

> `graph.py` 和 `optimizer.py` 核心算法已在 Phase 0 实现，本阶段主要做 GUI 集成。

- [x] `graph.py`：`MapGraph`、`build_map_graph`、`find_all_routes` DFS 枚举（Phase 0 完成）
- [x] `optimizer.py`：`rank_routes` 加权评分（Phase 0 完成）
- [ ] GUI：识别结果 → 构建 MapGraph → 调用 `rank_routes`
- [ ] GUI：路线列表展示 Top 3（含节点组成描述）
- [ ] GUI：点击路线条目，在地图预览图上高亮对应路径

### Phase 3 — 路线绘制集成 ⏳ 待开始

> `drawer.py` 骨架已在 Phase 0 实现，待 Phase 1/2 完成后接入测试。

- [x] `drawer.py` 骨架：圆圈标记 + 连线笔画生成（Phase 0 完成）
- [ ] GUI：「绘制选中路线」按钮接入 `draw_route_on_screen`（含倒计时 + 进度回调）
- [ ] 在不同游戏分辨率下测试坐标准确性
- [ ] 调优圆圈大小和连线粗细

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

---

## 8. 接口契约

### 8.1 `features/route_planner/recognizer.py`

```python
def recognize_map(
    screenshot: PIL.Image.Image,
    templates_dir: str,
    match_threshold: float = 0.75
) -> tuple[list[MapNode], list[tuple[int, int]]]:
    """
    输入：游戏地图截图 + 节点模板目录
    输出：(节点列表, 边列表)
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

---

*本文档最后更新：2026-03-15，Phase 0 全部交付完成。*
