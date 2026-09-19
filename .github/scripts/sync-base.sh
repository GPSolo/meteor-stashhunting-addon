#!/usr/bin/env bash
# =============================================================================
# sync-base.sh -- base-branch (QoL) feature-set synchronizer
#
# Ports the base feature set (the 7 files in base-source.txt) from the source
# branch (26.2 -- canonical, mojmap/unobfuscated) into a TARGET version branch
# (yarn-mapped 1.21.x) via **that branch's own pinned loom migrateMappings**:
#
#   1. Create a per-sync branch from the target in a DEDICATED WORKTREE
#      (sync-tmp/worktree), so run-to-run state can never leak between syncs:
#        sync/base-<source>-to-<target>
#      The target branch itself is NEVER touched (delivery is PR-based).
#
#   2. Copy the 7 manifest files from the source commit. The source is written
#      in Mojang-mapped names; loom's migrateMappings task converts the project's
#      "from" namespace, so for yarn targets we temporarily point the project's
#      mappings at official Mojang mappings for the SAME minecraft version, then
#      run:
#        ./gradlew migrateMappings --input <manifest-only dir> \
#                                  --output <migrated dir> \
#                                  --mappings <branch yarn_mappings>
#      and restore build.gradle. loom 1.8 -> 1.14 all accept these options.
#
#   3. fixups.py --fix   : apply the small mechanical residual set loom leaves
#                          behind for that toolchain generation (validated
#                          byte-for-byte against the accepted 1.21.1 port).
#      fixups.py --verify: fail if any raw mojmap token survives migration.
#
#   4. apply_manifest.py : idempotent metadata edits (module + mixin
#                          registration; plus, for MOJMAP targets only, the
#                          build.gradle compileOnly fabric-resource-loader-v1
#                          mirror of 26.2 -- see the 26.x merged-jar
#                          MinecraftServer/DataResourceStore note) -- the only
#                          thing that touches Addon.java / *mixins.json /
#                          build.gradle, never their per-branch content.
#
#   5. GATE: ./gradlew build -- the same gate CI runs. If it fails, nothing is
#      pushed and the run exits non-zero.
#
#   6. DELIVERY:
#        dry (default) -> commit on the sync branch locally, NO push.
#        push          -> commit + push the sync branch.
#        pr            -> commit + push sync branch + open/refresh the PR
#                         (base = target branch, head = sync branch).
#
# EXIT CODES:
#   0  success (migrate + fixups + manifest + gate all green, delivered)
#   2  usage / missing tool / bad ref
#   3  migrateMappings failed or fixups --verify found surviving mojmap tokens
#      (loom generation gap; fix by bumping THIS branch's loom -- never by
#      widening fixups rules to swallow mojmap output)
#   4  manifest application/verification failed
#   5  build gate failed
#   6  no changes (already in sync -- normal no-op)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"

die() { printf 'fatal: %s\n' "$*" >&2; exit "${2:-2}"; }

# ---------------------------------------------------------------------------
# args
# ---------------------------------------------------------------------------
source_branch="26.2"
source_ref=""
target=""
delivery=""
loom_override=""
pr_title=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source-branch=*) source_branch="${1#*=}"; shift ;;
    --source-branch)   source_branch="$2"; shift 2 ;;
    --source=*)        source_ref="${1#*=}"; shift ;;
    --source)          source_ref="$2"; shift 2 ;;
    --target=*)        target="${1#*=}"; shift ;;
    --target)          target="$2"; shift 2 ;;
    --delivery=*)      delivery="${1#*=}"; shift ;;
    --delivery)        delivery="$2"; shift 2 ;;
    --loom=*)          loom_override="${1#*=}"; shift ;;
    --loom)            loom_override="$2"; shift 2 ;;
    --pr-title=*)      pr_title="${1#*=}"; shift ;;
    --pr-title)        pr_title="$2"; shift 2 ;;
    *) die "unknown argument: $1" 2 ;;
  esac
done

[ -n "$source_branch" ] || source_branch="26.2"
delivery="${delivery:-${SYNC_DELIVERY:-dry}}"
case "$delivery" in dry|push|pr) ;; *) die "unknown delivery '$delivery' (dry|push|pr)" 2 ;; esac

cd "$REPO_ROOT"
[ -n "$target" ] || target="$(git rev-parse --abbrev-ref HEAD)"

