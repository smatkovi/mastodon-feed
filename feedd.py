#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Puts Mastodon posts into the Harmattan Events feed.

Polls the home timeline and the notifications and hands each new one to
com.nokia.home.EventFeed. Runs as a user-session job; the account comes from
mastodon-feed's settings page.

Note on addItem: it answers -1 and says nothing at all if a single key is
missing. The full set below is not decoration -- leave one out and nothing
ever appears in the feed, with no error anywhere to explain it.
"""
import hashlib
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import mastodon_api as api

# Der Dienst wird ueber den Sitzungs-D-Bus aktiviert und laeuft dadurch als
# "user". Der Name wird beim Start beansprucht: damit gilt die Aktivierung als
# abgeschlossen, und eine zweite Instanz beendet sich sofort wieder.
BUS_NAME = "org.smatkovi.MastodonFeed"

SOURCE = "mastodon-feed"   # Quellname im Feed
DISPLAY = "Mastodon"
ICON = "icon-m-content-description"

TAG = re.compile(r"<[^>]+>")
ENTITIES = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
            ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'"), ("&nbsp;", " "))


def plain(html):
    """Mastodon sends HTML; the feed wants a line of text."""
    text = html.replace("</p><p>", "\n\n").replace("<br />", "\n").replace("<br>", "\n")
    text = TAG.sub("", text)
    for entity, char in ENTITIES:
        text = text.replace(entity, char)
    return text.strip()


A_TAG = re.compile(r"<a\s([^>]*)>", re.I)
HREF = re.compile(r'href="([^"]*)"', re.I)
KLASSE = re.compile(r'class="([^"]*)"', re.I)


def entschaerft(url):
    """&amp; und Freunde zurueckuebersetzen -- im href stehen sie escaped."""
    for entity, char in ENTITIES:
        url = url.replace(entity, char)
    return url


def linkziel(status, host=""):
    """Der Link, auf den ein Beitrag zeigt -- oder "" fuer keinen.

    Das Feld "action" eines Feed-Eintrags ist fuer die Ereignisansicht eine
    Adresse: beim Tippen ruft sie ContentAction dafuer auf, und der Browser
    hat sich fuer http und https eingetragen (x-maemo-urischeme/http in
    browser.desktop). Leer heisst: tippen tut nichts, so wie bisher.

    Zuerst die Vorschaukarte -- das ist Mastodons eigene Auskunft „dieser
    Beitrag zeigt auf etwas". Sonst der erste Link im Text, aber ohne
    Erwaehnungen und Schlagwoerter: die traegt Mastodon als <a> mit der Klasse
    "mention" bzw. "hashtag" ein und sie fuehren nur auf ein Profil oder eine
    Schlagwortseite, die der alte Browser ohnehin nicht darstellt.
    """
    karte = status.get("card") or {}
    if karte.get("url"):
        return entschaerft(karte["url"])
    for attrs in A_TAG.findall(status.get("content") or ""):
        adresse = HREF.search(attrs)
        if not adresse:
            continue
        klassen = KLASSE.search(attrs)
        klassen = klassen.group(1) if klassen else ""
        if "mention" in klassen or "hashtag" in klassen:
            continue
        url = entschaerft(adresse.group(1))
        # Guertel und Hosentraeger, falls die Klasse einmal fehlt: auf der
        # eigenen Instanz sind /@jemand und /tags/… genau diese beiden Faelle.
        if host and (u"//%s/@" % host) in url:
            continue
        if u"/tags/" in url:
            continue
        return url
    return ""


SESSION_BUS_FILE = "/tmp/session_bus_address.user"


def session_bus_address():
    """Harmattan writes the current session bus address here.

    An Upstart job has no session environment of its own, and the feed lives
    on the session bus, so without this the daemon has nothing to talk to.
    Read every time: the address changes with the session.
    """
    try:
        with open(SESSION_BUS_FILE) as fh:
            for line in fh:
                if "DBUS_SESSION_BUS_ADDRESS=" not in line:
                    continue
                value = line.split("=", 1)[1].strip().rstrip(";")
                if value and value[0] in "\"'" and value[-1] == value[0]:
                    value = value[1:-1]
                return value
    except (IOError, OSError):
        pass
    return ""


def feed():
    import dbus
    address = session_bus_address()
    if address:
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
    if "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
        raise RuntimeError("no session bus -- is the desktop up yet?")
    bus = dbus.SessionBus()
    return dbus.Interface(bus.get_object("com.nokia.home.EventFeed", "/eventfeed"),
                          "com.nokia.home.EventFeed")


CACHE = os.path.join(config.HOME, ".cache", "mastodon-feed")

# What one poll may pull down, so a timeline full of pictures cannot turn
# into a five-minute download on 2G. Whatever is left over simply arrives
# without its picture; the text is the point.
MAX_DOWNLOADS = 20
# How much of the disk the pictures may keep. /home/user is a small partition
# on this device, so this stays modest and the oldest files go first.
CACHE_BYTES = 6 * 1024 * 1024

EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def cache_path(url):
    """A stable file name per URL, with the extension the feed can recognise."""
    # JSON hands back unicode, and md5 will not take that -- an accented
    # character in a URL would otherwise kill the whole poll.
    raw = url.encode("utf-8") if isinstance(url, unicode) else url
    name = hashlib.md5(raw).hexdigest()
    tail = url.split("?")[0].lower()
    for ext in EXTENSIONS:
        if tail.endswith(ext):
            return os.path.join(CACHE, name + ext)
    return os.path.join(CACHE, name + ".jpg")


class Budget(object):
    """One poll's allowance of downloads."""

    def __init__(self, limit):
        self.left = limit

    def picture(self, url):
        """Local path for url, downloading it once. "" if it cannot be had.

        A picture already in the cache costs nothing and is never counted
        against the allowance -- only new ones are.
        """
        if not url:
            return ""
        path = cache_path(url)
        if os.path.exists(path):
            os.utime(path, None)      # keep what is still in use from ageing out
            return path
        if self.left <= 0:
            return ""
        self.left -= 1
        try:
            if not os.path.isdir(CACHE):
                os.makedirs(CACHE, 0755)
            return api.fetch(url, path)
        except Exception, exc:
            print "picture:", exc
            return ""


