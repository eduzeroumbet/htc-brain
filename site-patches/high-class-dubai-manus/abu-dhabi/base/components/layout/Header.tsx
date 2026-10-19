'use client';

import Image from 'next/image';
import {ChevronDown, Globe2, Menu, Sparkles, X} from 'lucide-react';
import {useTranslations} from 'next-intl';
import {usePathname} from 'next/navigation';
import {useEffect, useRef, useState} from 'react';
import type {Locale} from '@/i18n/routing';
import {locales} from '@/i18n/routing';
import {routePath, translateCurrentPath, type RouteKey} from '@/lib/routes';
import {brandAssets} from '@/content/images';
import {whatsappUrl} from '@/lib/whatsapp';
import {WhatsAppLink} from '@/components/ui/WhatsAppLink';

const navKeys: RouteKey[] = ['services','experiences','destinations','itineraries','business','dubai','about'];
const languageNames: Record<Locale,string>={pt:'Português',en:'English',es:'Español',ar:'العربية',hi:'हिन्दी',ru:'Русский',de:'Deutsch'};

export function Header({locale}: {locale: Locale}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const closeRef=useRef<HTMLButtonElement>(null);

  useEffect(()=>{
    document.body.style.overflow=open?'hidden':'';
    if(open) closeRef.current?.focus();
    return()=>{document.body.style.overflow='';};
  },[open]);

  useEffect(()=>{
    const onKey=(event:KeyboardEvent)=>{if(event.key==='Escape')setOpen(false);};
    window.addEventListener('keydown',onKey);
    return()=>window.removeEventListener('keydown',onKey);
  },[]);

  const localeLink=(item:Locale)=><a
    key={item}
    href={translateCurrentPath(pathname,item)}
    hrefLang={item}
    lang={item}
    dir={item==='ar'?'rtl':'ltr'}
    aria-current={item===locale?'page':undefined}
    onClick={()=>{document.cookie=`NEXT_LOCALE=${item};path=/;max-age=31536000;samesite=lax`;setOpen(false);}}
    className={`flex min-h-11 items-center justify-between gap-4 rounded-sm px-3 text-sm transition ${item===locale?'bg-brass-500 text-night-950':'text-sand-100 hover:bg-white/10'}`}
  ><span>{languageNames[item]}</span><span className="text-[10px] font-bold uppercase tracking-[.12em]">{item}</span></a>;

  return <header className="sticky top-0 z-50 border-b border-white/[0.07] bg-night-950/95 text-sand-100 backdrop-blur-xl">
    <div className="mx-auto flex h-[72px] max-w-content items-center justify-between gap-4 px-6 lg:px-10">
      <a href={routePath(locale,'home')} className="shrink-0 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brass-400"><Image src={brandAssets.logo} width={732} height={156} alt="High Class Travel Experiences" className="h-9 w-auto object-contain sm:h-10" priority/></a>
      <p className="hidden text-xs font-semibold uppercase tracking-[.14em] text-sand-200 xl:block">Dubai · 24/7 · 7 languages</p>
      <div className="hidden items-center gap-3 lg:flex">
        <details className="group relative">
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-sm border border-white/10 px-4 text-sm font-semibold hover:border-brass-500"><Globe2 size={16}/>{languageNames[locale]}<ChevronDown size={14} className="transition group-open:rotate-180"/></summary>
          <div className="absolute end-0 top-[calc(100%+10px)] z-50 min-w-56 rounded-sm border border-white/10 bg-night-950 p-2 shadow-2xl">{locales.map(localeLink)}</div>
        </details>
        <WhatsAppLink href={whatsappUrl(locale)} location="header_desktop" compact className="rounded-sm px-5"><Sparkles size={16}/>{t('cta.plan')}</WhatsAppLink>
      </div>
      <button ref={closeRef} type="button" onClick={()=>setOpen(!open)} aria-expanded={open} aria-controls="mobile-nav" aria-label={open?t('menu.close'):t('menu.open')} className="relative z-[60] flex size-11 items-center justify-center rounded-sm border border-white/10 lg:hidden">{open?<X/>:<Menu/>}</button>
    </div>
    <div className="hidden border-t border-white/[0.06] lg:block">
      <nav className="mx-auto flex h-14 max-w-content items-center justify-center gap-5 px-8 xl:gap-9" aria-label="Principal">{navKeys.map(key=><a key={key} href={routePath(locale,key)} className="whitespace-nowrap text-sm font-semibold text-sand-100/75 transition hover:text-brass-400">{t(`nav.${key}`)}</a>)}</nav>
    </div>
    <div id="mobile-nav" aria-hidden={!open} className={`fixed inset-0 z-50 min-h-dvh overflow-y-auto bg-night-950 px-6 pb-10 pt-24 transition duration-200 lg:hidden ${open?'visible translate-y-0 opacity-100':'invisible -translate-y-2 opacity-0'}`}>
      <nav className="mx-auto max-w-lg" aria-label="Mobile">
        <p className="mb-3 text-xs font-semibold uppercase tracking-[.14em] text-brass-400">{t('nav.more')}</p>
        <div className="grid">{navKeys.map(key=><a key={key} href={routePath(locale,key)} onClick={()=>setOpen(false)} className="border-b border-white/[0.08] py-4 font-display text-3xl text-sand-100">{t(`nav.${key}`)}</a>)}</div>
        <WhatsAppLink href={whatsappUrl(locale)} location="header_mobile" onClick={()=>setOpen(false)} className="mt-6 flex min-h-12"><Sparkles size={16}/>{t('cta.plan')}</WhatsAppLink>
        <details className="mt-7 rounded-sm border border-white/10 p-3"><summary className="flex min-h-11 cursor-pointer list-none items-center justify-between font-semibold"><span className="flex items-center gap-2"><Globe2 size={16}/>{t('lang.label')}</span><ChevronDown size={16}/></summary><div className="mt-2 grid gap-1 sm:grid-cols-2">{locales.map(localeLink)}</div></details>
        <a href={routePath(locale,'contact')} onClick={()=>setOpen(false)} className="mt-6 block py-3 text-center text-sm text-sand-200 underline decoration-brass-500 underline-offset-4">{t('nav.contact')}</a>
      </nav>
    </div>
  </header>;
}
