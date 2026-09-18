#!/usr/bin/env python3
"""Residual fixups applied AFTER loom's migrateMappings.

WHY THIS FILE IS (AND SHOULD STAY) NEARLY EMPTY:
   loom 1.8's migrateMappings was validated byte-for-byte on the 1.21.1 port:
   for all 7 manifest files, the raw loom output equals the accepted final port
   (qol-port d20269c) EXACTLY -- including GuiMessage->ChatHudLine,
   ChatComponent->ChatHud, mixin @Mixin() targets, mixin method="..." strings
   (onGameMessage/onChatMessage/onProfilelessChatMessage/onOverlayMessage/
   onTitle/onSubtitle), ChunkPos.pack->ChunkPos.toLong, .pack()->.toLong(),
   .identifier()->.getValue(), etc. So loom is the single source of truth.

   Different TARGET branches pin different loom versions (1.8 for 1.21.1/1.21.4,
   1.10 for 1.21.5, 1.13 for 1.21.8/1.21.10, 1.14.9 for 1.21.11, 1.15+ for
   26.1.2). Each loom's migrateMappings is expected to cover the same core set
   (loom centers radically improved remapping coverage). Any residual that a
   specific loom version leaves is a BUG IN THAT BRANCH'S loom, not in our
   rules -- and the correct fix is to bump that branch's loom version, never to
   accumulate per-version textual rules.

   This file exists purely as a CONDITIONAL SAFETY NET:
     - Each rule fires ONLY when a raw mojmap token survives migration output.
     - Rules are keyed per-toolchain version, so if loom on some branch handles
       a token (or doesn't), the rule list for that branch is the ground truth
       during Phase 2.
     - `verify` mode is what the build gate actually runs: it greps migrated
       output for a DENYLIST of raw mojmap tokens that loom must have rewritten;
       if any survives, the sync FAILS (exit 3) instead of silently shipping a
       file that would fail `./gradlew build` at lint/compile time.

   Rule shape (see FIXUPS dict below):
       (old, new, is_regex)
   Tokens are only substituted if `old` is present (literal) / matches (regex),
   making application idempotent and no-op when the output is already correct.

   The DENYLIST is the important part; keep it minimal and mojmap-only so it
   never false-positives on legitimate yarn identifiers.
"""
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# -----------------------------------------------------------------------------
# DENYLIST: raw mojmap tokens that loom MUST have rewritten. If any survives in
# migrated output, phase-2 build gate aborts with exit 3 so we fix by bumping
# that branch's loom -- never by widening this list.
# -----------------------------------------------------------------------------
DENYLIST = [
    "net.minecraft.client.gui.components.ChatComponent",
    "net.minecraft.client.multiplayer.chat.GuiMessage",
    "GuiMessage",
    "@Mixin(mixin.GuiMessageHud.class)",
    "handleSystemChat",
    "handlePlayerChat",
    "handleDisguisedChat",
    "setActionBarText",
    "setTitleText",
    "setSubtitleText",
    "setOverlayText",
    "ChunkPos.pack(",
    ".pack()",
    ".identifier()",
    ".x()",
    ".z()",
    "getGameProfile().name()",
    "mc.world.getMinY()",
    "mc.world.getMaxY()",
    "mc.level.getMinY()",
    "mc.level.getMaxY()",
    "AttributeModifierSlot.ARMOR",
]

# Per-toolchain-version FIXUPS: version placeholder uses the compute key from
# gradle.properties (yarn_mappings for yarn targets, minecraft for mojmap).
FIXUPS: Dict[str, List[Tuple[str, str, bool]]] = {
    # Pre-1.21.4 yarn targets sometimes need the ARMOR loop unrolled when the
    # target's EquipmentSlotGroup lacks an iterable ARMOR constant. Phase 2
    # verifies per version and trims/adds as the build gate dictates.
    "1.21.1": [
        ("for (EquipmentSlot slot : AttributeModifierSlot.ARMOR)",
         "for (EquipmentSlot slot : new EquipmentSlot[] { EquipmentSlot.HEAD, EquipmentSlot.CHEST, EquipmentSlot.LEGS, EquipmentSlot.FEET })",
         False),
    ],
}
# mojmap targets: no fixups (loom not used; files copied as-is are already mojmap).
FIXUPS.setdefault("*", [])


def _apply_one(rule: Tuple[str, str, bool], text: str) -> Tuple[str, int]:
    old, new, is_regex = rule
    if is_regex:
        text2, n = re.subn(old, new, text)
    else:
        n = text.count(old)
        text2 = text.replace(old, new) if n else text
    return text2, n


def run_fixups(migrated_dir: Path, mc_version: str, cli_version: str) -> int:
    count = 0
    rules = FIXUPS.get(mc_version, []) or FIXUPS.get(cli_version, []) or FIXUPS["*"]
    for java in sorted(migrated_dir.rglob("*.java")):
        orig = java.read_text(encoding="utf-8")
        text = orig
        for rule in rules:
            text, n = _apply_one(rule, text)
            count += n
        if text != orig:
            java.write_text(text, encoding="utf-8")
            print(f"[fixups] {java.relative_to(migrated_dir)}: "
                  f"{count} replacements", file=sys.stderr)
    return count


def verify(migrated_dir: Path) -> int:
    """Gate: fail (exit 3) if a DENYLIST token survives migration output."""
    hits = []
    for java in sorted(migrated_dir.rglob("*.java")):
        text = java.read_text(encoding="utf-8")
        for bad in DENYLIST:
            if bad in text:
                hits.append((java.relative_to(migrated_dir).as_posix(), bad))
    if hits:
        for rel, bad in hits:
            print(f"[verify] FAIL: {rel} still contains mojmap token {bad!r}",
                  file=sys.stderr)
        print("[verify] loom did not fully remap this version; bump this "
              "branch's loom (not fixups.py)", file=sys.stderr)
        return 3
    return 0


def main() -> None:
    if len(sys.argv) != 4:
        print("usage: fixups.py <migrated_dir> <mc_version> "
              "<--fix|--verify>", file=sys.stderr)
        sys.exit(2)
    migrated_dir = Path(sys.argv[1])
    mc_version = sys.argv[2]
    mode = sys.argv[3]
    if mode == "--verify":
        sys.exit(verify(migrated_dir))
    else:
        run_fixups(migrated_dir, mc_version, mc_version)
        sys.exit(verify(migrated_dir))


if __name__ == "__main__":
    main()
