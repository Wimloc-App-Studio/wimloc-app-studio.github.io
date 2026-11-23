// Wimloc Invest : cotations en direct depuis le navigateur (CNBC, sans clé).
// Renvoie {symbole: {last, prev, time, dev}} ; les cours en pence (GBp) sont convertis en livres.
"use strict";
async function coursDirect(symboles){
  const out = {};
  const num = x => { if (x == null) return null; const v = parseFloat(String(x).replace(/[,%+]/g, "")); return isFinite(v) ? v : null; };
  for (let i = 0; i < symboles.length; i += 40){
    const lot = symboles.slice(i, i + 40).join("|");
    const url = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=" + encodeURIComponent(lot) +
      "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1";
    try {
      const r = await fetch(url, {cache: "no-store"});
      if (!r.ok) continue;
      let q = (await r.json())?.FormattedQuoteResult?.FormattedQuote || [];
      if (!Array.isArray(q)) q = [q];
      for (const x of q){
        const last = num(x.last); if (last == null) continue;
        const k = x.currencyCode === "GBp" ? 0.01 : 1, ch = num(x.change);
        let t = x.last_time ? Date.parse(String(x.last_time).replace(/([+-]\d\d)(\d\d)$/, "$1:$2")) : NaN;
        out[x.symbol] = {last: last*k, prev: ch != null ? (last - ch)*k : null, time: isFinite(t) ? new Date(t).toISOString() : null,
                         dev: x.currencyCode === "GBp" ? "GBP" : x.currencyCode};
      }
    } catch (e) { /* hors ligne ou service indisponible : on garde les données publiées */ }
  }
  return out;
}
