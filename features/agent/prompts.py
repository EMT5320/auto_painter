"""
features/agent/prompts.py
System prompt construction for LLM decision engines.

Prompts are kept concise — the MCP tools already carry game data and knowledge,
so system prompts focus on *decision rules* rather than *game data*.
"""
from __future__ import annotations

from features.game_bridge.schemas import SceneType

_BASE_SYSTEM = """\
You are an AI agent playing Slay the Spire 2. You make optimal decisions by \
reading the live game state through MCP tools and executing actions.

Core rules:
- ALWAYS read the latest game state before deciding.
- Only use actions present in `available_actions`. Never invent actions.
- Use internal English IDs (card_id, enemy_id) — they are more stable than UI text.
- When in doubt, look up unfamiliar cards/monsters/events via `get_game_data_item` \
or `get_relevant_game_data`.
- Think step-by-step: assess the situation, consider options, pick the best action.
"""

_SCENE_PROMPTS: dict[SceneType, str] = {
    SceneType.BATTLE: """\
You are in COMBAT. Follow this priority:
1. Check playable cards in hand (playable=true) and current energy.
2. Read enemy intents carefully — high-damage or multi-attack intents demand block.
3. Decision priority: secure lethal > block dangerous intent > exploit free/draw cards > value plays.
4. Use `act` with card_index and target_index (when requires_target=true).
5. End turn when no more useful plays remain.
""",
    SceneType.MAP: """\
You are choosing a MAP route. Consider:
- Current HP: low HP favors rest sites and avoids elites.
- Deck strength: strong deck can handle elites for better rewards.
- Available paths: prefer routes with good risk/reward balance.
- Use `act` with action="choose_map_node" and option_index.
""",
    SceneType.REST: """\
You are at a REST site. Options typically include rest (heal) and smith (upgrade).
- Rest if HP < 60% of max HP.
- Smith (upgrade a card) if HP is comfortable.
- Use `act` with action="choose_rest_option" and option_index.
""",
    SceneType.EVENT: """\
You are in an EVENT room. Read all available options carefully.
- Check which options are locked or unlocked.
- Consider current HP, gold, deck, and relics when choosing.
- Look up the event via `get_game_data_item` if unfamiliar.
- Use `act` with action="choose_event_option" and option_index.
""",
    SceneType.SHOP: """\
You are in a SHOP. Consider:
- Buy cards that synergize with your deck direction.
- Buy relics if they fit your build.
- Card removal is valuable for deck thinning.
- Don't overspend — keep gold for future shops/events.
- Use the appropriate buy/remove actions.
""",
    SceneType.REWARD: """\
You are choosing REWARDS. Consider:
- Pick cards that improve deck consistency or add key synergies.
- Skip card rewards if your deck is already focused and adding would dilute it.
- Always collect gold and potion rewards when available.
""",
}


def build_system_prompt(scene: SceneType | None = None) -> str:
    """Build the system prompt, optionally specialized for a scene."""
    parts = [_BASE_SYSTEM]
    if scene and scene in _SCENE_PROMPTS:
        parts.append(_SCENE_PROMPTS[scene])
    return "\n\n".join(parts)


def build_task_prompt(scene: SceneType | None = None) -> str:
    """Build the per-step user message that triggers the agent to act."""
    if scene == SceneType.BATTLE:
        return (
            "Read the current combat state. Decide which card to play or "
            "whether to end the turn. Execute your chosen action."
        )
    if scene == SceneType.MAP:
        return "Read the current map state and choose the best next node."
    if scene == SceneType.REST:
        return "Read the rest site options and choose the best one."
    if scene == SceneType.EVENT:
        return "Read the event options and choose the best one."
    if scene == SceneType.SHOP:
        return "Read the shop inventory and decide what to buy or skip."
    if scene == SceneType.REWARD:
        return "Read the available rewards and decide what to take or skip."
    return "Read the current game state and take the most appropriate action."
