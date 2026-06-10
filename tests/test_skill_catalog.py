from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from bot import skill_catalog
from bot import skill_scores


def _card(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(64, 64, 3), dtype=np.uint8)


class SkillCatalogTests(unittest.TestCase):
    def test_register_unknown_tracks_pending_metadata_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_dir = root / "catalog"
            manifest = root / "skills-catalog.json"
            card = _card(7)

            with patch.object(skill_catalog, "CATALOG_DIR", catalog_dir), patch.object(
                skill_catalog, "MANIFEST_PATH", manifest
            ):
                catalog_id1, is_new1 = skill_catalog.register_card(
                    card,
                    skill_id="unknown",
                    category="unknown",
                    confidence=0.21,
                    context="farm",
                )
                catalog_id2, is_new2 = skill_catalog.register_card(
                    card,
                    skill_id="unknown",
                    category="unknown",
                    confidence=0.33,
                    context="farm",
                )

                data = json.loads(manifest.read_text(encoding="utf-8"))
                entries = data["entries"]

            fp = catalog_id1.removeprefix("catalog/")
            self.assertEqual(catalog_id1, catalog_id2)
            self.assertTrue(is_new1)
            self.assertFalse(is_new2)
            self.assertEqual(len(list(catalog_dir.glob("*.png"))), 1)
            self.assertEqual(entries[fp]["seen_count"], 2)
            self.assertTrue(entries[fp]["needs_label"])
            self.assertEqual(entries[fp]["source"], "unlabeled")
            self.assertEqual(entries[fp]["source_context"], "farm")
            self.assertEqual(entries[fp]["confidence"], 0.33)

    def test_pending_catalog_entries_only_include_unlabeled_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "skills-catalog.json"
            manifest.write_text(
                json.dumps(
                    {
                        "entries": {
                            "aaa": {
                                "file": "aaa.png",
                                "skill_id": "catalog/aaa",
                                "category": "unknown",
                                "source": "unlabeled",
                                "needs_label": True,
                                "seen_count": 3,
                            },
                            "bbb": {
                                "file": "bbb.png",
                                "skill_id": "dano/bolt",
                                "category": "dano",
                                "source": "labeled",
                                "needs_label": False,
                                "seen_count": 1,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(skill_catalog, "MANIFEST_PATH", manifest):
                pending = skill_catalog.list_pending_entries()

            self.assertEqual([row["fp"] for row in pending], ["aaa"])
            self.assertEqual(pending[0]["seen_count"], 3)

    def test_labeled_catalog_entry_is_not_reopened_as_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_dir = root / "catalog"
            manifest = root / "skills-catalog.json"
            card = _card(11)

            with patch.object(skill_catalog, "CATALOG_DIR", catalog_dir), patch.object(
                skill_catalog, "MANIFEST_PATH", manifest
            ):
                skill_catalog.register_card(
                    card,
                    skill_id="dano/bolt",
                    category="dano",
                    confidence=0.91,
                )
                skill_catalog.register_card(
                    card,
                    skill_id="unknown",
                    category="unknown",
                    confidence=0.15,
                    context="farm",
                )
                pending = skill_catalog.list_pending_entries()
                data = json.loads(manifest.read_text(encoding="utf-8"))
                fp = next(iter(data["entries"]))

            self.assertEqual(pending, [])
            self.assertEqual(data["entries"][fp]["skill_id"], "dano/bolt")
            self.assertFalse(data["entries"][fp]["needs_label"])

    def test_update_skill_meta_rejects_duplicate_catalog_skill_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_dir = root / "catalog"
            skills_dir = root / "skills"
            manifest = root / "skills-catalog.json"
            config = {
                "categories": ["dano", "utilidad"],
                "groups": [],
                "scores": {},
                "groups_map": {},
            }
            manifest.write_text(
                json.dumps(
                    {
                        "entries": {
                            "aaa": {
                                "file": "aaa.png",
                                "skill_id": "dano/bolt",
                                "category": "dano",
                                "source": "labeled",
                                "needs_label": False,
                            },
                            "bbb": {
                                "file": "bbb.png",
                                "skill_id": "catalog/bbb",
                                "category": "unknown",
                                "source": "unlabeled",
                                "needs_label": True,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            catalog_dir.mkdir()
            (catalog_dir / "bbb.png").write_bytes(b"not-an-image")

            with patch.object(skill_catalog, "MANIFEST_PATH", manifest), patch.object(
                skill_catalog, "CATALOG_DIR", catalog_dir
            ), patch.object(skill_scores, "CATALOG_DIR", catalog_dir), patch.object(
                skill_scores, "SKILLS_DIR", skills_dir
            ), patch.object(
                skill_scores, "load_skills", return_value=config
            ), patch.object(
                skill_scores, "save_skills", lambda _cfg: None
            ):
                with self.assertRaisesRegex(ValueError, "duplicada|Ya existe"):
                    skill_scores.update_skill_meta(
                        skill_id="catalog/bbb",
                        name="bolt",
                        category="dano",
                        score=80,
                        catalog_fp="bbb",
                    )

    def test_pending_skill_rows_include_image_url_and_review_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "skills-catalog.json"
            manifest.write_text(
                json.dumps(
                    {
                        "entries": {
                            "aaa": {
                                "file": "aaa.png",
                                "skill_id": "catalog/aaa",
                                "category": "unknown",
                                "source": "unlabeled",
                                "needs_label": True,
                                "seen_count": 4,
                                "best_confidence": 0.42,
                                "last_seen_at": "2026-06-10T04:00:00",
                                "source_context": "farm",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "categories": ["dano", "utilidad"],
                "groups": ["boss"],
                "scores": {},
                "groups_map": {},
            }

            with patch.object(skill_catalog, "MANIFEST_PATH", manifest), patch.object(
                skill_scores, "load_skills", return_value=config
            ):
                rows = skill_scores.list_pending_skill_rows()

            self.assertEqual(rows[0]["id"], "catalog/aaa")
            self.assertEqual(rows[0]["catalog_fp"], "aaa")
            self.assertEqual(rows[0]["image_url"], "/api/skills/catalog-image?fp=aaa")
            self.assertEqual(rows[0]["score"], 0)
            self.assertEqual(rows[0]["seen_count"], 4)
            self.assertEqual(rows[0]["source_context"], "farm")


if __name__ == "__main__":
    unittest.main()
