#!/bin/bash
mkdir -p /tmp/o; cd /tmp/o
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'
O='https://wimloc-app-studio.github.io'
t(){ echo "=== $1"; curl -sS -m 20 -A "$UA" -H "Origin: $O" -D - -o body.txt "$2" | grep -i -E '^HTTP|access-control|content-type'; head -c 200 body.txt; echo; }
{
t cnbc_json "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=GOOGL%7CTTE-FR&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
t cnbc_jsonp "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=GOOGL%7CTTE-FR&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=jsonp&callback=wimloc&events=1"
t cnbc_chart "https://ts-api.cnbc.com/harmony/app/charts/1D.json?symbol=GOOGL"
t yahoo "https://query1.finance.yahoo.com/v8/finance/chart/GOOGL?range=1d&interval=5m"
t stooq "https://stooq.com/q/l/?s=googl.us&f=sd2t2c&h&e=csv"
t frankfurter "https://api.frankfurter.app/latest?from=EUR&to=USD"
t ecb "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?lastNObservations=1&format=jsondata"
} > out.txt 2>&1
