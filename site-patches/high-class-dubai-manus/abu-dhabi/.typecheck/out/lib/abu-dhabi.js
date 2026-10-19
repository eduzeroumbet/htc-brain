"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.abuDhabiIdsByKind = exports.abuDhabiPageIds = exports.abuDhabiPages = exports.abuDhabiHub = exports.abuDhabiPendingFacts = exports.abuDhabiSources = exports.abuDhabiUpdatedAt = void 0;
exports.abuDhabiLocation = abuDhabiLocation;
exports.abuDhabiPageKey = abuDhabiPageKey;
exports.abuDhabiLinkPath = abuDhabiLinkPath;
exports.isAbuDhabiLinkKey = isAbuDhabiLinkKey;
const routes_1 = require("./routes");
// Content date for sitemap lastModified. Change it whenever the Abu Dhabi texts change.
exports.abuDhabiUpdatedAt = '2026-10-18';
exports.abuDhabiSources = {
    S1: { name: 'Visit Abu Dhabi, Things to do', url: 'https://visitabudhabi.ae/en/things-to-do-home', updatedAt: '2026-10-08', consultedAt: '2026-10-19' },
    S2: { name: 'Visit Abu Dhabi, 100 things to do in Abu Dhabi', url: 'https://visitabudhabi.ae/en/plan-your-trip/article-hub/100-things-to-do-in-abu-dhabi', updatedAt: '2026-10-08', consultedAt: '2026-10-19' },
    S3: { name: 'Visit Abu Dhabi, Summer in Abu Dhabi', url: 'https://visitabudhabi.ae/en/campaign/summer-in-abu-dhabi-long-stay-couple-gcc-dvc', updatedAt: '2026-10-09', consultedAt: '2026-10-19' },
    S4: { name: 'Visit Abu Dhabi, 17 of Abu Dhabi’s top indoor activities', url: 'https://visitabudhabi.ae/en/plan-your-trip/article-hub/14-indoor-places-in-abu-dhabi', updatedAt: '2026-10-14', consultedAt: '2026-10-19' },
    S5: { name: 'Visit Abu Dhabi, Abu Dhabi Little Do’s', url: 'https://visitabudhabi.ae/en/plan-your-trip/article-hub/abu-dhabi-little-dos', updatedAt: '2026-10-17', consultedAt: '2026-10-19' },
    S6: { name: 'Visit Abu Dhabi, Family things to do in Abu Dhabi', url: 'https://visitabudhabi.ae/en/things-to-do/families', updatedAt: '2026-10-04', consultedAt: '2026-10-19' },
    S7: { name: 'Visit Abu Dhabi, How many days to spend in Abu Dhabi', url: 'https://visitabudhabi.ae/en/plan-your-trip/article-hub/how-many-days-in-abu-dhabi', updatedAt: '2026-10-06', consultedAt: '2026-10-19' },
    S8: { name: 'Visit Abu Dhabi, shuttle bus routes 2026 (PDF)', url: 'https://visitabudhabi.ae/-/media/project/vad/galleryimages/plan-your-trip/around-the-emirate/shuttle-bus/exp-ad_bus-routes-interactive_full_2026.pdf', updatedAt: '2026-09-22', consultedAt: '2026-10-19' },
    I1: { name: 'High Class Travel Experiences, Abu Dhabi programmes', url: 'https://highclass.you/en/destinations/abu-dhabi', updatedAt: null, consultedAt: '2026-10-18' }
};
// Facts that stay "A CONFIRMAR" (status) and are never shown to the public as values. Internal notes, in Portuguese.
exports.abuDhabiPendingFacts = {
    'AC-01': { status: 'A CONFIRMAR', topic: 'Horários, preços, ingressos e reservas de cada atração' },
    'AC-02': { status: 'A CONFIRMAR', topic: 'Regras de entrada, código de vestimenta e fotografia por atração' },
    'AC-03': { status: 'A CONFIRMAR', topic: 'Restrições de idade e altura, acessibilidade e adequação por perfil' },
    'AC-04': { status: 'A CONFIRMAR', topic: 'Sheikh Zayed Grand Mosque: localização detalhada, vestimenta, reserva e fotografia (o catálogo atual cita "Saadiyat Cultural District", sem fonte)' },
    'AC-05': { status: 'A CONFIRMAR', topic: '"Yas Waves": nome oficial ou equivalente a Yas Waterworld Abu Dhabi' },
    'AC-06': { status: 'A CONFIRMAR', topic: 'Instituições de Saadiyat abertas na data de publicação' },
    'AC-07': { status: 'A CONFIRMAR', topic: 'Temperaturas mês a mês e meses recomendados por perfil' },
    'AC-08': { status: 'A CONFIRMAR', topic: 'Nome oficial atual do aeroporto AUH, transporte terrestre e tempos de traslado' },
    'AC-09': { status: 'A CONFIRMAR', topic: 'Distância e tempo de viagem Dubai–Abu Dhabi e viabilidade no mesmo dia' },
    'AC-10': { status: 'A CONFIRMAR', topic: 'Shuttle: dias de operação, frequência e tarifas' },
    'AC-12': { status: 'A CONFIRMAR', topic: 'Liwa: fonte oficial específica, localização, atividades, temporada e segurança' },
    'AC-13': { status: 'A CONFIRMAR', topic: 'Jebel Hafit/Jebel Hafeet: grafia oficial, rota, trilhas e regras de camping' },
    'AC-14': { status: 'A CONFIRMAR', topic: 'Jubail Mangrove Park: ponto de partida, operador, reserva, maré e regras ambientais' },
    'AC-15': { status: 'A CONFIRMAR', topic: 'Emirates Palace: acesso de não hóspedes, reservas e código de vestimenta' },
    'AC-16': { status: 'A CONFIRMAR', topic: 'Qasr Al Hosn: programação, exposições e situação operacional' },
    'AC-17': { status: 'A CONFIRMAR', topic: 'Qasr Al Watan: áreas abertas, apresentações e regras de segurança' },
    'AC-18': { status: 'A CONFIRMAR', topic: 'Louvre Abu Dhabi: exposições em cartaz e dias de fechamento' },
    'AC-19': { status: 'A CONFIRMAR', topic: 'Ferrari World e Yas Island: atrações em operação e ingressos combinados' },
    'AC-20': { status: 'A CONFIRMAR', topic: 'Warner Bros. World Abu Dhabi: calendário operacional' },
    'AC-21': { status: 'A CONFIRMAR', topic: 'Corniche: zonas de praia, regras de banho, serviços e fechamentos' },
    'AC-22': { status: 'A CONFIRMAR', topic: 'Saadiyat: acesso e regras das praias' },
    'AC-23': { status: 'A CONFIRMAR', topic: 'Faixas de temperatura do verão (só em conteúdo sazonal da fonte)' },
    'AC-24': { status: 'A CONFIRMAR', topic: 'Regras de conduta além do vestuário' },
    'AC-25': { status: 'A CONFIRMAR', topic: 'Volume e dificuldade das palavras-chave (Search Console e ferramenta datada; ação 96f63f7d)' },
    'AC-26': { status: 'A CONFIRMAR', topic: 'Oferta de transporte privado e guia em Abu Dhabi (operações da High Class)' },
    'AC-27': { status: 'A CONFIRMAR', topic: 'Conferência dos fatos em fonte do DCT Abu Dhabi' }
};
exports.abuDhabiHub = { sources: ['S1', 'S2', 'S3', 'S4', 'S7', 'S8', 'I1'], pending: ['AC-04', 'AC-07', 'AC-08', 'AC-09', 'AC-10', 'AC-24', 'AC-27'], related: ['dubai-hub', 'dubai-abu-dhabi-6n'], indexable: true };
exports.abuDhabiPages = {
    'sheikh-zayed-grand-mosque': { kind: 'attraction', sources: ['S1', 'S2', 'S3'], pending: ['AC-01', 'AC-02', 'AC-04'], related: ['qasr-al-watan', 'culture', 'one-day', 'hub'], indexable: true },
    'louvre-abu-dhabi': { kind: 'attraction', sources: ['S1', 'S3', 'S4', 'S6'], pending: ['AC-01', 'AC-02', 'AC-18'], related: ['saadiyat-island', 'culture', 'weekend', 'hub'], indexable: true },
    'qasr-al-watan': { kind: 'attraction', sources: ['S1', 'S2', 'S4', 'S6'], pending: ['AC-01', 'AC-02', 'AC-17'], related: ['sheikh-zayed-grand-mosque', 'qasr-al-hosn', 'culture', 'hub'], indexable: true },
    'ferrari-world-yas-island': { kind: 'attraction', sources: ['S1', 'S4', 'S5', 'S6', 'S7'], pending: ['AC-01', 'AC-02', 'AC-03', 'AC-19'], related: ['warner-bros-world-abu-dhabi', 'yas-waterworld-abu-dhabi', 'family', 'hub'], indexable: true },
    'warner-bros-world-abu-dhabi': { kind: 'attraction', sources: ['S3', 'S4', 'S5', 'S6'], pending: ['AC-01', 'AC-02', 'AC-03', 'AC-20'], related: ['ferrari-world-yas-island', 'yas-waterworld-abu-dhabi', 'family', 'hub'], indexable: true },
    // noindex until AC-05 is closed (Edu decides).
    'yas-waterworld-abu-dhabi': { kind: 'attraction', sources: ['S1', 'S5', 'S7'], pending: ['AC-01', 'AC-02', 'AC-03', 'AC-05'], related: ['ferrari-world-yas-island', 'warner-bros-world-abu-dhabi', 'family', 'hub'], indexable: false },
    'saadiyat-island': { kind: 'attraction', sources: ['S1', 'S4', 'S8'], pending: ['AC-01', 'AC-02', 'AC-06', 'AC-10', 'AC-22'], related: ['louvre-abu-dhabi', 'culture', 'luxury', 'hub'], indexable: true },
    corniche: { kind: 'attraction', sources: ['S3', 'S6'], pending: ['AC-01', 'AC-21'], related: ['one-day', 'weekend', 'family', 'hub'], indexable: true },
    'al-ain-jebel-hafeet': { kind: 'attraction', sources: ['S2', 'S7'], pending: ['AC-01', 'AC-03', 'AC-13'], related: ['liwa-desert', 'mangroves-jubail', 'culture', 'hub'], indexable: true },
    // noindex until AC-12 is closed (Edu decides).
    'liwa-desert': { kind: 'attraction', sources: ['S1', 'S2'], pending: ['AC-01', 'AC-02', 'AC-03', 'AC-12'], related: ['al-ain-jebel-hafeet', 'mangroves-jubail', 'hub'], indexable: false },
    'mangroves-jubail': { kind: 'attraction', sources: ['S1', 'S8'], pending: ['AC-01', 'AC-02', 'AC-03', 'AC-10', 'AC-14'], related: ['al-ain-jebel-hafeet', 'liwa-desert', 'family', 'hub'], indexable: true },
    'emirates-palace': { kind: 'attraction', sources: ['S1'], pending: ['AC-01', 'AC-02', 'AC-15'], related: ['luxury', 'corniche', 'hub'], indexable: true },
    'qasr-al-hosn': { kind: 'attraction', sources: ['S4'], pending: ['AC-01', 'AC-02', 'AC-16'], related: ['qasr-al-watan', 'culture', 'hub'], indexable: true },
    'one-day': { kind: 'itinerary', sources: ['S3', 'S7', 'I1'], pending: ['AC-01', 'AC-04', 'AC-09', 'AC-26'], related: ['sheikh-zayed-grand-mosque', 'louvre-abu-dhabi', 'qasr-al-watan', 'corniche', 'how-many-days'], indexable: true, stops: ['sheikh-zayed-grand-mosque', 'louvre-abu-dhabi', 'corniche'] },
    weekend: { kind: 'itinerary', sources: ['S7'], pending: ['AC-01', 'AC-02', 'AC-09', 'AC-19', 'AC-26'], related: ['one-day', 'ferrari-world-yas-island', 'saadiyat-island', 'how-many-days'], indexable: true, stops: ['sheikh-zayed-grand-mosque', 'qasr-al-watan', 'corniche', 'louvre-abu-dhabi', 'qasr-al-hosn', 'ferrari-world-yas-island'] },
    family: { kind: 'itinerary', sources: ['S5', 'S6'], pending: ['AC-01', 'AC-02', 'AC-03', 'AC-20'], related: ['ferrari-world-yas-island', 'warner-bros-world-abu-dhabi', 'yas-waterworld-abu-dhabi', 'corniche'], indexable: true, stops: ['ferrari-world-yas-island', 'warner-bros-world-abu-dhabi', 'yas-waterworld-abu-dhabi', 'louvre-abu-dhabi', 'qasr-al-watan', 'corniche'] },
    luxury: { kind: 'itinerary', sources: ['S1'], pending: ['AC-01', 'AC-02', 'AC-15', 'AC-26'], related: ['emirates-palace', 'saadiyat-island', 'louvre-abu-dhabi'], indexable: true, stops: ['louvre-abu-dhabi', 'saadiyat-island', 'qasr-al-watan', 'sheikh-zayed-grand-mosque', 'emirates-palace'] },
    culture: { kind: 'itinerary', sources: ['S1', 'S2', 'S4', 'S7'], pending: ['AC-01', 'AC-02', 'AC-04'], related: ['louvre-abu-dhabi', 'qasr-al-watan', 'qasr-al-hosn', 'sheikh-zayed-grand-mosque', 'al-ain-jebel-hafeet'], indexable: true, stops: ['sheikh-zayed-grand-mosque', 'qasr-al-watan', 'louvre-abu-dhabi', 'qasr-al-hosn', 'al-ain-jebel-hafeet'] },
    'how-many-days': { kind: 'article', sources: ['S1', 'S5', 'S6', 'S7'], pending: ['AC-01', 'AC-02', 'AC-09', 'AC-26'], related: ['hub', 'one-day', 'weekend', 'family', 'culture', 'ferrari-world-yas-island'], indexable: true },
    summer: { kind: 'article', sources: ['S1', 'S3', 'S4', 'S5'], pending: ['AC-01', 'AC-04', 'AC-07', 'AC-23'], related: ['hub', 'louvre-abu-dhabi', 'corniche', 'weekend', 'family'], indexable: true }
};
exports.abuDhabiPageIds = Object.keys(exports.abuDhabiPages);
const abuDhabiIdsByKind = (kind) => exports.abuDhabiPageIds.filter(id => exports.abuDhabiPages[id].kind === kind);
exports.abuDhabiIdsByKind = abuDhabiIdsByKind;
// Tracking: GA4 lead_intent location / Meta wa_position = abudhabi_<tipo>_<chave>; ref page_key = abudhabi-<tipo>-<chave>.
function abuDhabiLocation(id) { return id === 'hub' ? 'abudhabi_hub_abu-dhabi' : `abudhabi_${exports.abuDhabiPages[id].kind}_${id}`; }
function abuDhabiPageKey(id) { return `abudhabi-${exports.abuDhabiPages[id].kind}-${id}`; }
function abuDhabiLinkPath(locale, key) {
    if (key === 'hub')
        return (0, routes_1.destinationPath)(locale, 'abu-dhabi');
    if (key === 'dubai-hub')
        return (0, routes_1.routePath)(locale, 'dubai');
    if (key === 'dubai-abu-dhabi-6n')
        return (0, routes_1.itineraryPath)(locale, 'dubai-abu-dhabi-6n');
    return (0, routes_1.abuDhabiPath)(locale, key);
}
function isAbuDhabiLinkKey(value) {
    return value === 'hub' || value === 'dubai-hub' || value === 'dubai-abu-dhabi-6n' || value in exports.abuDhabiPages;
}
