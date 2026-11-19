import json, urllib.request, urllib.parse, sys, os
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36","Accept":"application/json, text/plain, */*"}
out=sys.argv[1]; os.makedirs(out,exist_ok=True)
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=40) as r: return r.read().decode("utf-8","replace")
    except Exception as e: return "ERR "+repr(e)
syms="BGO-FR|NVO|CRI-FR|BGOB-FR|NOVO_B-DK|NOVOb-DK"
u="https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="+urllib.parse.quote(syms,safe="")+"&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
open(f"{out}/q2.json","w").write(get(u))
for s in ["BHP-GB",".STOXX50E","VIRI-FR"]:
    t=get("https://ts-api.cnbc.com/harmony/app/charts/1Y.json?symbol="+urllib.parse.quote(s,safe=""))
    open(f"{out}/c_{s}.json","w").write(t[:1500]+"\n...\n"+t[-600:])
t=get("https://api.nasdaq.com/api/calendar/dividends?date=2026-09-12")
import re
open(f"{out}/cal.txt","w").write(str(len(t))+"\n"+"\n".join(re.findall(r'\{"companyName":"[^}]*(?:"CVX"|"GOOGL"|"ENB"|"SFL")[^}]*\}',t)))
t=get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip")
open(f"{out}/ecb.txt","w").write(str(len(t)))
