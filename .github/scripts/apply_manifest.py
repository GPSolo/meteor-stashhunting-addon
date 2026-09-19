#!/usr/bin/env python3
"""Idempotent manifest application -- the ONLY thing that edits metadata.

WHAT IT DOES (ground-truthed across origin/26.2 <-> origin/1.21.1):
   Every toolchain branch pins loom, and loom's migrateMappings is the single
   engine that rewrites BOTH code and strings inside the manifest files
   (Phase 1 proved byte-exactness on 1.21.1 for all 7 files: raw loom output ==
   accepted port). So the code files themselves need NO help here.

   But three *metadata* edits are not in any .java the loom consumes, and are
   the exact spots that differ between the accepted 1.21.1 port and 26.2:

     1. MODULE REGISTRATION (Addon.java)
          origin/26.2    : Modules.get().add(new TripResumer());   (present)
          origin/1.21.1  : (ABSENT -- grep count 0 in d20269c port)
        -> this script inserts the registration line immediately AFTER the
           ElytraFlyPlusPlus registration anchor, which is present on every
           known branch (verified 26.2:82 and accepted-1.21.1:82).
        -> Idempotent: if `new TripResumer()` (or any manifest module reg)
           already exists in Addon.java, the insert is skipped.

     2. MIXIN REGISTRATION (jefff-mod.mixins.json "client" array)
          origin/26.2 client: [
              ..., ClientPacketListenerMixin, ChatComponentMixin ]  (2 new)
          origin/1.21.1 client: [ LivingEntityMixin, EntityMixin,
              KeyBindingMixin, XaeroDrawingMixin ]                 (neither)
        -> this script appends the two manifest mixin classes to the branch's
           mixins.json client[] array if (and only if) they are missing.
        -> Idempotent: membership is checked before append.

     3. MOJMAP TARGET build.gradle DEPENDENCY (26.1.2 / any unobfuscated
        target). The loom merged game jar for the 26.x MC blob declares
        `MinecraftServer implements net.fabricmc.fabric.api.resource.v1.
        DataResourceStore`, so compiling ANY code that touches MinecraftServer
        (the QoL serverKey() chain) requires that fabric interface on the
        compile classpath. This script mirrors origin/26.2's exact
        compileOnly fabric-resource-loader-v1 line into the mojmap target's
        build.gradle (idempotent, verified). Yarn targets (1.21.x) are a
        no-op: their merged jars do not implement the fabric interface.

   SAFETY INVARIANT (mirrors fixups.py):
     - `verify` mode is what the build gate runs: it asserts the registrations
       EXIST in the MIGRATED output (Addon.java must contain the TripResumer
       registration AND mixins.json client[] must contain both mixin classes;
       mojmap targets must also carry the fabric-resource-loader compileOnly
       line). If any is missing the sync FAILS -- never silently ships a port
       that would surface as "this intended QoL module isn't registered" or
       that cannot compile against the merged game jar's fabric interface.
"""
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# QoL modules that must be registered in Addon.java, keyed with their anchor.
# (module_class, anchor_registration). Anchor must exist on ALL branches; it is
# the same on accepted-1.21.1 (line 82) and 26.2 (line 30-region).
MODULE_REGISTRATIONS: List[Tuple[str, str]] = [
    ("TripResumer",
     "Modules.get().add(new ElytraFlyPlusPlus());"),
]

# Mixin classes (short names) that must be present in the branch's
# jefff-mod.mixins.json "client" array. The mixins.json filename itself is
# identical on both ends (jefff-mod.mixins.json) -- verified.
MIXIN_CLASSES: List[str] = [
    "ChatComponentMixin",
    "ClientPacketListenerMixin",
]

# ---------------------------------------------------------------------------
# Mojmap-target build.gradle dependency (mirrors origin/26.2 build.gradle)
# ---------------------------------------------------------------------------
# The loom "merged" game jar for the 26.x MC blob (same merge hash
# 1b9cc516b9 for 26.1.2 and 26.2) declares MinecraftServer as implementing
# net.fabricmc.fabric.api.resource.v1.DataResourceStore. javac therefore
# needs that interface on the compile classpath the moment any source touches
# MinecraftServer (the QoL port's serverKey() calls
# mc.getSingleplayerServer().getWorldData().getLevelName()). 26.2 pins the
# interface compileOnly -- mirror its exact line here, idempotently.
# Yarn-mapped targets (1.21.x) never get this: their merged jars do not carry
# the fabric interface, and anything extra would be dead weight.
MOJMAP_FABRIC_COMMENT = (
    "// Fabric API resource loader (compile only - the merged game jar has "
    "MinecraftServer implement DataResourceStore)"
)
MOJMAP_FABRIC_DEP = (
    'compileOnly "net.fabricmc.fabric-api:fabric-resource-loader-v1:'
    "2.0.13+9edec1269e\""
)
# Anchor line to insert after (present on every known branch's build.gradle).
MOJMAP_DEP_ANCHOR = 'implementation "net.fabricmc:fabric-loader:${project.loader_version}"'


