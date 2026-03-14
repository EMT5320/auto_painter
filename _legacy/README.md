# _legacy/ — 旧版代码存档

此目录存放重构前的根目录旧模块，已于 2026-03-15 迁移至分层架构。
保留仅供参考，**不应再被主代码 import**。

| 旧文件 | 迁移目的地 |
|--------|-----------|
| `image_processor.py` | `features/painter/processor.py` |
| `path_optimizer.py`  | `core/path_opt.py` |
| `mouse_controller.py`| `core/mouse.py` |

如需删除此目录，确认以上迁移目标文件均完整即可。
