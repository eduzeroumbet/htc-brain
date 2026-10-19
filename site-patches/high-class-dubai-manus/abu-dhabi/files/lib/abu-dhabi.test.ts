import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {describe,expect,it} from 'vitest';
import {abuDhabiHub,abuDhabiLocation,abuDhabiPageIds,abuDhabiPageKey,abuDhabiPages,isAbuDhabiLinkKey} from './abu-dhabi';
import {abuDhabiLocales,abuDhabiPath,abuDhabiSlugs,destinationPath,translateCurrentPath} from './routes';
import {whatsappRefPages} from './whatsapp-ref';

type Page = {metaTitle:string;metaDescription:string;h1:string;whatsappContext:string;[key:string]:unknown};
const content=(locale:string)=>JSON.parse(readFileSync(join(process.cwd(),`content/${locale}/abu-dhabi.json`),'utf8')) as {ui:{pending:string};hub:Page;pages:Record<string,Page>};

describe('Abu Dhabi guide', () => {
  it('has one slug per page and locale, without duplicates', () => {
    for(const locale of abuDhabiLocales){
      expect(Object.keys(abuDhabiSlugs[locale]).sort()).toEqual([...abuDhabiPageIds].sort());
      expect(new Set(Object.values(abuDhabiSlugs[locale])).size).toBe(abuDhabiPageIds.length);
    }
  });

  it('keeps 13 attractions, 5 itineraries and 2 articles per locale', () => {
    const kinds=abuDhabiPageIds.map(id=>abuDhabiPages[id].kind);
    expect(kinds.filter(kind=>kind==='attraction')).toHaveLength(13);
    expect(kinds.filter(kind=>kind==='itinerary')).toHaveLength(5);
    expect(kinds.filter(kind=>kind==='article')).toHaveLength(2);
  });

  it('has unique meta title and description in every locale, with the final suffix', () => {
    const titles=new Set<string>();const descriptions=new Set<string>();
    for(const locale of abuDhabiLocales){
      const data=content(locale);
      expect(Object.keys(data.pages).sort()).toEqual([...abuDhabiPageIds].sort());
      for(const page of [data.hub,...Object.values(data.pages)]){
        expect(page.metaTitle.endsWith(' | High Class')).toBe(true);
        expect(page.metaTitle).not.toContain('High Class Dubai');
        if(locale!=='ar'){expect(page.metaTitle.length).toBeLessThanOrEqual(60);expect(page.metaDescription.length).toBeLessThanOrEqual(160);}
        expect(titles.has(page.metaTitle)).toBe(false);expect(descriptions.has(page.metaDescription)).toBe(false);
        titles.add(page.metaTitle);descriptions.add(page.metaDescription);
      }
    }
  });

  it('only cites registered sources and links to known pages', () => {
    for(const locale of abuDhabiLocales){
      const data=content(locale);
      for(const [id,page] of [['hub',data.hub] as const,...Object.entries(data.pages)]){
        const text=JSON.stringify(page);
        const sources=id==='hub'?abuDhabiHub.sources:abuDhabiPages[id as keyof typeof abuDhabiPages].sources;
        for(const [,marker] of text.matchAll(/\[(S\d+|I1)\]/g))expect(sources,`${locale}/${id} cites ${marker}`).toContain(marker);
        for(const [,key] of text.matchAll(/\[\[([a-z0-9-]+)\|/g))expect(isAbuDhabiLinkKey(key),`${locale}/${id} links ${key}`).toBe(true);
      }
    }
  });

  it('registers a language-independent WhatsApp ref key for every page', () => {
    const pages=whatsappRefPages();
    for(const locale of abuDhabiLocales)for(const id of abuDhabiPageIds)expect(pages[abuDhabiPath(locale,id)]).toBe(abuDhabiPageKey(id));
    expect(pages[destinationPath('en','abu-dhabi')]).toBe('destino-abu-dhabi');
    expect(abuDhabiLocation('sheikh-zayed-grand-mosque')).toBe('abudhabi_attraction_sheikh-zayed-grand-mosque');
    expect(abuDhabiPageKey('one-day')).toBe('abudhabi-itinerary-one-day');
  });

  it('switches language on guide pages and falls back to the hub where the guide is not published', () => {
    expect(translateCurrentPath('/en/destinations/abu-dhabi/sheikh-zayed-grand-mosque','pt')).toBe('/pt/destinos/abu-dhabi/grande-mesquita-sheikh-zayed');
    expect(translateCurrentPath(encodeURI('/pt/destinos/abu-dhabi/abu-dhabi-1-dia'),'ar')).toBe(abuDhabiPath('ar','one-day'));
    expect(translateCurrentPath('/en/destinations/abu-dhabi/abu-dhabi-in-summer','de')).toBe('/de/reiseziele/abu-dhabi');
    expect(translateCurrentPath('/en/destinations/dubai','pt')).toBe('/pt/destinos/dubai');
  });
});
