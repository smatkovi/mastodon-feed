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

SOURCE = "mastodon-feed"
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


def add(iface, title, body, footer, when, url, icon=ICON, images=(), video=False):
    import dbus
    item = dbus.Dictionary({
        "icon": dbus.String(icon),
        "title": dbus.String(title),
        "body": dbus.String(body),
        "imageList": dbus.Array(list(images), signature="s"),
        "timestamp": dbus.String(when),
        "footer": dbus.String(footer),
        "video": dbus.Boolean(video),
        "action": dbus.String(""),
        "sourceName": dbus.String(SOURCE),
        "sourceDisplayName": dbus.String(DISPLAY),
    }, signature="sv")
    return int(iface.addItem(item))


def status_item(iface, status, footer, budget, cfg):
    account = status.get("account") or {}
    who = account.get("display_name") or account.get("acct") or "?"
    body = plain(status.get("content") or "")
    shown = status
    if status.get("reblog"):
        inner = status["reblog"]
        who = "%s \xe2\x86\xbb %s" % (who, (inner.get("account") or {}).get("acct", "?"))
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

    return add(iface, who, body, footer,
               status.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               status.get("url") or "", icon, images, video)


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


def main():
    while True:
        cfg = config.load()
        if not cfg["instance"] or not cfg["token"]:
            # Not set up yet. Sleep rather than exit: the settings page may
            # fill this in at any moment and respawning a dead job is noisier.
            time.sleep(60)
            continue
        try:
            cfg = poll_once(cfg, feed())
            config.save(cfg)
        except api.MastodonError, e:
            print "mastodon:", e
        except Exception, e:
            print "feed:", e
        time.sleep(max(120, int(cfg.get("interval", 600))))


if __name__ == "__main__":
    main()
