import json, urllib.request, urllib.parse, sys, os
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36","Accept":"application/json, text/plain, */*"}
out=sys.argv[1]; os.makedirs(out,exist_ok=True)
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=40) as r: return r.read().decode("utf-8","replace")
    except Exception as e: return "ERR "+repr(e)
syms="GOOGL|GOOG|ACN|BABA|AMZN|ASPI|BHP-GB|BKNG|CAP-FR|CVX|DSY-FR|ENB|GEV|GE|NOVOB-DK|RIO-GB|SGO-FR|SFL|SHELL-NL|SONY|TTE-FR|VIRI-FR|MDT|UAA|FTNT|PDD|GEHC|BHP.L|SHEL-NL|NOVO.B-DK|.STOXX50E|EURGBP=|EURDKK="
u="https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="+urllib.parse.quote(syms,safe="")+"&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
open(f"{out}/cnbc_quote.json","w").write(get(u))
for s in ["CAP-FR","ACN"]:
    for rng in ["1Y","5Y","ALL"]:
        open(f"{out}/chart_{s}_{rng}.json","w").write(get("https://ts-api.cnbc.com/harmony/app/charts/"+rng+".json?symbol="+urllib.parse.quote(s,safe=""))[:3000])
for s in ["ACN","CVX","SFL"]:
    open(f"{out}/nasdaq_div_{s}.json","w").write(get(f"https://api.nasdaq.com/api/quote/{s}/dividends?assetclass=stocks")[:6000])
open(f"{out}/nasdaq_cal.json","w").write(get("https://api.nasdaq.com/api/calendar/dividends?date=2026-11-20")[:3000])
