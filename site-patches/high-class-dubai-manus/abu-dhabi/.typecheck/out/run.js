"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const routes_1 = require("./lib/routes");
const abu_dhabi_1 = require("./lib/abu-dhabi");
const whatsapp_ref_1 = require("./lib/whatsapp-ref");
const assert = (c, m) => { if (!c) {
    console.log('FAIL', m);
    process.exitCode = 1;
}
else
    console.log('ok  ', m); };
const pages = (0, whatsapp_ref_1.whatsappRefPages)();
assert(routes_1.abuDhabiLocales.every(l => abu_dhabi_1.abuDhabiPageIds.every(id => pages[(0, routes_1.abuDhabiPath)(l, id)] === (0, abu_dhabi_1.abuDhabiPageKey)(id))), 'ref keys for 80 pages');
assert(pages[(0, routes_1.destinationPath)('ar', 'abu-dhabi')] === 'destino-abu-dhabi', 'hub ref key unchanged');
assert(pages[(0, routes_1.routePath)('pt', 'dubai')] === 'dubai', 'dubai ref key unchanged');
assert((0, routes_1.translateCurrentPath)('/en/destinations/abu-dhabi/sheikh-zayed-grand-mosque', 'pt') === '/pt/destinos/abu-dhabi/grande-mesquita-sheikh-zayed', 'switch en->pt');
assert((0, routes_1.translateCurrentPath)(encodeURI((0, routes_1.abuDhabiPath)('ar', 'summer')), 'es') === '/es/destinos/abu-dhabi/abu-dabi-en-verano', 'switch ar->es');
assert((0, routes_1.translateCurrentPath)('/en/destinations/abu-dhabi/abu-dhabi-in-summer', 'de') === '/de/reiseziele/abu-dhabi', 'fallback to hub in de');
assert((0, routes_1.translateCurrentPath)('/pt/dubai/visto-dubai-brasileiros', 'en') === '/en/dubai', 'dubai article behaviour unchanged');
assert((0, routes_1.translateCurrentPath)('/en/destinations/dubai', 'ar') === (0, routes_1.destinationPath)('ar', 'dubai'), 'dubai destination unchanged');
assert((0, abu_dhabi_1.abuDhabiLocation)('hub') === 'abudhabi_hub_abu-dhabi' && (0, abu_dhabi_1.abuDhabiLocation)('culture') === 'abudhabi_itinerary_culture', 'locations');
assert((0, abu_dhabi_1.abuDhabiLinkPath)('es', 'dubai-abu-dhabi-6n') === '/es/itinerarios/dubai-abu-dhabi-6-noches', 'link to dubai+abu dhabi programme');
assert((0, whatsapp_ref_1.whatsappRefScript)().includes('abudhabi-attraction-qasr-al-hosn'), 'script embeds new keys');
console.log('example AR path:', (0, routes_1.abuDhabiPath)('ar', 'sheikh-zayed-grand-mosque'));
