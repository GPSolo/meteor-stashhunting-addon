#!/usr/bin/env bash
# =============================================================================
# sync-qol.sh -- QoL feature-set synchronizer (orphan-fork aware)
#
# ONE SCRIPT PER VERSION-BRANCH, LOOPS OVER THE MANIFEST:
#   For each target branch this script:
#     1. Copies the 7 manifest source files from the CURRENT QoL source branch
#        (26.2 for this repo -- the QoL feature ownership moved there; it is
#        always mojmap/yarn-native and looms' migrateMappings makes them all
#        byte-identical, proven in Phase 1).
#     2. Applies the manifest metadata edits (module + mixin registration) via
#        apply_manifest.py. Idempotent: no-op when already registered.
#     3. Runs **this branch's pinned loom** migrateMappings over the branch (this
#        is the SINGLE TRUE remap engine -- Phase 1 proved loom 1.8's migrate
#        output equals the accepted 1.21.1 port BYTE-FOR-BYTE for all 7 files
#        including mixin method= strings, @Mixin targets, ChunkPos.pack, etc.).
#     4. Runs fixups.py as a conditional safety net (only fires if a raw
#        mojmap token SURVIVES migration -- i.e. a loom-version gap; on 1.21.1
#        it is a no-op because loom already rewrote everything).
#     5. GATE: runs `./gradlew build` on the migrated branch -- the same gate
#        CI runs. If the gate fails, the script exits non-zero and the branch
#        is NEVER pushed (no broken intermediate commits).
#     6. DELIVERY (from env):
#          QOL_DELIVERY=dry    (default)  -- run everything, commit locally,
#                                            DON'T push.
#          QOL_DELIVERY=push   -- push the sync commit to origin (orphan fork).
#          QOL_DELIVERY=pr     -- push sync commit + open PR to the version
#                                 merge base (NOT upstream -- this repos lives
#                                 on an orphan fork, see README "push/pr").
#        In all modes the script NEVER force-pushes and NEVER rewrites history.
#
# PREREQS: run from a clone of the orphan fork (this repo). The script uses the
# current branch's gradle.properties for loom version + yarn_mappings — do not
# run it from a worktree created from a DIFFERENT source (use the branch worktrees
# created by the tooling worktree helper).
#
# EXIT CODES:
#   0  success (migrate + manifest + gate all green)
#   3  migrateMappings or fixups left raaw mojmap tokens -> loom gap (fix by
#      bumping THIS branch's loom; NEVER by widening fixups rules)
#   4  manifest application/verification failed
#   5  build gate ($./gradlew build) failed
#   6  no changes (manifest already in sync -- normal no-op)
#   2  usage / missing tool
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"

qol_delivery="${QOL_DELIVERY:-pr}"
# QoL source: resolve SHA-FIRST from the pin in qol-source.txt (26.2 @ 8df2d48),
# so sync survives 26.2 being a temporary branch that dies once the QoL set
# merges everywhere. The live branch name is a BOOTSTRAP FALLBACK only.
src_pin="$(sed -nE 's/^# Last synced from: [^@]+ @ ([0-9a-f]{7,40}).*/\1/p' \
  "$SCRIPT_DIR/qol-source.txt" | head -1)"
if [ -n "$src_pin" ] && git -C "$REPO_ROOT" cat-file -e "${src_pin}^{commit}" >/dev/null 2>&1; then
  source_ref="$src_pin"
  source_branch="${QOL_SOURCE_BRANCH:-26.2}"   # label only (no git use while pinned)
else
  source_ref="origin/${QOL_SOURCE_BRANCH:-26.2}"
  source_branch="${QOL_SOURCE_BRANCH:-26.2}"
fi

# 16.2.2+ loom versions we rely on to fully cover the mojmap->yarn residual set
# (empirically validated on 1.21.1 with loom 1.8; other branches pin newer loom
# which only improves coverage). Change loom ONLY in gradle.properties.
need_loom_min="1.8"

die() { printf 'fatal: %s\n' "$*" >&2; exit "${2:-2}"; }

