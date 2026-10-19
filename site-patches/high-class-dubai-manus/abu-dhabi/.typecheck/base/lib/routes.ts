import type {Locale} from '@/i18n/routing';

export type RouteKey = 'home' | 'about' | 'services' | 'business' | 'experiences' | 'destinations' | 'itineraries' | 'dubai' | 'dubaiNow' | 'agencies' | 'events' | 'fleet' | 'hotels' | 'contact' | 'privacy' | 'terms' | 'cancellation' | 'cookies';
export type ServiceId = 'private-tours' | 'concierge' | 'transfers' | 'hotels' | 'flights' | 'travel-essentials' | 'special-services' | 'trade-shows' | 'corporate' | 'events' | 'desert' | 'sea-sky' | 'motorsport' | 'dining-shopping';
export type DubaiArticleId = 'visa' | 'season' | 'rules' | 'transport' | 'fairs';
export type DestinationId = 'dubai' | 'abu-dhabi' | 'ras-al-khaimah' | 'sharjah' | 'ajman' | 'fujairah' | 'umm-al-quwain' | 'oman' | 'catar' | 'arabia-saudita';
export type ItineraryId = 'dubai-essencial-4n' | 'dubai-familia-5n' | 'lua-de-mel-5n' | 'dubai-abu-dhabi-6n' | 'dubai-completo-10-14n' | 'stopover-48h';

export const routeSlugs: Record<Locale, Record<RouteKey, string>> = {
  pt: {home:'',about:'sobre',services:'servicos',business:'negocios',experiences:'experiencias',destinations:'destinos',itineraries:'roteiros',dubai:'dubai',dubaiNow:'dubai-seguro-agora-2026',agencies:'para-agencias',events:'eventos-hcb1',fleet:'frota',hotels:'hoteis-por-perfil',contact:'contato',privacy:'politica-de-privacidade',terms:'termos-de-servico',cancellation:'cancelamento-e-remarcacao',cookies:'politica-de-cookies'},
  en: {home:'',about:'about',services:'services',business:'business',experiences:'experiences',destinations:'destinations',itineraries:'itineraries',dubai:'dubai',dubaiNow:'is-dubai-safe-now-2026',agencies:'for-travel-agencies',events:'hcb1-events',fleet:'fleet',hotels:'hotels-by-profile',contact:'contact',privacy:'privacy',terms:'terms-of-service',cancellation:'cancellation-and-rescheduling',cookies:'cookie-policy'},
  es: {home:'',about:'nosotros',services:'servicios',business:'negocios',experiences:'experiencias',destinations:'destinos',itineraries:'itinerarios',dubai:'dubai',dubaiNow:'dubai-es-seguro-ahora-2026',agencies:'para-agencias',events:'eventos-hcb1',fleet:'flota',hotels:'hoteles-por-perfil',contact:'contacto',privacy:'privacidad',terms:'terminos-de-servicio',cancellation:'cancelacion-y-reprogramacion',cookies:'politica-de-cookies'},
  ar: {home:'',about:'من-نحن',services:'الخدمات',business:'الأعمال',experiences:'التجارب',destinations:'الوجهات',itineraries:'البرامج',dubai:'دبي',dubaiNow:'هل-دبي-آمنة-الآن-2026',agencies:'لوكالات-السفر',events:'فعاليات-hcb1',fleet:'الأسطول',hotels:'الفنادق-حسب-الملف',contact:'اتصل-بنا',privacy:'الخصوصية',terms:'شروط-الخدمة',cancellation:'الإلغاء-وإعادة-الجدولة',cookies:'سياسة-ملفات-الارتباط'},
  hi: {home:'',about:'हमारे-बारे-में',services:'सेवाएं',business:'व्यवसाय',experiences:'अनुभव',destinations:'गंतव्य',itineraries:'यात्रा-कार्यक्रम',dubai:'दुबई',dubaiNow:'क्या-दुबई-अभी-सुरक्षित-है-2026',agencies:'ट्रैवल-एजेंसियां',events:'hcb1-इवेंट्स',fleet:'वाहन-बेड़ा',hotels:'प्रोफाइल-के-अनुसार-होटल',contact:'संपर्क',privacy:'गोपनीयता',terms:'सेवा-शर्तें',cancellation:'रद्दीकरण',cookies:'कुकी-नीति'},
  ru: {home:'',about:'о-нас',services:'услуги',business:'бизнес',experiences:'впечатления',destinations:'направления',itineraries:'маршруты',dubai:'дубай',dubaiNow:'безопасен-ли-дубай-сейчас-2026',agencies:'для-агентств',events:'события-hcb1',fleet:'автопарк',hotels:'отели-по-профилю',contact:'контакты',privacy:'конфиденциальность',terms:'условия-обслуживания',cancellation:'отмена-и-перенос',cookies:'политика-cookie'},
  de: {home:'',about:'ueber-uns',services:'leistungen',business:'geschaeftsreisen',experiences:'erlebnisse',destinations:'reiseziele',itineraries:'reiseprogramme',dubai:'dubai',dubaiNow:'ist-dubai-jetzt-sicher-2026',agencies:'fuer-reiseagenturen',events:'hcb1-events',fleet:'fuhrpark',hotels:'hotels-nach-reiseprofil',contact:'kontakt',privacy:'datenschutz',terms:'nutzungsbedingungen',cancellation:'stornierung-und-umbuchung',cookies:'cookie-richtlinie'}
};

