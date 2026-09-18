#!/usr/bin/env python3
"""Idempotent manifest application -- the ONLY thing that edits metadata.

WHAT IT DOES (ground-truthed across origin/26.2 <-> origin/1.21.1):
   Every toolchain branch pins loom, and loom's migrateMappings is the single
   engine that rewrites BOTH code and strings inside the manifest files
   (Phase 1 proved byte-exactness on 1.21.1 for all 7 files: raw loom output ==
   accepted port). So the code files themselves need NO help here.

   But two *metadata* edits are not in any .java the loom consumes, and are
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

   SAFETY INVARIANT (mirrors fixups.py):
     - `verify` mode is what the build gate runs: it asserts the registrations
       EXIST in the MIGRATED output (Addon.java must contain the TripResumer
       registration AND mixins.json client[] must contain both mixin classes).
       If either is missing the sync FAILS (exit 3) -- never silently ships a
       port that would surface as "this intended QoL module isn't registered".
     - Application is always performed BEFORE loom in the pipeline, because loom
       is what remaps string tokens (mixin method=..., @Mixin targets) and we
       want the strings that loom DOESN'T touch (mixin class names in
       mixins.json; module class in Addon.java) to reflect the final manifest
       while loom is the last mover. Ordering matters and Phase 1 validated that
       ordering produces byte-exact output.
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
        idx = text.find(anchor) + len(anchor)
        nl = text.index("\n", idx)
        indent = text[idx:nl]  # keep everything between anchor-end and newline
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
        short = cls.replace("Mixin", "")  # stored as "ChatComponent"/"ClientPacketListener"?
        # The manifest stores SHORT names (both 26.2 and 1.21.1 use short
        # names: ChatComponentMixin is listed as "ChatComponentMixin"? -- see
        # glossary; mixin files are ChatComponentMixin.java so short = same).
        if cls not in client:
            client.append(cls)
            added += 1
    if added:
        data["client"] = client
        mixins_json.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    return added


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
    print(f"[apply_manifest] modules +{mods}, mixins +{mix}",
          file=sys.stderr)