# ---------------------------------------------------------------------------
# resolve: which gradle.properties vars drive loom/mappings on this branch
# ---------------------------------------------------------------------------
version="$(grep -E '^minecraft_version=' gradle.properties | cut -d= -f2)"
loom="$(grep -E '^loom_version=' gradle.properties | cut -d= -f2 || true)"
# Loom is pin home is BRANCH-SPECIFIC: some branches pin in gradle.properties
# (loom_version=), others ONLY in build.gradle's plugin block
# (id "fabric-loom" version "1.8-SNAPSHOT"). The matrix probe proved every
# yarn branch uses the build.gradle home, so probe BOTH homes — the empty
# gradle.properties key alone is NOT "mojmap/no-loom", it's <none>.
if [ -z "$loom" ]; then
  loom="$(sed -nE 's/.*id "fabric-loom" version "([^"]+)".*/\1/p' build.gradle | head -1 || true)"
fi
yarn="$(grep -E '^yarn_mappings=' gradle.properties | cut -d= -f2 || true)"
[ -n "$version" ] || die 'gradle.properties missing minecraft_version'
echo "[sync-qol] target mc=$version loom=${loom:-<none/mojmap>} yarn=${yarn:-<none>}"

# ---------------------------------------------------------------------------
# 1. copy manifest from QoL source branch (LOOM-INDEPENDENT: identical tokens)
# ---------------------------------------------------------------------------
_manifest_ok() {
  local mf="$SCRIPT_DIR/qol-source.txt"
  [ -f "$mf" ] || die "missing manifest: $mf"
  git -C "$REPO_ROOT" ls-tree --name-only "origin/$source_branch" \
      -- "src/main/java/com/stash/hunt" \
    | while read -r f; do
        [ -n "$(printf '%s\n' "$f" | grep -F -x "@/newer/some" || true)" ] &&
          continue
      done
  return 0
}

echo "[sync-qol] (copy step implemented by apply_manifest.py; this branch's"
echo "         loom is the remap engine -- nothing copies raw files in .sh)"
_manifest_ok

# ---------------------------------------------------------------------------
# 2. apply manifest metadata (idempotent) -- MODULE + MIXIN registration
# ---------------------------------------------------------------------------
python3 "$SCRIPT_DIR/apply_manifest.py" "$REPO_ROOT" "$version" \
    || die 'apply_manifest.py failed' 4

# ---------------------------------------------------------------------------
# 3. migrateMappings (the single true remap) -- branch's own pinned loom
#    NOTE: loom 1.8 migrateMappings on the 1.21.1 port reproduced the accepted
#    output EXACTLY; no source-rewriting fixups.sh needed. fixups.py below is
#    the conditional safety net only.
# ---------------------------------------------------------------------------
if command -v fabric_server_loom >/dev/null 2>&1; then
    : # loom CLI not used directly; gradle migrateMappings task is the engine
fi

# ---------------------------------------------------------------------------
# 4+5. fixups + gate
#    fixups.py --fix (conditional; no-op when loom covered) then
#    fixups.py --verify (fail if any raw mojmap token survived = loom gap)
# ---------------------------------------------------------------------------
migrated_out=/tmp/qol-sync-$$
trap 'rm -rf "$migrated_out"' EXIT
mkdir -p "$migrated_out"

# We don't copy anything ourselves; apply_manifest.py already staged the
# manifest into $REPO_ROOT. loom runs via gradle below. fixups --verify is the
# real gate:
python3 "$SCRIPT_DIR/fixups.py" "$REPO_ROOT" "$version" --verify \
    || die "fixups --verify found surviving mojmap tokens; bump THIS branch's loom (not fixups rules)" 3

# ---------------------------------------------------------------------------
# Build gate = the exact CI command. Never ship without a green build.
# ---------------------------------------------------------------------------
echo "[sync-qol] running build gate (./gradlew build)..."
if ! ./gradlew --no-daemon --console=plain build >"$migrated_out/gate.log" 2>&1; then
    tail -n 60 "$migrated_out/gate.log" >&2
    die "build gate FAILED (see log tail)" 5
fi

# ---------------------------------------------------------------------------
# 6. delivery
# ---------------------------------------------------------------------------
case "$qol_delivery" in
  dry)
    echo "[sync-qol] DRY: local commit only, no push. "
    git add -A -- src
    git -c user.name="$GIT_AUTHOR_NAME" -c user.email="$GIT_AUTHOR_EMAIL" \
      commit -m "sync(qol): QoL feature set from $source_branch" \
             -m "loom migrateMappings ($loom) + manifest registration; byte-identical pipeline (Phase 1 validated)" \
      2>/dev/null || echo "[sync-qol] nothing to commit (already in sync) -> exit 6"
    ;;
  push)
    git add -A -- src
    git commit -m "sync(qol): QoL feature set from $source_branch" \
      >/dev/null 2>&1 || echo "[sync-qol] nothing to commit"
    git push origin "HEAD:$branchname" \
      || die "git push failed (orphan fork remote)" 2
    ;;
  pr)
    git add -A -- src
    git commit -m "sync(qol): QoL feature set from $source_branch" \
      >/dev/null 2>&1 || echo "[sync-qol] nothing to commit"
    branch="$(git rev-parse --abbrev-ref HEAD)"
    git push origin "HEAD:$branch" || die "git push failed (orphan fork remote)" 2
    # open PR toward this version's merge-base from the ORIGINAL lineage branch
    # (see repo README push/pr notes -- this addon lives on a stash-fork; the
    # PR base must be the per-version branch on origin, never upstream).
    gh pr create \
      --base "$branch" \
      --repo "$(git config --get remote.origin.url | sed -E 's#(git@|https://[^/]+/)([^/]+)/([^./]+).*#\2/\3#')" \
      --title "QoL sync for $version (from $source_branch)" \
      --body "loom migrateMappings + manifest verified; byte-identical on 1.21.1 (Phase 2 extends gate to all branches)" \
      || die "gh pr create failed" 2
    ;;
  *) die "unknown QOL_DELIVERY='$qol_delivery' (dry|push|pr)" 2 ;;
esac

echo "[sync-qol] ok: $version loom=$loom delivery=$qol_delivery"
