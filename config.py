# -*- coding: utf-8 -*-
"""Where the account lives. One small JSON file, owner-readable only.

It holds an access token, so the mode is set explicitly rather than left to
the umask: this is the one piece of the package worth protecting.
"""
import json
import os

def _home():
    """The account always lives in the phone owner's home.

    An Upstart job starts with no HOME at all -- its
    environment is UPSTART_JOB, TERM, PATH and PWD=/ and nothing else -- so
    expanduser("~") lands somewhere useless and the daemon then decides the
    account is not set up yet and sleeps for ever, silently. Hence the
    explicit look-up rather than trusting the environment.
    """
    home = os.environ.get("HOME", "")
    if home and os.path.isdir(os.path.join(home, ".config")):
        return home
    try:
        import pwd
        return pwd.getpwnam("user").pw_dir
    except (ImportError, KeyError):
        return "/home/user"


HOME = _home()
DIR = os.path.join(HOME, ".config", "mastodon-feed")
PATH = os.path.join(DIR, "account.json")

DEFAULTS = {
    "instance": "",
    "account": "",
    "token": "",
    "home": True,          # the home timeline in the feed
    "mentions": True,      # and notifications addressed to you
    "interval": 600,       # seconds between polls; the N950 is on 3G
    # Pictures cost data, and this phone drops to 2G often enough that both
    # of these are worth being able to switch off separately: avatars are
    # small but come with almost every post, thumbnails are the big ones.
    "avatars": True,       # profile picture as the item's icon
    "images": True,        # thumbnails of attached pictures
    "last_home": "",
    "last_notification": "",
}


def load():
    data = dict(DEFAULTS)
    try:
        with open(PATH) as fh:
            data.update(json.load(fh))
    except (IOError, OSError, ValueError):
        pass
    return data


def save(data):
    if not os.path.isdir(DIR):
        os.makedirs(DIR, 0700)
    tmp = PATH + ".new"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.chmod(tmp, 0600)
    os.rename(tmp, PATH)


def clear():
    try:
        os.remove(PATH)
    except (IOError, OSError):
        pass
