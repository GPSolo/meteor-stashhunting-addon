# jeff mod (For minecraft 1.21.1, 1.21.4, 1.21.5, 1.21.8, 1.21.10, 1.21.11, 26.1.2)
#### Make an issue or DM me on discord `0x658` with any questions (Check the FAQ first)
#### Pull Requests are welcome, please make them to the 1.21.1 branch.
#### Check the [Wiki](https://github.com/miles352/meteor-stashhunting-addon/wiki) for a full list of features and options.
## Features
### Modules
- ElytraFlyPlusPlus
  - Has a bounce mode with a baritone obstacle passer for highways, including ring-roads.
  - Motion Y Boost mode can go up to 200 bps. (Patched on 2b2t)
  - Fake fly option allows you to fly with a chestplate on to minimize lost durability. (Patched on 2b2t)
- TrailFollower (Credit to [WarriorLost](https://github.com/warriorlost) for creating the original TrailFollower this was based off)
  - Follows trails in all dimensions using either pitch40 or baritone. May break on path splits or other cases.
- TrailMaker
  - Saves the chunks you plot using the xaeros map, and adjusts your yaw to face each chunk in order as you go to each one.
- BetterStashFinder
  - Pretty much the same as meteors stash finder except some extra features:
    - It doesn't look for stashes in unloaded chunks
    - It can mark the stash finds on the Xaero Minimap
    - It can send stash hits to a discord webhook
- OldChunkNotifier
  - Sends a message to a discord webhook when old chunks are found.
- DiscordNotifs
  - Logs different things to a discord webhook.
- Pitch40Util
  - Used alongside meteors pitch40. Auto sets min and max bounds so that you continue to gain height. Also has an auto firework mode for when you lose velocity.
- NoJumpDelay
  - Removes the delay between jumping.
- GrimAirPlace
  - Meteor's airplace code but with a grim bypass.
- Search Area
  - Requires some other mod to make you move.
  - Spirals you or goes in a rectangle area by changing where you look.
- AutoLogPlus
  - Provides some additional triggers to log out, such as logging at a certain Y value, or on low armor durability.
- ChestIndex
  - Automatically opens chests in range and collects a list of every item inside. They can then be printed to the chat in different ways. You can also save them to a JSON file.
- GotoPosition
  - Looks at the position specified and holds w.
- HighlightOldLava
  - Highlights lava that is of a certain height. This used to be helpful for tracing paths in the nether but with new pallete newchunks its not really useful.
- AFKVanillaFly (Made by [xqyet](https://github.com/xqyet))
  - Keeps you at the same Y value by adjusting your pitch up and down, and uses rockets to keep you moving.
- VanityESP (Made by [xqyet](https://github.com/xqyet))
  - Highlights item frames that have mapart in them, and banners.
- AutoPortal (Made by [xqyet](https://github.com/xqyet))
  - Automatically places and lights a portal.
### HUD
- Weather
  - Displays the current weather in the world.
- EntityList
  - Displays the count of all the entities within render distance. (Made by [g-a-l-a-x-i-a](https://github.com/g-a-l-a-x-i-a))

## Maintenance: Base Sync (whole src tree)
The ENTIRE `src/main/java` tree (canonical on the `26.2` base branch) is kept in sync
across every version branch with an automated pipeline
(`sync-base` workflow → `.github/scripts/sync-base.sh`). CommandExample, a HUD module, a
mixins tweak — anything committed under `src/main/java` on `26.2` reaches every supported
version.

How it works:
- A run creates a dedicated worktree from `origin/<target>` on a `sync/base-26.2-to-<target>`
  branch (**the target branch itself is never touched**) and delivers as PRs.
- Yarn targets (1.21.x): the whole tree is run through loom `migrateMappings` with that
  branch's own pinned loom, residual mechanical fixups are applied (`.github/scripts/fixups.py`),
  and mixin registration in `mixins.json` is auto-applied idempotently (`.github/scripts/apply_manifest.py`).
  The target's `src/main/java` is then **replaced** by the migrated tree (mirror semantics).
- Mojmap target (26.1.2): the tree is copied verbatim; `apply_manifest` also adds the
  `compileOnly fabric-resource-loader-v1` line mirroring 26.2's build.gradle (the 26.x
  merged game jar declares `MinecraftServer implements DataResourceStore`).
- `src/main/resources` (mixins.json, fabric.mod.json) is never overwritten — mixins are
  auto-registered, per-branch metadata stays put.
- The pipeline mirrors the whole tree even when a gate fails: if the `./gradlew build` gate
  (exit `5`) or `fixups --verify` (exit `3`) fails, the migrated tree is **still delivered** as
  a PR marked with the failing check + a log excerpt, so remaining port issues can be fixed
  directly on the sync branch instead of stalling the pipeline. The run stays red; exit codes:
  `0` ok, `2` usage/ref, `3` migrate crash (no PR) or fixups verify (delivered), `4` manifest
  (no PR), `5` build gate (delivered), `6` already in sync.
- PR titles describe what is being added (set `pr_title` at dispatch); PR bodies list the
  source commits being ported (delta since the `base-source.txt` "Last synced from" pin).

Dispatch inputs (`workflow_dispatch` on the default branch):
- `version` — target branch(es), comma-separated, e.g. `1.21.1,1.21.8,26.1.2`.
- `source_branch` — base source (default `26.2`).
- `source_ref` — pin an exact source commit (empty = live `origin/<source_branch>` HEAD).
- `delivery` — `dry` (local commit only), `push`, or `pr` (default; opens/refreshes the PR).
- `loom` — override the target's loom pin (empty = branch pin).
- `pr_title` — PR title message describing what is being added (empty = default
  `Base sync: 26.2 -> <target>`).

Locally: `SYNC_DELIVERY=dry bash .github/scripts/sync-base.sh --target 1.21.1`

## FAQ
- Q: How do I install this / where is the jar file?
  - A: Download the latest release from the releases tab on the right and put it in your mods folder.
- Q: Why isn't mod x showing up?
  - A: Make sure you have the required dependencies. For all mods to work it is recommended to have [XaeroPlus](https://github.com/rfresh2/XaeroPlus), [Xaero's Minimap](https://modrinth.com/mod/xaeros-minimap), [Baritone](https://github.com/cabaletta/baritone), and [Xaero's World Map](https://modrinth.com/mod/xaeros-world-map). Sometimes the baritone versions from the official repo do not work, I would recommend downloading the meteor version from the link at the bottom of this page.
- Q: Why is Search Area going in a straight line?
  - A: Search Area automatically saves your path, and will go back to where you left off if you start it again. If you want to make a new path, change the name or click the reset button.
- Q: Why is my game crashing?
  - A: There is a known crash when switching the modes on Search Area while using it - don't do that. Another common crash is due to using PathSeeker with this mod, if you are using that, try removing it and see if it fixes it first. Otherwise, please make an issue or DM me the crash report found in .minecraft/crash-reports.

# [Older Versions of Baritone / Meteor](https://maven.meteordev.org/#/snapshots/meteordevelopment/) 
