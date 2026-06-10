"""Selección de skills sin IA por template matching.

Cada template en templates/skills/<categoria>/<nombre>.png tiene un ID
`categoria/nombre` y un puntaje en config/skills.json -> scores.
In-game se elige la carta con mayor puntaje (desempate: confianza del match).

Las cartas sin match confiable se guardan en templates/unknown_skills/.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from . import vision
from .configs import load_skills
from .log import get_logger
from .vision import TEMPLATES

log = get_logger("skills")

SKILLS_DIR = TEMPLATES / "skills"
UNKNOWN_DIR = TEMPLATES / "unknown_skills"


@dataclass
class SkillTemplate:
    skill_id: str
    category: str
    image: np.ndarray


@dataclass
class CardEval:
    index: int
    skill_id: str
    category: str
    confidence: float
    score: int
    tap_x: int
    tap_y: int
    card_image: np.ndarray | None = None


class SkillPicker:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_skills()
        self.threshold = float(self.config.get("match_threshold", 0.82))
        self.rank_order: list[str] = list(
            self.config.get("rank_order", ["dano", "atk_speed", "movilidad", "utilidad", "unknown"])
        )
        self.avoid: set[str] = set(self.config.get("avoid", []))
        self.selection_mode = str(self.config.get("selection_mode", "score")).lower()
        self.scores: dict[str, int] = {
            str(k): int(v) for k, v in self.config.get("scores", {}).items()
        }
        self.groups_map: dict[str, str] = {
            str(k): str(v) for k, v in self.config.get("groups_map", {}).items()
        }
        self.category_defaults: dict[str, int] = {
            str(k): int(v) for k, v in self.config.get("category_defaults", {}).items()
        }
        self._templates: list[SkillTemplate] = self._load_templates()

    def _load_templates(self) -> list[SkillTemplate]:
        loaded: list[SkillTemplate] = []
        if not SKILLS_DIR.exists():
            return loaded
        for cat_dir in sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir()):
            for tpl in cat_dir.glob("*.png"):
                img = cv2.imread(str(tpl))
                if img is not None:
                    loaded.append(SkillTemplate(f"{cat_dir.name}/{tpl.stem}", cat_dir.name, img))
        return loaded

    def score_for(self, skill_id: str, category: str) -> int:
        if skill_id in self.scores:
            return self.scores[skill_id]
        if category in self.category_defaults:
            return self.category_defaults[category]
        try:
            rank = self.rank_order.index(category)
            return max(0, 100 - rank * 20)
        except ValueError:
            return 0

    def classify(self, card: np.ndarray) -> tuple[str, str, float]:
        best = SkillTemplate("unknown", "unknown", card)
        best_conf = 0.0
        for tpl in self._templates:
            conf = vision.find_template(card, tpl.image, scales=vision.SKILL_SCALES).confidence
            if conf > best_conf:
                best_conf, best = conf, tpl
            if best_conf >= 0.95:
                break
        if best_conf >= self.threshold:
            return best.skill_id, best.category, best_conf
        if best_conf >= 0.5:
            return best.skill_id, best.category, best_conf
        return "unknown", "unknown", best_conf

    def _save_unknown(self, card: np.ndarray, index: int) -> None:
        try:
            UNKNOWN_DIR.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            cv2.imwrite(str(UNKNOWN_DIR / f"{stamp}_card{index}.png"), card)
            log.info("Skill no reconocida guardada para etiquetar (carta %d)", index)
        except Exception:  # noqa: BLE001
            pass

    def _rank(self, category: str) -> int:
        try:
            return self.rank_order.index(category)
        except ValueError:
            return len(self.rank_order)

    def detect_cards(self, screen: np.ndarray) -> list[vision.Region]:
        return vision.find_card_icons(screen)

    def evaluate(
        self,
        screen: np.ndarray,
        card_regions: list[vision.Region],
        *,
        catalog: bool = True,
        context: str = "play",
    ) -> list[CardEval]:
        from .skill_catalog import register_card

        evaluations: list[CardEval] = []
        for i, region in enumerate(card_regions):
            x, y, w, h = region
            card = vision.crop(screen, region)
            skill_id, category, confidence = self.classify(card)
            score = self.score_for(skill_id, category)
            evaluations.append(
                CardEval(i, skill_id, category, confidence, score, x + w // 2, y + h // 2, card)
            )
            if catalog:
                register_card(card, skill_id=skill_id, category=category, confidence=confidence, context=context)
            elif skill_id == "unknown":
                self._save_unknown(card, i)
            log.info(
                "Carta %d -> %s [%s] score=%d (conf=%.2f) @(%d,%d)",
                i,
                skill_id,
                category,
                score,
                confidence,
                x + w // 2,
                y + h // 2,
            )
        return evaluations

    def choose(
        self,
        screen: np.ndarray,
        fallback_regions: list[vision.Region] | None = None,
        *,
        catalog: bool = True,
        context: str = "play",
    ) -> CardEval:
        regions = self.detect_cards(screen)
        if len(regions) == 1:
            log.info("Detección dinámica halló 1 carta; reintento con banda amplia")
            regions = vision.find_card_icons(screen, band=(520, 920))
        if len(regions) < 2 and fallback_regions:
            use = fallback_regions if len(regions) == 0 else regions
            if len(regions) == 0:
                log.info("Detección dinámica halló %d cartas; uso regiones calibradas", len(regions))
                regions = use[:3]
            else:
                log.info("Detección dinámica halló %d carta(s)", len(regions))
        if not regions:
            raise ValueError("No se detectaron cartas de skill")
        evaluations = self.evaluate(screen, regions, catalog=catalog, context=context)
        non_avoid = [e for e in evaluations if e.category not in self.avoid]
        if not non_avoid:
            log.warning("Todas las cartas son de categoría a evitar; se elige la menos mala")
        pool = non_avoid or evaluations

        if self.selection_mode == "category":
            pool.sort(key=lambda e: (self._rank(e.category), -e.confidence))
        else:
            pool.sort(key=lambda e: (-e.score, self._rank(e.category), -e.confidence))

        chosen = pool[0]
        log.info(
            "Skill elegida: carta %d (%s score=%d)",
            chosen.index,
            chosen.skill_id,
            chosen.score,
        )
        return chosen
