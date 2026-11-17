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

# ---------- SYNOP : quantités de pluie mesurées (toutes les 6 h) ----------
TR_HOURS = {1: 6, 2: 12, 3: 18, 4: 24, 5: 1, 6: 2, 7: 3, 8: 9, 9: 15}


def rrr_mm(code):
    v = int(code)
    if v == 990:
        return 0.0          # traces
    if v >= 991:
        return (v - 990) / 10.0
    return float(v)


def parse_synop(report, when):
    """Extrait la pluie (groupes 6RRRt et 7R24) et Tx/Tn d'un message SYNOP."""
    tok = report.replace("=", " ").split()
    if "AAXX" not in tok:
        return None
    i = tok.index("AAXX")
    body = tok[i + 3:]
    if not body:
        return None
    out = {"time": int(when.timestamp()), "rr": None, "r24": None, "tx": None, "tn": None}
    sec1, sec3, cur = [], [], "1"
    for t in body:
        if t in ("333", "555", "222") or t.startswith("222"):
            cur = t[:3]
            continue
        if cur == "1":
            sec1.append(t)
        elif cur == "333":
            sec3.append(t)
    if not sec1 or not sec1[0][:1].isdigit():
        return None
    ir = sec1[0][0]
    groups = sec1[2:]
    if groups and groups[0].startswith("00"):
        groups = groups[1:]
    last = 0
    for g in groups:
        if len(g) != 5 or not g[0].isdigit():
            continue
        d = int(g[0])
        if d < last:
            break
        last = d
        if d == 6 and g[1:4].isdigit() and g[4].isdigit() and g[4] != "0":
            out["rr"] = {"mm": rrr_mm(g[1:4]), "h": TR_HOURS.get(int(g[4]), 6)}
    last = -1
    for g in sec3:
        if len(g) != 5 or not g[0].isdigit():
            continue
        d = int(g[0])
        if d < last:      # groupes supplémentaires (ex. rayonnement après 55SSS) : ignorés
            continue
        last = d
        if d == 1 and g[1] in "01" and g[2:].isdigit():
            out["tx"] = (1 if g[1] == "0" else -1) * int(g[2:]) / 10
        elif d == 2 and g[1] in "01" and g[2:].isdigit():
            out["tn"] = (1 if g[1] == "0" else -1) * int(g[2:]) / 10
        elif d == 6 and g[1:4].isdigit() and g[4].isdigit() and g[4] != "0" and out["rr"] is None:
            out["rr"] = {"mm": rrr_mm(g[1:4]), "h": TR_HOURS.get(int(g[4]), 6)}
        elif d == 7 and g[1:].isdigit():
            v = int(g[1:])
            out["r24"] = 0.0 if v == 9999 else v / 10
    if out["rr"] is None and ir == "3":   # station : « pas de précipitation »
        out["rr"] = {"mm": 0.0, "h": 6 if when.hour % 6 == 0 else 3}
    return out


synop = []
try:
    now = dt.datetime.now(dt.timezone.utc)
    b = (now - dt.timedelta(hours=54)).strftime("%Y%m%d%H%M")
    txt = get_retry(f"https://www.ogimet.com/cgi-bin/getsynop?block={WMO}&begin={b}&end={now:%Y%m%d%H%M}")
    for line in txt.splitlines():
        p = line.split(",", 6)
        if len(p) == 7 and p[0] == WMO:
            when = dt.datetime(int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]), tzinfo=dt.timezone.utc)
            s_ = parse_synop(p[6], when)
            if s_:
                synop.append(s_)
    synop.sort(key=lambda x: x["time"], reverse=True)
except Exception as e:  # noqa: BLE001
    errors.append(f"synop: {e}")

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

