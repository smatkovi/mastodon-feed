#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bestaetigt am Geraet, dass `url` der Schluessel fuers Tippen ist.

Laeuft auf dem Geraet (Python 2.6 + python-dbus), nicht auf dem Rechner:

    python tools/feed-probe.py spalten                     # Tabelle events
    python tools/feed-probe.py url    https://example.org/ # Adresse in "url"
    python tools/feed-probe.py action https://example.org/ # Adresse in "action"
    python tools/feed-probe.py weg                         # Probe wieder weg

`MEventFeed::addItem` nimmt an dieser Stelle ein `const QUrl &url`; "action"
dagegen ist ein D-Bus-Aufruf (`dienst pfad schnittstelle methode …`), und eine
Adresse darin bleibt wirkungslos -- das war der Fehler bis 2.0. Der Eintrag mit
`action` ist hier die Kontrolle: er darf *nicht* reagieren. "spalten" zeigt
dazu, was die Datenbank des Feeds wirklich fuehrt.
"""

import os
import sys
import time

QUELLE = "mastodon-probe"
DATENBANK = os.path.expanduser(
    "~/.config/meegotouchhome-nokia/eventsfeed.data")


def spalten():
    import sqlite3
    verbindung = sqlite3.connect(DATENBANK)
    for tabelle in ("events", "refreshactions"):
        try:
            zeilen = verbindung.execute(
                "pragma table_info(%s)" % tabelle).fetchall()
        except sqlite3.Error, fehler:
            print "%s: %s" % (tabelle, fehler)
            continue
        print "%s: %s" % (tabelle, ", ".join(z[1] for z in zeilen))
    return 0


def schnittstelle():
    import dbus
    bus = dbus.SessionBus()
    return dbus.Interface(
        bus.get_object("com.nokia.home.EventFeed", "/eventfeed"),
        "com.nokia.home.EventFeed")


def eintragen(schluessel, adresse):
    import dbus
    # Der bekannt gute Satz aus feed.rs, unveraendert -- und *nur* der
    # Unterschied, um den es geht: die Adresse in "url" oder in "action".
    eintrag = {
        "icon": "/usr/share/icons/hicolor/80x80/apps/mastodon-feed.png",
        "title": dbus.String("Probe: Adresse in \"%s\"" % schluessel),
        "body": dbus.String("Tippen. Oeffnet sich %s, ist \"%s\" das Feld."
                            % (adresse, schluessel)),
        "imageList": dbus.Array([], signature="s"),
        "timestamp": dbus.String(time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                               time.gmtime())),
        "footer": dbus.String("mastodon-feed"),
        "video": dbus.Boolean(False),
        "action": dbus.String(""),
        "sourceName": dbus.String(QUELLE),
        "sourceDisplayName": dbus.String("Probe"),
    }
    eintrag[schluessel] = dbus.String(adresse)
    kennung = int(schnittstelle().addItem(
        dbus.Dictionary(eintrag, signature="sv")))
    print "addItem -> %d" % kennung
    return 0 if kennung >= 0 else 1


def weg():
    schnittstelle().removeItemsBySourceName(QUELLE)
    print "Probe-Eintraege entfernt"
    return 0


def main(argv):
    was = argv[1] if len(argv) > 1 else ""
    if was == "spalten":
        return spalten()
    if was == "weg":
        return weg()
    if was in ("url", "action") and len(argv) > 2:
        return eintragen(was, argv[2])
    print __doc__
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
