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

WHOLE-TREE NOTE (ChunkPos accessors):
   26.2's ChunkPos is a Java RECORD (x()/z() accessors). loom cannot translate
   a method call into the yarn public FIELD (chunk.x / chunk.z) or into
   getStartX()/getStartZ() -- those names never existed in the target's
   mappings. Which form is "correct" depends on the CALL SITE's intent, so
   these rules are FILE-SCOPED (FILE_RULES / FILE_REGEX_RULES), grounded in
   each file's accepted port:
     - TrailFollower (highway/region math, block coordinates) -> getStartX()/
       getStartZ()
     - BetterStashFinder / OldChunkNotifier / ElytraFlyPlusPlus / TrailMaker
       (chunk-INDEX math) -> the public fields .x / .z
   The global `chunkPos.x()` -> `getStartX()` translation would CORRUPT the
   index-math files (getStartX() is x << 4 -- a different value), which is why
   the scoping is mandatory, not cosmetic.

MOJMAP TARGETS (26.x -- verbatim copy, no loom):
   Both sides are mojmap for DIFFERENT minecraft versions, so a small
   per-version mechanical set (MOJMAP_RULES) rewrites 26.2-only API calls into
   the target's accepted form. `--verify` for these targets asserts that no
   rule's `old` token survives anywhere (i.e. every known drift spot was
   rewritten).

