#!/usr/bin/env python3
"""Residual fixups applied AFTER loom's migrateMappings.

WHY THIS FILE IS SMALL:
   loom's migrateMappings converts the *mapping namespace* of the project for a
   single minecraft version. Because the synced src tree is, apart from mapping
   names, identical on 26.2 and the yarn branches (proven by the accepted
   ports), loom's mojmap->yarn pass on the TARGET version covers almost
   everything. loom 1.8 leaves a small, fully enumerated residual set (mixin
   @Inject method= strings, a few accessor renames, AttributeModifierSlot.
   ARMOR, GuiMessage->ChatHudLine). Validated 2026-09-18: migrate + these
   rules reproduces the accepted ports byte-for-byte.

   Newer loom (1.10/1.13/1.14/1.15+) remaps most of the residual set itself
   (1.13+ adds MixinRemapper for method= strings). Every rule is therefore an
   IDEMPOTENT NO-OP when the target text is already present, so the common
   rule set is safe to share: rules only fire on mojmap leftovers.

YARN VERSION SLICES (cross-VERSION drift -- loom cannot translate these even
   in principle, because the names never existed in the target's mappings):
     1.21.1   : isFallFlying(), World.getTopY(), getBottomY(),
                PlayerInventory.selectedSlot FIELD, GameProfile.getName()
     1.21.4   : isGliding(), HeightLimitView.getTopYInclusive(), getBottomY(),
                selectedSlot FIELD, GameProfile.getName()
     1.21.5/8 : isGliding(), getTopYInclusive(), getBottomY(),
                PlayerInventory.getSelectedSlot() METHOD, GameProfile.getName()
     1.21.10+ : isGliding(), getTopYInclusive(), getBottomY(),
                getSelectedSlot() METHOD, GameProfile.name FIELD
   FIXUPS keyed by minecraft version; "*" = the 1.21.10/11 slice.
   Ground truth: 1.21.1 validated byte-for-byte vs the accepted port; the
   boundaries verified against the 1.21.4 yarn tiny + every branch's own code,
   and arbitrated further by the ./gradlew build gate each target runs.

   `--verify` is the gate the build runs: if ANY raw mojmap token from
   DENYLIST (plus the generation's EXTRA_DENYLIST) survives in the migrated
   CODE, the sync FAILS (exit 3). Comments are stripped before scanning (the
   accepted 1.21.1 port itself carries a doc comment naming handleSystemChat/
   ... -- documenting the 6b6t bypass -- so comments are exempt by ground
   truth). Fix by bumping THAT branch's loom version -- never by widening
   these rules to swallow mojmap output.
"""
import re
import sys
from pathlib import Path
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Denylist for `verify` (code-only scan -- comments are stripped; the accepted
# 1.21.1 port documents mojmap names in a comment, so comments are exempt).
# EXTRA_DENYLIST adds generation-specific bans:
#   1.21.4+ (modern yarn): isFallFlying and the no-arg getTopY() do NOT exist;
#     surviving them in code means the port is wrong.
# ---------------------------------------------------------------------------
DENYLIST = [
    "net.minecraft.client.gui.components.ChatComponent",
    "net.minecraft.client.multiplayer.chat.GuiMessage",
    "net.minecraft.client.multiplayer.ClientPacketListener",
    "GuiMessage",
    "handleSystemChat",
    "handlePlayerChat",
    "handleDisguisedChat",
    "setActionBarText",
    "setTitleText",
    "setSubtitleText",
    "ChunkPos.pack(",
    ".pack()",
    ".identifier()",
    ".x()",
    ".z()",
    "mc.world.getMinY()",
    "mc.world.getMaxY()",
    "mc.level.getMinY()",
    "mc.level.getMaxY()",
    "AttributeModifierSlot.ARMOR",
]

EXTRA_DENYLIST: dict = {
    # legacy yarn (1.21.1): getSelectedSlot() is gone (field is the API);
    # GameProfile must use the getName() getter. isFallFlying/getTopY are
    # CORRECT here -- never banned.
    "1.21.1": ["getSelectedSlot()", "getGameProfile().name()"],
    # hybrid (1.21.4)/mid (1.21.5, 1.21.8): isFallFlying and no-arg getTopY()
    # are gone; getName() getter is the API; slot is still the field on 1.21.4
    "1.21.4": ["getSelectedSlot()", "getGameProfile().name()", "isFallFlying", "getTopY()"],
    "1.21.5": ["getGameProfile().name()", "isFallFlying", "getTopY()"],
    "1.21.8": ["getGameProfile().name()", "isFallFlying", "getTopY()"],
    # late yarn (1.21.10+): GameProfile.name is a FIELD again -- .name() is
    # CORRECT here and must NOT be banned; getSelectedSlot() method is the API
    "*": ["isFallFlying", "getTopY()"],
}

# ---------------------------------------------------------------------------
# Rules: (old, new, is_regex). Ordered; idempotent (fires only when present).
# Shared cross-generation rules were validated byte-for-byte against the
# accepted 1.21.1 port (loom 1.8 + these rules == deployed files).
# ---------------------------------------------------------------------------
COMMON_YARN_RULES: List[Tuple[str, str, bool]] = [
    # mixin @Inject method= strings (quotes bound -> comments untouched)
    ('method = "handleSystemChat"', 'method = "onGameMessage"', False),
    ('method = "handlePlayerChat"', 'method = "onChatMessage"', False),
    ('method = "handleDisguisedChat"', 'method = "onProfilelessChatMessage"', False),
    ('method = "setActionBarText"', 'method = "onOverlayMessage"', False),
    ('method = "setTitleText"', 'method = "onTitle"', False),
    ('method = "setSubtitleText"', 'method = "onSubtitle"', False),
    # ChatComponent mixin chat line type (loom 1.8 leaves the import+param)
    ("net.minecraft.client.multiplayer.chat.GuiMessage",
     "net.minecraft.client.gui.hud.ChatHudLine", False),
    ("GuiMessage guiMessage", "ChatHudLine chatHudLine", False),
    ("guiMessage.content()", "chatHudLine.content()", False),
    # ChunkPos helpers
    ("ChunkPos.pack(x, z)", "ChunkPos.toLong(x, z)", False),
    ("chunkPos.pack()", "chunkPos.toLong()", False),
    # AttributeModifierSlot.ARMOR -> explicit slots (drop the now-unused import)
    ("import net.minecraft.component.type.AttributeModifierSlot;\n", "", False),
    ("for (EquipmentSlot slot : AttributeModifierSlot.ARMOR)",
     "for (EquipmentSlot slot : new EquipmentSlot[] { EquipmentSlot.HEAD, EquipmentSlot.CHEST, EquipmentSlot.LEGS, EquipmentSlot.FEET })",
     False),
]

# GameProfile accessor through 1.21.8: yarn used getName(); 1.21.10+ yarn
# reverted to the mojmap-style public FIELD .name() -- no rule for those.
GP_NAME_GETTER: List[Tuple[str, str, bool]] = [
    ("getGameProfile().name()", "getGameProfile().getName()", False),
]

# Cross-VERSION source drift (26.2 mojmap names that MC/yarn renamed going
# forward) -- loom CANNOT translate these even in principle, because they never
# existed in the target version's mappings. Ground truth = the accepted 1.21.1
# port (legacy), the 1.21.4 yarn tiny + compiler (hybrid), and the 1.21.5+
# branches' own code (modern; build gate arbitrates).
LEGACY_YARN_RULES: List[Tuple[str, str, bool]] = [   # 1.21.1
    (".getMaxY()", ".getTopY()", False),             # World no-arg (1.21.1 only)
    (".getMinY()", ".getBottomY()", False),
    # PlayerInventory.getSelectedSlot() -> public FIELD (method gone)
    (".getInventory().getSelectedSlot()", ".getInventory().selectedSlot", False),
]
MID_YARN_RULES: List[Tuple[str, str, bool]] = [   # 1.21.4 (hybrid)
    (".getMaxY()", ".getTopYInclusive()", False),    # HeightLimitView
    (".getMinY()", ".getBottomY()", False),
    (".isFallFlying()", ".isGliding()", False),      # LivingEntity
    # slot: still the public FIELD on 1.21.4 (method does not exist yet)
    (".getInventory().getSelectedSlot()", ".getInventory().selectedSlot", False),
]
MODERN_YARN_RULES: List[Tuple[str, str, bool]] = [   # 1.21.5/1.21.8/1.21.10/1.21.11
    (".getMaxY()", ".getTopYInclusive()", False),
    (".getMinY()", ".getBottomY()", False),
    (".isFallFlying()", ".isGliding()", False),
    # getSelectedSlot() METHOD exists (field turned private) -- no rule
]

# Build the regex rules as compiled patterns for readability.
_REGEX_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\.identifier\(\)"), ".getValue()"),
    (re.compile(r"getChunkPos\(\)\.x\(\)"), "getChunkPos().getStartX()"),
    (re.compile(r"getChunkPos\(\)\.z\(\)"), "getChunkPos().getStartZ()"),
    (re.compile(r"chunkPos\.x\(\)"), "chunkPos.getStartX()"),
    (re.compile(r"chunkPos\.z\(\)"), "chunkPos.getStartZ()"),
    (re.compile(r"chunkDelta\.x\(\)"), "chunkDelta.getStartX()"),
    (re.compile(r"chunkDelta\.z\(\)"), "chunkDelta.getStartZ()"),
]

