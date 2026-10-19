import Image from 'next/image';
import {getTranslations} from 'next-intl/server';
import {MapPin, Phone} from 'lucide-react';
import {site} from '@/config/site';
import {company} from '@/config/company';
import type {Locale} from '@/i18n/routing';
import {locales} from '@/i18n/routing';
import {routePath, servicePath, type RouteKey, type ServiceId} from '@/lib/routes';
import {brandAssets} from '@/content/images';
import {CookiePreferencesButton} from '@/components/analytics/CookiePreferencesButton';

const nav: RouteKey[] = ['services','experiences','destinations','itineraries','business','dubai','about','contact'];
const serviceNav: {label:'privateTours'|'concierge'|'transfers'|'tradeShows';service:ServiceId}[]=[
  {label:'privateTours',service:'private-tours'},{label:'concierge',service:'concierge'},{label:'transfers',service:'transfers'},{label:'tradeShows',service:'trade-shows'}
];
const signature: Record<Locale,string>={pt:'Dubai como só quem vive aqui conhece.',en:'Dubai the way only locals know it.',es:'Dubái como solo quien vive aquí la conoce.',ar:'دبي كما يعرفها من يعيش فيها',hi:'दुबई, जैसा यहाँ रहने वाले जानते हैं।',ru:'Дубай глазами тех, кто живёт здесь.',de:'Dubai, wie es nur Ortskundige kennen.'};
const legal: RouteKey[]=['privacy','terms','cancellation','cookies'];

export async function Footer({locale}:{locale:Locale}){
  const t=await getTranslations();
  return <footer className="border-t border-white/[0.07] bg-night-950 text-sand-100">
    <div className="mx-auto grid max-w-content gap-10 px-6 py-16 sm:grid-cols-2 lg:grid-cols-[1.35fr_1fr_1fr_1.2fr] lg:px-10">
      <div><Image src={brandAssets.logo} width={732} height={156} alt="High Class Travel Experiences" className="h-10 w-auto object-contain"/><p className={`mt-5 max-w-sm text-lg text-sand-200 ${locale==='ar'?'font-arabic':'font-display italic'}`}>{signature[locale]}</p><p className="mt-5 max-w-sm text-xs leading-5 text-sand-100/55">{company.legalName} · {t('footer.licenses')}</p></div>
      <div><h2 className="mb-4 text-xs font-semibold uppercase tracking-[.12em] text-brass-400">{t('footer.navigation')}</h2><nav className="grid gap-y-3" aria-label={t('footer.navigation')}>{nav.map(key=><a key={key} href={routePath(locale,key)} className="text-sm text-sand-100/65 hover:text-sand-100">{t(`nav.${key}`)}</a>)}</nav></div>
      <div><h2 className="mb-4 text-xs font-semibold uppercase tracking-[.12em] text-brass-400">{t('nav.services')}</h2><nav className="grid gap-y-3" aria-label={t('nav.services')}>{serviceNav.map(item=><a key={item.service} href={servicePath(locale,item.service)} className="text-sm leading-5 text-sand-100/65 hover:text-sand-100">{t(`serviceNav.${item.label}`)}</a>)}<a href={routePath(locale,'hotels')} className="text-sm text-sand-100/65 hover:text-sand-100">{t('nav.hotels')}</a><a href={routePath(locale,'fleet')} className="text-sm text-sand-100/65 hover:text-sand-100">{t('nav.fleet')}</a></nav></div>
      <div><h2 className="mb-4 text-xs font-semibold uppercase tracking-[.12em] text-brass-400">{t('nav.contact')}</h2><address className="not-italic text-sm leading-6 text-sand-100/65"><a href={site.mapsUrl} target="_blank" rel="noopener" className="flex items-start gap-2 hover:text-sand-100"><MapPin size={15} className="mt-1 shrink-0 text-brass-400"/><span>{site.address.line1}<br/>{site.address.line2}<br/>{t('footer.location')}</span></a><a href="tel:+97142263224" className="mt-4 flex items-center gap-2 hover:text-sand-100"><Phone size={15} className="text-brass-400"/><bdi>{company.telephone}</bdi></a></address><div className="mt-5 grid gap-2 text-sm"><a href={site.social.instagram} target="_blank" rel="noopener" className="text-sand-100/65 hover:text-sand-100">Instagram</a><p className="text-sand-100/55">Dubai Chamber · Câmara de Comércio Árabe-Brasileira</p></div></div>
    </div>
    <div className="border-t border-white/[0.07]"><div className="mx-auto grid max-w-content gap-6 px-6 py-7 text-xs text-sand-100/70 lg:grid-cols-[1fr_auto] lg:items-center lg:px-10"><div className="flex flex-wrap gap-x-5 gap-y-3">{legal.map(key=><a key={key} href={routePath(locale,key)} className="hover:text-sand-100">{t(`footer.${key}`)}</a>)}<CookiePreferencesButton label={t('cookie.preferences')}/></div><div className="flex flex-wrap items-center gap-3" aria-label={t('lang.label')}>{locales.map(item=><a key={item} href={routePath(item,'home')} className={item===locale?'text-brass-400':'hover:text-sand-100'}>{item.toUpperCase()}</a>)}</div></div></div>
    <div className="border-t border-white/[0.07]"><div className="mx-auto flex max-w-content flex-col justify-between gap-3 px-6 py-5 text-[11px] text-sand-100/50 md:flex-row lg:px-10"><p>{company.legalName} · {new Date().getFullYear()} · {t('footer.rights')}</p><p>{company.eventsCompany.legalName} · {company.eventsCompany.license}</p></div></div>
  </footer>;
}
