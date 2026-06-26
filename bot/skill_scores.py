"""Skill scores and metadata (templates + catalog)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import cv2

from .configs import load_skills, save_skills
from .log import get_logger
from .skill_catalog import (
    CATALOG_DIR,
    delete_catalog_entry,
    find_catalog_fp,
    list_catalog_entries_full,
    list_catalog_fps_for_skill,
    list_pending_entries,
    merge_catalog_entry,
    update_catalog_entry,
)
from .skills import SKILLS_DIR, SkillPicker

log = get_logger("skill_scores")

SkillEntry = tuple[str, str, Path]  # skill_id, category, path

_NAME_RE = re.compile(r"^[\w\-]+$")

_LEGACY_PREFIXES = ("active/", "damage/", "neutral/", "damage_reduction/")


def discover_skills() -> list[SkillEntry]:
    found: list[SkillEntry] = []
    if not SKILLS_DIR.exists():
        return found
    for cat_dir in sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir()):
        for tpl in sorted(cat_dir.glob("*.png")):
            skill_id = f"{cat_dir.name}/{tpl.stem}"
            found.append((skill_id, cat_dir.name, tpl))
    return found


def valid_categories(config: dict[str, Any] | None = None) -> list[str]:
    cfg = config or load_skills()
    return list(cfg.get("categories", ["dano", "utilidad", "movilidad", "atk_speed"]))


def valid_groups(config: dict[str, Any] | None = None) -> list[str]:
    cfg = config or load_skills()
    return list(cfg.get("groups", []))


def category_labels(config: dict[str, Any] | None = None) -> dict[str, str]:
    cfg = config or load_skills()
    labels = dict(cfg.get("category_labels", {}))
    for cat in valid_categories(cfg):
        labels.setdefault(cat, cat)
    return labels


def group_labels(config: dict[str, Any] | None = None) -> dict[str, str]:
    cfg = config or load_skills()
    labels = dict(cfg.get("group_labels", {}))
    for grp in valid_groups(cfg):
        labels.setdefault(grp, grp)
    return labels


def _normalize_name(name: str) -> str:
    clean = name.strip().replace(" ", "_")
    if not clean or not _NAME_RE.match(clean):
        raise ValueError(f"Invalid name: {name!r} (use letters, numbers, _ or -)")
    return clean


def resolve_skill_id(query: str) -> str:
    query = query.strip().replace("\\", "/")
    if query.startswith("catalog/"):
        return query
    if "/" not in query:
        query = f"*/{query}"
    entries = discover_skills()
    if query.startswith("*/"):
        stem = query[2:]
        matches = [sid for sid, _, _ in entries if sid.split("/", 1)[1] == stem]
    else:
        matches = [sid for sid, _, _ in entries if sid == query]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"Skill not found: {query!r}. Use 'skills list' to see IDs.")
    raise ValueError(f"Ambiguous ID {query!r}: {', '.join(matches)}")


def get_scores(config: dict[str, Any] | None = None) -> dict[str, int]:
    cfg = config or load_skills()
    raw = cfg.get("scores", {})
    return {str(k): int(v) for k, v in raw.items()}


def get_groups_map(config: dict[str, Any] | None = None) -> dict[str, str]:
    cfg = config or load_skills()
    raw = cfg.get("groups_map", {})
    return {str(k): str(v) for k, v in raw.items()}


def group_for(skill_id: str, config: dict[str, Any] | None = None) -> str:
    return get_groups_map(config).get(skill_id, "")


def set_score(skill_id: str, score: int, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or load_skills())
    scores = dict(cfg.get("scores", {}))
    scores[skill_id] = int(score)
    cfg["scores"] = scores
    save_skills(cfg)
    return cfg


def set_group(skill_id: str, group: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    # Always read from disk: set_score may have just saved.
    cfg = load_skills()
    groups_map = dict(cfg.get("groups_map", {}))
    grp = group.strip()
    if grp and grp not in valid_groups(cfg):
        raise ValueError(f"Invalid group: {grp!r}")
    if grp:
        groups_map[skill_id] = grp
    else:
        groups_map.pop(skill_id, None)
    cfg["groups_map"] = groups_map
    save_skills(cfg)
    return cfg


def bump_score(skill_id: str, delta: int = 1, config: dict[str, Any] | None = None) -> int:
    cfg = config or load_skills()
    scores = get_scores(cfg)
    picker = SkillPicker(cfg)
    category = skill_id.split("/", 1)[0]
    current = scores.get(skill_id, picker.score_for(skill_id, category))
    new_score = current + int(delta)
    set_score(skill_id, new_score, cfg)
    return new_score


def _migrate_score(old_id: str, new_id: str, config: dict[str, Any]) -> None:
    if old_id == new_id:
        return
    scores = dict(config.get("scores", {}))
    if old_id in scores:
        scores[new_id] = scores.pop(old_id)
        config["scores"] = scores
    groups_map = dict(config.get("groups_map", {}))
    if old_id in groups_map:
        groups_map[new_id] = groups_map.pop(old_id)
        config["groups_map"] = groups_map


def promote_catalog_template(fp: str, category: str, name: str) -> bool:
    """Copy catalog icon to templates/skills/ for in-game matching."""
    src = CATALOG_DIR / f"{fp}.png"
    if not src.exists():
        log.warning("Catalog has no PNG to promote: %s", fp)
        return False
    dst = SKILLS_DIR / category / f"{name}.png"
    if dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = cv2.imread(str(src))
    if img is None:
        log.warning("Could not read catalog PNG: %s", src)
        return False
    cv2.imwrite(str(dst), img)
    log.info("Template promovido: %s -> %s", fp, dst.relative_to(SKILLS_DIR.parent))
    return True


def _rename_template(old_id: str, new_id: str) -> None:
    old_path: Path | None = None
    for skill_id, _, path in discover_skills():
        if skill_id == old_id:
            old_path = path
            break
    if old_path is None:
        return
    category, name = new_id.split("/", 1)
    new_path = SKILLS_DIR / category / f"{name}.png"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    if new_path.resolve() == old_path.resolve():
        return
    if new_path.exists():
        raise ValueError(f"Template already exists: {new_id}")
    old_path.rename(new_path)


def _is_legacy_active(skill_id: str) -> bool:
    return skill_id.startswith("active/")


def _assert_unique_skill_id(new_id: str, old_id: str, catalog_fp: str | None) -> None:
    category, name = new_id.split("/", 1)
    template_path = SKILLS_DIR / category / f"{name}.png"
    if template_path.exists() and old_id != new_id:
        raise ValueError(f"Duplicate skill already exists: {new_id}")
    for fp, skill_id, _category, _source, _conf in list_catalog_entries_full():
        if fp == catalog_fp:
            continue
        if skill_id == new_id:
            raise ValueError(f"Duplicate skill already exists in catalog: {new_id}")


def _catalog_images_map() -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for fp, skill_id, _category, source, _conf in list_catalog_entries_full():
        grouped.setdefault(skill_id, []).append({
            "fp": fp,
            "image_url": f"/api/skills/catalog-image?fp={fp}",
            "source": source,
        })
    return grouped


def merge_skill_image(fp: str, target_skill_id: str) -> dict[str, Any]:
    target = target_skill_id.strip()
    if "/" not in target or target.startswith("catalog/"):
        raise ValueError("Pick a labeled skill (category/name)")
    category = target.split("/", 1)[0]
    cats = valid_categories()
    if category not in cats:
        raise ValueError(f"Invalid category in target: {category!r}")
    merge_catalog_entry(fp, skill_id=target, category=category)
    stem = target.split("/", 1)[1]
    promote_catalog_template(fp, category, stem)
    return {"id": target, "fp": fp, "category": category}


def delete_skill_image(*, skill_id: str, catalog_fp: str | None = None) -> dict[str, Any]:
    sid = skill_id.strip()
    if catalog_fp:
        if not delete_catalog_entry(catalog_fp):
            raise ValueError(f"Catalog entry not found: {catalog_fp}")
        has_template = any(s == sid for s, _, _ in discover_skills())
        has_catalog = bool(list_catalog_fps_for_skill(sid))
        if not has_template and not has_catalog:
            cfg = load_skills()
            scores = dict(cfg.get("scores", {}))
            if sid in scores:
                scores.pop(sid)
                cfg["scores"] = scores
            groups_map = dict(cfg.get("groups_map", {}))
            if sid in groups_map:
                groups_map.pop(sid)
                cfg["groups_map"] = groups_map
            save_skills(cfg)
        return {"deleted": "catalog", "id": sid, "fp": catalog_fp}

    removed_template = False
    for entry_id, _category, path in discover_skills():
        if entry_id == sid:
            path.unlink()
            removed_template = True
            break
    if not removed_template:
        raise ValueError(f"Skill template not found: {sid}")
    cfg = load_skills()
    scores = dict(cfg.get("scores", {}))
    scores.pop(sid, None)
    groups_map = dict(cfg.get("groups_map", {}))
    groups_map.pop(sid, None)
    cfg["scores"] = scores
    cfg["groups_map"] = groups_map
    save_skills(cfg)
    return {"deleted": "template", "id": sid}


def update_skill_meta(
    *,
    skill_id: str,
    name: str,
    category: str,
    group: str = "",
    score: int | None = None,
    catalog_fp: str | None = None,
) -> dict[str, Any]:
    cfg = dict(load_skills())
    cats = valid_categories(cfg)
    cat = category.strip()
    if cat not in cats:
        raise ValueError(f"Invalid category: {cat!r}. Valid: {', '.join(cats)}")
    stem = _normalize_name(name)
    new_id = f"{cat}/{stem}"
    old_id = skill_id.strip()
    if _is_legacy_active(old_id):
        raise ValueError("active/* entries were removed; rename as a normal skill")

    fp = catalog_fp or find_catalog_fp(old_id)
    _assert_unique_skill_id(new_id, old_id, fp)
    if fp or old_id.startswith("catalog/"):
        if not fp:
            fp = old_id.removeprefix("catalog/")
        update_catalog_entry(fp, skill_id=new_id, category=cat)
        promote_catalog_template(fp, cat, stem)
    else:
        try:
            resolved = resolve_skill_id(old_id)
        except ValueError:
            resolved = old_id
        _rename_template(resolved, new_id)

    _migrate_score(old_id, new_id, cfg)
    if score is not None:
        cfg = set_score(new_id, int(score), cfg)
    elif old_id != new_id:
        save_skills(cfg)
    cfg = set_group(new_id, group.strip(), cfg)
    return {"id": new_id, "category": cat, "group": group_for(new_id, cfg), "name": stem}


def list_skill_rows(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = config or load_skills()
    picker = SkillPicker(cfg)
    groups_map = get_groups_map(cfg)
    catalog_images = _catalog_images_map()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    scored_ids = set(get_scores(cfg))

    def append_row(
        skill_id: str,
        category: str,
        source: str,
        catalog_fp: str | None,
        entry_type: str,
    ) -> None:
        if _is_legacy_active(skill_id) or skill_id in seen:
            return
        name = skill_id.split("/", 1)[1] if "/" in skill_id else skill_id
        images = catalog_images.get(skill_id, [])
        if catalog_fp and not any(img["fp"] == catalog_fp for img in images):
            images = [{"fp": catalog_fp, "image_url": f"/api/skills/catalog-image?fp={catalog_fp}", "source": source}, *images]
        rows.append({
            "id": skill_id,
            "name": name,
            "category": category,
            "group": groups_map.get(skill_id, ""),
            "score": picker.score_for(skill_id, category),
            "source": source,
            "catalog_fp": catalog_fp,
            "catalog_images": images,
            "entry_type": entry_type,
        })
        seen.add(skill_id)

    for skill_id, category, _path in discover_skills():
        source = "manual" if skill_id in scored_ids else "template"
        append_row(skill_id, category, source, None, "template")

    for fp, skill_id, category, cat_source, _conf in list_catalog_entries_full():
        source = "manual" if skill_id in scored_ids else cat_source
        append_row(skill_id, category, source, fp, "catalog")

    for skill_id in sorted(scored_ids - seen):
        category = skill_id.split("/", 1)[0]
        append_row(
            skill_id,
            category,
            "manual (no template)",
            find_catalog_fp(skill_id),
            "manual",
        )

    rows.sort(key=lambda r: (-int(r["score"]), str(r["id"])))
    return rows


def list_pending_skill_rows(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = config or load_skills()
    picker = SkillPicker(cfg)
    rows: list[dict[str, Any]] = []
    for entry in list_pending_entries():
        category = str(entry.get("category", "unknown"))
        skill_id = str(entry.get("id", f"catalog/{entry['fp']}"))
        rows.append({
            "id": skill_id,
            "name": skill_id.split("/", 1)[1] if "/" in skill_id else skill_id,
            "category": category,
            "group": "",
            "score": picker.scores.get(skill_id, 0),
            "source": entry.get("source", "unlabeled"),
            "catalog_fp": entry["fp"],
            "entry_type": "pending_catalog",
            "image_url": f"/api/skills/catalog-image?fp={entry['fp']}",
            "seen_count": int(entry.get("seen_count", 1)),
            "best_confidence": float(entry.get("best_confidence", entry.get("confidence", 0.0))),
            "last_confidence": float(entry.get("last_confidence", entry.get("confidence", 0.0))),
            "last_seen_at": entry.get("last_seen_at", ""),
            "source_context": entry.get("source_context", ""),
        })
    return rows


def format_skill_table(rows: list[dict[str, Any]] | list[tuple[str, str, int, str]]) -> str:
    if not rows:
        return "No skills in templates/skills/. Crop icons with calibrate --crop."
    if isinstance(rows[0], dict):
        tuples = [
            (r["id"], r["category"], r.get("group", ""), r["score"], r["source"])
            for r in rows
        ]  # type: ignore[index]
    else:
        tuples = [(t[0], t[1], "", t[2], t[3]) for t in rows]  # type: ignore[assignment]
    lines = [f"{'SCORE':>5}  {'SKILL ID':<28} {'CAT':<12} {'GROUP':<14} SRC", "-" * 78]
    for skill_id, category, group, score, source in tuples:
        lines.append(f"{score:>5}  {skill_id:<28} {category:<12} {group or '-':<14} {source}")
    return "\n".join(lines)
