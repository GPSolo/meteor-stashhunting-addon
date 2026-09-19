# Development, Releases & Automation (maintainer reference)

Everything a maintainer needs to release, pre-release, and sync this project, plus how the
GitHub Actions automation works. Contributors should read
[CONTRIBUTING.md](./CONTRIBUTING.md) instead.

---

## 1. Repo & version model

**Branches** (8 version branches; `26.2` is the default and the only one you develop on):

- `26.2` — Mojang-mapped (mojmap), the **base/source branch** for all syncs and the
  current game version.
- `26.1.2` — mojmap port (kept in sync via `sync-base`).
- `1.21.1`, `1.21.4`, `1.21.5`, `1.21.8`, `1.21.10`, `1.21.11` — yarn-mapped ports.
- `sync/base-26.2-to-<target>` — short-lived sync branches created by the pipeline (you
  review/merge them as PRs; never commit to them directly).

**Version scheme** — `mod_version` in `gradle.properties` is `0.16.8-<branch>` per branch
(jar: `jefff-mod-0.16.8-26.2.jar`). `gradle.properties` is **not** part of the sync
manifest — version bumps are manual, per branch.

**TL;DR of the three things you can do** (details below):

| You want to… | Do this |
|---|---|
| Get a fresh test jar into the pre-release channel | Nothing — happens automatically on every push to any version branch |
| Manually trigger a pre-release build | Actions → **Publish Pre-Release** → Run workflow (pick branch) |
| Cut the next stable release | Bump `mod_version` (optional) → Actions → **Publish Release** |
| Port 26.2 changes to the other versions | Actions → **sync-base** → Run workflow |

---

## 2. GitHub Actions catalog

| Workflow | File | Triggers | What it does |
|---|---|---|---|
| **Build Pull Request** | `.github/workflows/pull_request.yml` | `pull_request` | Builds every PR with JDK 21 and uploads `build/libs` as an artifact (the merge gate). |
| **Publish Pre-Release** | `.github/workflows/publish.yml` | `push` to the 8 version branches + `workflow_dispatch` | Builds the pushed branch and updates the **single** pre-release channel `v<next>-pre` (currently `v0.16.9-pre`). Never marks `Latest`. |
| **Publish Release** | `.github/workflows/release.yml` | `workflow_dispatch` | Builds the chosen branch and creates the **stable** release `v<mod_version>` (prerelease-label off, marked `Latest`). |
| **sync-base** | `.github/workflows/sync-base.yml` | `workflow_dispatch` | Ports the 7-file QoL feature set from `26.2` to the requested target branch(es) and delivers PRs. |

---

### 2.1 Publish Pre-Release (`publish.yml`)

- Tags the release **`v0.16.9-pre`** ("Pre-release 0.16.9"). The next-version label lives in
  the workflow as `CHANNEL_VERSION="0.16.9"` — bump it when you cut each stable release
  (it does **not** change `mod_version` or jar internals).
- **One channel for all versions**: each run replaces only its own branch's jar, so the
  channel ends up holding the latest jar for every supported version.
- **Asset naming** — jars are renamed on upload so each one is self-identifying:

  ```
  jefff-mod-<channel-version>-<branch>-<commit-sha>.jar
  jefff-mod-0.16.9-26.2-abc1234.jar      # 26.2 build at commit abc1234
  jefff-mod-0.16.9-1.21.5-6d32437.jar    # 1.21.5 build at commit 6d32437
  ```

- Update path is idempotent and race-safe: if the tag exists it replaces this branch's old
  jar(s) (both the original `jefff-mod-...-<branch>.jar` and new-style names; the branch
  token is regex-anchored so `1.21.1` can never delete `1.21.10`/`1.21.11` jars); if the
  tag is missing it creates it, and if a concurrent run created it first it falls back to
  the update path.
- JDK is chosen per branch: **25** for `26.x`, **21** for `1.21.x`.

### 2.2 Publish Release (`release.yml`)

Manual stable-cut. Inputs:

| Input | Default | Meaning |
|---|---|---|
| `branch` | `26.2` | Version branch to release. |
| `version` | *(empty)* | Optional `mod_version` override (e.g. `0.16.9-26.2`). Applied only in the runner's `gradle.properties` — **nothing is committed**. |

It builds, then publishes tag **`v<mod_version>`** (or `v<version>` when overridden),
title `jefff-mod <version>`, not a pre-release, marked **Latest**. Idempotent: re-running
with an existing tag is a no-op.

> Stable and pre-release never collide: stable = `v0.16.8-26.2`, pre-release channel =
> `v0.16.9-pre`. Releasing does not touch the channel and vice-versa.

### 2.3 sync-base (`sync-base.yml`)

