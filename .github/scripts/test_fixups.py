"""Regression tests for the automatic 26.2 -> 26.3 compatibility port."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest

import fixups


class SwingCompatibilityTests(unittest.TestCase):
    def test_both_hands_are_rewritten_and_idempotent(self):
        for hand in ("MAIN_HAND", "OFF_HAND"):
            with self.subTest(hand=hand), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                java = root / "Example.java"
                original = f"mc.player.swing(InteractionHand.{hand});"
                java.write_text(original, encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(fixups.verify(root, "26.3"), 3)
                    self.assertEqual(fixups.run_fixups(root, "26.3"), 1)
                    self.assertEqual(fixups.verify(root, "26.3"), 0)
                    self.assertEqual(fixups.run_fixups(root, "26.3"), 0)
                self.assertEqual(java.read_text(encoding="utf-8"),
                                 f"mc.player.swing(InteractionHand.{hand}, "
                                 f"mc.player.getItemInHand(InteractionHand.{hand})"
                                 ".getInteractAnimation(), false);")

    def test_base_and_older_mojmap_are_unchanged(self):
        for version in ("26.2", "26.1.2"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                java = root / "Example.java"
                original = "mc.player.swing(InteractionHand.MAIN_HAND);"
                java.write_text(original, encoding="utf-8")
                self.assertEqual(fixups.run_fixups(root, version), 0)
                self.assertEqual(java.read_text(encoding="utf-8"), original)

    def test_verify_ignores_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Example.java").write_text(
                "// mc.player.swing(InteractionHand.MAIN_HAND);\n"
                "/* mc.player.swing(InteractionHand.OFF_HAND); */\n",
                encoding="utf-8")
            self.assertEqual(fixups.verify(root, "26.3"), 0)


if __name__ == "__main__":
    unittest.main()
