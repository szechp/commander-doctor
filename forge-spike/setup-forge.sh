#!/usr/bin/env bash
# Set up the Forge build the battlebox sims run on: clone Forge at a pinned
# commit into forge-spike/forge, apply our end-step snapshot logging hook
# (forge-snapshot-hook.patch, read by `deckdoctor sim analyze`), and build the
# desktop jar.
#
# Safe to re-run: every step is skipped when it is already done, so it can sit
# in a cloud environment's setup script or a fresh checkout's first run.
#
#   forge-spike/setup-forge.sh                     # pinned commit
#   FORGE_REF=master forge-spike/setup-forge.sh    # try a newer Forge
#
# Results from different Forge commits are not directly comparable (the AI
# changes), so record the commit with any new round.
set -euo pipefail

FORGE_REF="${FORGE_REF:-aa77ec917b035a4fadf7d92bfe6e72dfad53f65e}"  # 2026-10-25, used from r7a on
HERE="$(cd "$(dirname "$0")" && pwd)"
FORGE="${FORGE_DIR:-$HERE/forge}"
PATCH="$HERE/forge-snapshot-hook.patch"

if [ ! -d "$FORGE/.git" ]; then
  git clone -q --filter=blob:none https://github.com/Card-Forge/forge.git "$FORGE"
fi
if [ "$(git -C "$FORGE" rev-parse HEAD)" != "$(git -C "$FORGE" rev-parse "$FORGE_REF^{commit}" 2>/dev/null || true)" ]; then
  git -C "$FORGE" fetch -q --filter=blob:none origin "$FORGE_REF"
  git -C "$FORGE" checkout -- .
  git -C "$FORGE" checkout -q --detach FETCH_HEAD
  rm -f "$FORGE"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar
fi

if git -C "$FORGE" apply --reverse --check "$PATCH" 2>/dev/null; then
  echo "snapshot hook already applied"
else
  git -C "$FORGE" apply "$PATCH"
  rm -f "$FORGE"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar
fi

if ls "$FORGE"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar >/dev/null 2>&1; then
  echo "Forge jar already built"
else
  # Forge needs Java 17+. On NixOS, without one on PATH, nix supplies it.
  if command -v mvn >/dev/null && java -version 2>&1 | grep -qE 'version "(1[7-9]|[2-9][0-9])'; then
    (cd "$FORGE" && mvn -q -pl forge-gui-desktop -am package -DskipTests -Dcheckstyle.skip)
  else
    (cd "$FORGE" && nix shell nixpkgs#jdk17 nixpkgs#maven -c mvn -q -pl forge-gui-desktop -am package -DskipTests -Dcheckstyle.skip)
  fi
fi
ls "$FORGE"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar
