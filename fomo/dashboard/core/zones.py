"""Market zones: coin age x market cap, with live replay results from tools/zone_fit.py."""
import json, os
from . import config

PATH = os.path.join(config.ROOT, "model", "zone_table.json")
_t = {"mtime": 0, "data": None}


def label(age_min, mcap):
    age = "brand new" if age_min < 5 else "early" if age_min < 60 else "young" if age_min < 360 else "mature"
    cap = "<$15k" if mcap < 15000 else "$15k-80k" if mcap < 80000 else ">$80k"
    return f"{age} · {cap}"


def lookup(age_min, mcap):
    if age_min is None or not mcap:
        return None
    try:
        m = os.path.getmtime(PATH)
        if m != _t["mtime"]:
            _t.update(mtime=m, data=json.load(open(PATH)))
    except Exception:
        _t["data"] = None
    z = label(age_min, mcap)
    s = ((_t["data"] or {}).get("zones") or {}).get(z)
    return dict(zone=z, **(s or {}))