export function routePath(locale: Locale, key: RouteKey) {
  const slug = routeSlugs[locale][key];
  return `/${locale}${slug ? `/${slug}` : ''}`;
}

export const serviceSlugs: Record<Locale, Record<ServiceId, string>> = {
  pt: {'private-tours':'roteiros-privativos-guia-licenciado',concierge:'concierge-assistencia-24h',transfers:'transfers-motorista-privativo',hotels:'hospedagem-selecionada',flights:'voos-e-conexoes','travel-essentials':'vistos-seguro-esim','special-services':'servicos-especiais','trade-shows':'feiras-missoes-empresariais',corporate:'viagens-corporativas-incentive',events:'eventos-em-dubai',desert:'deserto-natureza','sea-sky':'mar-ceu-iate-helicoptero',motorsport:'automobilismo-adrenalina','dining-shopping':'gastronomia-compras-noite'},
  en: {'private-tours':'private-tours-licensed-guide',concierge:'concierge-assistance',transfers:'transfers-private-chauffeur',hotels:'curated-accommodation',flights:'flights-and-connections','travel-essentials':'visas-insurance-esim','special-services':'special-services','trade-shows':'trade-shows-business-missions',corporate:'corporate-travel-incentive-trips',events:'events-in-dubai',desert:'desert-nature','sea-sky':'sea-sky-yacht-helicopter',motorsport:'motorsport-adrenaline','dining-shopping':'dining-shopping-nightlife'},
  es: {'private-tours':'recorridos-privados-guia-licenciado',concierge:'concierge-asistencia-24h',transfers:'traslados-chofer-privado',hotels:'alojamiento-seleccionado',flights:'vuelos-y-conexiones','travel-essentials':'visados-seguro-esim','special-services':'servicios-especiales','trade-shows':'ferias-misiones-empresariales',corporate:'viajes-corporativos-incentivos',events:'eventos-en-dubai',desert:'desierto-naturaleza','sea-sky':'mar-cielo-yate-helicoptero',motorsport:'automovilismo-adrenalina','dining-shopping':'gastronomia-compras-noche'},
  ar: {'private-tours':'جولات-خاصة-بدليل-مرخص',concierge:'كونسيرج-ومساعدة',transfers:'النقل-والسائق',hotels:'إقامة-مختارة',flights:'الرحلات-والاتصالات','travel-essentials':'التأشيرات-والتأمين-esim','special-services':'خدمات-خاصة','trade-shows':'المعارض-وبعثات-الأعمال',corporate:'رحلات-الشركات-والحوافز',events:'فعاليات-دبي',desert:'الصحراء-والطبيعة','sea-sky':'البحر-والسماء',motorsport:'رياضة-السيارات-والمغامرة','dining-shopping':'المطاعم-والتسوق-والحياة-الليلية'},
  hi: {'private-tours':'निजी-टूर-लाइसेंस-गाइड',concierge:'कंसीयर्ज-24-7',transfers:'निजी-ट्रांसफर-ड्राइवर',hotels:'चुने-हुए-होटल',flights:'उड़ानें-और-कनेक्शन','travel-essentials':'वीजा-बीमा-esim','special-services':'विशेष-सेवाएं','trade-shows':'व्यापार-मेले',corporate:'कॉर्पोरेट-यात्रा',events:'दुबई-इवेंट्स',desert:'रेगिस्तान-प्रकृति','sea-sky':'समुद्र-आसमान',motorsport:'मोटरस्पोर्ट','dining-shopping':'भोजन-खरीदारी-नाइटलाइफ'},
  ru: {'private-tours':'частные-туры-с-лицензированным-гидом',concierge:'консьерж-24-7',transfers:'трансферы-и-водитель',hotels:'подбор-отелей',flights:'перелеты-и-стыковки','travel-essentials':'визы-страховка-esim','special-services':'специальные-услуги','trade-shows':'выставки-и-деловые-миссии',corporate:'корпоративные-поездки',events:'события-в-дубае',desert:'пустыня-и-природа','sea-sky':'море-и-небо',motorsport:'автоспорт-и-адреналин','dining-shopping':'рестораны-шопинг-и-ночная-жизнь'},
  de: {'private-tours':'private-touren-mit-lizenziertem-guide',concierge:'concierge-24-7',transfers:'transfers-und-chauffeur',hotels:'kuratierte-hotels',flights:'fluege-und-verbindungen','travel-essentials':'visa-versicherung-esim','special-services':'besondere-services','trade-shows':'messen-und-geschaeftsmissionen',corporate:'firmen-und-incentive-reisen',events:'events-in-dubai',desert:'wueste-und-natur','sea-sky':'meer-und-himmel',motorsport:'motorsport-und-adrenalin','dining-shopping':'gastronomie-shopping-und-nachtleben'}
};

