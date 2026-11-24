#!/bin/bash
mkdir -p /tmp/o; cd /tmp/o
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
t(){ echo "=== $1"; curl -sS -L -m 25 -A "$UA" -H 'Accept: text/html,application/json' -o "$1.body" -w '%{http_code} %{size_download}\n' "$2"; }
{
t sa_acn "https://stockanalysis.com/stocks/acn/dividend/"
t sa_tte "https://stockanalysis.com/quote/epa/TTE/dividend/"
t sa_bhp "https://stockanalysis.com/quote/lon/BHP/dividend/"
t nasdaq_acn "https://api.nasdaq.com/api/quote/ACN/dividends?assetclass=stocks"
t yahoo_div "https://query2.finance.yahoo.com/v8/finance/chart/TTE.PA?range=3y&interval=1mo&events=div"
t cnbc_div "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=ACN&requestMethod=extended&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
t digrin "https://www.digrin.com/stocks/detail/TTE.PA/"
} > out.txt 2>&1
for f in *.body; do echo "--- $f"; python3 - "$f" <<'P'
import sys,re
t=open(sys.argv[1],errors='replace').read()
for pat in [r'Dividend Growth[^<]{0,40}<[^>]*>[^<]{0,80}', r'"exDate":"[^"]+","[^}]{0,200}', r'ex_date[^,]{0,80}', r'"amount":"[^"]+"', r'divid[^"]{0,60}growth[^<]{0,80}']:
    m=re.findall(pat,t,flags=re.I)[:4]
    if m: print(pat[:20], m)
print(t[:300].replace('\n',' '))
P
done >> out.txt
rm -f *.body