def prune_cache():
    """Drop the oldest pictures once the cache grows past its allowance."""
    try:
        names = [os.path.join(CACHE, n) for n in os.listdir(CACHE)]
    except (IOError, OSError):
        return
    files = []
    total = 0
    for name in names:
        try:
            info = os.stat(name)
        except OSError:
            continue
        files.append((info.st_mtime, info.st_size, name))
        total += info.st_size
    files.sort()
    for _, size, name in files:
        if total <= CACHE_BYTES:
            break
        try:
            os.remove(name)
            total -= size
        except OSError:
            pass


def attachments(status, budget, want_images):
    """Local paths for the pictures hanging off a post, and whether it is video.

    Mastodon offers every attachment twice: the full-size url and a
    preview_url. The preview is the one worth having here -- a feed item
    shows a thumbnail, and the full size would be megabytes for no visible
    gain.
    """
    if not want_images:
        return [], False
    paths, video = [], False
    for media in status.get("media_attachments") or []:
        kind = media.get("type")
        if kind in ("video", "gifv"):
            video = True
        elif kind not in ("image",):
            continue
        path = budget.picture(media.get("preview_url") or media.get("url") or "")
        if path:
            paths.append(path)
    return paths, video


def add(iface, title, body, footer, when, ziel, icon=ICON, images=(), video=False):
    """Ein Eintrag in der Ereignisansicht. "ziel" ist die Adresse, die beim
    Tippen geoeffnet wird; leer heisst, der Eintrag reagiert nicht."""
    import dbus
    item = dbus.Dictionary({
        "icon": dbus.String(icon),
        "title": dbus.String(title),
        "body": dbus.String(body),
        "imageList": dbus.Array(list(images), signature="s"),
        "timestamp": dbus.String(when),
        "footer": dbus.String(footer),
        "video": dbus.Boolean(video),
        "action": dbus.String(ziel),
        "sourceName": dbus.String(SOURCE),
        "sourceDisplayName": dbus.String(DISPLAY),
    }, signature="sv")
    return int(iface.addItem(item))