# git identity: CI runners have no user.name/user.email configured, so
# `git commit` dies with "Author identity unknown". Supply a bot identity via
# GIT_AUTHOR_*/GIT_COMMITTER_* env ONLY when config is missing -- local
# checkouts keep their own configured author.
if ! git config user.name >/dev/null 2>&1 || ! git config user.email >/dev/null 2>&1; then
  export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-github-actions[bot]}"
  export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
  export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
  export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
fi

# ---------------------------------------------------------------------------
# resolve source commit
#   --source given? use it (branch, ref or sha) -- the workflow defaults this
#   to the LIVE origin/<source_branch> HEAD so new 26.2 commits propagate.
#   otherwise: origin/<source_branch> HEAD; fallback to the base-source.txt pin
#   (validated baseline) if the live branch cannot be resolved.
# ---------------------------------------------------------------------------
pin="$(sed -nE 's/^# Last synced from: [^@]+ @ ([0-9a-f]{7,40}).*/\1/p' \
  "$SCRIPT_DIR/base-source.txt" | head -1)"
if [ -z "$source_ref" ]; then
  if git cat-file -e "origin/${source_branch}^{commit}" >/dev/null 2>&1; then
    source_ref="origin/${source_branch}"
  elif [ -n "$pin" ] && git cat-file -e "${pin}^{commit}" >/dev/null 2>&1; then
    echo "[sync-base] warning: origin/${source_branch} not found; using base-source.txt pin ${pin:0:12}"
    source_ref="$pin"
  else
    die "cannot resolve source: origin/${source_branch} not found and no valid pin in base-source.txt"
  fi
fi
if ! git cat-file -e "${source_ref}^{commit}" >/dev/null 2>&1; then
  die "source ref not found: ${source_ref}"
fi
source_ref="$(git rev-parse --verify "${source_ref}^{commit}")"
echo "[sync-base] source: ${source_branch} @ ${source_ref:0:12} (baseline pin: ${pin:-none})"
echo "[sync-base] target: ${target} (branch: $(git rev-parse --abbrev-ref HEAD))"

# ---------------------------------------------------------------------------
# manifest (paths relative to src/main/java/com/stash/hunt/)
# ---------------------------------------------------------------------------
MANIFEST="$SCRIPT_DIR/base-source.txt"
[ -f "$MANIFEST" ] || die "missing manifest: $MANIFEST"
mapfile -t MANIFEST_FILES < <(grep -vE '^\s*(#|$)' "$MANIFEST")
[ "${#MANIFEST_FILES[@]}" -gt 0 ] || die "manifest is empty: $MANIFEST"

sync_branch="sync/base-${source_branch}-to-${target}"
sync_tmp="$REPO_ROOT/sync-tmp"
wt="$sync_tmp/worktree"

# ---------------------------------------------------------------------------
# 1. dedicated WORKTREE at the target tip (the target branch itself stays
#    untouched; because every run starts from a fresh worktree, dirty state
#    from a previous run -- e.g. a failed gate -- can never leak into this
#    one. The sync branch is force-created inside the worktree.)
# ---------------------------------------------------------------------------
git worktree remove --force "$wt" 2>/dev/null || true
rm -rf "$sync_tmp"; mkdir -p "$sync_tmp"
trap 'git worktree remove --force "$wt" 2>/dev/null || true' EXIT

if git ls-remote --exit-code origin "refs/heads/$sync_branch" >/dev/null 2>&1; then
  echo "[sync-base] deleting stale remote ${sync_branch} (PR, if any, is refreshed on re-push)"
  git push origin --delete "$sync_branch" >/dev/null 2>&1 || true
fi
git branch -D "$sync_branch" 2>/dev/null || true
git worktree add -B "$sync_branch" "$wt" "origin/$target" >/dev/null \
  || die "could not create worktree ${wt} (branch ${sync_branch} from origin/${target})"
cd "$wt"

# ---------------------------------------------------------------------------
# branch gradle metadata (forge/loom pins: gradle.properties AND build.gradle)
# -- resolved inside the WORKTREE so the TARGET's pins are read, never the
#    checkout the script happened to be launched from.
# ---------------------------------------------------------------------------
[ -f gradle.properties ] || die "no gradle.properties in $(pwd)"
mc_version="$(grep -E '^minecraft_version=' gradle.properties | cut -d= -f2)"
yarn="$(grep -E '^yarn_mappings=' gradle.properties | cut -d= -f2 || true)"
loom="$(grep -E '^loom_version=' gradle.properties | cut -d= -f2 || true)"
if [ -z "$loom" ]; then
  loom="$(sed -nE 's/.*id "fabric-loom" version "([^"]+)".*/\1/p' build.gradle 2>/dev/null | head -1 || true)"
fi
if [ -z "$loom" ]; then
  loom="$(sed -nE "s/.*id 'net\\.fabricmc\\.fabric-loom' version '([^']+)'.*/\\1/p" build.gradle 2>/dev/null | head -1 || true)"
