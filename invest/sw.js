// Wimloc Invest : réseau d'abord, copie locale si hors ligne.
const CACHE = "wimloc-invest-v2";
const BASE = ["./", "./direct.js", "./portefeuille/", "./portefeuille/portefeuille.json", "../style.css", "./icone-192.png", "./icone-512.png", "./manifest.webmanifest", "../images/marque_claire.png"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(BASE)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const donnees = url.hostname === "raw.githubusercontent.com";
  if (url.origin !== location.origin && !donnees) return;
  const cle = donnees ? url.origin + url.pathname : req;   // sans le paramètre anti-cache
  e.respondWith(fetch(req).then(rep => {
    if (rep.ok) { const copie = rep.clone(); caches.open(CACHE).then(c => c.put(cle, copie)); }
    return rep;
  }).catch(() => caches.match(cle).then(r => r || caches.match(req, {ignoreSearch: true}))));
});
