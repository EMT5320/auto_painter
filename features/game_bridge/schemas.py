"""
features/game_bridge/schemas.py
游戏状态数据模型定义

所有字段均使用 Optional，确保 Mod API 版本变化时只会降级而不崩溃。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class SceneType(str, Enum):
    MAP = "map"
    BATTLE = "battle"
    EVENT = "event"
    SHOP = "shop"
    REST = "rest"
    REWARD = "reward"
    BOSS_REWARD = "boss_reward"
    GAME_OVER = "game_over"
    MAIN_MENU = "main_menu"
    UNKNOWN = "unknown"


class NodeType(str, Enum):
    MONSTER = "monster"
    ELITE = "elite"
    BOSS = "boss"
    REST = "rest"
    SHOP = "shop"
    EVENT = "event"
    TREASURE = "treasure"
    START = "start"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# 基础数据类
# ---------------------------------------------------------------------------

@dataclass
class CardData:
    card_id: str
    name: str
    cost: int
    upgraded: bool = False
    exhausts: bool = False
    ethereal: bool = False
    raw: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> "CardData":
        return cls(
            card_id=d.get("id", ""),
            name=d.get("name", ""),
            cost=d.get("cost", 0),
            upgraded=d.get("upgraded", False),
            exhausts=d.get("exhausts", False),
            ethereal=d.get("ethereal", False),
            raw=d,
        )


@dataclass
class BuffData:
    buff_id: str
    name: str
    amount: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "BuffData":
        return cls(
            buff_id=d.get("id", ""),
            name=d.get("name", ""),
            amount=d.get("amount", 0),
        )


@dataclass
class EnemyState:
    enemy_id: str
    name: str
    hp: int
    max_hp: int
    block: int = 0
    intent: Optional[str] = None
    intent_damage: Optional[int] = None
    intent_times: Optional[int] = None
    buffs: list[BuffData] = field(default_factory=list)
    is_dead: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "EnemyState":
        return cls(
            enemy_id=d.get("id", ""),
            name=d.get("name", ""),
            hp=d.get("hp", 0),
            max_hp=d.get("max_hp", 0),
            block=d.get("block", 0),
            intent=d.get("intent"),
            intent_damage=d.get("intent_damage"),
            intent_times=d.get("intent_times"),
            buffs=[BuffData.from_dict(b) for b in d.get("buffs", [])],
            is_dead=d.get("is_dead", False),
        )


@dataclass
class RelicData:
    relic_id: str
    name: str
    counter: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "RelicData":
        return cls(
            relic_id=d.get("id", ""),
            name=d.get("name", ""),
            counter=d.get("counter"),
        )


@dataclass
class PotionData:
    potion_id: str
    name: str
    requires_target: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "PotionData":
        return cls(
            potion_id=d.get("id", ""),
            name=d.get("name", ""),
            requires_target=d.get("requires_target", False),
        )


@dataclass
class MapNodeData:
    node_id: str
    node_type: NodeType
    x: int = 0
    y: int = 0
    children: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "MapNodeData":
        return cls(
            node_id=d.get("id", ""),
            node_type=NodeType(d.get("type", "unknown")),
            x=d.get("x", 0),
            y=d.get("y", 0),
            children=d.get("children", []),
        )


# ---------------------------------------------------------------------------
# 顶层状态 Schema
# ---------------------------------------------------------------------------

@dataclass
class RunState:
    """整局运营状态，贯穿整个 Run"""
    character: Optional[str] = None
    act: Optional[int] = None
    floor: Optional[int] = None
    hp: Optional[int] = None
    max_hp: Optional[int] = None
    gold: Optional[int] = None
    ascension: Optional[int] = None
    potions: list[PotionData] = field(default_factory=list)
    relics: list[RelicData] = field(default_factory=list)
    deck: list[CardData] = field(default_factory=list)
    scene: SceneType = SceneType.UNKNOWN

    @classmethod
    def from_dict(cls, d: dict) -> "RunState":
        return cls(
            character=d.get("character"),
            act=d.get("act"),
            floor=d.get("floor"),
            hp=d.get("hp"),
            max_hp=d.get("max_hp"),
            gold=d.get("gold"),
            ascension=d.get("ascension"),
            potions=[PotionData.from_dict(p) for p in d.get("potions", [])],
            relics=[RelicData.from_dict(r) for r in d.get("relics", [])],
            deck=[CardData.from_dict(c) for c in d.get("deck", [])],
            scene=SceneType(d.get("scene", "unknown")),
        )


@dataclass
class BattleState:
    """战斗场景状态"""
    hand: list[CardData] = field(default_factory=list)
    draw_pile: list[CardData] = field(default_factory=list)
    discard_pile: list[CardData] = field(default_factory=list)
    exhaust_pile: list[CardData] = field(default_factory=list)
    energy: int = 0
    max_energy: int = 3
    player_block: int = 0
    player_buffs: list[BuffData] = field(default_factory=list)
    enemies: list[EnemyState] = field(default_factory=list)
    turn: int = 0
    potions: list[PotionData] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "BattleState":
        return cls(
            hand=[CardData.from_dict(c) for c in d.get("hand", [])],
            draw_pile=[CardData.from_dict(c) for c in d.get("draw_pile", [])],
            discard_pile=[CardData.from_dict(c) for c in d.get("discard_pile", [])],
            exhaust_pile=[CardData.from_dict(c) for c in d.get("exhaust_pile", [])],
            energy=d.get("energy", 0),
            max_energy=d.get("max_energy", 3),
            player_block=d.get("player_block", 0),
            player_buffs=[BuffData.from_dict(b) for b in d.get("player_buffs", [])],
            enemies=[EnemyState.from_dict(e) for e in d.get("enemies", [])],
            turn=d.get("turn", 0),
            potions=[PotionData.from_dict(p) for p in d.get("potions", [])],
        )


@dataclass
class MapState:
    """地图场景状态"""
    nodes: list[MapNodeData] = field(default_factory=list)
    current_node_id: Optional[str] = None
    available_next_nodes: list[MapNodeData] = field(default_factory=list)
    boss_node: Optional[MapNodeData] = None
    act: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "MapState":
        nodes = [MapNodeData.from_dict(n) for n in d.get("nodes", [])]
        next_ids = {n.node_id for n in [MapNodeData.from_dict(n) for n in d.get("available_next", [])]}
        available = [n for n in nodes if n.node_id in next_ids]
        boss_raw = d.get("boss_node")
        return cls(
            nodes=nodes,
            current_node_id=d.get("current_node_id"),
            available_next_nodes=available,
            boss_node=MapNodeData.from_dict(boss_raw) if boss_raw else None,
            act=d.get("act"),
        )


@dataclass
class ActionSet:
    """当前合法动作集合（由 rule_guard 生成或从 Mod API 获取）"""
    can_play_cards: list[str] = field(default_factory=list)
    can_use_potions: list[str] = field(default_factory=list)
    can_end_turn: bool = True
    can_choose_nodes: list[str] = field(default_factory=list)
    can_choose_rewards: list[str] = field(default_factory=list)
    raw: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> "ActionSet":
        return cls(
            can_play_cards=d.get("can_play_cards", []),
            can_use_potions=d.get("can_use_potions", []),
            can_end_turn=d.get("can_end_turn", True),
            can_choose_nodes=d.get("can_choose_nodes", []),
            can_choose_rewards=d.get("can_choose_rewards", []),
            raw=d,
        )


@dataclass
class GameSnapshot:
    """完整的游戏状态快照，用于轨迹记录和 Codex 输入"""
    run: RunState
    battle: Optional[BattleState] = None
    map: Optional[MapState] = None
    actions: Optional[ActionSet] = None
    timestamp: Optional[float] = None
    raw: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> "GameSnapshot":
        import time
        run = RunState.from_dict(d.get("run", {}))
        battle_raw = d.get("battle")
        map_raw = d.get("map")
        actions_raw = d.get("actions")
        return cls(
            run=run,
            battle=BattleState.from_dict(battle_raw) if battle_raw else None,
            map=MapState.from_dict(map_raw) if map_raw else None,
            actions=ActionSet.from_dict(actions_raw) if actions_raw else None,
            timestamp=d.get("timestamp", time.time()),
            raw=d,
        )
