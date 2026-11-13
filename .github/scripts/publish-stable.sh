#!/usr/bin/env bash
# One stable release per addon version; each MC branch uploads its own asset.
set -euo pipefail

: "${RELEASE_BRANCH:?Missing Minecraft version branch}"
: "${GITHUB_REPOSITORY:?Missing repository}"
[[ "$RELEASE_BRANCH" =~ ^(1\.21\.[0-9]+|26\.[0-9]+(\.[0-9]+)?)$ ]] || {
  echo "Invalid Minecraft version branch: $RELEASE_BRANCH" >&2; exit 1;
}

MOD_VERSION="$(sed -n 's/^mod_version=//p' gradle.properties | tr -d '\r')"
ARCHIVE_BASE="$(sed -n 's/^archives_base_name=//p' gradle.properties | tr -d '\r')"
RELEASE_VERSION="${MOD_VERSION%%-*}"
[[ "$RELEASE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "Invalid stable addon version: $MOD_VERSION" >&2; exit 1;
}
case "$MOD_VERSION" in
  "${RELEASE_VERSION}-${RELEASE_BRANCH}"|"${RELEASE_VERSION}-SNAPSHOT-${RELEASE_BRANCH}") ;;
  *) echo "mod_version does not match branch $RELEASE_BRANCH: $MOD_VERSION" >&2; exit 1 ;;
esac

# The release tag has NO MC suffix and NO v prefix (e.g. 0.16.8).
TAG="$RELEASE_VERSION"
JAR="build/libs/${ARCHIVE_BASE}-${MOD_VERSION}.jar"
ASSET="build/libs/jefff-mod-${RELEASE_VERSION}-${RELEASE_BRANCH}.jar"
[[ -f "$JAR" ]] || { echo "Built jar missing: $JAR" >&2; exit 1; }
if [[ "$JAR" != "$ASSET" ]]; then cp "$JAR" "$ASSET"; fi
HEAD_SHA="$(git rev-parse HEAD)"

upload_asset() {
  # Only replace this exact MC branch asset; never delete other versions.
  gh release upload "$TAG" "$ASSET" --repo "$GITHUB_REPOSITORY" --clobber
}

if gh release view "$TAG" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  upload_asset
elif ! gh release create "$TAG" "$ASSET" \
    --repo "$GITHUB_REPOSITORY" \
    --title "$RELEASE_VERSION" \
    --notes "Stable release ${RELEASE_VERSION}. Download the jar matching your Minecraft version; additional version builds are attached to this same release." \
    --target "$HEAD_SHA" --latest; then
  # Another MC branch may have created the shared release concurrently.
  # Fail real creation/upload errors instead of silently skipping the asset.
  gh release view "$TAG" --repo "$GITHUB_REPOSITORY" >/dev/null
  upload_asset
fi

# Preserve the existing title and notes when adding an asset to a release.
gh release edit "$TAG" --repo "$GITHUB_REPOSITORY" --latest
echo "Published $(basename "$ASSET") to shared stable release $TAG ($HEAD_SHA)."
