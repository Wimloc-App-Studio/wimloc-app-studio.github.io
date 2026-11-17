#!/usr/bin/env python3
"""Récupère les données de la station Séville Aéroport (LEZL / WMO 08391).

- METAR des 48 dernières heures (NOAA Aviation Weather Center, sans clé)
- Données journalières et mensuelles de la station (Meteostat, sans clé)

Écrit un fichier svq.json dans le dossier donné en argument.
Ne plante jamais : les erreurs sont listées dans le JSON.
"""
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import urllib.request

ICAO = "LEZL"
WMO = "08391"
UA = {"User-Agent": "wimloc-meteo/1.0 (+https://wimloc-app-studio.github.io/meteo/)"}
errors = []


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    if b[:2] == b"\x1f\x8b":
        b = gzip.decompress(b)
    return b.decode("utf-8")


def num(x):
    try:
        return None if x is None or str(x).strip() == "" else float(x)
    except ValueError:
        return None


def read_csv(text, defaults_by_len):
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    if not rows:
        return []
    if re.match(r"^[A-Za-z_]", rows[0][0].strip()):
        header = [c.strip().lower() for c in rows[0]]
        rows = rows[1:]
        return [dict(zip(header, r)) for r in rows]
    out = []
    for r in rows:
        cols = defaults_by_len.get(len(r)) or defaults_by_len["default"]
        out.append(dict(zip(cols, r)))
    return out


def pick(d, *names):
    for n in names:
        if n in d and str(d[n]).strip() != "":
            return num(d[n])
    return None


def norm_values(d):
    return {
        "tavg": pick(d, "tavg", "temp"),
        "tmin": pick(d, "tmin"),
        "tmax": pick(d, "tmax"),
        "prcp": pick(d, "prcp"),
        "wspd": pick(d, "wspd"),
        "wpgt": pick(d, "wpgt"),
        "pres": pick(d, "pres"),
        "tsun": pick(d, "tsun"),
    }


# ---------- METAR ----------
metar = []
try:
    raw = json.loads(get(f"https://aviationweather.gov/api/data/metar?ids={ICAO}&format=json&hours=48"))
    keep = ["obsTime", "reportTime", "temp", "dewp", "wdir", "wspd", "wgst", "visib",
            "altim", "slp", "wxString", "clouds", "cover", "rawOb"]
    metar = [{k: m.get(k) for k in keep} for m in raw]
    metar.sort(key=lambda m: m.get("obsTime") or 0, reverse=True)
except Exception as e:  # noqa: BLE001
    errors.append(f"metar: {e}")

# ---------- Journalier ----------
DAILY_DEFAULT = {
    11: ["date", "tavg", "tmin", "tmax", "prcp", "snow", "wdir", "wspd", "wpgt", "pres", "tsun"],
    "default": ["date", "tavg", "tmin", "tmax", "prcp", "snow", "wdir", "wspd", "wpgt", "pres", "tsun"],
}
daily = {}
year = dt.date.today().year
for y in (year - 1, year):
    try:
        for d in read_csv(get(f"https://data.meteostat.net/daily/{y}/{WMO}.csv.gz"), DAILY_DEFAULT):
            date = d.get("date") or d.get("time")
            if not date and d.get("year"):
                date = f"{int(float(d['year'])):04d}-{int(float(d['month'])):02d}-{int(float(d['day'])):02d}"
            if date:
                daily[date[:10]] = norm_values(d)
    except Exception as e:  # noqa: BLE001
        errors.append(f"daily {y}: {e}")
if not daily:
    try:
        for d in read_csv(get(f"https://bulk.meteostat.net/v2/daily/{WMO}.csv.gz"), DAILY_DEFAULT):
            if d.get("date"):
                daily[d["date"][:10]] = norm_values(d)
    except Exception as e:  # noqa: BLE001
        errors.append(f"daily legacy: {e}")
daily_list = [dict(date=k, **v) for k, v in sorted(daily.items())][-500:]

# ---------- Mensuel ----------
MONTHLY_DEFAULT = {
    12: ["year", "month", "tavg", "tmin", "tmax", "prcp", "snow", "wdir", "wspd", "wpgt", "pres", "tsun"],
    9: ["year", "month", "tavg", "tmin", "tmax", "prcp", "wspd", "pres", "tsun"],
    "default": ["year", "month", "tavg", "tmin", "tmax", "prcp", "snow", "wdir", "wspd", "wpgt", "pres", "tsun"],
}
monthly = []
for url in (f"https://data.meteostat.net/monthly/{WMO}.csv.gz",
            f"https://bulk.meteostat.net/v2/monthly/{WMO}.csv.gz"):
    try:
        rows = read_csv(get(url), MONTHLY_DEFAULT)
        tmp = []
        for d in rows:
            y = d.get("year")
            m = d.get("month")
            if (not y or not m) and d.get("date"):
                y, m = d["date"][:4], d["date"][5:7]
            if not y or not m:
                continue
            tmp.append(dict(year=int(float(y)), month=int(float(m)), **norm_values(d)))
        if tmp:
            monthly = tmp
            break
    except Exception as e:  # noqa: BLE001
        errors.append(f"monthly {url}: {e}")

out = {
    "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "station": {"name": "Sevilla Aeropuerto (San Pablo)", "icao": ICAO, "wmo": WMO,
                "lat": 37.418, "lon": -5.893, "alt": 34},
    "metar": metar,
    "daily": daily_list,
    "monthly": monthly,
    "errors": errors,
}
dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "data")
os.makedirs(dest, exist_ok=True)
with open(os.path.join(dest, "svq.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"metar={len(metar)} daily={len(daily_list)} monthly={len(monthly)} errors={errors}")
