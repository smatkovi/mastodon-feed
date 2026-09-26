#!/bin/sh
# Baut den Dienst fuer N9/N950 -- statisch gegen musl, auf dem Arch-Rechner.
#
#   tools/build-daemon.sh
#
# Warum nicht hier: auf dem Telefon gibt es keine Rust-Toolchain, und das
# Kreuzuebersetzen braucht ausserdem die musl-Header (siehe tools/cross.env).
set -e
cd "$(dirname "$0")/.."
FERN=/tmp/mastodon-feed-src
HOST=$(sh "$HOME/ps/nfsshift-sfos/tools/buildhost.sh")
echo "== Build-Rechner: $HOST"
rsync -a --delete --exclude build --exclude target --exclude .git \
      --exclude '*.deb' --exclude stage ./ "$HOST:$FERN/"
ssh "$HOST" 'sh /tmp/mastodon-feed-src/tools/remote-build.sh'
mkdir -p build
scp -q "$HOST:$FERN/build/mastodon-feedd" build/
echo "== mastodon-feedd fertig ($(stat -c %s build/mastodon-feedd) B)"
