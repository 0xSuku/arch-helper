"""Match skills_catalog against wiki icons and apply names, categories, groups."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.skill_catalog import CATALOG_DIR, MANIFEST_PATH, update_catalog_entry  # noqa: E402
from bot.skill_scores import set_group, update_skill_meta  # noqa: E402
from bot.skills import SKILLS_DIR  # noqa: E402

SKILLS_MD = ROOT / "uploads" / "Skills-0.md"

WIKI_CACHE = ROOT / "templates" / "wiki_icons"
MATCH_THRESHOLD = 0.72
APPLY_THRESHOLD = 0.76

# slug -> (category, group)
WIKI_META: dict[str, tuple[str, str]] = {
    "warriors_soul": ("dano", "main_weapon"),
    "power_trio": ("dano", "main_weapon"),
    "multishot": ("dano", "main_weapon"),
    "corrosive_field": ("dano", "planta"),
    "energy_beam": ("dano", "main_weapon"),
    "soul_of_strength": ("utilidad", ""),
    "sacred_protection": ("utilidad", ""),
    "sprite_king": ("dano", "sprite"),
    "super_meteor": ("dano", "meteoro"),
    "beam_strike": ("dano", "swords"),
    "circle_web": ("dano", "circulos"),
    "atk_increase": ("dano", "main_weapon"),
    "giants_strength": ("dano", "main_weapon"),
    "weapon_enchantment": ("dano", "main_weapon"),
    "soul_of_swiftness": ("atk_speed", "main_weapon"),
    "tracking_eye": ("utilidad", "main_weapon"),
    "diagonal_arrow": ("dano", "main_weapon"),
    "energy_ring": ("dano", "main_weapon"),
    "wall_piercing_arrow": ("dano", "main_weapon"),
    "wind_blessing": ("movilidad", ""),
    "water_walker": ("movilidad", ""),
    "slow_field": ("utilidad", ""),
    "revive": ("utilidad", ""),
    "super_blaze": ("dano", "elemental"),
    "super_bolt": ("dano", "elemental"),
    "super_venom": ("dano", "elemental"),
    "super_freeze": ("dano", "elemental"),
    "laser_sprite": ("dano", "sprite"),
    "sprite_frenzy": ("dano", "sprite"),
    "meteor_pursuit": ("dano", "meteoro"),
    "chain_meteors": ("dano", "meteoro"),
    "beam_circle": ("dano", "circulos"),
    "super_circle": ("dano", "circulos"),
    "magic_strike": ("dano", "swords"),
    "strike_boost": ("dano", "swords"),
    "twin_strike": ("dano", "swords"),
    "underworld_warrior": ("dano", "main_weapon"),
    "demon_slayer": ("dano", "main_weapon"),
    "warriors_heart": ("dano", "main_weapon"),
    "stand_strong": ("atk_speed", "main_weapon"),
    "short_range_strike": ("dano", "swords"),
    "perilous_fervor": ("dano", "main_weapon"),
    "lightwing_arrow": ("dano", "main_weapon"),
    "swift_arrow": ("atk_speed", "main_weapon"),
    "fairy_of_the_wind": ("atk_speed", "main_weapon"),
    "front_arrow": ("dano", "main_weapon"),
    "charged_arrow": ("dano", "main_weapon"),
    "piercing_arrow": ("dano", "main_weapon"),
    "split_shot": ("dano", "main_weapon"),
    "ricochet_arrow": ("dano", "main_weapon"),
    "lucky_band_aid": ("utilidad", ""),
    "lucky_cracker": ("utilidad", ""),
    "cloudfooted": ("movilidad", ""),
    "lucky_heart": ("utilidad", ""),
    "fountain_of_life": ("utilidad", ""),
    "heart_of_vitality": ("utilidad", ""),
    "angelic_shelter": ("utilidad", ""),
    "invincibility_potion": ("utilidad", ""),
    "abundant_potions": ("utilidad", ""),
    "blaze": ("dano", "elemental"),
    "bolt": ("dano", "elemental"),
    "venom": ("dano", "elemental"),
    "freeze": ("dano", "elemental"),
    "bomb_sprite": ("dano", "sprite"),
    "sprite_boost": ("dano", "sprite"),
    "circle_boost": ("dano", "circulos"),
    "blitz_strike": ("dano", "swords"),
    "instant_strike": ("dano", "swords"),
    "warriors_breath": ("dano", "main_weapon"),
    "fairys_breath": ("atk_speed", "main_weapon"),
    "breath_of_wind": ("movilidad", ""),
    "strength_blood": ("utilidad", ""),
    "restore_hp": ("utilidad", ""),
    "wounded_warrior": ("dano", "main_weapon"),
    "boss_slayer": ("utilidad", "main_weapon"),
    "long_range_power": ("dano", "main_weapon"),
    "frenzy_potion": ("atk_speed", ""),
    "bounce_arrow": ("dano", "main_weapon"),
    "rear_arrow": ("dano", "main_weapon"),
    "fiery_path": ("dano", "elemental"),
    "perilous_recovery": ("utilidad", ""),
    "demon_recovery": ("utilidad", ""),
    "flame_sprite": ("dano", "sprite"),
    "lightning_sprite": ("dano", "sprite"),
    "venom_sprite": ("dano", "sprite"),
    "ice_spike_sprite": ("dano", "sprite"),
    "demonslayer_meteor": ("dano", "meteoro"),
    "blaze_meteor_potion": ("dano", "meteoro"),
    "bolt_meteor_potion": ("dano", "meteoro"),
    "toxic_meteor_potion": ("dano", "meteoro"),
    "frost_meteor_potion": ("dano", "meteoro"),
    "fire_circle": ("dano", "circulos"),
    "bolt_circle": ("dano", "circulos"),
    "poison_circle": ("dano", "circulos"),
    "ice_circle": ("dano", "circulos"),
    "vampiric_circle": ("dano", "circulos"),
    "assault_strike": ("dano", "swords"),
    "blade_potion": ("dano", "swords"),
    "pursuit_strike": ("dano", "swords"),
    "riposte_strike": ("dano", "swords"),
    "plant_guardian": ("dano", "planta"),
    "vine_pursuit": ("dano", "planta"),
}

LEGACY_CAT = {"damage": "dano", "neutral": "utilidad", "damage_reduction": "utilidad"}


def slug(name: str) -> str:
    s = name.lower().replace("'", "").replace("-", "_")
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    aliases = {
        "diagonal_arrows": "diagonal_arrow",
        "cloud_footed": "cloudfooted",
        "rapid_fire": "multishot",
        "rapid_fire_meteors": "chain_meteors",
        "flying_sword_beam": "beam_strike",
        "rotating_web": "circle_web",
        "super_rotating_balls": "super_circle",
        "double_sword_shot": "twin_strike",
        "enchanted_swords": "magic_strike",
        "aqua_flight": "water_walker",
        "bane_of_bosses": "boss_slayer",
        "breath_of_the_wind": "breath_of_wind",
    }
    return aliases.get(s, s)


def parse_wiki_icons(md_text: str) -> dict[str, str]:
    pattern = re.compile(
        r"!\[([^\]]+\.png)\]\((https://img-archero-2\.game-vault\.net/[^)]+)\)([A-Za-z][^,\|\n\[]*)"
    )
    icons: dict[str, str] = {}
    for m in pattern.finditer(md_text):
        filename = m.group(1)
        url = m.group(2)
        name_part = m.group(3).strip()
        name = re.split(
            r"(ATK|Max HP|MOV|Multishot|Charge|Nearby|Your |Receive|Summon|Adds|Upon|Creates|Increases|Deals|Pick|Random|When|Standing|Projectiles|Backward|Chance|Cast|Get |Slow |Revive|Flame|Lightning|Poison|Ice |All |Doubles|Flying|Short|Perilous|Lucky|Cloud|Heart|Angel|Invinc|Abundant|Bomb|Sprite|Circle|Blitz|Instant|Warrior|Fairy|Breath|Strength|Restore|Wounded|Boss|Long|Frenzy|Bounce|Rear|Fiery|Demon|Blade|Pursuit|Riposte|Wall|Wind|Water|Giant|Weapon|Soul|Tracking|Energy|Super|Meteor|Chain|Beam|Twin|Underworld|Lightwing|Swift|Front|Charged|Piercing|Split|Ricochet|Fountain|Vampiric|Assault|Toxic|Frost|Bolt|Venom|Freeze|Blaze|Corrosive|Sacred|Power|Rapid|Rotating|Enchanted|Aqua|Slow|Magic|Strike|Laser)",
            name_part,
        )[0].strip()
        if not name:
            name = Path(filename).stem.replace("_", " ")
        key = slug(name if name else Path(filename).stem)
        if "/thumb/" in url:
            base = url.split("/thumb/")[-1].rsplit("/", 1)[0]
            full_url = f"https://img-archero-2.game-vault.net/{base}"
        else:
            full_url = url
        icons[key] = full_url
    return icons


def norm_icon(img: np.ndarray, size: int = 64) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(cv2.matchTemplate(norm_icon(a), norm_icon(b), cv2.TM_CCOEFF_NORMED)[0, 0])


def load_img(path: Path) -> np.ndarray | None:
    return cv2.imread(str(path))


def download_icon(key: str, url: str) -> Path | None:
    WIKI_CACHE.mkdir(parents=True, exist_ok=True)
    dest = WIKI_CACHE / f"{key}.png"
    if dest.exists():
        return dest
    try:
        r = requests.get(url, timeout=25)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return dest
    except Exception as exc:
        print(f"  skip download {key}: {exc}")
        return None


def migrate_template_dirs() -> None:
    if not SKILLS_DIR.exists():
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        return
    for old, new in LEGACY_CAT.items():
        src = SKILLS_DIR / old
        if not src.is_dir():
            continue
        dst = SKILLS_DIR / new
        dst.mkdir(parents=True, exist_ok=True)
        for tpl in src.glob("*.png"):
            target = dst / tpl.name
            if target.exists():
                continue
            shutil.move(str(tpl), str(target))
            print(f"  template {old}/{tpl.name} -> {new}/{tpl.name}")
        if not any(src.iterdir()):
            src.rmdir()


def build_references() -> dict[str, tuple[str, str, str, np.ndarray]]:
    refs: dict[str, tuple[str, str, str, np.ndarray]] = {}
    md = SKILLS_MD.read_text(encoding="utf-8", errors="replace")
    icons = parse_wiki_icons(md)
    print(f"Wiki icons parsed: {len(icons)}")
    for key, url in icons.items():
        path = download_icon(key, url)
        if path is None:
            continue
        img = load_img(path)
        if img is None:
            continue
        cat, grp = WIKI_META.get(key, ("unknown", ""))
        if cat == "unknown":
            continue
        refs[key] = (f"{cat}/{key}", cat, grp, img)

    for cat_dir in sorted(SKILLS_DIR.iterdir()):
        if not cat_dir.is_dir():
            continue
        for tpl in cat_dir.glob("*.png"):
            key = tpl.stem
            img = load_img(tpl)
            if img is None:
                continue
            cat = cat_dir.name
            grp = WIKI_META.get(key, (cat, ""))[1]
            refs[key] = (f"{cat}/{key}", cat, grp, img)
    return refs


def promote_template(fp: str, category: str, name: str) -> None:
    src = CATALOG_DIR / f"{fp}.png"
    if not src.exists():
        return
    dst_dir = SKILLS_DIR / category
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{name}.png"
    if dst.exists():
        return
    img = load_img(src)
    if img is not None:
        cv2.imwrite(str(dst), img)
        print(f"  template -> {dst.relative_to(ROOT)}")


def apply_label(fp: str, key: str, skill_id: str, category: str, group: str, score: float) -> None:
    name = skill_id.split("/", 1)[1]
    old_id = f"catalog/{fp}"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    current = manifest.get("entries", {}).get(fp, {})
    current_id = str(current.get("skill_id", old_id))
    if current_id.startswith("catalog/") or current.get("source") == "unlabeled":
        try:
            update_skill_meta(skill_id=old_id, name=name, category=category, group=group, catalog_fp=fp)
        except ValueError:
            update_catalog_entry(fp, skill_id=skill_id, category=category)
            if group:
                set_group(skill_id, group)
        promote_template(fp, category, name)
        print(f"  APPLIED {fp} -> {skill_id} [{category}/{group or '-'}] score={score:.3f}")
    elif group:
        set_group(current_id, group)
        print(f"  GROUP {current_id} -> {group}")


def match_labeled_catalog(img: np.ndarray, entries: dict) -> tuple[str, str, str, float] | None:
    best: tuple[str, str, str, float] | None = None
    for fp, meta in entries.items():
        skill_id = str(meta.get("skill_id", ""))
        if skill_id.startswith("catalog/") or skill_id.startswith("active/"):
            continue
        ref = load_img(CATALOG_DIR / f"{fp}.png")
        if ref is None:
            continue
        sc = similarity(img, ref)
        if sc >= 0.88 and (best is None or sc > best[3]):
            cat = skill_id.split("/", 1)[0]
            name = skill_id.split("/", 1)[1]
            grp = WIKI_META.get(name, (cat, ""))[1]
            best = (skill_id, cat, grp, sc)
    return best


def main() -> None:
    print("Migrating template folders...")
    migrate_template_dirs()

    refs = build_references()
    print(f"Reference icons: {len(refs)}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest.get("entries", {})

    targets = [
        fp for fp, meta in entries.items()
        if str(meta.get("skill_id", "")).startswith("catalog/")
        or str(meta.get("source", "")) == "unlabeled"
    ]
    print(f"Matching {len(targets)} unlabeled catalog entries...")

    applied = 0
    results: list[dict] = []
    for fp in sorted(targets):
        path = CATALOG_DIR / f"{fp}.png"
        img = load_img(path)
        if img is None:
            continue
        best_key = ""
        best_score = -1.0
        best_skill = ""
        best_cat = ""
        best_grp = ""
        for key, (skill_id, cat, grp, ref_img) in refs.items():
            sc = similarity(img, ref_img)
            if sc > best_score:
                best_score = sc
                best_key = key
                best_skill = skill_id
                best_cat = cat
                best_grp = grp
        results.append({
            "fp": fp,
            "wiki": best_key,
            "skill_id": best_skill,
            "category": best_cat,
            "group": best_grp,
            "score": round(best_score, 3),
        })
        print(f"{fp}: {best_key} -> {best_skill} score={best_score:.3f}")
        if best_score < APPLY_THRESHOLD:
            alt = match_labeled_catalog(img, entries)
            if alt is not None:
                best_skill, best_cat, best_grp, best_score = alt[0], alt[1], alt[2], alt[3]
                best_key = best_skill.split("/", 1)[1]
                print(f"  catalog match -> {best_skill} score={best_score:.3f}")
        if best_score >= APPLY_THRESHOLD and best_skill:
            apply_label(fp, best_key, best_skill, best_cat, best_grp, best_score)
            applied += 1

    for fp, meta in entries.items():
        skill_id = str(meta.get("skill_id", ""))
        if skill_id.startswith("catalog/") or skill_id.startswith("active/"):
            continue
        name = skill_id.split("/", 1)[1] if "/" in skill_id else skill_id
        if name in WIKI_META:
            cat, grp = WIKI_META[name]
            set_group(skill_id, grp)
            if meta.get("category") != cat:
                update_catalog_entry(fp, skill_id=skill_id, category=cat)

    scores_path = ROOT / "config" / "skills.json"
    skills_data = json.loads(scores_path.read_text(encoding="utf-8"))
    groups_map = dict(skills_data.get("groups_map", {}))
    for skill_id in skills_data.get("scores", {}):
        name = skill_id.split("/", 1)[1]
        if name in WIKI_META:
            _, grp = WIKI_META[name]
            if grp:
                groups_map[skill_id] = grp
    skills_data["groups_map"] = dict(sorted(groups_map.items()))
    scores_path.write_text(json.dumps(skills_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    out = ROOT / "scripts" / "wiki_match_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nApplied {applied} labels. Results -> {out}")


if __name__ == "__main__":
    main()