def status_item_raw(iface, status, footer, budget, cfg):
    account = status.get("account") or {}
    who = account.get("display_name") or account.get("acct") or "?"
    body = plain(status.get("content") or "")
    shown = status
    if status.get("reblog"):
        inner = status["reblog"]
        # u"..." here is not taste, it is required. As a byte string,
        # "\xe2\x86\xbb" makes Python 2 decode it as ASCII the moment the name
        # beside it is unicode -- and out of the JSON it always is. That threw
        # the whole round the first time a boost appeared in the timeline.
        who = u"%s ↻ %s" % (who, (inner.get("account") or {}).get("acct", "?"))
        body = plain(inner.get("content") or "")
        shown = inner
    if not body:
        body = "(no text)"

    icon = ICON
    if cfg.get("avatars"):
        # avatar_static, not avatar: an animated GIF would be a much bigger
        # download and the feed shows it as a still picture anyway.
        avatar = account.get("avatar_static") or account.get("avatar") or ""
        icon = budget.picture(avatar) or ICON

    images, video = attachments(shown, budget, cfg.get("images"))

    # Beim Tippen wird der Link geoeffnet, den der Beitrag enthaelt. Bei einem
    # geteilten Beitrag der des geteilten -- "shown" ist der, dessen Text auch
    # angezeigt wird. Hat er keinen, bleibt das Feld leer und der Eintrag
    # reagiert nicht aufs Tippen.
    ziel = linkziel(shown, cfg.get("instance", ""))

    return add(iface, who, body, footer,
               status.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               ziel, icon, images, video)


def status_item(iface, status, footer, budget, cfg):
    """One post, and a broken one does not take the rest down with it.

    A single post the code could not digest used to abort the whole round --
    and since "last_home" only moves on AFTER the loop, the next poll fetched
    the same posts and tripped over the same one. The marker never advanced
    and nothing arrived again, ever. Better to lose one post than all of them.
    """
    try:
        return status_item_raw(iface, status, footer, budget, cfg)
    except Exception, exc:
        print "post skipped (%s): %s" % (status.get("id"), exc)
        return 0


def poll_once(cfg, iface):
    """Returns the updated config; the caller saves it."""
    host, token = cfg["instance"], cfg["token"]
    budget = Budget(MAX_DOWNLOADS if (cfg.get("images") or cfg.get("avatars")) else 0)
    if cfg.get("home"):
        posts = api.home_timeline(host, token, cfg.get("last_home") or None)
        for status in reversed(posts):
            status_item(iface, status, "Mastodon", budget, cfg)
        if posts:
            cfg["last_home"] = str(posts[0]["id"])
    if cfg.get("mentions"):
        notes = api.notifications(host, token, cfg.get("last_notification") or None)
        for note in reversed(notes):
            status = note.get("status")
            if not status:
                continue
            kind = {"mention": "Mention", "favourite": "Favourite",
                    "reblog": "Boost"}.get(note.get("type"), note.get("type", ""))
            status_item(iface, status, kind, budget, cfg)
        if notes:
            cfg["last_notification"] = str(notes[0]["id"])
    prune_cache()
    return cfg


def open_log():
    """Eigenes Log statt einer Umleitung im Upstart-Job.

    Als D-Bus-Dienst gibt es keine Umleitung mehr, die jemand fuer uns
    einrichtet -- und /var/log gehoert root, wir laufen als "user". Das Log
    liegt deshalb neben dem Konto und wird gekappt, bevor es die kleine
    Home-Partition fuellt.
    """
    path = os.path.join(config.DIR, "feedd.log")
    try:
        if not os.path.isdir(config.DIR):
            os.makedirs(config.DIR, 0700)
        if os.path.exists(path) and os.path.getsize(path) > 256 * 1024:
            os.rename(path, path + ".1")
        handle = open(path, "a", 0)
        os.dup2(handle.fileno(), 1)
        os.dup2(handle.fileno(), 2)
    except (IOError, OSError):
        pass          # ohne Log weiterlaufen ist besser als gar nicht laufen


