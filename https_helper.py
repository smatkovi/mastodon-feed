#!/usr/bin/env python3
"""HTTPS for Harmattan, run under whatever Python 3 the device has.

Harmattan's own Python is 2.6 against OpenSSL 0.9.8, which every Mastodon
instance refuses -- they want TLS 1.2. The device may carry a newer Python
beside it (/opt/wunderw/bin/python3 on this N950, OpenSSL 1.1.1w), and that
one gets through. The Python 2 side shells out to this script rather than
trying to speak TLS itself.

    https_helper.py GET   <url> [json-headers]
    https_helper.py POST  <url> [json-headers] [json-body]
    https_helper.py FETCH <url> <destination>

Always answers with a JSON object on stdout: either the decoded response or
{"error": "..."}, so the caller never has to tell a crash from a 404.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
AGENT = "mastodon-feed/1.0 (MeeGo Harmattan)"

# A thumbnail this device can use is a few tens of kilobytes. The cap is not
# about disk but about time and data: this phone is often on 2G, where half a
# megabyte is a minute of waiting and a noticeable part of a data plan.
MAX_BYTES = 512 * 1024


def request(method, url, headers=None, body=None):
    data = None
    headers = dict(headers or {})
    headers.setdefault("User-Agent", AGENT)
    headers.setdefault("Accept", "application/json")
    if body is not None:
        data = urllib.parse.urlencode(body).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        # Mastodon puts a readable reason in the body; pass it on rather than
        # just the status, or "401" is all the user ever sees.
        try:
            reason = json.loads(detail).get("error_description") or \
                     json.loads(detail).get("error") or detail
        except ValueError:
            reason = detail
        return {"error": "HTTP %s: %s" % (exc.code, reason)}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}

    try:
        return {"ok": json.loads(raw)}
    except ValueError:
        return {"error": "response was not JSON: %s" % raw[:200]}


def fetch(url, dest):
    """Download to a file. Used for avatars and picture thumbnails.

    Written to a neighbouring .part first and renamed only once complete, so
    a connection that dies mid-picture cannot leave a truncated file behind
    that the cache would then serve for ever.
    """
    headers = {"User-Agent": AGENT, "Accept": "image/*"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    part = dest + ".part"
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                return {"error": "too big: %s bytes" % length}
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return {"error": "too big: over %d bytes" % MAX_BYTES}
        with open(part, "wb") as fh:
            fh.write(data)
        os.replace(part, dest)
        return {"ok": {"path": dest, "bytes": len(data)}}
    except Exception as exc:
        try:
            os.remove(part)
        except OSError:
            pass
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def main(argv):
    if len(argv) < 3:
        print(json.dumps({"error": "usage: https_helper.py METHOD URL [HEADERS] [BODY]"}))
        return 2
    method, url = argv[1].upper(), argv[2]
    if method == "FETCH":
        if len(argv) < 4:
            print(json.dumps({"error": "usage: https_helper.py FETCH URL DEST"}))
            return 2
        print(json.dumps(fetch(url, argv[3])))
        return 0
    headers = json.loads(argv[3]) if len(argv) > 3 and argv[3] else None
    body = json.loads(argv[4]) if len(argv) > 4 and argv[4] else None
    print(json.dumps(request(method, url, headers, body)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
