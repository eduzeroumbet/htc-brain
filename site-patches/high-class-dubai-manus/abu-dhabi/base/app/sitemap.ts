import type {MetadataRoute} from 'next';
import {publicSiteUrl} from '@/lib/site-url';
import {locales} from '@/i18n/routing';
import {destinationPath,destinationSlugs,dubaiArticlePathBySlug,itineraryPath,itinerarySlugs,routePath,servicePath,serviceSlugs,type DestinationId,type ItineraryId,type RouteKey,type ServiceId} from '@/lib/routes';
import {getDubaiArticles} from '@/lib/dubai-content';

const pages:RouteKey[]=['home','about','services','business','experiences','destinations','itineraries','dubai','dubaiNow','agencies','events','fleet','hotels','contact','privacy','terms','cancellation','cookies'];
const services=Object.keys(serviceSlugs.pt) as ServiceId[];
const destinations=Object.keys(destinationSlugs.pt) as DestinationId[];
const itineraries=Object.keys(itinerarySlugs.pt) as ItineraryId[];

export default async function sitemap():Promise<MetadataRoute.Sitemap>{
  const lastModified=new Date();
  const articles=await getDubaiArticles();
  const common={lastModified,changeFrequency:'monthly' as const};
  const pageEntries=locales.flatMap(locale=>pages.map(page=>({url:`${publicSiteUrl}${routePath(locale,page)}`,...common,changeFrequency:page==='home'?'weekly' as const:'monthly' as const,priority:page==='home'?1:0.8})));
  const serviceEntries=locales.flatMap(locale=>services.map(service=>({url:`${publicSiteUrl}${servicePath(locale,service)}`,...common,priority:0.75})));
  const destinationEntries=locales.flatMap(locale=>destinations.map(destination=>({url:`${publicSiteUrl}${destinationPath(locale,destination)}`,...common,priority:0.72})));
  const itineraryEntries=locales.flatMap(locale=>itineraries.map(itinerary=>({url:`${publicSiteUrl}${itineraryPath(locale,itinerary)}`,...common,priority:0.78})));
  const articleEntries=articles.map(article=>({url:`${publicSiteUrl}${dubaiArticlePathBySlug('pt',article.slug)}`,lastModified:new Date(`${article.updatedAt}T00:00:00Z`),changeFrequency:'monthly' as const,priority:0.8}));
  return [...pageEntries,...serviceEntries,...destinationEntries,...itineraryEntries,...articleEntries];
}
