#!/bin/sh
# Laeuft auf dem Build-Rechner, nicht hier.
set -e
SRC=/tmp/mastodon-feed-src
. "$SRC/tools/cross.env"
if [ ! -x "$CARGO_HOME/bin/cargo" ] || [ ! -d "$MUSL" ]; then
    sh "$SRC/tools/toolchain.sh"
    . "$SRC/tools/cross.env"
fi
cd "$SRC/daemon"
cargo build --release --target "$ZIEL"
mkdir -p "$SRC/build"
cp "target/$ZIEL/release/mastodon-feedd" "$SRC/build/"