def _find_addon_java(root: Path) -> Optional[Path]:
    """Locate the module-registration file by ANCHOR CONTENT, not by name.
    Robust to branch renames (26.2 branch once called it Add.java; yarn
    branches call it Addon.java). Search cost is O(#java files) per run, fine
    for a fan-out tool."""
    for path in sorted(root.rglob("*.java")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "new ElytraFlyPlusPlus()" in text:
            return path
    return None


def _register_modules(addon: Path) -> int:
    text = addon.read_text(encoding="utf-8")
    added = 0
    for module_class, anchor in MODULE_REGISTRATIONS:
        if f"new {module_class}()" in text:
            continue  # already registered (idempotent)
        if anchor not in text:
            print(f"[apply_manifest] anchor missing: {anchor!r} in {addon}",
                  file=sys.stderr)
            return -1
        # Insert immediately after the anchor line, matching its indentation.
        idx = text.find(anchor)
        nl = text.index("\n", idx)
        line_start = text.rfind("\n", 0, idx) + 1
        indent = text[line_start:idx]  # leading whitespace of the anchor line
        text = (text[:nl] + "\n" + indent + f"Modules.get().add(new {module_class}());"
                + text[nl:])
        added += 1
    if added:
        addon.write_text(text, encoding="utf-8")
    return added


def _register_mixins(mixins_json: Path) -> int:
    data = json.loads(mixins_json.read_text(encoding="utf-8"))
    client = data.get("client")
    if not isinstance(client, list):
        print(f"[apply_manifest] {mixins_json}: no 'client' array, aborting",
              file=sys.stderr)
        return -1
    added = 0
    for cls in MIXIN_CLASSES:
        # mixins.json stores full class names (ChatComponentMixin, ...) -- both
        # 26.2 and every yarn branch verified.
        if cls not in client:
            client.append(cls)
            added += 1
    if added:
        data["client"] = client
        mixins_json.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return added


def _is_mojmap_target(branch_root: Path) -> bool:
    """Unobfuscated/mojmap target == gradle.properties has NO yarn_mappings
    (same rule sync-base.sh uses to skip loom migrate)."""
    gp = branch_root / "gradle.properties"
    if gp.is_file():
        for line in gp.read_text(encoding="utf-8").splitlines():
            if line.startswith("yarn_mappings="):
                return False
    return True


def _ensure_mojmap_dep(build_gradle: Path) -> int:
    """Idempotently ensure the compileOnly fabric-resource-loader-v1 line (the
    exact one 26.2's build.gradle pins) exists in a mojmap target's
    build.gradle. Returns lines added (0 = already present), -1 on failure."""
    text = build_gradle.read_text(encoding="utf-8")
    if MOJMAP_FABRIC_DEP in text:
        return 0
    if MOJMAP_DEP_ANCHOR not in text:
        print(f"[apply_manifest] mojmap dep anchor missing: {MOJMAP_DEP_ANCHOR!r} "
              f"in {build_gradle}", file=sys.stderr)
        return -1
    idx = text.find(MOJMAP_DEP_ANCHOR)
    nl = text.index("\n", idx)
    line_start = text.rfind("\n", 0, idx) + 1
    indent = text[line_start:idx]  # leading whitespace of the anchor line
    insert = f"{indent}{MOJMAP_FABRIC_COMMENT}\n{indent}{MOJMAP_FABRIC_DEP}"
    text = text[:nl] + "\n" + insert + text[nl:]
    build_gradle.write_text(text, encoding="utf-8")
    return 2  # comment + dep line


def apply_manifest(branch_root: Path) -> Tuple[int, int]:
    addon = _find_addon_java(branch_root)
    if addon is None:
        print("[apply_manifest] no Addon.java with ElytraFlyPlusPlus anchor; "
              "refusing to continue", file=sys.stderr)
        return (-1, 0)
    mods = _register_modules(addon)
    mixins = []
    for mj in sorted((branch_root / "src" / "main" / "resources").glob("*mixins.json")):
        n = _register_mixins(mj)
        if n < 0:
            return (-1, 0)
        mixins.append(n)
    return (mods, sum(mixins))


def apply_build_metadata(branch_root: Path) -> int:
    """build.gradle edits for mojmap targets only (yarn targets: no-op)."""
    if not _is_mojmap_target(branch_root):
        return 0
    return _ensure_mojmap_dep(branch_root / "build.gradle")


def verify_manifest(branch_root: Path) -> int:
    """Build-gate check used AFTER migration: registrations must be present."""
    problems = 0
    addon = _find_addon_java(branch_root)
    if addon is None:
        print("[verify] no Addon.java found", file=sys.stderr)
        return 3
    text = addon.read_text(encoding="utf-8")
    for module_class, _ in MODULE_REGISTRATIONS:
        if f"new {module_class}()" not in text:
            print(f"[verify] Addon.java missing registration for {module_class}",
                  file=sys.stderr)
            problems += 1
    resources = branch_root / "src" / "main" / "resources"
    for mj in sorted(resources.glob("*mixins.json")):
        data = json.loads(mj.read_text(encoding="utf-8"))
        client = data.get("client") or []
        for cls in MIXIN_CLASSES:
            if cls not in client:
                print(f"[verify] {mj.name} missing mixin class {cls}",
                      file=sys.stderr)
                problems += 1
    if _is_mojmap_target(branch_root):
        bg = branch_root / "build.gradle"
        if not bg.is_file() or MOJMAP_FABRIC_DEP not in bg.read_text(encoding="utf-8"):
            print("[verify] mojmap target build.gradle missing compileOnly "
                  f"fabric-resource-loader-v1 ({MOJMAP_FABRIC_DEP!r})",
                  file=sys.stderr)
            problems += 1
    return 3 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: apply_manifest.py <src_root> <apply|verify>",
              file=sys.stderr)
        sys.exit(2)
    root = Path(sys.argv[1])
    mode = sys.argv[2]
    if mode == "verify":
        sys.exit(verify_manifest(root))
    mods, mix = apply_manifest(root)
    if mods < 0:
        sys.exit(3)
    bg = apply_build_metadata(root)
    if bg < 0:
        sys.exit(3)
    print(f"[apply_manifest] modules +{mods}, mixins +{mix}, build.gradle +{bg}",
          file=sys.stderr)
