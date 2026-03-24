"""
run_agent.py
STS2 智能助手入口

用法:
  python run_agent.py --engine codex_cli                 # Codex CLI (订阅方案，推荐)
  python run_agent.py --engine agent_sdk --api-key ...   # Agent SDK (API 调用)
  python run_agent.py --engine direct_llm --api-key ...  # 直接 LLM 调用（不走 MCP）
  python run_agent.py --engine codex_cli --model o3      # Codex CLI 指定模型
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from features.agent.config import EngineConfig, EngineType, ModelProvider
from features.agent.coordinator import Coordinator
from features.agent.rule_guard import RuleGuard
from features.game_bridge.mod_bridge import ModBridge
from features.telemetry.recorder import TrajectoryRecorder

logger = logging.getLogger("sts2_agent")

# 两次 step 之间的等待，避免过于频繁
STEP_INTERVAL = 2.0
# bridge 不可用时（游戏未启动/不在 run 中）的等待
WAIT_INTERVAL = 5.0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="STS2 AI Assistant")
    p.add_argument(
        "--engine",
        type=str,
        default="codex_cli",
        choices=[e.value for e in EngineType if e != EngineType.RULE_ONLY],
        help="Decision engine: codex_cli (Codex subscription, recommended), "
             "agent_sdk (OpenAI API via MCP), or direct_llm (LLM API only)",
    )
    p.add_argument(
        "--provider",
        type=str,
        default="openai",
        choices=[m.value for m in ModelProvider],
        help="LLM provider (default: openai)",
    )
    p.add_argument("--model", type=str, default=None, help="Model name override")
    p.add_argument("--api-key", type=str, default=None, help="API key (or set env var)")
    p.add_argument(
        "--profile",
        type=str,
        default="guided",
        choices=["guided", "layered", "full"],
        help="MCP tool profile — only used with agent_sdk engine (default: guided)",
    )
    p.add_argument("--host", type=str, default="127.0.0.1", help="Mod API host")
    p.add_argument("--port", type=int, default=8080, help="Mod API port")
    p.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args()


def build_config(args: argparse.Namespace) -> EngineConfig:
    provider = ModelProvider(args.provider)
    engine_type = EngineType(args.engine)
    config = EngineConfig(
        engine_type=engine_type,
        model_provider=provider,
        model_name=args.model,
        mcp_tool_profile=args.profile,
    )
    # 如果命令行传了 api-key，设到环境变量
    if args.api_key:
        import os
        env_var = {
            ModelProvider.OPENAI: "OPENAI_API_KEY",
            ModelProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
            ModelProvider.GOOGLE: "GOOGLE_API_KEY",
        }.get(provider, "OPENAI_API_KEY")
        os.environ[env_var] = args.api_key

    return config


async def main_loop(coordinator: Coordinator) -> None:
    """主循环：持续执行 step 直到手动中断。"""
    logger.info("=== STS2 AI Assistant started ===")
    logger.info("Waiting for game connection on bridge...")

    step_count = 0

    while True:
        try:
            ok = await coordinator.async_step()
            if ok:
                step_count += 1
                if step_count % 10 == 0:
                    logger.info("Completed %d steps", step_count)
                await asyncio.sleep(STEP_INTERVAL)
            else:
                # bridge 不可用 / 主菜单 / game over
                await asyncio.sleep(WAIT_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Loop cancelled, shutting down...")
            break
        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception("Unexpected error in main loop")
            await asyncio.sleep(WAIT_INTERVAL)


async def run(args: argparse.Namespace) -> None:
    config = build_config(args)

    # Codex CLI uses its own auth (codex login), no API key needed here
    if config.engine_type != EngineType.CODEX_CLI and not config.has_api_key:
        logger.error(
            "No API key found! Set %s env var or use --api-key",
            {
                ModelProvider.OPENAI: "OPENAI_API_KEY",
                ModelProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
                ModelProvider.GOOGLE: "GOOGLE_API_KEY",
                ModelProvider.OLLAMA: "(none needed)",
            }.get(config.model_provider, "OPENAI_API_KEY"),
        )
        sys.exit(1)

    bridge = ModBridge(host=args.host, port=args.port)
    rule_guard = RuleGuard()
    recorder = TrajectoryRecorder()
    coordinator = Coordinator(
        bridge=bridge,
        rule_guard=rule_guard,
        recorder=recorder,
        config=config,
    )

    # 注册 graceful shutdown
    loop = asyncio.get_running_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_name, lambda: asyncio.create_task(_shutdown(coordinator)))
        except NotImplementedError:
            # Windows 不支持 add_signal_handler for SIGTERM
            pass

    try:
        await coordinator.start()
        logger.info(
            "Engine: %s | Model: %s | Profile: %s",
            config.effective_engine_type().value,
            config.resolved_model,
            config.mcp_tool_profile,
        )
        await main_loop(coordinator)
    finally:
        logger.info("Stopping engine...")
        await coordinator.stop()
        logger.info("=== STS2 AI Assistant stopped ===")


async def _shutdown(coordinator: Coordinator) -> None:
    logger.info("Received shutdown signal")
    await coordinator.stop()
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nBye!")
