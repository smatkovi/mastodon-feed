# Mastodon Feed for MeeGo Harmattan (Nokia N9 / N950)

Puts the home timeline and the mentions of a Mastodon account into the
**Events view** — the feed on the home screen, where the built-in Twitter
and Facebook feeds once lived before those services turned their APIs off.

Ships as an architecture-independent `.deb`.

## Why this is not just an API client

Two things on this phone make the obvious approach impossible, and most of
the code exists because of them.

**The browser cannot do Mastodon's OAuth.** Harmattan's browser predates the
whole flow and cannot render the authorisation page. So there is no web step
at all: the settings page asks for the instance and the credentials,
registers itself with that instance through `POST /api/v1/apps`, and obtains
a token through the **password grant**. All of it in Python, none of it in a
browser.

**Harmattan's Python cannot reach any instance.** It is 2.6 against OpenSSL
0.9.8, and every Mastodon instance requires TLS 1.2. The device may carry a
newer Python beside it — `/opt/wunderw/bin/python3` on this N950, OpenSSL
1.1.1w — and that one gets through. So the Python 2 side never speaks TLS
itself: it shells out to `https_helper.py`, which runs under whatever Python 3
is present and always answers with one JSON object, so the caller never has
to tell a crash from a 404. Without such a Python the application says so
instead of failing quietly.

## Layout

| File | Purpose |
| --- | --- |
| `feedd.py` | The daemon. Polls the timeline and the notifications and hands each new item to `com.nokia.home.EventFeed` over D-Bus. |
| `mastodon_api.py` | The Mastodon calls: app registration, password grant, timeline, notifications. Every request goes through the helper. |
| `https_helper.py` | `GET` / `POST` / `FETCH` under a newer Python 3. The only place that touches TLS. |
| `mastodon-feed` | The settings page: instance, sign-in, the switches. PySide over Qt 4.7 and QtQuick 1.1, as BikeMe does on this device, so the package stays `all`. |
| `config.py` | Where the account lives: `~/.config/mastodon-feed/account.json`, mode 0600 — it holds the token. |
| `mastodon-feed.conf` | The Upstart job — a trigger and watchdog, not the daemon itself; see below. |
| `org.smatkovi.MastodonFeed.service` | The session D-Bus service that actually starts the daemon, as `user`. |
| `mkdeb.py` | Writes the `.deb` without dpkg. |

## Data, and switching pictures off

The N950 is often on 2G, so pictures are not all-or-nothing:

* **Avatare laden** — the poster's profile picture as the item's icon. Small,
  but almost every post has one.
* **Bilder laden** — thumbnails of attached pictures. These are the big ones.
  Always the preview, never the full-size image.

Both are separate switches on the settings page, and both are off-switchable
independently. There is a per-poll download budget on top, and a hard cap of
512 KB per file in the helper: on 2G half a megabyte is a minute of waiting
and a noticeable part of a data plan. The poll interval is a setting too
(default 600 s).

## How the daemon gets to run as the user

This is the part that took the longest, and the answer is not obvious.

The daemon **must** run as `user`: the account file is `0600 user:users` in
`~/.config/mastodon-feed/`, and nothing else on this device may read it.

An Upstart job under `/etc/init/apps/` cannot get there. It runs as uid 0 —
but with an **empty credential set**: no supplementary groups, no
capabilities. Measured on an N950:

| Attempt from that job | Result |
| --- | --- |
| `aegis-exec -u user …` | silently lands on **nobody** (65534) |
| `aegis-exec -s -u user -l "exec …"` | also nobody |
| `su -s /bin/sh user -c …` | `su: can't set groups: Operation not permitted` |
| read `/home/user/.config/…/account.json` as that root | `Permission denied` |
| read a `0600 user:users` file under `/var/lib` as that root | `Permission denied` |

And nobody cannot read the account either — so the daemon loaded the empty
defaults, decided the account was not set up, and slept for ever **without
writing a single line anywhere**. From the outside that looks exactly like a
feed that has quietly stopped updating.

The stock session services (`clipboard`, `feedengine`, `applifed`) do run as
`user`, with `aegis-exec -s -u user -l "exec …"` — note that with `-l` the
command must be **one string beginning with `exec `**, or the login shell gets
nothing to do and returns at once. But they live in `/etc/init/xsession/`, and
that door is closed to us: Aegis refuses any file there without a reference
hash —

    Aegis: mastodon-feed.conf verification failed (no reference hash)
    init: …: Error while loading configuration file: Permission denied

— and reference hashes come only from **signed** packages. Installing the same
file with `dpkg` does not help; the package has no `digsigsums`.

**What does work** is the session bus. A service activated over the *session*
D-Bus runs as the bus owner — `user` — with `HOME` set and the account
readable. And `/usr/share/dbus-1/services/` is open to third-party packages
(several other apps on this phone install there). So:

* `org.smatkovi.MastodonFeed.service` declares the daemon as a session
  service, and `feedd.py` claims that bus name on start — which also means a
  second copy exits instead of polling twice.
* The Upstart job under `/etc/init/apps/` no longer *runs* the daemon. It
  waits for the session bus, asks the bus to start the service, and then
  watches the name every five minutes and re-activates it if it is gone. That
  is what replaces `respawn`, which a D-Bus service does not have. Reaching
  the session bus from that bare root **is** allowed.

The log moved with it: as `user` we cannot write `/var/log`, so the daemon
writes `~/.config/mastodon-feed/feedd.log` itself (capped at 256 KB, one
rotation) and says on every start which uid it is running as.

## The other Harmattan trap

`com.nokia.home.EventFeed.addItem` answers `-1` and says nothing at all if a
single key is missing from the dictionary. Nothing appears in the feed, and
there is no error anywhere to explain it. The full key set in `feedd.py` is
not decoration.

## Installing

Developer mode, then in a terminal or over SSH:

    devel-su dpkg -i mastodon-feed_0.9_all.deb

Then open **Mastodon Feed** from the launcher, give it the instance and the
credentials, and the posts appear in the Events view. The token is stored
only on the phone, in `~/.config/mastodon-feed/account.json`.

The log is `~/.config/mastodon-feed/feedd.log`.

## Licence

GPL-3.0-or-later, like the other apps here — see `LICENSE`.

## Credentials

Nothing in this repository holds an account, a token or a client secret —
those are created on the device at sign-in and stay there. `config.py` only
carries empty defaults.