# ---------- Compléter avec GHCN-Daily (NOAA), série longue et plus complète ----------
ghcn_filled = 0
ghcn_days = {}
ghcn_gaps = []
try:
    txt = get_retry("https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/SPE00120512.csv")
    raw_rows = []
    for r in csv.DictReader(io.StringIO(txt)):
        date = (r.get("DATE") or "")[:10]
        if len(date) < 10:
            continue

        def val(name, r=r):
            v = (r.get(name) or "").strip()
            if not v:
                return None
            flags = (r.get(name + "_ATTRIBUTES") or "").split(",")
            if len(flags) > 1 and flags[1].strip():  # valeur rejetée par le contrôle qualité
                return None
            return float(v)
        raw_rows.append((date, val("PRCP"), val("TMAX"), val("TMIN")))
    tmax_vals = [x[2] for x in raw_rows if x[2] is not None]
    scale = 10.0 if tmax_vals and max(abs(v) for v in tmax_vals) > 60 else 1.0  # dixièmes de mm / de °C
    for date, p, tx, tn in raw_rows:
        ghcn_days[date] = (None if p is None else p / scale, None if tx is None else tx / scale, None if tn is None else tn / scale)
    acc = {}
    for date, p, tx, tn in raw_rows:
        k = (int(date[:4]), int(date[5:7]))
        a = acc.setdefault(k, {"p": 0.0, "np": 0, "tx": 0.0, "nx": 0, "tn": 0.0, "nn": 0})
        if p is not None:
            a["p"] += p / scale; a["np"] += 1
        if tx is not None:
            a["tx"] += tx / scale; a["nx"] += 1
        if tn is not None:
            a["tn"] += tn / scale; a["nn"] += 1
    by_key = {(m["year"], m["month"]): m for m in monthly}
    cur = (dt.date.today().year, dt.date.today().month)
    for (y, mo), a in acc.items():
        if (y, mo) >= cur:
            continue
        dim = (dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1)).day
        m = by_key.get((y, mo))
        if m is None:
            m = dict(year=y, month=mo, tavg=None, tmin=None, tmax=None, prcp=None, wspd=None, wpgt=None, pres=None, tsun=None)
            by_key[(y, mo)] = m
        changed = False
        if a["np"] >= dim - 1:  # mois complet (au plus 1 jour manquant)
            if m.get("prcp") is None or abs(m["prcp"] - a["p"]) > 0.5:
                m["prcp"] = round(a["p"], 1); m.pop("prcp_miss", None); changed = True
        elif dim - a["np"] <= 5 and m.get("prcp") is None:
            # quelques jours sans relevé (fréquent avant 1991) : total approché, légèrement sous-estimé
            m["prcp"] = round(a["p"], 1); m["prcp_miss"] = dim - a["np"]; changed = True
        if m.get("tmax") is None and a["nx"] >= 20:
            m["tmax"] = round(a["tx"] / a["nx"], 1); changed = True
        if m.get("tmin") is None and a["nn"] >= 20:
            m["tmin"] = round(a["tn"] / a["nn"], 1); changed = True
        ghcn_filled += changed
        if a["np"] < dim - 1:
            ghcn_gaps.append([y, mo, a["np"], dim, round(a["p"], 1)])
    monthly = [by_key[k] for k in sorted(by_key)]
except Exception as e:  # noqa: BLE001
    errors.append(f"ghcn: {e}")