export const destinationSlugs: Record<Locale, Record<DestinationId, string>> = {
  pt:{dubai:'dubai','abu-dhabi':'abu-dhabi','ras-al-khaimah':'ras-al-khaimah',sharjah:'sharjah',ajman:'ajman',fujairah:'fujairah','umm-al-quwain':'umm-al-quwain',oman:'oma',catar:'catar','arabia-saudita':'arabia-saudita'},
  en:{dubai:'dubai','abu-dhabi':'abu-dhabi','ras-al-khaimah':'ras-al-khaimah',sharjah:'sharjah',ajman:'ajman',fujairah:'fujairah','umm-al-quwain':'umm-al-quwain',oman:'oman',catar:'qatar','arabia-saudita':'saudi-arabia'},
  es:{dubai:'dubai','abu-dhabi':'abu-dhabi','ras-al-khaimah':'ras-al-khaimah',sharjah:'sharjah',ajman:'ajman',fujairah:'fujairah','umm-al-quwain':'umm-al-quwain',oman:'oman',catar:'catar','arabia-saudita':'arabia-saudita'},
  ar:{dubai:'دبي','abu-dhabi':'أبو-ظبي','ras-al-khaimah':'رأس-الخيمة',sharjah:'الشارقة',ajman:'عجمان',fujairah:'الفجيرة','umm-al-quwain':'أم-القيوين',oman:'عمان',catar:'قطر','arabia-saudita':'السعودية'},
  hi:{dubai:'दुबई','abu-dhabi':'अबू-धाबी','ras-al-khaimah':'रास-अल-खैमाह',sharjah:'शारजाह',ajman:'अजमान',fujairah:'फुजैराह','umm-al-quwain':'उम्म-अल-कुवैन',oman:'ओमान',catar:'कतर','arabia-saudita':'सऊदी-अरब'},
  ru:{dubai:'дубай','abu-dhabi':'абу-даби','ras-al-khaimah':'рас-эль-хайма',sharjah:'шарджа',ajman:'аджман',fujairah:'фуджейра','umm-al-quwain':'умм-эль-кувейн',oman:'оман',catar:'катар','arabia-saudita':'саудовская-аравия'},
  de:{dubai:'dubai','abu-dhabi':'abu-dhabi','ras-al-khaimah':'ras-al-khaimah',sharjah:'sharjah',ajman:'ajman',fujairah:'fujairah','umm-al-quwain':'umm-al-quwain',oman:'oman',catar:'katar','arabia-saudita':'saudi-arabien'}
};

