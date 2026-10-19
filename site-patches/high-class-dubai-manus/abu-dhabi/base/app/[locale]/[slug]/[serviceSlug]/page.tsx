import type {Metadata} from 'next';
import {notFound} from 'next/navigation';
import {setRequestLocale} from 'next-intl/server';
import {isLocale,locales,type Locale} from '@/i18n/routing';
import {getCatalogContent,getJourneysContent,getSiteContent} from '@/lib/content';
import {destinationIdFromSlug,destinationPath,destinationSlugs,itineraryIdFromSlug,itineraryPath,itinerarySlugs,routePath,serviceIdFromSlug,servicePath,serviceSlugs,type DestinationId,type ItineraryId,type ServiceId} from '@/lib/routes';
import {ServiceDetailPage} from '@/components/services/ServiceDetailPage';
import {DestinationDetailPage,ItineraryDetailPage} from '@/components/pages/PlanningPages';
import {publicSiteUrl} from '@/lib/site-url';

const serviceIds=Object.keys(serviceSlugs.pt) as ServiceId[];
const destinationIds=Object.keys(destinationSlugs.pt) as DestinationId[];
const itineraryIds=Object.keys(itinerarySlugs.pt) as ItineraryId[];

export function generateStaticParams(){return locales.flatMap(locale=>[
  ...serviceIds.map(id=>({locale,slug:routePath(locale,'services').split('/').pop()??'',serviceSlug:serviceSlugs[locale][id]})),
  ...destinationIds.map(id=>({locale,slug:routePath(locale,'destinations').split('/').pop()??'',serviceSlug:destinationSlugs[locale][id]})),
  ...itineraryIds.map(id=>({locale,slug:routePath(locale,'itineraries').split('/').pop()??'',serviceSlug:itinerarySlugs[locale][id]}))
]);}

function resolve(locale:Locale,parent:string,child:string){
  if(parent===routePath(locale,'services').split('/').pop()){const id=serviceIdFromSlug(locale,child);return id?{type:'service' as const,id}:null;}
  if(parent===routePath(locale,'destinations').split('/').pop()){const id=destinationIdFromSlug(locale,child);return id?{type:'destination' as const,id}:null;}
  if(parent===routePath(locale,'itineraries').split('/').pop()){const id=itineraryIdFromSlug(locale,child);return id?{type:'itinerary' as const,id}:null;}
  return null;
}

export async function generateMetadata({params}:{params:Promise<{locale:string;slug:string;serviceSlug:string}>}):Promise<Metadata>{
  const {locale:rawLocale,slug,serviceSlug}=await params;if(!isLocale(rawLocale))return{};
  const item=resolve(rawLocale,decodeURIComponent(slug),decodeURIComponent(serviceSlug));if(!item)return{};
  const [site,catalog,journeys]=await Promise.all([getSiteContent(rawLocale),getCatalogContent(rawLocale),getJourneysContent(rawLocale)]);
  const entity=item.type==='service'?site.services.find(entry=>entry.id===item.id):item.type==='destination'?catalog.destinations.find(entry=>entry.slug===item.id):journeys.itineraries.find(entry=>entry.slug===item.id);
  if(!entity)return{};
  const title=`${'title' in entity?entity.title:entity.name} | High Class Dubai`;
  const description='phrase' in entity?entity.phrase:entity.summary;
  const pathFor=(locale:Locale)=>item.type==='service'?servicePath(locale,item.id as ServiceId):item.type==='destination'?destinationPath(locale,item.id):itineraryPath(locale,item.id);
  const languages=Object.fromEntries(locales.map(locale=>[locale==='pt'?'pt-BR':locale,pathFor(locale)]));
  return {title,description,alternates:{canonical:pathFor(rawLocale),languages:{...languages,'x-default':pathFor('en')}},openGraph:{title,description,images:[`/${rawLocale}/opengraph-image`]}};
}

export default async function DetailRoute({params}:{params:Promise<{locale:string;slug:string;serviceSlug:string}>}){
  const {locale:rawLocale,slug,serviceSlug}=await params;if(!isLocale(rawLocale))notFound();
  const locale=rawLocale;const resolved=resolve(locale,decodeURIComponent(slug),decodeURIComponent(serviceSlug));if(!resolved)notFound();setRequestLocale(locale);
  const [site,catalog,journeys]=await Promise.all([getSiteContent(locale),getCatalogContent(locale),getJourneysContent(locale)]);
  let title='';let parentTitle='';let url='';let parentUrl='';let page:React.ReactNode;
  if(resolved.type==='service'){
    const service=site.services.find(item=>item.id===resolved.id);if(!service)notFound();
    title=service.title;parentTitle=site.servicesIndex.title;url=servicePath(locale,resolved.id);parentUrl=routePath(locale,'services');page=<ServiceDetailPage locale={locale} content={site} service={service}/>;
  }else if(resolved.type==='destination'){
    const item=catalog.destinations.find(entry=>entry.slug===resolved.id);if(!item)notFound();
    title=item.name;parentTitle=catalog.meta.title;url=destinationPath(locale,resolved.id);parentUrl=routePath(locale,'destinations');page=<DestinationDetailPage locale={locale} item={item}/>;
  }else{
    const item=journeys.itineraries.find(entry=>entry.slug===resolved.id);if(!item)notFound();
    title=item.title;parentTitle='Itineraries';url=itineraryPath(locale,resolved.id);parentUrl=routePath(locale,'itineraries');page=<ItineraryDetailPage locale={locale} item={item}/>;
  }
  const breadcrumb={'@context':'https://schema.org','@type':'BreadcrumbList',itemListElement:[{'@type':'ListItem',position:1,name:'Home',item:`${publicSiteUrl}/${locale}`},{'@type':'ListItem',position:2,name:parentTitle,item:`${publicSiteUrl}${parentUrl}`},{'@type':'ListItem',position:3,name:title,item:`${publicSiteUrl}${url}`}]};
  return <><script type="application/ld+json" dangerouslySetInnerHTML={{__html:JSON.stringify(breadcrumb)}}/>{page}</>;
}