out = {
    "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "station": {"name": "Sevilla Aeropuerto (San Pablo)", "icao": ICAO, "wmo": WMO,
                "lat": 37.418, "lon": -5.893, "alt": 34},
    "metar": metar,
    "synop": synop,
    "daily": daily_list,
    "monthly": monthly,
    "errors": errors,
}
dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "data")
os.makedirs(dest, exist_ok=True)
with open(os.path.join(dest, "svq.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
out["ghcn_filled"] = ghcn_filled
out["ghcn_gaps"] = ghcn_gaps
with open(os.path.join(dest, "svq.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"metar={len(metar)} daily={len(daily_list)} monthly={len(monthly)} ghcn_filled={ghcn_filled} errors={errors}")

# ---------- Historique journalier depuis 1980 (pour les alertes records) ----------
try:
    start = dt.date(1980, 1, 1)
    end = dt.date.today() - dt.timedelta(days=1)
    tx_l, tn_l, p_l = [], [], []
    d = start
    while d <= end:
        k = d.isoformat()
        g = ghcn_days.get(k, (None, None, None))
        ms = daily.get(k) or {}
        p = g[0] if g[0] is not None else ms.get("prcp")
        tx = g[1] if g[1] is not None else ms.get("tmax")
        tn = g[2] if g[2] is not None else ms.get("tmin")
        tx_l.append(None if tx is None else round(tx, 1))
        tn_l.append(None if tn is None else round(tn, 1))
        p_l.append(None if p is None else round(p, 1))
        d += dt.timedelta(days=1)
    with open(os.path.join(dest, "svq_hist.json"), "w", encoding="utf-8") as f:
        json.dump({"start": start.isoformat(), "end": end.isoformat(), "tmax": tx_l, "tmin": tn_l, "prcp": p_l,
                   "source": "GHCN-Daily SPE00120512 (NOAA) + Meteostat 08391"}, f, separators=(",", ":"))
    print("hist", len(tx_l), "jours, Tmax manquants", tx_l.count(None), "pluie manquante", p_l.count(None))
except Exception as e:  # noqa: BLE001
    print("hist error", e)

# ---------- Anomalie de température Europe (une fois par jour) ----------
OM_FC = "https://api.open-meteo.com/v1/forecast"
OM_AR = "https://archive-api.open-meteo.com/v1/archive"
EU = {"latMin": 34, "latMax": 70, "lonMin": -12, "lonMax": 42, "step": 3}
YEARS = [1991, 1995, 1999, 2003, 2007, 2011, 2015, 2019]
spent = []


def paced(n):
    """Reste sous 500 appels Open-Meteo par minute glissante."""
    while True:
        now = time.time()
        while spent and now - spent[0][0] > 61:
            spent.pop(0)
        if sum(x[1] for x in spent) + n <= 500:
            spent.append((now, n))
            return
        time.sleep(max(1, 61 - (now - spent[0][0])))


def om_grid(base, params, pts):
    out = []
    for k in range(0, len(pts), 100):
        b = pts[k:k + 100]
        paced(len(b))
        url = (f"{base}?latitude={','.join(str(p[0]) for p in b)}&longitude={','.join(str(p[1]) for p in b)}&{params}")
        for attempt in range(3):
            try:
                r = json.loads(get(url))
                break
            except Exception:  # noqa: BLE001
                if attempt == 2:
                    raise
                time.sleep(65)
        out += r if isinstance(r, list) else [r]
    return out


anom_path = os.path.join(dest, "anom_eu.json")
today_utc = dt.datetime.now(dt.timezone.utc).date()
prev = None
try:
    with open(anom_path, encoding="utf-8") as f:
        prev = json.load(f)
except Exception:  # noqa: BLE001
    pass
if prev and prev.get("date") == today_utc.isoformat():
    print("anomalie Europe déjà à jour")
else:
    try:
        lats = [EU["latMin"] + i * EU["step"] for i in range(int((EU["latMax"] - EU["latMin"]) / EU["step"]) + 1)]
        lons = [EU["lonMin"] + j * EU["step"] for j in range(int((EU["lonMax"] - EU["lonMin"]) / EU["step"]) + 1)]
        pts = [(la, lo, i, j) for i, la in enumerate(lats) for j, lo in enumerate(lons)]
        N = 14
        ssum = [[[0.0] * len(lons) for _ in lats] for _ in range(N)]
        cnt = [[[0] * len(lons) for _ in lats] for _ in range(N)]
        for y in YEARS:
            md = today_utc.strftime("%m-%d")
            if md == "02-29" and y % 4:
                md = "02-28"
            s0 = dt.date.fromisoformat(f"{y}-{md}")
            res = om_grid(OM_AR, f"daily=temperature_2m_mean&start_date={s0}&end_date={s0 + dt.timedelta(days=N - 1)}&timezone=GMT", pts)
            for loc, (_, _, i, j) in zip(res, pts):
                for k, v in enumerate((loc.get("daily") or {}).get("temperature_2m_mean") or []):
                    if v is not None and k < N:
                        ssum[k][i][j] += v
                        cnt[k][i][j] += 1
            print("normale", y, "ok")
        mean = [[[ssum[k][i][j] / cnt[k][i][j] if cnt[k][i][j] else None for j in range(len(lons))] for i in range(len(lats))] for k in range(N)]
        clim = [[[None] * len(lons) for _ in lats] for _ in range(N)]
        for k in range(N):
            for i in range(len(lats)):
                for j in range(len(lons)):
                    vals = [mean[q][i][j] for q in range(max(0, k - 3), min(N, k + 4)) if mean[q][i][j] is not None]
                    clim[k][i][j] = sum(vals) / len(vals) if vals else None
        res = om_grid(OM_FC, f"daily=temperature_2m_mean&forecast_days={N}&timezone=GMT", pts)
        fc = [[[None] * len(lons) for _ in lats] for _ in range(N)]
        for loc, (_, _, i, j) in zip(res, pts):
            for k, v in enumerate((loc.get("daily") or {}).get("temperature_2m_mean") or []):
                if k < N:
                    fc[k][i][j] = v
        anom = [[[None if fc[k][i][j] is None or clim[k][i][j] is None else round(fc[k][i][j] - clim[k][i][j], 1)
                  for j in range(len(lons))] for i in range(len(lats))] for k in range(N)]
        fcr = [[[None if v is None else round(v, 1) for v in row] for row in g] for g in fc]
        with open(anom_path, "w", encoding="utf-8") as f:
            json.dump({"date": today_utc.isoformat(), "grid": {"latMin": EU["latMin"], "lonMin": EU["lonMin"], "step": EU["step"]},
                       "years": YEARS, "anom": anom, "fc": fcr}, f, separators=(",", ":"))
        print("anomalie Europe calculée")
    except Exception as e:  # noqa: BLE001
        print("anomalie Europe : échec", e)  # l'ancien fichier (s'il existe) est conservé
