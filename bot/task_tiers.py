"""Agrupación de tareas del panel por nivel de confianza."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .device import ROOT
from .paths.daily import EXTRA_CLAIMS, MAIN_LOOP_ORDER

MANIFEST_PATH = ROOT / "config" / "daily-claims.json"

DEFAULT_TIERS: dict[str, dict[str, str]] = {
    "trusted": {
        "label": "Confiables",
        "hint": "Probados en MuMu — podés usarlos sin drama",
    },
    "candidate": {
        "label": "Por validar",
        "hint": "Implementados, pero todavía no los confirmamos a fondo",
    },
    "paused": {
        "label": "En pausa",
        "hint": "Evitar por ahora — rotos, incompletos o loop muy largo",
    },
}

DEFAULT_TIER_ORDER = ("trusted", "candidate", "paused")

DEFAULT_PANEL_TASKS: dict[str, dict[str, Any]] = {
    "farm": {"label": "Farm energía", "tier": "trusted", "job": "farm"},
    "farm_forever": {"label": "Farm infinito", "tier": "trusted", "job": "farm_forever"},
    "play": {"label": "Play N partidas", "tier": "candidate", "job": "play", "needs_games": True},
    "daily_main": {"label": "Loop principal daily", "tier": "paused", "job": "daily_main"},
}

DEFAULT_CLAIM_TIERS: dict[str, str] = {
    "shackled_jungle": "trusted",
    "abyssal_tide": "candidate",
    "popups": "candidate",
    "shop": "candidate",
    "gold_cave": "trusted",
    "guild": "candidate",
    "hunt": "candidate",
    "great_value": "candidate",
    "privilege": "candidate",
    "messages": "candidate",
    "sidebar_events": "candidate",
    "island_treasure": "candidate",
    "angler_bounty": "candidate",
    "campaign_rout": "candidate",
    "friends": "candidate",
    "events": "paused",
    "daily_main": "paused",
    "task_center": "paused",
    "camp": "paused",
    "trophy": "paused",
}


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def tier_meta(data: dict[str, Any] | None = None) -> tuple[dict[str, dict[str, str]], tuple[str, ...]]:
    raw = dict(data or _load_manifest())
    tiers = dict(DEFAULT_TIERS)
    tiers.update(raw.get("tiers") or {})
    order = tuple(raw.get("tier_order") or DEFAULT_TIER_ORDER)
    return tiers, order


def _claim_tier(claim_id: str, claim: dict[str, Any]) -> str:
    tier = str(claim.get("tier") or DEFAULT_CLAIM_TIERS.get(claim_id) or "candidate")
    if tier not in DEFAULT_TIERS:
        return "candidate"
    return tier


def list_panel_items() -> list[dict[str, Any]]:
    raw = _load_manifest()
    tiers, _ = tier_meta(raw)
    items: list[dict[str, Any]] = []

    panel_tasks = dict(DEFAULT_PANEL_TASKS)
    panel_tasks.update(raw.get("panel_tasks") or {})
    for task_id, meta in panel_tasks.items():
        if not isinstance(meta, dict):
            continue
        tier = str(meta.get("tier") or "candidate")
        if tier not in tiers:
            tier = "candidate"
        items.append({
            "id": task_id,
            "label": str(meta.get("label") or task_id.replace("_", " ")),
            "tier": tier,
            "job": str(meta.get("job") or task_id),
            "kind": "task",
            "main_loop": False,
            "needs_games": bool(meta.get("needs_games")),
        })

    claims_cfg = raw.get("claims") or {}
    main = set(MAIN_LOOP_ORDER)
    for claim_id in MAIN_LOOP_ORDER + EXTRA_CLAIMS:
        claim = claims_cfg.get(claim_id) if isinstance(claims_cfg.get(claim_id), dict) else {}
        name = str((claim or {}).get("name") or claim_id.replace("_", " "))
        items.append({
            "id": claim_id,
            "label": name,
            "tier": _claim_tier(claim_id, claim or {}),
            "job": f"daily:{claim_id}",
            "kind": "claim",
            "main_loop": claim_id in main,
        })

    return items


def grouped_panel_items() -> dict[str, Any]:
    raw = _load_manifest()
    tiers, order = tier_meta(raw)
    items = list_panel_items()
    groups: list[dict[str, Any]] = []
    for tier_id in order:
        meta = tiers.get(tier_id) or {"label": tier_id, "hint": ""}
        group_items = [it for it in items if it["tier"] == tier_id]
        groups.append({
            "id": tier_id,
            "label": meta.get("label", tier_id),
            "hint": meta.get("hint", ""),
            "items": group_items,
        })
    return {"tiers": tiers, "tier_order": list(order), "groups": groups}
