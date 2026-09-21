# -*- coding: utf-8 -*-
"""Mastodon over HTTPS from Harmattan's Python 2.6.

Every request goes through https_helper.py under a newer Python 3, because
2.6's ssl cannot do TLS 1.2 and no instance will talk to it. Nothing here
needs a browser: Mastodon's password grant hands out a token directly, which
is the only workable route on a device whose browser predates the whole flow.
"""
import json
import os
import subprocess

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "https_helper.py")

# Looked at in order; the first one that exists is used.
PYTHON3_CANDIDATES = (
    "/opt/wunderw/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
)

SCOPES = "read"
APP_NAME = "Feed"
APP_WEBSITE = "https://github.com/smatkovi"


class MastodonError(Exception):
    pass


def python3_path():
    for path in PYTHON3_CANDIDATES:
        if os.path.exists(path):
            return path
    return ""


def _call(method, url, headers=None, body=None):
    python3 = python3_path()
    if not python3:
        raise MastodonError(
            "No Python 3 on this device. Harmattan's own Python cannot do "
            "TLS 1.2, which every Mastodon instance requires.")
    args = [python3, HELPER, method, url,
            json.dumps(headers or {}), json.dumps(body or {}) if body else ""]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    if proc.returncode != 0 and not out:
        raise MastodonError((err or "helper failed").strip()[:200])
    try:
        answer = json.loads(out)
    except ValueError:
        raise MastodonError("helper said: %s" % (out or err)[:200])
    if "error" in answer:
        raise MastodonError(answer["error"])
    return answer["ok"]


def fetch(url, dest):
    """Download one picture to dest. Returns the path, or raises.

    Same detour as every other request: the old Python cannot do TLS 1.2, so
    the newer one fetches the bytes.
    """
    python3 = python3_path()
    if not python3:
        raise MastodonError("no Python 3 for TLS 1.2")
    proc = subprocess.Popen([python3, HELPER, "FETCH", url, dest],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    try:
        answer = json.loads(out)
    except ValueError:
        raise MastodonError("helper said: %s" % (out or err)[:200])
    if "error" in answer:
        raise MastodonError(answer["error"])
    return answer["ok"]["path"]


def normalise_instance(text):
    """'graz.social', 'https://graz.social/', '@me@graz.social' -> host."""
    text = (text or "").strip()
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    text = text.replace("https://", "").replace("http://", "")
    return text.strip("/ ").split("/")[0]


def instance_title(host):
    return _call("GET", "https://%s/api/v1/instance" % host).get("title", host)


def register_app(host):
    data = _call("POST", "https://%s/api/v1/apps" % host, body={
        "client_name": APP_NAME,
        "redirect_uris": "urn:ietf:wg:oauth:2.0:oob",
        "scopes": SCOPES,
        "website": APP_WEBSITE,
    })
    return data["client_id"], data["client_secret"]


def password_token(host, client_id, client_secret, username, password):
    """The password grant. Instances may switch it off, and it never works
    with two-factor authentication -- both come back as a readable error
    rather than a bare 401."""
    data = _call("POST", "https://%s/oauth/token" % host, body={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "password",
        "username": username,
        "password": password,
        "scope": SCOPES,
    })
    return data["access_token"]


def verify(host, token):
    return _call("GET", "https://%s/api/v1/accounts/verify_credentials" % host,
                 headers={"Authorization": "Bearer %s" % token})


def home_timeline(host, token, since_id=None, limit=20):
    url = "https://%s/api/v1/timelines/home?limit=%d" % (host, limit)
    if since_id:
        url += "&since_id=%s" % since_id
    return _call("GET", url, headers={"Authorization": "Bearer %s" % token})


def notifications(host, token, since_id=None, limit=20):
    url = "https://%s/api/v1/notifications?limit=%d" % (host, limit)
    if since_id:
        url += "&since_id=%s" % since_id
    return _call("GET", url, headers={"Authorization": "Bearer %s" % token})