def claim_name():
    """True, wenn dieser Prozess der Dienst ist; False, wenn schon einer laeuft.

    Der Umweg ueber den Sitzungsbus ist nicht Geschmackssache: ein Upstart-Job
    unter /etc/init/apps laeuft als uid 0 mit leerem Rechtesatz und kann die
    Kennung nicht wechseln -- aegis-exec landet dort auf nobody, su scheitert
    an "can't set groups", und weder nobody noch dieser root darf
    ~/.config/mastodon-feed/account.json lesen. Ein ueber den Sitzungsbus
    aktivierter Dienst dagegen laeuft als Besitzer des Busses, also als "user",
    mit HOME und Zugriff auf das Konto.
    """
    import dbus
    bus = dbus.SessionBus()
    reply = bus.request_name(BUS_NAME, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
    return reply == dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER


QUELLEN = ("feedd.py", "config.py", "mastodon_api.py", "https_helper.py")


def quellen_stand():
    """Pruefsumme der eigenen Dateien -- die Kennung der laufenden Fassung.

    Ueber den Inhalt, nicht ueber den Zeitstempel: mkdeb.py setzt im Paket
    jede Datei auf mtime 0, damit die Pakete reproduzierbar sind. Nach der
    Installation traegt also auch die neue Fassung den 1. Januar 1970, und ein
    Vergleich der Zeitstempel saehe nie eine Aenderung. Die vier Dateien sind
    zusammen 30 KB; einmal in der Minute kostet das nichts.
    """
    hier = os.path.dirname(os.path.abspath(__file__))
    summe = hashlib.md5()
    for name in QUELLEN:
        try:
            with open(os.path.join(hier, name), "rb") as fh:
                summe.update(fh.read())
        except (IOError, OSError):
            summe.update(name)
    return summe.hexdigest()


STAND = quellen_stand()


def abgeloest():
    """True, wenn inzwischen eine neue Fassung installiert wurde.

    Das postinst kann den laufenden Dienst nicht zuverlaessig beenden: unter
    aegis darf das Installationsskript den fremden Prozess nicht abschiessen
    (der Aufruf geht still daneben). Und der Upstart-Job startet feedd.py ja
    nicht selbst, er sieht nur nach, ob jemand den Bus-Namen haelt -- der alte
    Prozess haelt ihn weiter und liefe mit dem alten Code bis zum naechsten
    Neustart des Geraets. Also loest sich der Dienst selbst ab: er beendet
    sich, gibt den Namen frei, und der Job aktiviert binnen fuenf Minuten die
    neue Fassung.
    """
    return quellen_stand() != STAND


def warten(sekunden):
    """Schlafen, aber jede Minute nachsehen, ob der Schalter umgelegt wurde.

    Das Abfrageintervall sind 600 s. Wer den Feed abschaltet, tut das genau
    dann, wenn er nichts mehr geladen haben will -- und nicht erst in zehn
    Minuten. Die Rueckgabe sagt, ob weitergeschlafen werden soll.
    """
    rest = sekunden
    while rest > 0:
        time.sleep(min(60, rest))
        rest -= 60
        if not config.load().get("enabled", True):
            return
        if abgeloest():
            return


def main():
    open_log()
    try:
        if not claim_name():
            print "mastodon-feed: laeuft bereits, dieser Start endet hier"
            return
    except Exception, e:
        # Ohne Sitzungsbus gibt es ohnehin keinen Feed, in den geschrieben
        # werden koennte -- aber sagen statt schweigen.
        print "mastodon-feed: kein Sitzungsbus:", e
        return

    print "mastodon-feed: gestartet %s als uid %d" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), os.getuid())
    sys.stdout.flush()
    gesagt = None                 # welcher Zustand zuletzt im Log steht
    while True:
        if abgeloest():
            print "mastodon-feed: neue Fassung installiert, dieser Dienst endet"
            sys.stdout.flush()
            return
        cfg = config.load()
        if not cfg.get("enabled", True):
            # Der Hauptschalter aus der Einstellungsseite. Nur beim Wechsel
            # ins Log, sonst waere das Log nach einer Nacht voll davon.
            if gesagt != "aus":
                print "mastodon-feed: abgeschaltet, es wird nichts geholt"
                sys.stdout.flush()
                gesagt = "aus"
            time.sleep(60)
            continue
        if gesagt == "aus":
            print "mastodon-feed: wieder eingeschaltet"
            sys.stdout.flush()
        gesagt = "an"
        if not cfg["instance"] or not cfg["token"]:
            # Not set up yet. Sleep rather than exit: the settings page may
            # fill this in at any moment and respawning a dead job is noisier.
            # Gesagt wird es trotzdem: genau dieser Zustand sah frueher wie ein
            # stiller Stillstand aus, weil er nichts ins Log schrieb.
            print "mastodon-feed: kein Konto eingerichtet, warte"
            sys.stdout.flush()
            time.sleep(60)
            continue
        try:
            cfg = poll_once(cfg, feed())
            # Nur die beiden Marken zurueckschreiben, nicht die ganze Kopie:
            # ein Abruf dauert auf 2G Minuten, und in dieser Zeit kann die
            # Einstellungsseite laengst einen Schalter umgelegt haben. Die
            # ganze Kopie zu speichern haette ihn wieder zurueckgestellt.
            config.update(last_home=cfg.get("last_home", ""),
                          last_notification=cfg.get("last_notification", ""))
        except api.MastodonError, e:
            print "mastodon:", e
        except Exception, e:
            print "feed:", e
        warten(max(120, int(cfg.get("interval", 600))))


if __name__ == "__main__":
    main()