FIXUPS: dict = {
    # 1.21.1 (loom 1.8) -- byte-for-byte validated against the accepted port
    "1.21.1": COMMON_YARN_RULES + GP_NAME_GETTER + LEGACY_YARN_RULES,
    # 1.21.4 (loom 1.8): isGliding/getTopYInclusive, but slot is still a field
    "1.21.4": COMMON_YARN_RULES + GP_NAME_GETTER + MID_YARN_RULES,
    # 1.21.5/1.21.8 (loom 1.10/1.13): modern API (method-based slot)
    "1.21.5": COMMON_YARN_RULES + GP_NAME_GETTER + MODERN_YARN_RULES,
    "1.21.8": COMMON_YARN_RULES + GP_NAME_GETTER + MODERN_YARN_RULES,
    # 1.21.10/1.21.11 (loom 1.13/1.14.9): GameProfile.name is a FIELD again,
    # so the getName() getter rule must NOT fire -- MODERN only
    "*": COMMON_YARN_RULES + MODERN_YARN_RULES,
}

# ---------------------------------------------------------------------------
def apply_rules(text: str, rules: List[Tuple]) -> str:
    for rule in rules:
        old, new, is_regex = rule
        if is_regex:
            text, _ = re.subn(old, new, text)
        else:
            text = text.replace(old, new) if old in text else text
    for pat, new in _REGEX_RULES:
        text, _ = pat.subn(new, text)
    return text


