#!/bin/bash
# SessionStart hook for Claude Code cloud sessions.
# Installs Flutter outside the repo and resolves pub dependencies so
# `flutter analyze` / `dart analyze` and `flutter test` work in the session.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# Pin to the Flutter release the committed pubspec.lock was resolved with
# (see "version" in .flutter-plugins-dependencies; 3.38.7 ships Dart 3.10.7).
# A newer stable rewrites pubspec.lock and analysis_options.yaml on `pub get`.
FLUTTER_VERSION="${FLUTTER_VERSION:-3.38.7}"
FLUTTER_HOME="${FLUTTER_HOME:-$HOME/flutter}"
FLUTTER_BIN="$FLUTTER_HOME/bin"

log() { echo "[session-start] $*"; }

installed_version() {
  git -C "$FLUTTER_HOME" describe --tags --exact-match 2>/dev/null || true
}

if [ -x "$FLUTTER_BIN/flutter" ] && [ "$(installed_version)" = "$FLUTTER_VERSION" ]; then
  log "Flutter $FLUTTER_VERSION already present at $FLUTTER_HOME"
else
  log "Cloning Flutter $FLUTTER_VERSION into $FLUTTER_HOME"
  rm -rf "$FLUTTER_HOME"
  git clone --depth 1 --branch "$FLUTTER_VERSION" https://github.com/flutter/flutter.git "$FLUTTER_HOME"
fi

export PATH="$FLUTTER_BIN:$PATH"
export PUB_CACHE="${PUB_CACHE:-$HOME/.pub-cache}"

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export FLUTTER_HOME=\"$FLUTTER_HOME\""
    echo "export PATH=\"$FLUTTER_BIN:\$PATH\""
    echo "export PUB_CACHE=\"$PUB_CACHE\""
  } >> "$CLAUDE_ENV_FILE"
fi

# First invocation downloads the Dart SDK that matches this Flutter checkout.
flutter config --no-analytics >/dev/null
flutter --version
dart --version

# Host engine artifacts (incl. flutter_tester) so `flutter test` needs no download.
flutter precache --universal

cd "$PROJECT_DIR"
log "Resolving pub dependencies in $PROJECT_DIR"
flutter pub get

log "Done"