fi
[ -n "$mc_version" ] || die "gradle.properties missing minecraft_version"
if [ -n "$loom_override" ]; then loom="$loom_override"; fi
is_mojmap=0
[ -z "$yarn" ] && is_mojmap=1   # no yarn_mappings -> unobfuscated/mojmap target
echo "[sync-base] mc=${mc_version} loom=${loom:-<none>} yarn=${yarn:-<none/mojmap>} mojmap_target=$is_mojmap"

import_dir="$sync_tmp/import/src/main/java"
migrated_dir="$sync_tmp/migrated"
mkdir -p "$import_dir" "$migrated_dir"

# copy manifest files from source into the import tree (mojmap-written)
for f in "${MANIFEST_FILES[@]}"; do
  src_path="src/main/java/com/stash/hunt/${f}"
  if ! git cat-file -e "${source_ref}:${src_path}" >/dev/null 2>&1; then
    die "source ${source_ref:0:12} missing manifest path: ${src_path}"
  fi
  mkdir -p "$import_dir/com/stash/hunt/$(dirname "$f")"
  git show "${source_ref}:${src_path}" > "$import_dir/com/stash/hunt/${f}"
done
echo "[sync-base] imported ${#MANIFEST_FILES[@]} manifest files from ${source_branch}"

# ---------------------------------------------------------------------------
# 2+3. migrate + fixups (yarn targets only)
# ---------------------------------------------------------------------------
if [ "$is_mojmap" -eq 1 ]; then
  echo "[sync-base] mojmap/unobfuscated target: copying manifest verbatim (no loom migrate)"
  for f in "${MANIFEST_FILES[@]}"; do
    cp "$import_dir/com/stash/hunt/${f}" "src/main/java/com/stash/hunt/${f}"
  done
else
  # point the project's "from" namespace at official mojmap for THIS mc version
  if ! grep -q 'mappings "net\.fabricmc:yarn:\${project\.yarn_mappings}:v2"' build.gradle; then
    die "unexpected mappings line shape in build.gradle (expected yarn \${project.yarn_mappings}) -- refusing to patch"
  fi
  cp build.gradle "$sync_tmp/build.gradle.bak"
  sed -i 's#mappings "net\.fabricmc:yarn:\${project\.yarn_mappings}:v2"#mappings loom.officialMojangMappings()#' build.gradle

  echo "[sync-base] running loom migrateMappings (${loom}) mojmap -> yarn(${yarn})..."
  if ! ./gradlew --no-daemon --console=plain migrateMappings \
      --input "$import_dir" \
      --output "$migrated_dir" \
      --mappings "$yarn" >"$sync_tmp/migrate.log" 2>&1; then
    mv "$sync_tmp/build.gradle.bak" build.gradle
    tail -n 60 "$sync_tmp/migrate.log" >&2
    die "loom migrateMappings FAILED (log tail above); build.gradle restored" 3
  fi
  mv "$sync_tmp/build.gradle.bak" build.gradle

  echo "[sync-base] applying residual fixups..."
  python3 "$SCRIPT_DIR/fixups.py" "$migrated_dir" "$mc_version" --fix \
    || die "fixups.py --fix failed" 3
  python3 "$SCRIPT_DIR/fixups.py" "$migrated_dir" "$mc_version" --verify \
    || die "fixups --verify found surviving mojmap tokens; bump THIS branch's loom (not the rules)" 3

  for f in "${MANIFEST_FILES[@]}"; do
    migrated_file="$migrated_dir/com/stash/hunt/${f}"
    [ -f "$migrated_file" ] || die "migrateMappings produced no output for ${f}"
    cp "$migrated_file" "src/main/java/com/stash/hunt/${f}"
  done
  echo "[sync-base] migrated ${#MANIFEST_FILES[@]} files into src/"
fi

# ---------------------------------------------------------------------------
# 4. manifest metadata (idempotent) -- MODULE + MIXIN registration
# ---------------------------------------------------------------------------
python3 "$SCRIPT_DIR/apply_manifest.py" "$wt" apply \
  || die "apply_manifest.py failed" 4
