"""Chainable action catalog for the panel."""
from __future__ import annotations

from typing import Any

from ..actions import describe_step, normalize_step

CATEGORIES: tuple[dict[str, str], ...] = (
    {"id": "farm", "label": "Farm & play", "hint": "Spend energy in campaign"},
    {"id": "dungeons", "label": "Dungeons", "hint": "Combat event modes"},
    {"id": "arena", "label": "Arena", "hint": "PvP fights"},
    {"id": "daily", "label": "Daily", "hint": "Claims and daily loops"},
)

CHAIN_ACTIONS: list[dict[str, Any]] = [
    {
        "id": "farm",
        "category": "farm",
        "label": "Farm energy",
        "description": "Play the level until energy runs out.",
        "template": {"action": "farm"},
        "params": [
            {"key": "level", "label": "Level", "type": "number", "default": 50, "min": 1, "max": 99},
        ],
    },
    {
        "id": "farm_forever",
        "category": "farm",
        "label": "Farm forever",
        "description": "Farm in a loop and wait for energy to refill.",
        "template": {"action": "farm", "forever": True},
        "params": [
            {"key": "level", "label": "Level", "type": "number", "default": 50, "min": 1, "max": 99},
            {
                "key": "energy_wait",
                "label": "Energy wait (min)",
                "type": "number",
                "default": 60,
                "min": 10,
                "max": 180,
            },
        ],
    },
    {
        "id": "play",
        "category": "farm",
        "label": "Play N games",
        "description": "Fixed number of campaign runs.",
        "template": {"action": "play"},
        "params": [
            {"key": "games", "label": "Games", "type": "number", "default": 5, "min": 1, "max": 99},
            {"key": "level", "label": "Level", "type": "number", "default": 50, "min": 1, "max": 99},
        ],
    },
    {
        "id": "shackled_jungle",
        "category": "dungeons",
        "label": "Shackled Jungle",
        "description": "Daily dungeon — skills only, no movement.",
        "template": {"action": "claim", "name": "shackled_jungle"},
        "params": [
            {"key": "runs", "label": "Attempts", "type": "number", "default": 3, "min": 1, "max": 10},
        ],
    },
    {
        "id": "abyssal_tide",
        "category": "dungeons",
        "label": "Abyssal Tide",
        "description": "Daily AFK dungeon.",
        "template": {"action": "claim", "name": "abyssal_tide"},
        "params": [
            {"key": "runs", "label": "Attempts", "type": "number", "default": 2, "min": 1, "max": 10},
        ],
    },
    {
        "id": "gold_cave",
        "category": "dungeons",
        "label": "Gold Cave",
        "description": "Gold dungeon quick raids.",
        "template": {"action": "claim", "name": "gold_cave"},
        "params": [],
    },
    {
        "id": "arena",
        "category": "arena",
        "label": "Arena",
        "description": "Fight rivals below the max power threshold.",
        "template": {"action": "claim", "name": "arena"},
        "params": [
            {"key": "fights", "label": "Fights", "type": "number", "default": 2, "min": 1, "max": 20},
            {
                "key": "max_power",
                "label": "Max power (M)",
                "type": "number",
                "default": 5,
                "min": 1,
                "max": 20,
                "step": 0.5,
            },
        ],
    },
    {
        "id": "peak_arena",
        "category": "arena",
        "label": "Peak Arena",
        "description": "High-season arena fights.",
        "template": {"action": "claim", "name": "peak_arena"},
        "params": [
            {"key": "fights", "label": "Fights", "type": "number", "default": 2, "min": 1, "max": 20},
        ],
    },
    {
        "id": "daily_main",
        "category": "daily",
        "label": "Main daily loop",
        "description": "Popups, shop, events, guild, hunt, sidebar (no friends).",
        "template": {"action": "daily_main"},
        "params": [
            {"key": "force", "label": "Force (ignore checks)", "type": "bool", "default": False},
        ],
    },
    {
        "id": "rune_ruins",
        "category": "daily",
        "label": "Rune Ruins",
        "description": "Spend keys on runes (multiple of 5).",
        "template": {"action": "claim", "name": "rune_ruins"},
        "params": [
            {"key": "keys", "label": "Keys", "type": "number", "default": 30, "min": 5, "max": 100, "step": 5},
        ],
    },
]

_ACTION_BY_ID = {a["id"]: a for a in CHAIN_ACTIONS}


def chain_catalog_payload() -> dict[str, Any]:
    return {"categories": list(CATEGORIES), "actions": CHAIN_ACTIONS}


def catalog_action(action_id: str) -> dict[str, Any] | None:
    return _ACTION_BY_ID.get(action_id)


def default_params(action: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for spec in action.get("params", []):
        out[spec["key"]] = spec.get("default")
    return out


def build_step(action_id: str, params: dict[str, Any]) -> dict[str, Any]:
    action = catalog_action(action_id)
    if action is None:
        raise ValueError(f"Unknown action: {action_id}")
    step = dict(action["template"])
    for spec in action.get("params", []):
        key = spec["key"]
        if key not in params:
            continue
        value = params[key]
        if spec.get("type") == "bool":
            step[key] = bool(value)
        elif spec.get("type") == "number":
            if value is None or value == "":
                continue
            if key == "max_power":
                step[key] = float(value)
            else:
                step[key] = int(float(value))
        else:
            step[key] = value
    if params.get("force"):
        step["force"] = True
    return normalize_step(step)


def match_catalog_id(step: dict[str, Any]) -> str | None:
    normalized = normalize_step(dict(step))
    for action in CHAIN_ACTIONS:
        template = action["template"]
        if normalized.get("action") != template.get("action"):
            continue
        if template.get("action") == "claim" and normalized.get("name") != template.get("name"):
            continue
        if template.get("action") == "farm" and bool(template.get("forever")) != bool(normalized.get("forever")):
            continue
        return action["id"]
    return None


def chain_item_from_step(step: dict[str, Any]) -> dict[str, Any] | None:
    action_id = match_catalog_id(step)
    if action_id is None:
        return None
    action = catalog_action(action_id)
    assert action is not None
    normalized = normalize_step(dict(step))
    params = default_params(action)
    for spec in action.get("params", []):
        key = spec["key"]
        if key in normalized:
            params[key] = normalized[key]
    return {
        "catalog_id": action_id,
        "enabled": True,
        "params": params,
    }


def preset_steps_to_chain(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    for step in steps:
        item = chain_item_from_step(step)
        if item is not None:
            chain.append(item)
        else:
            chain.append(
                {
                    "catalog_id": None,
                    "enabled": True,
                    "params": {},
                    "raw_step": normalize_step(dict(step)),
                    "label": describe_step(normalize_step(dict(step))),
                }
            )
    return chain


def chain_to_steps(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for item in chain:
        if not item.get("enabled", True):
            continue
        if item.get("raw_step"):
            steps.append(dict(item["raw_step"]))
            continue
        catalog_id = item.get("catalog_id")
        if not catalog_id:
            continue
        steps.append(build_step(catalog_id, item.get("params") or {}))
    return steps
