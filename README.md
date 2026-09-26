# Mastodon Feed for MeeGo Harmattan (Nokia N9 / N950)

Puts the home timeline and the mentions of a Mastodon account into the
**Events view** — the feed on the home screen, where the built-in Twitter
and Facebook feeds once lived before those services turned their APIs off.

Ships as an `armel` `.deb`: the daemon is a static Rust binary, the settings
page is still Python.

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
0.9.8, and every Mastodon instance requires TLS 1.2. That is why the daemon
is Rust now (see below) — it speaks TLS itself. The settings page is still
Python and still cannot, so signing in shells out to `https_helper.py`, which
runs under whatever newer Python 3 the device carries
(`/opt/wunderw/bin/python3` on this N950, OpenSSL 1.1.1w) and always answers
with one JSON object, so the caller never has to tell a crash from a 404.
Without such a Python, signing in says so instead of failing quietly.

## The daemon is Rust (2.0)

`daemon/` holds it: one static binary against musl, so Harmattan's glibc 2.10
does not come into it, and rustls for TLS with its own root certificates —
the device's certificate store is from 2011 and does not know today's
issuers. A poll of an instance now takes half a second on the N950 instead of
spawning a second Python interpreter per request.

The daemon keeps every constraint of the Python one, because they come from
the device and not from the language: it is started through the **session**
D-Bus so that it runs as `user`, it writes only the two markers back into
`account.json` (the settings page owns the rest), and its item dictionary
carries the full set of keys with exactly the types the Events view expects.

Built with `tools/build-daemon.sh`, which cross-compiles on the Arch machine
(`armv7-unknown-linux-musleabi`, `rust-lld` as the linker — see
`tools/cross.env`); `tools/build-deb.sh` then packs it. Two switches help
when something is wrong on the device itself: `--probe <instance>` fetches an
instance's name, which proves TLS and name resolution without an account, and
`--eintrag <file.json>` puts one post from a JSON file into the Events view,
which proves the session bus and the item dictionary.

## Layout

| File | Purpose |
| --- | --- |
| `daemon/src/main.rs` | The daemon. Polls the timeline and the notifications and hands each new item to `com.nokia.home.EventFeed` over D-Bus. |
| `daemon/src/mastodon.rs` | The Mastodon calls, over rustls — timeline, notifications, pictures. |
| `daemon/src/feed.rs` | The Events view: session bus, the bus name, the item dictionary. |
| `daemon/src/text.rs` | HTML to one line of text, and the link a post points at. |
| `daemon/src/bilder.rs` | Pictures: the per-poll budget, the cache and its pruning. |
| `daemon/src/einstellungen.rs` | `account.json` — read whole, written one key at a time. |
| `mastodon_api.py` | The Mastodon calls of the *settings page*: app registration, password grant, sign-in. Goes through the helper. |
| `https_helper.py` | `GET` / `POST` / `FETCH` under a newer Python 3. All that is left of the TLS crutch, and only for signing in. |
| `mastodon-feed` | The settings page: instance, sign-in, the switches. PySide over Qt 4.7 and QtQuick 1.1, as BikeMe does on this device. |
| `config.py` | Where the account lives: `~/.config/mastodon-feed/account.json`, mode 0600 — it holds the token. |
| `mastodon-feed.conf` | The Upstart job — a trigger and watchdog, not the daemon itself; see below. |
| `org.smatkovi.MastodonFeed.service` | The session D-Bus service that actually starts the daemon, as `user`. |
| `mkdeb.py` | Writes the `.deb` without dpkg. |

## Tapping an item opens its link

A feed item's `action` field is an address: MeeGo Touch Home hands it to
`ContentAction::Action::defaultActionForScheme` when the item is tapped, and
`browser.desktop` has registered itself for `x-maemo-urischeme/http` and
`…/https`. So putting the post's link there is all it takes — no service of
our own, no desktop file.

Which link: Mastodon's own preview card if the post has one (`card.url`,
that is the instance saying "this post points at something"), otherwise the
first `<a href>` in the post's HTML. Mentions and hashtags are skipped —
Mastodon marks them `class="u-url mention"` and `class="mention hashtag"`,
and they only lead to a profile or a tag page that this browser cannot render
anyway. `&amp;` in the href is translated back, or the query string arrives
broken. A boost uses the boosted post's link, the one whose text is shown.

A post without a link leaves `action` empty, and then the item does not react
to a tap — same as before. The post's own permalink would be the obvious
fallback, but a Mastodon status page is not something the 2011 browser makes
a good job of.

## Switching the feed off

**Feed laden** is the master switch on the settings page. Off means the daemon
fetches nothing at all — no poll, no pictures, no traffic — while the account
stays signed in and whatever is already in the Events view stays there. The
daemon is not stopped for it: it keeps looking every minute, so switching the
feed back on takes effect within a minute and needs no restart.

Two details that are not decoration. The daemon checks the switch again every
60 seconds *while it waits out the poll interval* — otherwise switching off on
2G would still allow one more ten-minute poll, which is exactly the moment
somebody reaches for the switch. And both sides write single keys through
`config.update()` rather than saving their whole copy of the config: a poll
takes minutes on 2G, and a settings page that wrote back its startup snapshot
would undo the markers the daemon had just advanced — the next poll would then
put the same posts in the feed a second time.

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
  service, and the daemon claims that bus name on start — which also means a
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
there is no error anywhere to explain it. The full key set in
`daemon/src/feed.rs` is not decoration, and neither are its types: the
timestamp goes over as a string, `video` as a boolean, `imageList` as an
array of strings.

Since 2.0 the daemon also notices when it has been replaced: it compares the
inode behind its own path every minute and ends when `dpkg` has swapped it.
Without that, a new version would not reach the running service at all — the
Upstart job does not start it, it only checks whether somebody holds the bus
name, and from `postinst` Aegis refuses to kill the old process ("Operation
not permitted"), while the same `kill` over `sudo` goes through.

## Installing

Developer mode, then in a terminal or over SSH:

    devel-su dpkg -i mastodon-feed_2.0_armel.deb

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