WHOLE-TREE YARN DRIFT (MC API moved between 26.2 and the 1.21.x yarns -- loom
   cannot translate these, they never existed in the target's mappings:
     - 26.x moved screen handling (screen()/setScreen()/toastManager()) from
       MinecraftClient onto Gui/InGameHud; 1.21.x keeps it on Minecraft
       (currentScreen / setScreen / getToastManager().add()).
     - 26.x Block builder-chains (waxed()/oxidized()/unaffected()) are plain
       block constants on 1.21.x (WAXED_*).
     - meteor-client renamed its IVec3 mixin interface to IVec3d.
     - 26.x mojmap renamed ClickType -> ContainerInput; 1.21.x yarn still uses
       SlotActionType.
     - meteor-client's Command.build() generic: 26.2 (mojmap) uses
       ClientSuggestionProvider; every 1.21.x yarn uses CommandSource. loom
       maps the import to net.minecraft.client.network.ClientCommandSource,
       which does NOT satisfy the superclass override -- so CommandExample is
       fixed file-scoped (FILE_RULES), not globally.
   Every rule is an IDEMPOTENT NO-OP on already-correct text; all six yarn
   branches share one rule set (verified against every branch's accepted port).

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
    # Whole-tree yarn drift (26.2 API moved; covered by WHOLE_TREE_YARN_RULES --
    # surviving them means a NEW drift site appeared and needs a rule, NOT a
    # loom bump): screen/toasts live on 26.x's Gui (yarn: mc.inGameHud), the
    # Block builder-chains, meteor-client IVec3->IVec3d, ClickType->
    # ContainerInput rename, and the Command.build() generic mismatch that
    # loom maps to the wrong yarn class.
    "mc.inGameHud.screen()",
    "mc.inGameHud.setScreen(",
    "mc.inGameHud.toastManager()",
    "ContainerInput",
    "meteordevelopment.meteorclient.mixininterface.IVec3;",
    "((IVec3) event.movement)",
    "ClientCommandSource",
    "Blocks.CUT_COPPER.waxed()",
    "Blocks.COPPER_BLOCK.waxed()",
    # 26.2 mojmap renamed ResourceLocation -> Identifier (loom 1.13 leaves the
    # import unmigrated) and SoundInstance.getIdentifier() (yarn: getId()).
    "import net.minecraft.resources.Identifier;",
    "event.sound.getIdentifier()",
    # 26.2 mojmap ClientPacketListener.decoratedHashOpsGenenerator(): must never
    # survive on any yarn branch -- every branch's fixup (or loom) rewrites it
    # to the version-correct form (see the hasher notes after WHOLE_TREE_...).
    "decoratedHashOpsGenenerator",
]

EXTRA_DENYLIST: dict = {
    # legacy yarn (1.21.1): getSelectedSlot() is gone (field is the API);
    # GameProfile must use the getName() getter (id()/name() accessors do not
    # exist). isFallFlying/getTopY are CORRECT here -- never banned.
    # canHaveWeather() absent -> bedWorks() form. Pre-Builder meteor-client:
    # MeteorToast.Builder must not survive (constructor form is the API).
    "1.21.1": ["getSelectedSlot()", "getGameProfile().name()", "mc.world.canHaveWeather()", "profile.id()", "profile.name()", "MeteorToast.Builder"],
    # hybrid (1.21.4)/mid (1.21.5, 1.21.8): isFallFlying and no-arg getTopY()
    # are gone; getName() getter is the API; slot is still the field on 1.21.4
    "1.21.4": ["getSelectedSlot()", "getGameProfile().name()", "isFallFlying", "getTopY()", "mc.world.canHaveWeather()", "profile.id()", "profile.name()", "MeteorToast.Builder"],
    "1.21.5": ["getGameProfile().name()", "isFallFlying", "getTopY()", "mc.world.canHaveWeather()", "profile.id()", "profile.name()", "MeteorToast.Builder", "getComponentHasher()"],
    "1.21.8": ["getGameProfile().name()", "isFallFlying", "getTopY()", "mc.world.canHaveWeather()", "profile.id()", "profile.name()"],
    # 1.21.10 (loom 1.13): GameProfile.name is a FIELD again -- .name() is
    # CORRECT here, getName() must NOT survive; canHaveWeather() still absent
    "1.21.10": ["isFallFlying", "getTopY()", "mc.world.canHaveWeather()", "getGameProfile().getName()"],
    # late yarn (1.21.11): GameProfile.name is a FIELD again -- .name() is
    # CORRECT here and must NOT be banned; canHaveWeather() EXISTS here and
    # must NOT be banned; getSelectedSlot() method is the API
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

# 26.2's GameProfile exposes id()/name() accessors (matching 1.21.10+ yarn);
# the 1.21.1..1.21.8 yarn line only has getId()/getName(). loom cannot bridge
# the rename (leftover .id()/.name() compile on 1.21.10+, fail elsewhere), so
# the 1.21.1-1.21.8 slices rewrite them. Variable is `profile` at every known
# site (DiscordNotifs); if a new file uses a different receiver the gate will
# flag it and this rule gains another entry.
PROFILE_ACCESSOR_RULES: List[Tuple[str, str, bool]] = [
    ("profile.id()", "profile.getId()", False),
    ("profile.name()", "profile.getName()", False),
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
    (".isFallFlying()", ".isGliding()", False),      # LivingEntity call sites
    # method= string + handler-name form (1.21.4+) -- the 26.2 mojmap source
    # injects the pre-rename target `isFallFlying`; yarn renamed it isGliding.
    ('method = "isFallFlying"', 'method = "isGliding"', False),
    # slot: still the public FIELD on 1.21.4 (method does not exist yet)
    (".getInventory().getSelectedSlot()", ".getInventory().selectedSlot", False),
]
MODERN_YARN_RULES: List[Tuple[str, str, bool]] = [   # 1.21.5/1.21.8/1.21.10/1.21.11
    (".getMaxY()", ".getTopYInclusive()", False),
    (".getMinY()", ".getBottomY()", False),
    (".isFallFlying()", ".isGliding()", False),
    ('method = "isFallFlying"', 'method = "isGliding"', False),
    # getSelectedSlot() METHOD exists (field turned private) -- no rule
]

# Cross-VERSION drift that is IDENTICAL on every yarn branch (see module doc
# "WHOLE-TREE YARN DRIFT"): the 26.2 API moved/renamed in ways loom cannot
# bridge, and all six 1.21.x branches share the same accepted form.
WHOLE_TREE_YARN_RULES: List[Tuple[str, str, bool]] = [
    # 26.x Gui (yarn: mc.inGameHud) owns screen/toasts; 1.21.x Minecraft does.
    ("mc.inGameHud.screen() instanceof", "mc.currentScreen instanceof", False),
    ("mc.inGameHud.setScreen(", "mc.setScreen(", False),
    ("mc.inGameHud.toastManager().addToast(", "mc.getToastManager().add(", False),
    # 26.2 Block builder-chains -> plain block constants on 1.21.x
    ("Blocks.CUT_COPPER.waxed().oxidized()", "Blocks.WAXED_OXIDIZED_CUT_COPPER", False),
    ("Blocks.COPPER_BLOCK.waxed().unaffected()", "Blocks.WAXED_COPPER_BLOCK", False),
    ("Blocks.COPPER_BLOCK.waxed().oxidized()", "Blocks.WAXED_OXIDIZED_COPPER", False),
    # meteor-client mixin interface rename IVec3 -> IVec3d (26.2 -> yarn deps);
    # the import + the cast site are distinct strings, so these are safe
    # without word-boundary regex.
    ("import meteordevelopment.meteorclient.mixininterface.IVec3;",
     "import meteordevelopment.meteorclient.mixininterface.IVec3d;", False),
    ("((IVec3) event.movement)", "((IVec3d) event.movement)", False),
    # 26.x mojmap renamed ClickType -> ContainerInput; 1.21.x yarn kept
    # SlotActionType (loom cannot bridge the rename).
    ("import net.minecraft.world.inventory.ContainerInput;",
     "import net.minecraft.screen.slot.SlotActionType;", False),
    ("ContainerInput.SWAP", "SlotActionType.SWAP", False),
    # 26.2 mojmap renamed ResourceLocation -> Identifier; loom 1.13 (1.21.8/
    # 1.21.10) does not know `net.minecraft.resources.Identifier` as a source
    # name, so the import survives unmigrated. loom 1.14.9 (1.21.11) remaps it
    # itself -- the rule is an idempotent NO-OP there. The simple class name
    # (Identifier) is identical in both mappings, so only the import line moves.
    ("import net.minecraft.resources.Identifier;",
     "import net.minecraft.util.Identifier;", False),
    # 26.2 mojmap SoundInstance.getIdentifier() (yarn 1.21.x: getId());
    # remapped by loom 1.14.9, left for 1.13 -- idempotent either way.
    ("event.sound.getIdentifier()", "event.sound.getId()", False),
    # 26.2 mojmap ResourceLocation.parse(String) (renamed class Identifier +
    # parse factory); yarn 1.21.x has no parse() -- it's Identifier.of().
    # loom 1.14.9 remaps it, 1.13 does not; Identifier.of() is the accepted
    # form on every yarn branch (idempotent no-op where loom already fixed it).
    ("Identifier.parse(", "Identifier.of(", False),
]

# The 26.2 hasher method is VERSION-SLICED (loom's output differs per loom
# generation; never a global rule):
#   26.2 mojmap ClientPacketListener.decoratedHashOpsGenenerator() (yes, that
#   is the shipped name). loom 1.13/1.14.9 (1.21.8/1.21.10/1.21.11) remap it to
#   yarn's getComponentHasher() -- CORRECT there, no rule. loom 1.10 (1.21.5)
#   leaves it unmigrated and 1.21.5 yarn is still unmapped for it -- the
#   accepted port uses method_68823(), handled by the 1.21.5 slice. loom 1.8
#   (1.21.1/1.21.4) leaves the whole HashedStack block unmigrated -- handled by
#   the ELYTRA_LEGACY_SWAP rules, never by a global token rewrite.
#   DENYLIST keeps bare `decoratedHashOpsGenenerator` (+ the 1.21.5 slice bans
#   `getComponentHasher`) so a NEW drift site fails --verify.

# meteor-client's MeteorToast gained a Builder (title/icon/text) in a late
# 1.21.8-era snapshot; 1.21.1/1.21.4/1.21.5 meteor-client only has the
# (icon, title, text) constructor. Sliced to the old-dependency branches.
METEOR_TOAST_CTOR_RULES: List[Tuple[str, str, bool]] = [
    ('new MeteorToast.Builder(title).icon(Items.CHEST).text("Found Stash!").build()',
     'new MeteorToast(Items.CHEST, title, "Found Stash!")', False),
]

# GameProfile.name on 1.21.10 is the public FIELD again (mojmap-style) --
# loom 1.13 leaves 26.2's getName() call unmigrated and 1.21.10 has NO
# getName(); the correct form is .name() (loom 1.14.9 on 1.21.11 remaps it by
# itself, so this rule lives only in the "1.21.10" slice, never in "*").
GP_NAME_FIELD: List[Tuple[str, str, bool]] = [
    ("getGameProfile().getName()", "getGameProfile().name()", False),
]

# ClientLevel.canHaveWeather() is a 26.2 call that yarn added partway through
# the 1.21.x line: it EXISTS on 1.21.11 (the accepted port keeps it) but not on
# 1.21.1..1.21.10 (accepted: getDimension().bedWorks()). Sliced, NOT global --
# see the "*" (1.21.11) FIXUPS entry that deliberately omits this rule.
CAN_HAVE_WEATHER_RULE: List[Tuple[str, str, bool]] = [
    ("mc.world.canHaveWeather()", "mc.world.getDimension().bedWorks()", False),
]

FIXUPS: dict = {
    # 1.21.1 (loom 1.8) -- byte-for-byte validated against the accepted port
    "1.21.1": COMMON_YARN_RULES + GP_NAME_GETTER + LEGACY_YARN_RULES
              + PROFILE_ACCESSOR_RULES + METEOR_TOAST_CTOR_RULES
              + WHOLE_TREE_YARN_RULES + CAN_HAVE_WEATHER_RULE,
    # 1.21.4 (loom 1.8): isGliding/getTopYInclusive, but slot is still a field
    "1.21.4": COMMON_YARN_RULES + GP_NAME_GETTER + MID_YARN_RULES
              + PROFILE_ACCESSOR_RULES + METEOR_TOAST_CTOR_RULES
              + WHOLE_TREE_YARN_RULES + CAN_HAVE_WEATHER_RULE,
    # 1.21.5 (loom 1.10): modern API (method-based slot) but the pre-Builder
    # meteor-client; gets the constructor-form toast. loom 1.10 leaves the
    # 26.2 mojmap hasher call (decoratedHashOpsGenenerator()) unmigrated, and
    # 1.21.5 yarn has no mapped name for it -- the accepted port calls the
    # unmapped method_68823().
    "1.21.5": COMMON_YARN_RULES + GP_NAME_GETTER + MODERN_YARN_RULES
              + PROFILE_ACCESSOR_RULES + METEOR_TOAST_CTOR_RULES
              + WHOLE_TREE_YARN_RULES + CAN_HAVE_WEATHER_RULE
              + [("decoratedHashOpsGenenerator()", "method_68823()", False)],
    # 1.21.8 (loom 1.13): modern API (method-based slot)
    "1.21.8": COMMON_YARN_RULES + GP_NAME_GETTER + MODERN_YARN_RULES
              + PROFILE_ACCESSOR_RULES + WHOLE_TREE_YARN_RULES + CAN_HAVE_WEATHER_RULE,
    # 1.21.10 (loom 1.13): GameProfile.name is a FIELD again (getName() is
    # gone) -- getName() -> .name() via GP_NAME_FIELD (reverse of the getter
    # rule used below 1.21.10); canHaveWeather still absent
    "1.21.10": COMMON_YARN_RULES + MODERN_YARN_RULES
               + WHOLE_TREE_YARN_RULES + CAN_HAVE_WEATHER_RULE + GP_NAME_FIELD,
    # 1.21.11 (loom 1.14.9): GameProfile.name is a FIELD again, so the
    # getName() getter rule must NOT fire; canHaveWeather() EXISTS here so the
    # bedWorks() rule must NOT fire -- MODERN + WHOLE_TREE only
    "*": COMMON_YARN_RULES + MODERN_YARN_RULES + WHOLE_TREE_YARN_RULES,
}

# ---------------------------------------------------------------------------
# Whole-tree ChunkPos accessor translations -- FILE-SCOPED (see module doc:
# block-coordinate sites want getStartX()/getStartZ(), chunk-index sites want
# the public .x/.z fields; a global rule would corrupt one or the other).
# ---------------------------------------------------------------------------
GLOBAL_REGEX_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\.identifier\(\)"), ".getValue()"),
]

# Block-coordinate call sites (TrailFollower highway/region math) -- byte-
# for-byte ground truth: chunkPos.getStartX()/getStartZ() etc. loom already
# converts chunkPosition() -> getChunkPos() at migration time, so only the
# accessor call remains to rewrite.
FILE_REGEX_RULES: dict = {
    "com/stash/hunt/modules/TrailFollower.java": [
        (re.compile(r"getChunkPos\(\)\.x\(\)"), "getChunkPos().getStartX()"),
        (re.compile(r"getChunkPos\(\)\.z\(\)"), "getChunkPos().getStartZ()"),
        (re.compile(r"chunkPos\.x\(\)"), "chunkPos.getStartX()"),
        (re.compile(r"chunkPos\.z\(\)"), "chunkPos.getStartZ()"),
        (re.compile(r"chunkDelta\.x\(\)"), "chunkDelta.getStartX()"),
        (re.compile(r"chunkDelta\.z\(\)"), "chunkDelta.getStartZ()"),
    ],
    # Chunk-index call sites -- the accepted ports use the public yarn fields
    # chunk.x / chunk.z. Regex form survives loom's class renames (e.g.
    # Vec3 -> Vec3d) because it only touches the accessor call itself.
    "com/stash/hunt/modules/BetterStashFinder.java": [
        (re.compile(r"chunkPos\.x\(\)"), "chunkPos.x"),
        (re.compile(r"chunkPos\.z\(\)"), "chunkPos.z"),
    ],
    "com/stash/hunt/modules/OldChunkNotifier.java": [
        (re.compile(r"chunkPos\.x\(\)"), "chunkPos.x"),
        (re.compile(r"chunkPos\.z\(\)"), "chunkPos.z"),
        (re.compile(r"playerChunkPos\.x\(\)"), "playerChunkPos.x"),
        (re.compile(r"playerChunkPos\.z\(\)"), "playerChunkPos.z"),
    ],
}

# Literal (context-bound) translations that would be unsafe as bare regexes.
# chunk().getPos() accessors -> fields (both files' accepted ports).
_CHUNKPOS_GETPOS_RULES: List[Tuple[str, str, bool]] = [
    ("event.chunk().getPos().x()", "event.chunk().getPos().x", False),
    ("event.chunk().getPos().z()", "event.chunk().getPos().z", False),
]
FILE_RULES: dict = {
    "com/stash/hunt/modules/BetterStashFinder.java": _CHUNKPOS_GETPOS_RULES,
    "com/stash/hunt/modules/OldChunkNotifier.java": _CHUNKPOS_GETPOS_RULES,
    "com/stash/hunt/modules/ElytraFlyPlusPlus.java": [
        ("new BlockPos(pos.x() * 16 + x, y, pos.z() * 16 + z)",
         "new BlockPos(pos.x * 16 + x, y, pos.z * 16 + z)", False),
    ],
    "com/stash/hunt/modules/TrailMaker.java": [
        ("removeHighlight(point.x(), point.z(), dimension)",
         "removeHighlight(point.x, point.z, dimension)", False),
    ],
    # meteor-client Command.build() generic mismatch (see WHOLE-TREE YARN DRIFT
    # in the module doc): loom maps net.minecraft.commands.CommandSource to
    # net.minecraft.client.network.ClientCommandSource, but the yarn superclass
    # requires net.minecraft.command.CommandSource. File-scoped because the
    # replacement must NOT touch the brigadier LiteralArgumentBuilder generic.
    "com/stash/hunt/commands/CommandExample.java": [
        ("import net.minecraft.client.network.ClientCommandSource;",
         "import net.minecraft.command.CommandSource;", False),
        ("build(LiteralArgumentBuilder<ClientCommandSource>",
         "build(LiteralArgumentBuilder<CommandSource>", False),
    ],
}

# ---------------------------------------------------------------------------
# Mojmap targets (26.x -- verbatim copy, no loom): mechanical rewrites of
# 26.2-only API calls into the target's accepted form. Keyed by target
# version; ground truth = each accepted port's file content.
# ---------------------------------------------------------------------------
MOJMAP_RULES: dict = {
    # 26.1.2: 26.2 moved toastManager()/setScreen()/screen() onto the Gui;
    # 26.1.2 keeps them on Minecraft. 26.2's Block builder-chains
    # (waxed()/oxidized()/unaffected()) are plain block constants here.
    "26.1.2": [
        ("mc.gui.toastManager().addToast", "mc.getToastManager().addToast", False),
        ("mc.gui.setScreen(", "mc.setScreen(", False),
        ("mc.gui.screen() instanceof", "mc.screen instanceof", False),
        ("Blocks.CUT_COPPER.waxed().oxidized()", "Blocks.WAXED_OXIDIZED_CUT_COPPER", False),
        ("Blocks.COPPER_BLOCK.waxed().unaffected()", "Blocks.WAXED_COPPER_BLOCK", False),
        ("Blocks.COPPER_BLOCK.waxed().oxidized()", "Blocks.WAXED_OXIDIZED_COPPER", False),
    ],
}


def _is_mojmap_target(mc_version: str) -> bool:
    """26.x targets are unobfuscated/mojmap (no loom migration) -- their
    fixups come from MOJMAP_RULES instead of the yarn FIXUPS slices."""
    return mc_version.startswith("26.")


def apply_rules(text: str, rules: List[Tuple],
                regex_rules: List[Tuple[re.Pattern, str]]) -> str:
    for rule in rules:
        old, new, is_regex = rule
        if is_regex:
            text = re.sub(old, new, text)
        elif old in text:
            text = text.replace(old, new)
    for pat, new in regex_rules:
        text = pat.subn(new, text)[0]
    return text


def run_fixups(sync_dir: Path, mc_version: str) -> int:
    is_mojmap = _is_mojmap_target(mc_version)
    count = 0
    for java in sorted(sync_dir.rglob("*.java")):
        rel = java.relative_to(sync_dir).as_posix()
        if is_mojmap:
            rules = list(MOJMAP_RULES.get(mc_version, []))
            regexes: List[Tuple[re.Pattern, str]] = []
        else:
            rules = list(FIXUPS.get(mc_version) or FIXUPS["*"])
            rules += FILE_RULES.get(rel, [])
            regexes = GLOBAL_REGEX_RULES + FILE_REGEX_RULES.get(rel, [])
        orig = java.read_text(encoding="utf-8")
        text = apply_rules(orig, rules, regexes)
        if text != orig:
            java.write_text(text, encoding="utf-8")
            print(f"[fixups] rewrote {rel}", file=sys.stderr)
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


def verify(sync_dir: Path, mc_version: str) -> int:
    if _is_mojmap_target(mc_version):
        banned = [old for (old, _, _) in MOJMAP_RULES.get(mc_version, [])]
        fail_msg = ("[verify] surviving 26.2-only API tokens; add a "
                    "MOJMAP_RULES entry for them (or bump the rule)")
    else:
        banned = DENYLIST + (EXTRA_DENYLIST.get(mc_version) or EXTRA_DENYLIST["*"])
        fail_msg = ("[verify] loom did not fully remap this version; bump this "
                    "branch's loom (not fixups.py)")
    hits = []
    for java in sorted(sync_dir.rglob("*.java")):
        text = _strip_comments(java.read_text(encoding="utf-8"))
        for bad in banned:
            if bad in text:
                hits.append((java.relative_to(sync_dir).as_posix(), bad))
    if hits:
        for rel, bad in hits[:25]:
            print(f"[verify] FAIL: {rel} still contains mojmap token {bad!r}",
                  file=sys.stderr)
        print(fail_msg, file=sys.stderr)
        return 3
    print("[verify] ok: no surviving mojmap tokens")
    return 0


def main() -> None:
    if len(sys.argv) != 4:
        print("usage: fixups.py <sync_src_dir> <mc_version> <--fix|--verify>",
              file=sys.stderr)
        sys.exit(2)
    sync_dir = Path(sys.argv[1])
    if not sync_dir.is_dir():
        print(f"fixups.py: not a directory: {sync_dir}", file=sys.stderr)
        sys.exit(2)
    mc_version = sys.argv[2]
    mode = sys.argv[3]
    if mode == "--verify":
        sys.exit(verify(sync_dir, mc_version))
    run_fixups(sync_dir, mc_version)
    sys.exit(verify(sync_dir, mc_version))


if __name__ == "__main__":
    main()