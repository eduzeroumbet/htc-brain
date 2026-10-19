"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.whatsappRefPages = whatsappRefPages;
exports.whatsappRefScript = whatsappRefScript;
const routing_1 = require("../i18n/routing");
const routes_1 = require("./routes");
// ref = <page_key>-<lang>; page_key is language independent so the same page shares one key in every locale.
const routeKeys = { home: 'home', about: 'sobre', services: 'servicos', business: 'negocios', experiences: 'experiencias', destinations: 'destinos', itineraries: 'roteiros', dubai: 'dubai', dubaiNow: 'dubai-seguro', agencies: 'para-agencias', events: 'eventos-hcb1', fleet: 'frota', hotels: 'hoteis', contact: 'contato', privacy: 'politica-privacidade', terms: 'termos', cancellation: 'cancelamento', cookies: 'politica-cookies' };
const serviceKeys = { 'private-tours': 'roteiros-privativos', concierge: 'concierge', transfers: 'transfers', hotels: 'hospedagem', flights: 'voos', 'travel-essentials': 'vistos-seguro-esim', 'special-services': 'servicos-especiais', 'trade-shows': 'feiras-missoes', corporate: 'corporativo', events: 'eventos-dubai', desert: 'deserto', 'sea-sky': 'mar-ceu', motorsport: 'automobilismo', 'dining-shopping': 'gastronomia-compras' };
const articleKeys = { visa: 'visto-dubai', season: 'melhor-epoca-dubai', rules: 'regras-dubai', transport: 'transporte-dubai', fairs: 'feiras-em-dubai' };
function whatsappRefPages() {
    const pages = { '/': 'home' };
    for (const locale of routing_1.locales) {
        for (const key of Object.keys(routes_1.routeSlugs[locale]))
            pages[(0, routes_1.routePath)(locale, key)] = routeKeys[key];
        for (const id of Object.keys(routes_1.serviceSlugs[locale]))
            pages[(0, routes_1.servicePath)(locale, id)] = serviceKeys[id];
        for (const id of Object.keys(routes_1.destinationSlugs[locale]))
            pages[(0, routes_1.destinationPath)(locale, id)] = `destino-${id}`;
        for (const id of Object.keys(routes_1.itinerarySlugs[locale]))
            pages[(0, routes_1.itineraryPath)(locale, id)] = id;
    }
    // Dubai articles are published only in Portuguese.
    for (const id of Object.keys(routes_1.dubaiArticleSlugs.pt))
        pages[(0, routes_1.dubaiArticlePath)('pt', id)] = articleKeys[id];
    return pages;
}
// Runs in the browser from the root layout <head>. Never touches the phone number: only the text, ref and utm_* query params change.
function whatsappRefScript() {
    return `(function(){var PAGES=${JSON.stringify(whatsappRefPages())};var LANGS=${JSON.stringify(routing_1.locales)};var UTM=['utm_source','utm_medium','utm_campaign','utm_term','utm_content'];var SEL='a[href*="wa.me/"],a[href*="api.whatsapp.com/send"]';
function path(){var p=location.pathname;try{p=decodeURIComponent(p)}catch(e){}return p.length>1?p.replace(/\\/+$/,''):p}
function lang(p){var s=p.split('/')[1];return LANGS.indexOf(s)>-1?s:'pt'}
function key(p){if(PAGES[p])return PAGES[p];var parts=p.split('/').filter(Boolean);if(!parts.length||(parts.length===1&&LANGS.indexOf(parts[0])>-1))return 'home';return parts[parts.length-1]||'pagina'}
function decorate(href){try{var p=path(),ref=key(p)+'-'+lang(p),url=new URL(href,location.href),q=new URLSearchParams(location.search);UTM.forEach(function(k){if(q.has(k))url.searchParams.set(k,q.get(k))});var text=(url.searchParams.get('text')||'').replace(/\\s*\\(ref=[^)]*\\)\\s*$/,'');url.searchParams.set('text',(text?text+' ':'')+'(ref='+ref+')');url.searchParams.set('ref',ref);return url.toString()}catch(e){return href}}
function apply(a){var href=a.getAttribute('href');if(!href)return;if(href!==a.dataset.waDecorated)a.dataset.waOriginal=href;var next=decorate(a.dataset.waOriginal);if(next!==href)a.setAttribute('href',next);a.dataset.waDecorated=next}
function all(){var links=document.querySelectorAll(SEL);for(var i=0;i<links.length;i++)apply(links[i])}
document.addEventListener('click',function(e){var a=e.target&&e.target.closest&&e.target.closest(SEL);if(a)apply(a)},true);
function start(){all();if(window.MutationObserver)new MutationObserver(all).observe(document.body,{childList:true,subtree:true})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start()})();`;
}