def run_fixups(migrated_dir: Path, mc_version: str) -> int:
    rules = FIXUPS.get(mc_version) or FIXUPS["*"]
    count = 0
    for java in sorted(migrated_dir.rglob("*.java")):
        orig = java.read_text(encoding="utf-8")
        text = apply_rules(orig, rules)
        if text != orig:
            java.write_text(text, encoding="utf-8")
            print(f"[fixups] rewrote {java.relative_to(migrated_dir)}",
                  file=sys.stderr)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Comment stripping for `verify` (scan CODE only -- comments may legitimately
# document mojmap names, as the accepted 1.21.1 port does).
# ---------------------------------------------------------------------------
def _strip_comments(text: str) -> str:
    """Remove Java // and /* */ comments outside of string/char literals.

    Strings are kept intact so any surviving mojmap token inside a string
    (e.g. an unmigrated @Inject method= target) still fails the gate.
    Block-comment lines are preserved so reported line numbers stay truthful.
    """
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == '"':                       # string literal (handles \")
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(text[i:j]); i = j
        elif c == "'":                     # char literal (handles \')
            j = i + 1
            while j < n and text[j] != "'":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(text[i:j]); i = j
        elif c == "/" and nxt == "/":      # line comment
            j = text.find("\n", i)
            out.append("\n" if j >= 0 else "")
            i = n if j < 0 else j
        elif c == "/" and nxt == "*":      # block comment
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, j))
            i = j
        else:
            out.append(c); i += 1
    return "".join(out)


def verify(migrated_dir: Path, mc_version: str) -> int:
    banned = DENYLIST + (EXTRA_DENYLIST.get(mc_version) or EXTRA_DENYLIST["*"])
    hits = []
    for java in sorted(migrated_dir.rglob("*.java")):
        text = _strip_comments(java.read_text(encoding="utf-8"))
        for bad in banned:
            if bad in text:
                hits.append((java.relative_to(migrated_dir).as_posix(), bad))
    if hits:
        for rel, bad in hits[:25]:
            print(f"[verify] FAIL: {rel} still contains mojmap token {bad!r}",
                  file=sys.stderr)
        print("[verify] loom did not fully remap this version; bump this "
              "branch's loom (not fixups.py)", file=sys.stderr)
        return 3
    print("[verify] ok: no surviving mojmap tokens")
    return 0


def main() -> None:
    if len(sys.argv) != 4:
        print("usage: fixups.py <migrated_src_dir> <mc_version> <--fix|--verify>",
              file=sys.stderr)
        sys.exit(2)
    migrated_dir = Path(sys.argv[1])
    if not migrated_dir.is_dir():
        print(f"fixups.py: not a directory: {migrated_dir}", file=sys.stderr)
        sys.exit(2)
    mc_version = sys.argv[2]
    mode = sys.argv[3]
    if mode == "--verify":
        sys.exit(verify(migrated_dir, mc_version))
    run_fixups(migrated_dir, mc_version)
    sys.exit(verify(migrated_dir, mc_version))


if __name__ == "__main__":
    main()