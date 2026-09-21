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
| `mastodon-feed.conf` | The Upstart job. |
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

## Two Harmattan traps this ran into

* **`addItem` answers `-1` and says nothing** if a single key is missing from
  the dictionary. Leave one out and nothing ever appears in the feed, with no
  error anywhere to explain it. The full key set in `feedd.py` is not
  decoration.
* **The Upstart job must drop to uid `user`.** As root, Aegis refuses to exec
  `/opt/wunderw/bin/python3` — "Operation not permitted" — and that
  interpreter is the only one on the device that can do TLS 1.2, so as root
  the daemon reaches no instance at all. `aegis-exec -u user` does the drop,
  and the log redirection is set up before it so the log stays writable.
  Plain `-u`, without `-s -l`: with those the command produces no output and
  returns at once, and Upstart sees the job exit the moment it starts.

## Installing

Developer mode, then in a terminal or over SSH:

    devel-su dpkg -i mastodon-feed_0.8_all.deb

Then open **Mastodon Feed** from the launcher, give it the instance and the
credentials, and the posts appear in the Events view. The token is stored
only on the phone, in `~/.config/mastodon-feed/account.json`.

The log is `/var/log/mastodon-feed.log`.

## Licence

GPL-3.0-or-later, like the other apps here — see `LICENSE`.

## Credentials

Nothing in this repository holds an account, a token or a client secret —
those are created on the device at sign-in and stay there. `config.py` only
carries empty defaults.
