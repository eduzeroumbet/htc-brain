import type {AbuDhabiContent} from '@/content/types';
import {brandAssets} from '@/content/images';
import {site} from '@/config/site';
import {publicSiteUrl} from '@/lib/site-url';
import {abuDhabiHub,abuDhabiIdsByKind,abuDhabiPages,abuDhabiSources} from '@/lib/abu-dhabi';
import {abuDhabiLocales,abuDhabiPath,destinationPath,routePath,type AbuDhabiLocale,type AbuDhabiPageId} from '@/lib/routes';

export const abuDhabiLanguageCodes: Record<AbuDhabiLocale,string> = {pt:'pt-BR',en:'en',es:'es',ar:'ar'};
export const abuDhabiOgLocales: Record<AbuDhabiLocale,string> = {pt:'pt_BR',en:'en_GB',es:'es_ES',ar:'ar_AE'};

// hreflang only between the four published locales, x-default in English (same rule as the rest of the site).
export function abuDhabiLanguages(pathFor: (locale: AbuDhabiLocale) => string) {
  return {...Object.fromEntries(abuDhabiLocales.map(locale=>[abuDhabiLanguageCodes[locale],pathFor(locale)])),'x-default':pathFor('en')};
}

const absolute = (path: string) => `${publicSiteUrl}${path}`;
const organization = {'@type':'Organization',name:site.name,url:publicSiteUrl,logo:{'@type':'ImageObject',url:absolute(brandAssets.logo)}};

function breadcrumb(locale: AbuDhabiLocale, content: AbuDhabiContent, page?: {name: string; path: string}) {
  const items = [
    {name:content.ui.home,path:routePath(locale,'home')},
    {name:content.ui.destinations,path:routePath(locale,'destinations')},
    {name:content.cityName,path:destinationPath(locale,'abu-dhabi')},
    ...(page?[page]:[])
  ];
  return {'@context':'https://schema.org','@type':'BreadcrumbList',itemListElement:items.map((item,index)=>({'@type':'ListItem',position:index+1,name:item.name,item:absolute(item.path)}))};
}

export function abuDhabiSchemas(locale: AbuDhabiLocale, id: AbuDhabiPageId | 'hub', content: AbuDhabiContent): object[] {
  const hubUrl = absolute(destinationPath(locale,'abu-dhabi'));
  const destinationRef = {'@type':'TouristDestination','@id':`${hubUrl}#destination`,name:content.cityName};
  if(id==='hub') {
    const attractions = abuDhabiIdsByKind('attraction').map(item=>({'@type':'TouristAttraction',name:content.pages[item].h1,url:absolute(abuDhabiPath(locale,item))}));
    return [
      {'@context':'https://schema.org',...destinationRef,description:content.hub.metaDescription,url:hubUrl,includesAttraction:attractions,subjectOf:{'@type':'WebPage',url:hubUrl,inLanguage:abuDhabiLanguageCodes[locale],citation:abuDhabiHub.sources.map(source=>abuDhabiSources[source].url)}},
      breadcrumb(locale,content)
    ];
  }
  const page = content.pages[id];
  const entry = abuDhabiPages[id];
  const url = absolute(abuDhabiPath(locale,id));
  const crumbs = breadcrumb(locale,content,{name:page.h1,path:abuDhabiPath(locale,id)});
  if(entry.kind==='attraction') {
    return [{'@context':'https://schema.org','@type':'TouristAttraction','@id':`${url}#attraction`,name:page.h1,description:page.metaDescription,url,containedInPlace:destinationRef},crumbs];
  }
  if(entry.kind==='itinerary') {
    return [{'@context':'https://schema.org','@type':'TouristTrip',name:page.h1,description:page.metaDescription,url,provider:organization,itinerary:{'@type':'ItemList',itemListElement:(entry.stops??[]).map((stop,index)=>({'@type':'ListItem',position:index+1,item:{'@type':'TouristAttraction',name:content.pages[stop].h1,url:absolute(abuDhabiPath(locale,stop))}}))}},crumbs];
  }
  const article = {'@context':'https://schema.org','@type':'Article',headline:page.h1,description:page.metaDescription,inLanguage:abuDhabiLanguageCodes[locale],url,mainEntityOfPage:url,author:organization,publisher:organization,about:destinationRef,citation:entry.sources.map(source=>abuDhabiSources[source].url)};
  const faq = page.faq?.length?[{'@context':'https://schema.org','@type':'FAQPage',mainEntity:page.faq.map(item=>({'@type':'Question',name:item.question,acceptedAnswer:{'@type':'Answer',text:item.answer.replace(/\[(?:S\d+|I1)\]/g,'').replace(/\[\[[a-z0-9-]+\|([^\]]+)\]\]/g,'$1').replace(/\*\*/g,'').replace(/\s+/g,' ').trim()}}))}]:[];
  return [article,...faq,crumbs];
}
