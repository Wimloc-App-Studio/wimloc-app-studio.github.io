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
import time
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


def parse_metar(raw, when):
    """Décodage simple d'un METAR brut au format attendu par la page."""
    m = {"rawOb": raw, "obsTime": int(when.timestamp()), "clouds": []}
    body = raw.split(" RMK")[0].split(" TEMPO")[0].split(" BECMG")[0].split(" NOSIG")[0]
    w = re.search(r" (\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT", body)
    if w:
        m["wdir"] = w.group(1) if w.group(1) == "VRB" else int(w.group(1))
        m["wspd"] = int(w.group(2))
        m["wgst"] = int(w.group(3)) if w.group(3) else None
    t = re.search(r" (M?\d{2})/(M?\d{2})? ", body + " ")
    if t:
        conv = lambda s: -int(s[1:]) if s.startswith("M") else int(s)  # noqa: E731
        m["temp"] = conv(t.group(1))
        m["dewp"] = conv(t.group(2)) if t.group(2) else None
    q = re.search(r" Q(\d{4})", body)
    if q:
        m["altim"] = int(q.group(1))
    if "CAVOK" in body:
        m["visib"] = "6+"
        m["cover"] = "CAVOK"
    else:
        v = re.search(r"KT(?: \d{3}V\d{3})? (\d{4}) ", body + " ")
        if v:
            vm = int(v.group(1))
            m["visib"] = "6+" if vm >= 9999 else round(vm / 1609, 2)
    for c in re.finditer(r" (FEW|SCT|BKN|OVC)(\d{3})", body):
        m["clouds"].append({"cover": c.group(1), "base": int(c.group(2)) * 100})
    for c in ("NSC", "SKC", "CLR", "NCD"):
        if f" {c}" in body:
            m["cover"] = c
    wx = re.findall(r" ((?:[-+]|VC)?(?:MI|BC|PR|DR|BL|SH|TS|FZ)?(?:DZ|RA|SN|SG|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PO|SQ|FC|SS|DS)+)(?= )", body + " ")
    m["wxString"] = " ".join(wx) or None
    return m


def get_retry(url, tries=3):
    last = None
    for k in range(tries):
        try:
            return get(url)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (k + 1))
    raise last


# ---------- METAR ----------
metar = []
try:
    raw = json.loads(get_retry(f"https://aviationweather.gov/api/data/metar?ids={ICAO}&format=json&hours=48"))
    keep = ["obsTime", "reportTime", "temp", "dewp", "wdir", "wspd", "wgst", "visib",
            "altim", "slp", "wxString", "clouds", "cover", "rawOb"]
    metar = [{k: m.get(k) for k in keep} for m in raw]
except Exception as e:  # noqa: BLE001
    errors.append(f"metar awc: {e}")
if not metar:  # secours 1 : Ogimet (historique 48 h)
    try:
        now = dt.datetime.now(dt.timezone.utc)
        b = (now - dt.timedelta(hours=48)).strftime("%Y%m%d%H%M")
        txt = get_retry(f"https://www.ogimet.com/cgi-bin/getmetar?icao={ICAO}&begin={b}&end={now:%Y%m%d%H%M}")
        for line in txt.splitlines():
            p = line.split(",", 6)
            if len(p) == 7 and p[0] == ICAO:
                when = dt.datetime(int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]), tzinfo=dt.timezone.utc)
                metar.append(parse_metar(p[6].strip().rstrip("="), when))
    except Exception as e:  # noqa: BLE001
        errors.append(f"metar ogimet: {e}")
if not metar:  # secours 2 : NOAA, dernier METAR seulement
    try:
        lines = get_retry(f"https://tgftp.nws.noaa.gov/data/observations/metar/stations/{ICAO}.TXT").strip().splitlines()
        when = dt.datetime.strptime(lines[0].strip(), "%Y/%m/%d %H:%M").replace(tzinfo=dt.timezone.utc)
        metar.append(parse_metar(lines[1].strip(), when))
    except Exception as e:  # noqa: BLE001
        errors.append(f"metar tgftp: {e}")
metar.sort(key=lambda m: m.get("obsTime") or 0, reverse=True)

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
# Meteostat complète avec des valeurs de modèle, y compris pour les jours à venir : on ne garde que le passé
today = dt.date.today().isoformat()
daily_list = [dict(date=k, **v) for k, v in sorted(daily.items()) if k < today][-500:]

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
        cur = (dt.date.today().year, dt.date.today().month)
        tmp = [r for r in tmp if (r["year"], r["month"]) < cur]  # le mois en cours est recalculé à partir des jours
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
