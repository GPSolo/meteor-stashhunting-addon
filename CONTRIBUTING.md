# Contributing to meteor-stashhunting-addon

Thanks for wanting to contribute! This is a Meteor Client addon that supports **8 Minecraft
versions** on separate branches. The current game branch is `26.2`, and it is the **only
branch where development happens** — everything else is an automated port of it.

## How the branch layout works (read this first)

| Branch | MC version | Mappings | Role |
|---|---|---|---|
| `26.2` | 26.2 | Mojang (mojmap) | **Default branch — all development happens here** |
| `1.21.1`, `1.21.4`, `1.21.5`, `1.21.8`, `1.21.10`, `1.21.11` | those versions | Yarn | Ports, maintained by CI |
| `26.1.2` | 26.1.2 | Mojang (mojmap) | Port, maintained by CI |

The 1.21.x and 26.1.2 branches are **never edited by hand**. A CI pipeline (`sync-base`)
keeps a small set of shared feature files in sync across all of them by running each
branch's own `migrateMappings` against the source on `26.2` and delivering pull requests.
Because of this:

- **Make all pull requests against `26.2`.**
- Changes pushed directly to a version branch are treated as outside the model and will
  be overwritten by the next sync of that feature set (or ignored entirely).

## Building locally

Requirements:

- JDK **21** to work on the `1.21.x` branches, JDK **25** for the `26.x` branches (this
  matches what CI uses).
- A working Gradle setup — the repo ships the standard Gradle wrapper (`./gradlew`).

```sh
# clone and switch to the development branch
git clone https://github.com/GPSolo/meteor-stashhunting-addon.git
cd meteor-stashhunting-addon
git checkout 26.2

# build
./gradlew build
```

The build output is `build/libs/jefff-mod-<version>.jar`. To try it in-game, drop the jar
in your `.minecraft/mods` folder — see the README for the required dependencies (Xaero's
Minimap / World Map, XaeroPlus, Baritone).

## Making changes

- Keep changes consistent with the surrounding code. This is a Meteor addon, so follow
  Meteor Client's own conventions (packages under `com.stash.hunt`, register modules in
  `Addon.java`, etc.).
- If your change touches one of the **shared synced files** (see below), say so in the PR
  description — the maintainer will run the sync pipeline after merging so it reaches every
  version branch automatically.
- If your change is **version-specific** (e.g. only relevant on one MC version), note that
  too, so it stays out of the sync set.

### The synced "QoL" feature set

These 7 files on `26.2` are the feature set that gets ported to every other version branch:

```
src/main/java/com/stash/hunt/NewerNewChunksData.java
src/main/java/com/stash/hunt/mixin/ChatComponentMixin.java
src/main/java/com/stash/hunt/mixin/ClientPacketListenerMixin.java
src/main/java/com/stash/hunt/modules/AutoEXPPlus.java
src/main/java/com/stash/hunt/modules/AutoLogPlus.java
src/main/java/com/stash/hunt/modules/TrailFollower.java
src/main/java/com/stash/hunt/modules/TripResumer.java
```

Anything inside these files must stay **branch-agnostic apart from Minecraft mappings**
(because the whole file is migrated and overwritten on every other branch). If a feature
needs per-version behavior, it should not be one of these files.

## Submitting a pull request

1. Fork the repo, create a branch from `26.2` (e.g. `fix/trail-resumer-echo`).
2. Make your change; make sure `./gradlew build` passes.
3. Open the PR **against `26.2`**, with a clear description of what and why.
4. If relevant, mention the MC version you tested on and any required dependencies.
5. Reference any related issue (`Closes #123`).

Every PR is built automatically by the **Build Pull Request** workflow; a green build is
required before it can be merged.

## Reporting bugs

Open an issue and include:

- Which branch / MC version the bug is on (`26.2`, `1.21.5`, …).
- The exact mod version (the version in the jar filename you're running).
- Your Meteor Client version and the required dependencies you have installed.
- Steps to reproduce, and any logs / crash reports (`.minecraft/crash-reports`).

## Getting help

- Check the [FAQ in the README](https://github.com/GPSolo/meteor-stashhunting-addon#faq) first.
- Open an issue, or reach out on Discord (`0x658`).