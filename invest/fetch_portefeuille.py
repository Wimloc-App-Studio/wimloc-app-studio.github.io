#!/usr/bin/env python3
"""Wimloc Invest : cours, historique et dividendes des titres du portefeuille.

Lit la liste des titres dans invest/portefeuille/portefeuille.json et écrit prices.json
dans le dossier donné en argument (en gardant l'historique déjà publié).
Sources sans clé : CNBC (cotations, graphiques, dividendes), BCE (taux de change officiels).
Ne plante jamais : les erreurs sont listées dans le JSON.
"""
import csv
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import zipfile

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}
HERE = os.path.dirname(os.path.abspath(__file__))
DEVISES = ["USD", "GBP", "DKK", "CAD", "JPY", "CHF", "CNY", "SEK", "NOK", "HKD"]
DEPUIS = "2025-06-01"
BENCH = [".STOXX50E", ".SPX", ".IXIC"]
errors = []


def get(url, binary=False, tries=2):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                b = r.read()
            return b if binary else b.decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * i)
    raise last


def num(x):
    if x is None:
        return None
    s = str(x).strip().replace(",", "").replace("%", "").replace("+", "")
    try:
        v = float(s)
        return v if v == v else None
    except ValueError:
        return None


def err(where, e):
    errors.append(f"{where}: {type(e).__name__}: {str(e)[:150]}")
    print("  ✗", errors[-1], file=sys.stderr)


def us_date(s):
    try:
        return dt.datetime.strptime(s, "%m/%d/%Y").date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def quotes(symbols):
    out = {}
    for i in range(0, len(symbols), 40):
        chunk = "|".join(symbols[i:i + 40])
        url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
               + urllib.parse.quote(chunk, safe="")
               + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
        try:
            q = json.loads(get(url)).get("FormattedQuoteResult", {}).get("FormattedQuote", [])
            for x in q if isinstance(q, list) else [q]:
                out[x.get("symbol")] = x
        except Exception as e:  # noqa: BLE001
            err("CNBC cotations", e)
    return out


def chart(sym):
    t = get("https://ts-api.cnbc.com/harmony/app/charts/1Y.json?symbol=" + urllib.parse.quote(sym, safe=""))
    bars = json.loads(t).get("barData", {}).get("priceBars") or []
    out = []
    for b in bars:
        tt, c = str(b.get("tradeTime") or ""), num(b.get("close"))
        if len(tt) >= 8 and c is not None:
            out.append([f"{tt[:4]}-{tt[4:6]}-{tt[6:8]}", c])
    if not out:
        raise ValueError("aucune barre")
    return out


def ecb():
    z = zipfile.ZipFile(io.BytesIO(get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip", binary=True)))
    text = z.read(z.namelist()[0]).decode("utf-8")
    out = {c: [] for c in DEVISES}
    for r in csv.DictReader(io.StringIO(text)):
        d = r.get("Date", "").strip()
        if d < DEPUIS:
            continue
        for c in DEVISES:
            v = num(r.get(c))
            if v:
                out[c].append([d, v])
    for c in out:
        out[c].sort()
    return out


def merge(*lists):
    m = {}
    for lst in lists:
        for d, v in lst or []:
            if d >= DEPUIS and v is not None:
                m[d] = round(v, 6)
    return [[k, m[k]] for k in sorted(m)]


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "prices.json")
    old = {}
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:  # noqa: BLE001
        pass
    with open(os.path.join(HERE, "portefeuille", "portefeuille.json"), encoding="utf-8") as f:
        pf = json.load(f)
    syms = list(pf.get("titres", {}).keys())
    for extra in pf.get("suivis", []):
        if extra not in syms:
            syms.append(extra)
    syms += [b for b in BENCH if b not in syms]

    q = quotes(syms + ["EUR=", "EURGBP=", "EURDKK=", "EURCAD=", "EURJPY=", "EURCHF=", "EURCNY="])
    titres = {}
    for s in syms:
        o = old.get("titres", {}).get(s, {})
        x = q.get(s) or {}
        cur = x.get("currencyCode")
        k = 0.01 if cur == "GBp" else 1.0
        hist = None
        try:
            hist = [[d, v * k] for d, v in chart(s)]
        except Exception as e:  # noqa: BLE001
            err(f"{s} historique", e)
        time.sleep(0.4)
        last = num(x.get("last"))
        ch = num(x.get("change"))
        ev = x.get("EventData") or {}
        item = {
            "nom": x.get("name") or o.get("nom"),
            "dev": "GBP" if cur == "GBp" else (cur or o.get("dev")),
            "last": last * k if last is not None else o.get("last"),
            "prev": (last - ch) * k if last is not None and ch is not None else o.get("prev"),
            "time": x.get("last_time") or o.get("time"),
            "div": num(x.get("dividend")) * k if num(x.get("dividend")) is not None else None,
            "rend": num(x.get("dividendyield")),
            "ex": us_date(ev.get("div_ex_date")) or o.get("ex"),
            "ex_montant": (num(ev.get("div_amount")) or 0) * (k if cur == "GBp" else 1) or o.get("ex_montant"),
            "hist": merge(o.get("hist"), hist),
        }
        if last is None and not x:
            err(f"{s} cotation", ValueError("absent de CNBC"))
            item["stale"] = True
        # garder les détachements observés (date -> montant)
        ex_hist = dict((o.get("ex_hist") or {}))
        if item["ex"] and item["ex_montant"]:
            ex_hist[item["ex"]] = item["ex_montant"]
        item["ex_hist"] = ex_hist
        titres[s] = item
        print(f"{s:10} {item['last']} {item['dev']} {len(item['hist'])} j")

    fx_old = old.get("fx", {})
    try:
        e = ecb()
    except Exception as ex:  # noqa: BLE001
        err("BCE", ex)
        e = {}
    live = {"USD": "EUR=", "GBP": "EURGBP=", "DKK": "EURDKK=", "CAD": "EURCAD=", "JPY": "EURJPY=", "CHF": "EURCHF=", "CNY": "EURCNY="}
    fx = {}
    for c in DEVISES:
        lv = num((q.get(live.get(c, "")) or {}).get("last")) if c in live else None
        fx[c] = {"hist": merge((fx_old.get(c) or {}).get("hist"), e.get(c)), "live": lv or (fx_old.get(c) or {}).get("live")}

    data = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "titres": titres, "fx": fx, "errors": errors}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"OK : {len(titres)} titres, {len(errors)} erreurs")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("Erreur inattendue :", e, file=sys.stderr)
