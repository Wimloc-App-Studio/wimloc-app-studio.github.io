#!/usr/bin/env python3
"""Wimloc Invest : récupère les cours de bourse, les changes et les taux à 10 ans.

Sources gratuites, sans clé, essayées dans l'ordre jusqu'à ce que l'une réponde :
- Yahoo Finance (graphique journalier), CNBC (cotation), Stooq (cotation)
- BCE (taux de change de référence, officiels)
- Trésor américain, Bundesbank, Banque d'Angleterre, ministère des Finances japonais
  (taux officiels de fin de journée), FRED en dernier recours

Écrit data.json dans le dossier donné en argument. Garde l'historique déjà publié
(fichier data.json présent dans ce dossier) pour dessiner les courbes.
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
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.8",
}
KEEP_DAYS = 130
errors = []
TODAY = dt.datetime.now(dt.timezone.utc)

# id, nom, groupe, Yahoo, CNBC, Stooq
ITEMS = [
    ("cac40", "CAC 40", "europe", "^FCHI", ".FCHI", "^cac"),
    ("ibex35", "IBEX 35", "europe", "^IBEX", ".IBEX", "^ibex"),
    ("dax", "DAX", "europe", "^GDAXI", ".GDAXI", "^dax"),
    ("stoxx50", "Euro Stoxx 50", "europe", "^STOXX50E", ".STOXX50E", "^stx"),
    ("ftse100", "FTSE 100", "europe", "^FTSE", ".FTSE", "^ukx"),
    ("sp500", "S&P 500", "ameriques", "^GSPC", ".SPX", "^spx"),
    ("dow", "Dow Jones", "ameriques", "^DJI", ".DJI", "^dji"),
    ("nasdaq", "Nasdaq", "ameriques", "^IXIC", ".IXIC", "^ndq"),
    ("nikkei", "Nikkei 225", "asie", "^N225", ".N225", "^nkx"),
    ("shanghai", "Shanghai", "asie", "000001.SS", ".SSEC", "^shc"),
    ("hangseng", "Hang Seng", "asie", "^HSI", ".HSI", "^hsi"),
    ("eurusd", "EUR / USD", "change", "EURUSD=X", "EUR=", "eurusd"),
    ("eurcny", "EUR / CNY", "change", "EURCNY=X", "EURCNY=", "eurcny"),
    ("usdcny", "USD / CNY", "change", "CNY=X", "CNY=", "usdcny"),
    ("or", "Or (once, $)", "matieres", "GC=F", "@GC.1", "gc.f"),
    ("brent", "Pétrole Brent ($)", "matieres", "BZ=F", "@LCO.1", "cb.f"),
    ("fr10", "France", "taux", None, "FR10Y", "10fry.b"),
    ("de10", "Allemagne", "taux", None, "DE10Y", "10dey.b"),
    ("es10", "Espagne", "taux", None, "ES10Y", "10esy.b"),
    ("us10", "États-Unis", "taux", "^TNX", "US10Y", "10usy.b"),
    ("uk10", "Royaume-Uni", "taux", None, "GB10Y", "10uky.b"),
    ("jp10", "Japon", "taux", None, "JP10Y", "10jpy.b"),
]
FRED_MONTHLY = {"fr10": "IRLTLT01FRM156N", "de10": "IRLTLT01DEM156N", "es10": "IRLTLT01ESM156N",
                "uk10": "IRLTLT01GBM156N", "jp10": "IRLTLT01JPM156N"}


def get(url, tries=2, accept=None):
    last = None
    for i in range(tries):
        try:
            h = dict(UA)
            if accept:
                h["Accept"] = accept
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=40) as r:
                b = r.read()
            if b[:2] == b"\x1f\x8b":
                b = gzip.decompress(b)
            return b.decode("utf-8-sig", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * i)
    raise last


def num(x):
    if x is None:
        return None
    s = str(x).strip().replace(",", "").replace("%", "").replace("+", "")
    if s in ("", "-", "N/A", "UNCH", "null"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v == v else None  # NaN


def err(where, e):
    msg = f"{where}: {type(e).__name__}: {str(e)[:160]}"
    errors.append(msg)
    print("  ✗", msg, file=sys.stderr)


# ---------- Yahoo ----------
def yahoo(sym):
    q = urllib.parse.quote(sym)
    last = None
    for host in ("query1", "query2"):
        try:
            t = get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?range=6mo&interval=1d&includePrePost=false", tries=1)
            res = json.loads(t)["chart"]["result"][0]
            break
        except Exception as e:  # noqa: BLE001
            last = e
    else:
        raise last
    meta = res["meta"]
    off = meta.get("gmtoffset") or 0
    closes = res.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    hist = []
    for ts, c in zip(res.get("timestamp") or [], closes):
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(ts + off, dt.timezone.utc).date().isoformat()
        if hist and hist[-1][0] == d:
            hist[-1] = [d, c]
        else:
            hist.append([d, c])
    price = num(meta.get("regularMarketPrice"))
    mt = meta.get("regularMarketTime")
    if price is None:
        raise ValueError("pas de cours")
    tday = dt.datetime.fromtimestamp(mt + off, dt.timezone.utc).date().isoformat() if mt else None
    if hist and tday and hist[-1][0] == tday:
        hist[-1][1] = price
        prev = hist[-2][1] if len(hist) > 1 else None
    else:
        prev = hist[-1][1] if hist else None
        if tday:
            hist.append([tday, price])
    return {
        "price": price, "prev": prev, "src": "Yahoo Finance",
        "time": dt.datetime.fromtimestamp(mt, dt.timezone.utc).isoformat() if mt else None,
        "hist": hist,
    }


# ---------- CNBC (toutes les cotations d'un coup) ----------
CNBC = {}


def cnbc_load():
    syms = "|".join(i[4] for i in ITEMS if i[4])
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
           + urllib.parse.quote(syms, safe="")
           + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
    try:
        data = json.loads(get(url))
        quotes = data.get("FormattedQuoteResult", {}).get("FormattedQuote", [])
        if isinstance(quotes, dict):
            quotes = [quotes]
        for q in quotes:
            CNBC[q.get("symbol")] = q
        print(f"  CNBC : {len(CNBC)} cotations")
    except Exception as e:  # noqa: BLE001
        err("CNBC", e)


def cnbc(sym):
    q = CNBC.get(sym)
    if not q:
        raise KeyError("absent")
    price = num(q.get("last"))
    if price is None:
        raise ValueError("pas de cours")
    ch = num(q.get("change"))
    prev = price - ch if ch is not None else num(q.get("previous_day_closing"))
    t = q.get("last_time")  # ex. 2026-11-19T14:20:05.000+0000
    try:
        iso = dt.datetime.strptime(t[:19] + t[-5:], "%Y-%m-%dT%H:%M:%S%z").astimezone(dt.timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        iso = None
    day = (iso or TODAY.isoformat())[:10]
    return {"price": price, "prev": prev, "src": "CNBC", "time": iso, "hist": [[day, price]]}


def cnbc_hist(sym):
    """Clôtures journalières sur 1 an (graphique CNBC)."""
    t = get("https://ts-api.cnbc.com/harmony/app/charts/1Y.json?symbol=" + urllib.parse.quote(sym, safe=""))
    data = json.loads(t)
    bars = []

    def walk(o):
        if isinstance(o, list) and o and isinstance(o[0], dict) and "close" in o[0]:
            bars.extend(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    out = []
    for b in bars:
        v = num(b.get("close"))
        d = None
        tt = str(b.get("tradeTime") or "")
        if re.match(r"^\d{8}", tt):
            d = f"{tt[:4]}-{tt[4:6]}-{tt[6:8]}"
        elif b.get("tradeTimeinMills"):
            d = dt.datetime.fromtimestamp(int(b["tradeTimeinMills"]) / 1000, dt.timezone.utc).date().isoformat()
        if d and v is not None:
            out.append([d, v])
    if not out:
        raise ValueError("aucune barre")
    return sorted(out)


# ---------- Stooq ----------
def stooq(sym):
    t = get(f"https://stooq.com/q/l/?s={urllib.parse.quote(sym)}&f=sd2t2c&h&e=csv")
    rows = list(csv.DictReader(io.StringIO(t)))
    if not rows:
        raise ValueError("vide")
    r = {k.strip().lower(): v for k, v in rows[0].items()}
    price = num(r.get("close"))
    if price is None:
        raise ValueError("N/D")
    d = r.get("date")
    return {"price": price, "prev": None, "src": "Stooq", "time": None, "hist": [[d, price]] if d else []}


# ---------- Sources officielles ----------
def ecb_fx():
    """Taux de référence BCE des 90 derniers jours : {devise: [[date, valeur], ...]}."""
    t = get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml")
    root = ET.fromstring(t)
    out = {}
    for cube in root.iter():
        d = cube.attrib.get("time")
        if not d:
            continue
        for c in cube:
            out.setdefault(c.attrib["currency"], []).append([d, float(c.attrib["rate"])])
    for k in out:
        out[k].sort()
    return out


def us_treasury():
    out = []
    for y in (TODAY.year - 1, TODAY.year):
        t = get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                f"{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
        for r in csv.DictReader(io.StringIO(t)):
            v = num(r.get("10 Yr"))
            try:
                d = dt.datetime.strptime(r["Date"], "%m/%d/%Y").date().isoformat()
            except Exception:  # noqa: BLE001
                continue
            if v is not None:
                out.append([d, v])
    return sorted(out)


def bundesbank():
    t = get("https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A"
            "?format=csv&lang=en&lastNObservations=140")
    out = []
    for line in t.splitlines():
        m = re.match(r'^"?(\d{4}-\d{2}-\d{2})"?[;,]"?(-?\d+(?:[.,]\d+)?)"?', line.strip())
        if m:
            out.append([m.group(1), float(m.group(2).replace(",", "."))])
    if not out:
        raise ValueError("aucune donnée lue")
    return sorted(out)


def boe():
    start = (TODAY - dt.timedelta(days=200)).strftime("%d/%b/%Y")
    t = get("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes"
            f"&Datefrom={start}&Dateto=now&SeriesCodes=IUDMNPY&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
    out = []
    for r in csv.reader(io.StringIO(t)):
        if len(r) < 2:
            continue
        try:
            d = dt.datetime.strptime(r[0].strip(), "%d %b %Y").date().isoformat()
        except ValueError:
            continue
        v = num(r[1])
        if v is not None:
            out.append([d, v])
    if not out:
        raise ValueError("aucune donnée lue")
    return sorted(out)


def mof_japan():
    t = get("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv")
    rows = list(csv.reader(io.StringIO(t)))
    hi = next(i for i, r in enumerate(rows) if r and r[0].strip().lower() == "date")
    col = [c.strip() for c in rows[hi]].index("10Y")
    out = []
    for r in rows[hi + 1:]:
        try:
            d = dt.datetime.strptime(r[0].strip(), "%Y/%m/%d").date().isoformat()
        except (ValueError, IndexError):
            continue
        v = num(r[col]) if len(r) > col else None
        if v is not None:
            out.append([d, v])
    if not out:
        raise ValueError("aucune donnée lue")
    return sorted(out)


def fred(series):
    t = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")
    out = []
    for r in list(csv.reader(io.StringIO(t)))[1:]:
        v = num(r[1]) if len(r) > 1 else None
        if v is not None:
            out.append([r[0], v])
    return out[-24:]


def from_series(hist, src, monthly=False):
    if not hist:
        raise ValueError("vide")
    return {"price": hist[-1][1], "prev": hist[-2][1] if len(hist) > 1 else None,
            "src": src, "time": None, "hist": hist, "asof": hist[-1][0], "monthly": monthly}


def safe(name, fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        err(name, e)
        return None


def merge_hist(*lists):
    m = {}
    for lst in lists:
        for d, v in lst or []:
            if d and v is not None:
                m[str(d)[:10]] = round(float(v), 6)
    keys = sorted(m)[-KEEP_DAYS:]
    return [[k, m[k]] for k in keys]


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "data.json")
    old = {}
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f).get("items", {})
    except Exception:  # noqa: BLE001
        pass

    print("Cotations CNBC…")
    cnbc_load()
    print("Sources officielles…")
    ecb = safe("BCE", ecb_fx) or {}
    official = {
        "us10": ("Trésor américain", safe("Trésor US", us_treasury)),
        "de10": ("Bundesbank", safe("Bundesbank", bundesbank)),
        "uk10": ("Banque d'Angleterre", safe("Banque d'Angleterre", boe)),
        "jp10": ("Ministère des Finances du Japon", safe("MOF Japon", mof_japan)),
    }
    ecb_cross = {}
    if ecb.get("USD") and ecb.get("CNY"):
        usd = dict(ecb["USD"])
        ecb_cross["usdcny"] = [[d, v / usd[d]] for d, v in ecb["CNY"] if d in usd]
    ecb_series = {"eurusd": ecb.get("USD"), "eurcny": ecb.get("CNY"), "usdcny": ecb_cross.get("usdcny")}

    items = {}
    for iid, name, group, ysym, csym, ssym in ITEMS:
        print(f"{name}…")
        res = None
        chain = []
        if group == "taux":
            chain.append(("CNBC", cnbc, csym))
            chain.append(("Stooq", stooq, ssym))
            if iid in official and official[iid][1]:
                chain.append((official[iid][0], lambda h, s=official[iid][0]: from_series(h, s), official[iid][1]))
            if ysym:
                chain.append(("Yahoo", yahoo, ysym))
        else:
            chain.append(("CNBC", cnbc, csym))
            if ysym:
                chain.append(("Yahoo", yahoo, ysym))
            chain.append(("Stooq", stooq, ssym))
            if ecb_series.get(iid):
                chain.append(("BCE", lambda h: from_series(h, "BCE (référence)"), ecb_series[iid]))
        for label, fn, arg in chain:
            if not arg:
                continue
            try:
                res = fn(arg)
                break
            except Exception as e:  # noqa: BLE001
                err(f"{name} / {label}", e)
        if res is None and iid in FRED_MONTHLY:
            r = safe(f"{name} / FRED", fred, FRED_MONTHLY[iid])
            if r:
                res = from_series(r, "FRED (moyenne mensuelle OCDE)", monthly=True)

        prev_item = old.get(iid, {})
        extra = official.get(iid, (None, None))[1] if group == "taux" else None
        ch = None
        if csym and res is not None and res.get("src") in ("CNBC", "Stooq"):
            ch = safe(f"{name} / historique CNBC", cnbc_hist, csym)
        if res is None:
            if prev_item.get("price") is not None:
                prev_item["stale"] = True
                items[iid] = prev_item
            continue
        if res.get("monthly"):
            hist = res["hist"]
        else:
            hist = merge_hist(prev_item.get("hist") if not prev_item.get("monthly") else None, extra, ch, res.get("hist"))
        if res.get("prev") is None and len(hist) > 1:
            last_day = (res.get("time") or res.get("asof") or TODAY.isoformat())[:10]
            older = [v for d, v in hist if d < last_day]
            res["prev"] = older[-1] if older else None
        item = {"name": name, "group": group, "price": res["price"], "prev": res.get("prev"),
                "src": res["src"], "time": res.get("time"), "hist": hist}
        if res.get("asof"):
            item["asof"] = res["asof"]
        if res.get("monthly"):
            item["monthly"] = True
        if group == "change" and ecb_series.get(iid):
            item["ecb"] = ecb_series[iid][-1]
        items[iid] = item

    data = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "items": items, "errors": errors}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"OK : {len(items)}/{len(ITEMS)} éléments, {len(errors)} erreurs")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("Erreur inattendue :", e, file=sys.stderr)