python3 "$SCRIPT_DIR/apply_manifest.py" "$wt" verify \
  || die "apply_manifest.py verify failed" 4

# ---------------------------------------------------------------------------
# 5. build gate -- never ship without a green build
# ---------------------------------------------------------------------------
echo "[sync-base] running build gate (./gradlew build)..."
if ! ./gradlew --no-daemon --console=plain build >"$sync_tmp/gate.log" 2>&1; then
  tail -n 60 "$sync_tmp/gate.log" >&2
  die "build gate FAILED (see log tail)" 5
fi
echo "[sync-base] build gate green"

# ---------------------------------------------------------------------------
# 6. delivery
# ---------------------------------------------------------------------------
git add -A -- src
# mojmap targets: apply_manifest.py also edits build.gradle (mirrors 26.2's
# compileOnly fabric-resource-loader-v1 -- the 26.x merged game jar declares
# MinecraftServer implements that fabric interface). Stage it so the PR
# carries the change; yarn targets never diff build.gradle here.
if [ "$is_mojmap" -eq 1 ] && ! git diff --quiet -- build.gradle; then
  git add build.gradle
fi
if git diff --cached --quiet; then
  echo "[sync-base] nothing to commit -- already in sync -> exit 6"
  exit 6
fi

base="$(sed -nE 's/^# Last synced from: [^@]+ @ ([0-9a-f]+).*/\1/p' "$MANIFEST" | head -1 || true)"
delta=""
if [ -n "$base" ] && git cat-file -e "${base}^{commit}" >/dev/null 2>&1; then
  delta="$(git log --oneline --no-merges "${base}..${source_ref}" -- "src/main/java/com/stash/hunt" 2>/dev/null | head -20 || true)"
fi
[ -n "$delta" ] || delta="(no new source commits since baseline ${base:-none}; initial/refresh port)"

title="Base sync: ${source_branch} -> ${target}"
[ -n "$pr_title" ] && title="Base sync: ${pr_title} (${source_branch} -> ${target})"
body="Automated base-branch synchronization.

- Source: ${source_branch} @ ${source_ref:0:12}
- Target: ${target}
- Loom: ${loom}${is_mojmap:+ (mojmap target -- verbatim copy, no migration)}
- Pipeline: loom migrateMappings (via ${SCRIPT_DIR}) + residual fixups + manifest registration + \`./gradlew build\` gate.

Source commits being ported:
${delta}

Please review: mixin \`@Inject(method=...)\` strings, chunk coordinate accessors and any API that changed between Minecraft versions. Resolve remaining porting issues manually, then merge."

git commit -m "sync(base): ${source_branch} -> ${target}" \
         -m "loom migrateMappings + residual fixups + manifest registration; build gate green." \
  >/dev/null

case "$delivery" in
  dry)
    echo "[sync-base] DRY: committed locally on ${sync_branch}, NOT pushed."
    git --no-pager diff --stat origin/"$target"...HEAD || true
    ;;
  push)
    git push --set-upstream origin "$sync_branch" || die "git push failed" 2
    echo "[sync-base] PUSHED ${sync_branch} (to be merged into ${target})"
    ;;
  pr)
    git push --set-upstream origin "$sync_branch" || die "git push failed" 2
    if command -v gh >/dev/null 2>&1; then
      repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
      [ -n "$repo" ] || repo="${GITHUB_REPOSITORY:-}"
      if [ -z "$repo" ]; then die "cannot determine repo for gh" 2; fi
      existing="$(gh pr view "$sync_branch" --repo "$repo" --json url --jq .url 2>/dev/null || true)"
      if [ -n "$existing" ]; then
        echo "[sync-base] PR already open: ${existing}"
        gh pr edit "$sync_branch" --repo "$repo" --title "$title" --body "$body" >/dev/null 2>&1 \
          || echo "[sync-base] warn: gh pr edit failed (PR still updated by push)"
      else
        gh pr create \
          --repo "$repo" \
          --base "$target" \
          --head "$sync_branch" \
          --title "$title" \
          --body "$body" \
          || die "gh pr create failed" 2
      fi
    else
      echo "[sync-base] gh not available; pushed ${sync_branch}, open the PR manually"
    fi
    ;;
esac

echo "[sync-base] ok: ${target} loom=${loom} delivery=${delivery}"