Ports the **7-file QoL feature set** (`base-source.txt`, canonical on `26.2`) into target
version branches using **each target's own pinned loom `migrateMappings`**, delivered as
PRs. See [section 4](#4-syncing-the-base-feature-set) for usage and
[section 5](#5-sync-pipeline-internals) for internals.

---

## 3. Making releases

### Pre-release (test jars)

**Automatic** — any `git push` to `26.2` (or any version branch) builds and drops that
branch's jar into `v0.16.9-pre`. That's your normal dev/test loop: commit → push → grab
the fresh jar from the pre-release.

**Manual** — Actions → **Publish Pre-Release** → Run workflow (leave defaults; dispatch
builds the selected branch). Useful to rebuild without a commit.

The pre-release channel is **never** marked Latest, so the stable release's badge is
unaffected.

### Stable release (cut a version)

1. *(Optional but recommended)* Bump `mod_version` in `gradle.properties` on the branch(es)
   you're releasing — e.g. `0.16.9-26.2` — commit and push.
2. Actions → **Publish Release** → Run workflow. Pick `branch` (and `version` instead of
   step 1 if you want an override without a commit).
3. Wait for the run → verify the new `v<version>` release is `Latest` with the jar attached.
4. **(Once per cycle)** If you bumped the version, update `CHANNEL_VERSION` in
   `publish.yml` to the *next* version (e.g. `0.16.10`) and push — this is just the label of
   the pre-release channel.

---

## 4. Syncing the base feature set

### When to sync

After merging changes to **any of the 7 synced files** on `26.2`. Files:

```
src/main/java/com/stash/hunt/NewerNewChunksData.java
src/main/java/com/stash/hunt/mixin/ChatComponentMixin.java
src/main/java/com/stash/hunt/mixin/ClientPacketListenerMixin.java
src/main/java/com/stash/hunt/modules/AutoEXPPlus.java
src/main/java/com/stash/hunt/modules/AutoLogPlus.java
src/main/java/com/stash/hunt/modules/TrailFollower.java
src/main/java/com/stash/hunt/modules/TripResumer.java
```

### How to run it

Actions → **sync-base** → Run workflow. Inputs:

| Input | Default | Meaning |
|---|---|---|
| `version` | `1.21.1,1.21.4,1.21.5,1.21.8,1.21.10,1.21.11,26.1.2` | Target branch(es), comma-separated, no spaces. |
| `source_branch` | `26.2` | Base/QoL source branch (manifest files are ported from here). |
| `source_ref` | *(empty)* | Pin source to an exact commit; empty = live `origin/<source_branch>` HEAD. |
| `delivery` | `pr` | `dry` (local commit, no push) · `push` (push sync branch) · `pr` (push + open/refresh PR). |
| `loom` | *(empty)* | Loom version override; empty = the target branch's pin. |
| `pr_title` | *(empty)* | PR title message, e.g. `TripResumer echo fix` → `Base sync: TripResumer echo fix (26.2 -> 1.21.5)`. |

### What comes out

One PR per target: `sync/base-26.2-to-<target>` → base `1.21.5` (etc.). **The target branch
itself is never touched.** Each PR body lists the source commits being ported. Review and
merge. A green `./gradlew build` is mandatory first (exit `6` = "already in sync" is a
normal, green no-op).

**After the PRs merge**, bump the informational pin in
`.github/scripts/base-source.txt` (`Last synced from: 26.2 @ <sha>`) and commit on `26.2`.

**Local equivalent:** `SYNC_DELIVERY=dry bash .github/scripts/sync-base.sh --target 1.21.5`
(needs a full clone, not just a worktree, plus JDK 21/25 per target).

---

## 5. Sync pipeline internals

`sync-base.sh` (consumes `base-source.txt`, `fixups.py`, `apply_manifest.py`):

1. Create `sync/base-<source>-to-<target>` in a **dedicated worktree** (`sync-tmp/`) —
   run-to-run state can never leak.
2. Copy the **7 manifest files** (mojmap) from the source; temporarily point the target's
   mappings at official Mojang mappings for the *same* MC version and run:
   `./gradlew migrateMappings` with the target's yarn pin; restore `build.gradle`.
3. `fixups.py` — small mechanical residual fixes loom leaves behind for that toolchain
   generation (`--verify` fails if any raw mojmap token survives).
4. `apply_manifest.py` — idempotent metadata: module + mixin registration; for **mojmap
   targets only** it also mirrors 26.2's `compileOnly fabric-resource-loader-v1` line in
   `build.gradle` (26.x merged jars declare `MinecraftServer implements DataResourceStore`;
   only `fabric-resource-loader-v1` provides it).
5. **Gate:** `./gradlew build` — nothing ships without green.
6. **Deliver:** `dry` / `push` / `pr` (PR base = target branch, head = sync branch).

**Exit codes:** `0` ok · `2` usage/ref · `3` migrate/fixups (loom generation gap — fix by
bumping *that branch's* loom, never by widening fixups) · `4` manifest · `5` build gate ·
`6` already in sync (no-op).

**Manifest rules** (`.github/scripts/base-source.txt`): (1) each line must exist on the
source branch; (2) files must be branch-agnostic apart from MC mappings — never add a file
with version-specific content; (3) `Addon.java`, `*mixins.json`, `build.gradle`,
`gradle.properties` are handled **only** by `apply_manifest.py` idempotent inserts.

**Workflow mechanics:** a tiny `matrix-prep` bash job splits the comma-separated `version`
input into JSON (GitHub expressions have no string `replace`); each target runs in its own
`sync-base-<target>` concurrency group (parallel across targets, serial within one);
tooling scripts are pulled from the default branch via `git archive origin/26.2
.github/scripts`; per-target artifacts `sync-tmp/migrate.log` + `gate.log` are uploaded.

---

## 6. Local dev environment notes

- **JDKs:** 1.21.x branches build with JDK 21, 26.x with JDK 25 — keep both installed
  (matching what CI pins).
- **Per-branch checkouts:** the repo is usually checked out as one worktree per version
  branch (e.g. `Base-26.2/`, `1.21.5/`). The root holding them is **not** a git checkout.
- **Pushing `/.github/workflows` changes**: requires a GitHub token with the `workflow`
  scope. With the `gh` CLI: `gh auth refresh -h github.com -s workflow`, and use HTTPS
  transport (`gh config set git_protocol https -h github.com`).
- `CheckBuilds.sh` (local, untracked) is a helper that builds each version branch in turn —
  a plain `./gradlew build` per branch does the same.