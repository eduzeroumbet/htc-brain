import type {Metadata} from 'next';
import {notFound} from 'next/navigation';
import {setRequestLocale} from 'next-intl/server';
import {abuDhabiIdFromSlug,abuDhabiLocales,abuDhabiPath,abuDhabiSlugs,destinationIdFromSlug,destinationSlugs,isAbuDhabiLocale,routeSlugs,type AbuDhabiLocale} from '@/lib/routes';
import {abuDhabiPageIds,abuDhabiPages} from '@/lib/abu-dhabi';
import {getAbuDhabiContent} from '@/lib/abu-dhabi-content';
import {abuDhabiLanguages,abuDhabiOgLocales,abuDhabiSchemas} from '@/lib/abu-dhabi-seo';
import {AbuDhabiPage} from '@/components/abu-dhabi/AbuDhabiPage';

type Params = Promise<{locale:string;slug:string;serviceSlug:string;childSlug:string}>;

// Only /{locale}/destinations/abu-dhabi/{page} exists at this depth, in pt, en, es and ar.
export function generateStaticParams(){return abuDhabiLocales.flatMap(locale=>abuDhabiPageIds.map(id=>({locale,slug:routeSlugs[locale].destinations,serviceSlug:destinationSlugs[locale]['abu-dhabi'],childSlug:abuDhabiSlugs[locale][id]})));}

function resolve(locale:string,slug:string,serviceSlug:string,childSlug:string){
  if(!isAbuDhabiLocale(locale))return null;
  if(decodeURIComponent(slug)!==routeSlugs[locale].destinations||destinationIdFromSlug(locale,decodeURIComponent(serviceSlug))!=='abu-dhabi')return null;
  const id=abuDhabiIdFromSlug(locale,decodeURIComponent(childSlug));
  return id?{locale:locale as AbuDhabiLocale,id}:null;
}

export async function generateMetadata({params}:{params:Params}):Promise<Metadata>{
  const {locale,slug,serviceSlug,childSlug}=await params;
  const item=resolve(locale,slug,serviceSlug,childSlug);if(!item)return{};
  const page=(await getAbuDhabiContent(item.locale)).pages[item.id];
  const canonical=abuDhabiPath(item.locale,item.id);
  const article=abuDhabiPages[item.id].kind==='article';
  return {
    title:{absolute:page.metaTitle},
    description:page.metaDescription,
    alternates:{canonical,languages:abuDhabiLanguages(locale=>abuDhabiPath(locale,item.id))},
    openGraph:{type:article?'article':'website',title:page.metaTitle,description:page.metaDescription,url:canonical,locale:abuDhabiOgLocales[item.locale],siteName:'High Class Travel Experiences'},
    twitter:{card:'summary_large_image',title:page.metaTitle,description:page.metaDescription},
    ...(abuDhabiPages[item.id].indexable?{}:{robots:{index:false,follow:true}})
  };
}

export default async function AbuDhabiChildRoute({params}:{params:Params}){
  const {locale,slug,serviceSlug,childSlug}=await params;
  const item=resolve(locale,slug,serviceSlug,childSlug);if(!item)notFound();
  setRequestLocale(item.locale);
  const content=await getAbuDhabiContent(item.locale);
  return <>{abuDhabiSchemas(item.locale,item.id,content).map((schema,index)=><script key={index} type="application/ld+json" dangerouslySetInnerHTML={{__html:JSON.stringify(schema)}}/>)}<AbuDhabiPage locale={item.locale} id={item.id} content={content}/></>;
}
