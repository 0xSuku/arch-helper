from __future__ import annotations

import unittest

import cv2
import numpy as np

from bot.run_end_dismiss import _item_detail_close_point, is_item_detail_popup, is_post_run_overlay


class RunEndDismissTests(unittest.TestCase):
    def test_item_detail_popup_counts_as_post_run_overlay(self) -> None:
        screen = np.zeros((1600, 900, 3), dtype=np.uint8)
        # Beige/orange item detail modal with a strong close button area.
        screen[180:1190, 30:870] = (170, 205, 235)
        screen[300:1130, 60:840] = (185, 220, 245)
        screen[190:330, 730:850] = (35, 120, 210)

        self.assertTrue(is_item_detail_popup(screen))
        self.assertTrue(is_post_run_overlay(screen))

    def test_item_detail_close_point_uses_actual_orange_x(self) -> None:
        screen = np.zeros((1600, 900, 3), dtype=np.uint8)
        cv2.circle(screen, (810, 257), 42, (25, 125, 220), -1)

        x, y = _item_detail_close_point(screen)

        self.assertTrue(790 <= x <= 830)
        self.assertTrue(235 <= y <= 280)

    def test_combat_field_roulette_is_not_item_detail_popup(self) -> None:
        screen = np.zeros((1600, 900, 3), dtype=np.uint8)
        screen[:, :] = (170, 150, 70)
        cv2.rectangle(screen, (115, 95), (785, 140), (45, 35, 25), -1)
        cv2.circle(screen, (45, 105), 42, (45, 35, 25), -1)
        cv2.circle(screen, (790, 450), 90, (40, 95, 185), -1)
        cv2.circle(screen, (790, 450), 60, (45, 170, 245), -1)
        cv2.circle(screen, (825, 455), 16, (40, 60, 220), -1)
        cv2.circle(screen, (820, 1510), 75, (40, 95, 220), -1)

        self.assertFalse(is_item_detail_popup(screen))
        self.assertFalse(is_post_run_overlay(screen))


if __name__ == "__main__":
    unittest.main()