export const itinerarySlugs: Record<Locale, Record<ItineraryId, string>> = {
  pt:{'dubai-essencial-4n':'dubai-essencial-4-noites','dubai-familia-5n':'dubai-familia-5-noites','lua-de-mel-5n':'lua-de-mel-5-noites','dubai-abu-dhabi-6n':'dubai-abu-dhabi-6-noites','dubai-completo-10-14n':'dubai-completo-10-a-14-noites','stopover-48h':'stopover-dubai-48-horas'},
  en:{'dubai-essencial-4n':'essential-dubai-4-nights','dubai-familia-5n':'dubai-family-5-nights','lua-de-mel-5n':'honeymoon-5-nights','dubai-abu-dhabi-6n':'dubai-abu-dhabi-6-nights','dubai-completo-10-14n':'complete-dubai-10-to-14-nights','stopover-48h':'dubai-stopover-48-hours'},
  es:{'dubai-essencial-4n':'dubai-esencial-4-noches','dubai-familia-5n':'dubai-familia-5-noches','lua-de-mel-5n':'luna-de-miel-5-noches','dubai-abu-dhabi-6n':'dubai-abu-dhabi-6-noches','dubai-completo-10-14n':'dubai-completo-10-a-14-noches','stopover-48h':'escala-dubai-48-horas'},
  ar:{'dubai-essencial-4n':'دبي-الأساسية-4-ليال','dubai-familia-5n':'دبي-للعائلة-5-ليال','lua-de-mel-5n':'شهر-العسل-5-ليال','dubai-abu-dhabi-6n':'دبي-أبو-ظبي-6-ليال','dubai-completo-10-14n':'دبي-الكاملة-10-14-ليلة','stopover-48h':'توقف-دبي-48-ساعة'},
  hi:{'dubai-essencial-4n':'दुबई-आवश्यक-4-रातें','dubai-familia-5n':'दुबई-परिवार-5-रातें','lua-de-mel-5n':'हनीमून-5-रातें','dubai-abu-dhabi-6n':'दुबई-अबू-धाबी-6-रातें','dubai-completo-10-14n':'संपूर्ण-दुबई-10-14-रातें','stopover-48h':'दुबई-स्टॉपओवर-48-घंटे'},
  ru:{'dubai-essencial-4n':'дубай-основное-4-ночи','dubai-familia-5n':'дубай-семья-5-ночей','lua-de-mel-5n':'медовый-месяц-5-ночей','dubai-abu-dhabi-6n':'дубай-абу-даби-6-ночей','dubai-completo-10-14n':'дубай-полный-10-14-ночей','stopover-48h':'стоповер-дубай-48-часов'},
  de:{'dubai-essencial-4n':'dubai-essentials-4-naechte','dubai-familia-5n':'dubai-familie-5-naechte','lua-de-mel-5n':'flitterwochen-5-naechte','dubai-abu-dhabi-6n':'dubai-abu-dhabi-6-naechte','dubai-completo-10-14n':'dubai-komplett-10-bis-14-naechte','stopover-48h':'dubai-stopover-48-stunden'}
};

export function servicePath(locale: Locale, id: ServiceId) { return `${routePath(locale,'services')}/${serviceSlugs[locale][id]}`; }
export function destinationPath(locale: Locale, id: DestinationId) { return `${routePath(locale,'destinations')}/${destinationSlugs[locale][id]}`; }
export function itineraryPath(locale: Locale, id: ItineraryId) { return `${routePath(locale,'itineraries')}/${itinerarySlugs[locale][id]}`; }

export const dubaiArticleSlugs: Record<Locale, Record<DubaiArticleId, string>> = Object.fromEntries((['pt','en','es','ar','hi','ru','de'] as Locale[]).map(locale=>[locale, locale==='pt'?{visa:'visto-dubai-brasileiros',season:'melhor-epoca-dubai',rules:'regras-dubai-turista',transport:'como-se-locomover-dubai',fairs:'feiras-em-dubai'}:{visa:'dubai-visa-requirements',season:'best-time-to-visit-dubai',rules:'dubai-rules-for-visitors',transport:'getting-around-dubai',fairs:'dubai-trade-show-calendar'}])) as Record<Locale, Record<DubaiArticleId,string>>;
export function dubaiArticlePath(locale: Locale, id: DubaiArticleId) { return `${routePath(locale,'dubai')}/${dubaiArticleSlugs[locale][id]}`; }
export function dubaiArticlePathBySlug(locale: Locale, slug: string) { return `${routePath(locale,'dubai')}/${slug}`; }

function entryKey<T extends string>(record: Record<T,string>, slug: string) { return Object.entries(record).find(([,value])=>value===slug)?.[0] as T|undefined; }

export function serviceIdFromSlug(locale:Locale,slug:string){return entryKey(serviceSlugs[locale],slug);}
export function destinationIdFromSlug(locale:Locale,slug:string){return entryKey(destinationSlugs[locale],slug);}
export function itineraryIdFromSlug(locale:Locale,slug:string){return entryKey(itinerarySlugs[locale],slug);}

export function translateCurrentPath(pathname: string, targetLocale: Locale) {
  const parts=decodeURI(pathname).split('/').filter(Boolean);
  const sourceLocale=parts[0] as Locale;
  if(!routeSlugs[sourceLocale]) return routePath(targetLocale,'home');
  const route=(Object.entries(routeSlugs[sourceLocale]).find(([,slug])=>slug===(parts[1]??''))?.[0]??'home') as RouteKey;
  if(route==='services'&&parts[2]) { const id=entryKey(serviceSlugs[sourceLocale],parts[2]); if(id) return servicePath(targetLocale,id); }
  if(route==='destinations'&&parts[2]) { const id=entryKey(destinationSlugs[sourceLocale],parts[2]); if(id) return destinationPath(targetLocale,id); }
  if(route==='itineraries'&&parts[2]) { const id=entryKey(itinerarySlugs[sourceLocale],parts[2]); if(id) return itineraryPath(targetLocale,id); }
  if(route==='dubai'&&parts[2]) return routePath(targetLocale,'dubai');
  return routePath(targetLocale,route);
}
