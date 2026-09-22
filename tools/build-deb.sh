#!/bin/sh
# Baut mastodon-feed als architekturunabhaengiges .deb.
#
#   tools/build-deb.sh            # nimmt die Version aus control
#   tools/build-deb.sh 1.0
#
# Bis 0.9 wurde von Hand gestaged; das hier haelt den Ablauf fest, damit
# eine neue Fassung nicht wieder zusammengesucht werden muss.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
cd "$HERE"
VERSION=${1:-$(sed -n 's/^Version: *//p' control | head -1)}
STAGE=$HERE/stage
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/mastodon-feed/qml" \
         "$STAGE/usr/share/applications" "$STAGE/usr/share/dbus-1/services" \
         "$STAGE/etc/init/apps" "$STAGE/usr/share/icons/hicolor/80x80/apps"

for f in feedd.py mastodon_api.py https_helper.py config.py mastodon-feed; do
    cp "$f" "$STAGE/opt/mastodon-feed/$f"
done
chmod 755 "$STAGE/opt/mastodon-feed/mastodon-feed"
cp qml/main.qml "$STAGE/opt/mastodon-feed/qml/main.qml"
cp mastodon-feed.desktop "$STAGE/usr/share/applications/"
cp org.smatkovi.MastodonFeed.service "$STAGE/usr/share/dbus-1/services/"
cp mastodon-feed.conf "$STAGE/etc/init/apps/"
cp postinst "$STAGE/DEBIAN/postinst"
chmod 755 "$STAGE/DEBIAN/postinst"

# Das Icon: exakte Squircle-Form der Standard-Apps, aus
# ~/ps/meego-icon-tool/squircle.py. Ein rundes Icon faellt im Raster auf.
cp icon-80.png "$STAGE/usr/share/icons/hicolor/80x80/apps/mastodon-feed.png"

# control samt Icon fuer den Programm-Manager. Die base64-Zeilen brauchen
# je ein fuehrendes Leerzeichen, sonst zeigt der Manager kein Bild.
VERSION="$VERSION" python3 - <<'PY'
import base64, os, textwrap
text = open("control").read().rstrip("\n")
zeilen = [z for z in text.split("\n") if not z.startswith("XB-Maemo-Icon-26")
          and not z.startswith(" " * 1 + "iVBOR")]
zeilen = [("Version: " + os.environ["VERSION"]) if z.startswith("Version:") else z
          for z in zeilen]
b64 = base64.b64encode(open("icon-64.png", "rb").read()).decode("ascii")
zeilen.append("XB-Maemo-Icon-26:")
zeilen += [" " + z for z in textwrap.wrap(b64, 76)]
open("stage/DEBIAN/control", "w").write("\n".join(zeilen) + "\n")
PY

OUT="$HERE/mastodon-feed_${VERSION}_all.deb"
python3 mkdeb.py "$STAGE" "$OUT"
echo "== $OUT"
