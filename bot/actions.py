"""Atomic actions the pipeline can chain."""
from __future__ import annotations

from typing import Any

from .log import get_logger
from .navigation import prepare_for_task
from .paths.base import BotContext
from .paths.daily import CLAIM_ALIASES, DailyPath
from .paths.play_level import PlayLevelPath

log = get_logger("actions")

CLAIM_ACTIONS = frozenset(
    {
        "arena",
        "peak_arena",
        "peak",
        "shackled_jungle",
        "shackled",
        "jungle",
        "abyssal_tide",
        "abyssal",
        "tide",
        "gold_cave",
        "rune_ruins",
        "rune",
        "events",
        "shop",
        "guild",
        "hunt",
        "friends",
        "daily_main",
    }
)

ACTION_ALIASES: dict[str, str] = {
    "peak": "peak_arena",
    "shackled": "shackled_jungle",
    "jungle": "shackled_jungle",
    "abyssal": "abyssal_tide",
    "tide": "abyssal_tide",
    "rune": "rune_ruins",
    "daily": "daily_main",
}


def normalize_action_name(name: str) -> str:
    key = name.strip().lower().replace("-", "_")
    return ACTION_ALIASES.get(key, key)


def resolve_claim_name(name: str) -> str:
    key = normalize_action_name(name)
    resolved = CLAIM_ALIASES.get(key, key)
    if resolved == "all":
        raise ValueError("Invalid 'all' action in pipeline; use daily_main or a list of claims")
    return resolved


def parse_inline_step(text: str) -> dict[str, Any]:
    """``arena:5``, ``farm:forever``, ``shackled:2``, ``play:10``."""
    raw = text.strip()
    if not raw:
        raise ValueError("Empty step")
    if ":" not in raw:
        return normalize_step({"action": raw})

    action, value = raw.split(":", 1)
    action = normalize_action_name(action)
    value = value.strip()

    if action in ("arena", "peak_arena"):
        return normalize_step({"action": action, "fights": int(value)})
    if action in ("shackled_jungle", "abyssal_tide"):
        return normalize_step({"action": action, "runs": int(value)})
    if action == "farm":
        if value.lower() in ("forever", "inf", "infinite"):
            return normalize_step({"action": "farm", "forever": True})
        return normalize_step({"action": "farm", "games": int(value)})
    if action == "play":
        return normalize_step({"action": "play", "games": int(value)})
    if action == "claim":
        return normalize_step({"action": "claim", "name": value})
    raise ValueError(f"Unrecognized inline syntax: {text!r}")


def normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    out = dict(step)
    action = normalize_action_name(str(out.pop("action", out.get("name", ""))))
    if not action:
        raise ValueError(f"Step without action: {step!r}")

    if action == "claim":
        claim = resolve_claim_name(str(out.pop("name", out.get("claim", ""))))
        out["action"] = "claim"
        out["name"] = claim
        return out

    if action in CLAIM_ACTIONS or action in CLAIM_ALIASES:
        claim = resolve_claim_name(action)
        out["action"] = "claim"
        out["name"] = claim
        return out

    out["action"] = action
    return out


def normalize_steps(steps: list[dict[str, Any] | str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in steps:
        if isinstance(item, str):
            normalized.append(parse_inline_step(item))
        else:
            normalized.append(normalize_step(item))
    return normalized


def _daily_kwargs(step: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if step.get("force"):
        kwargs["force"] = True
    if "recover_emulator" in step:
        kwargs["recover_emulator"] = bool(step["recover_emulator"])
    if "fights" in step:
        kwargs["arena_fights"] = int(step["fights"])
    if "max_power" in step:
        kwargs["arena_max_power"] = float(step["max_power"])
    if "exit_early" in step:
        kwargs["arena_exit_early"] = bool(step["exit_early"])
    if "confirm" in step:
        kwargs["arena_confirm"] = bool(step["confirm"])
    if "confirm_wait" in step:
        kwargs["arena_confirm_wait"] = float(step["confirm_wait"])
    if "battle_abort_s" in step:
        kwargs["arena_battle_abort_s"] = float(step["battle_abort_s"])
    if "reload_after_exit_s" in step:
        kwargs["arena_reload_after_exit_s"] = float(step["reload_after_exit_s"])
    if "keys" in step:
        kwargs["rune_ruins_keys"] = int(step["keys"])
    if "runs" in step:
        claim = step.get("name", "")
        if claim == "shackled_jungle":
            kwargs["shackled_jungle_runs"] = int(step["runs"])
        elif claim == "abyssal_tide":
            kwargs["abyssal_tide_runs"] = int(step["runs"])
    return kwargs


def execute_step(ctx: BotContext, step: dict[str, Any]) -> None:
    action = step["action"]
    log.info("Executing action: %s %s", action, {k: v for k, v in step.items() if k != "action"})

    if action == "claim":
        claim = resolve_claim_name(str(step["name"]))
        prepare_for_task(ctx, f"claim:{claim}")
        daily = DailyPath(ctx, **_daily_kwargs(step))
        daily.run_one(claim)
        return

    if action == "daily_main":
        claims = step.get("claims")
        prepare_for_task(ctx, "daily_main")
        daily = DailyPath(ctx, **_daily_kwargs(step))
        daily.run(claims)
        return

    if action == "farm":
        from .run_end_dismiss import configure_farm_ctx

        forever = bool(step.get("forever", False))
        task = "farm_forever" if forever else "farm"
        prepare_for_task(ctx, task)
        configure_farm_ctx(ctx)
        PlayLevelPath(
            ctx,
            level=int(step.get("level", 50)),
            games=None if forever or step.get("games") is None else int(step["games"]),
            battle_timeout=float(step.get("battle_timeout", 600.0)),
            max_games=int(step.get("max_games", 40)),
            forever=forever,
            energy_wait_s=float(step.get("energy_wait", 60.0)) * 60.0,
            dodge=bool(step.get("dodge", False)),
        ).run()
        return

    if action == "play":
        prepare_for_task(ctx, "play")
        PlayLevelPath(
            ctx,
            level=int(step.get("level", 50)),
            games=int(step.get("games", 1)),
            battle_timeout=float(step.get("battle_timeout", 600.0)),
            dodge=bool(step.get("dodge", False)),
        ).run()
        return

    raise ValueError(f"Unknown action: {action!r}")


def describe_step(step: dict[str, Any]) -> str:
    action = step.get("action", "?")
    if action == "claim":
        name = step.get("name", "?")
        extra: list[str] = []
        if "fights" in step:
            extra.append(f"{step['fights']} fights")
        if "runs" in step:
            extra.append(f"{step['runs']} runs")
        if "force" in step and step["force"]:
            extra.append("force")
        suffix = f" ({', '.join(extra)})" if extra else ""
        return f"{name}{suffix}"
    if action == "farm":
        return "farm forever" if step.get("forever") else f"farm x{step.get('games', 'energy')}"
    if action == "play":
        return f"play x{step.get('games', 1)}"
    if action == "daily_main":
        claims = step.get("claims")
        return "daily main" if not claims else f"daily {','.join(claims)}"
    return action
