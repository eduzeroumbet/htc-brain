import type {ReactNode} from 'react';
import {ArrowUpRight, CalendarDays, Check, ExternalLink, Info, Lightbulb, MapPin, Users} from 'lucide-react';
import type {AbuDhabiContent, AbuDhabiPageContent} from '@/content/types';
import {abuDhabiHub, abuDhabiIdsByKind, abuDhabiLinkPath, abuDhabiLocation, abuDhabiPages, abuDhabiSources, isAbuDhabiLinkKey, type AbuDhabiLinkKey, type AbuDhabiSourceId} from '@/lib/abu-dhabi';
import {abuDhabiPath, destinationPath, routePath, type AbuDhabiLocale, type AbuDhabiPageId} from '@/lib/routes';
import {whatsappUrl} from '@/lib/whatsapp';
import {WhatsAppLink} from '@/components/ui/WhatsAppLink';

const TOKEN = /(\*\*[^*]+\*\*|\[\[[a-z0-9-]+\|[^\]]+\]\]|\[(?:S\d+|I1)\])/g;
const LATIN = /([A-Za-z][A-Za-z0-9.’'&+-]*(?: [A-Za-z0-9][A-Za-z0-9.’'&+-]*)*)/g;

// Latin names inside Arabic text are isolated with <bdi> so they do not break the RTL flow.
function Isolated({text, rtl}: {text: string; rtl: boolean}) {
  if(!rtl) return <>{text}</>;
  return <>{text.split(LATIN).map((part,index)=>index%2===1?<bdi key={index}>{part}</bdi>:part)}</>;
}

function Rich({text, locale, cite, sourceLabel}: {text: string; locale: AbuDhabiLocale; cite: (id: string) => number | undefined; sourceLabel: string}) {
  const rtl = locale==='ar';
  return <>{text.split(TOKEN).map((part,index)=>{
    if(part.startsWith('**')&&part.endsWith('**')) return <strong key={index} className="font-semibold text-ink-900"><Rich text={part.slice(2,-2)} locale={locale} cite={cite} sourceLabel={sourceLabel}/></strong>;
    const link = part.match(/^\[\[([a-z0-9-]+)\|([^\]]+)\]\]$/);
    if(link) return isAbuDhabiLinkKey(link[1])?<a key={index} href={abuDhabiLinkPath(locale,link[1])} className="font-semibold text-brass-700 underline decoration-brass-500/40 underline-offset-4 hover:text-brass-800"><Isolated text={link[2]} rtl={rtl}/></a>:<Isolated key={index} text={link[2]} rtl={rtl}/>;
    const source = part.match(/^\[(S\d+|I1)\]$/);
    if(source) { const number = cite(source[1]); return number?<a key={index} href={`#fonte-${number}`} className="font-semibold text-brass-700 underline decoration-brass-500/40 underline-offset-4" aria-label={`${sourceLabel} ${number}`}>[{number}]</a>:null; }
    return <Isolated key={index} text={part} rtl={rtl}/>;
  })}</>;
}

function Card({href, eyebrow, title, text, icon}: {href: string; eyebrow: string; title: string; text: string; icon: ReactNode}) {
  return <a href={href} className="group flex min-h-[250px] flex-col rounded-sm border border-night-900/10 bg-white p-6 transition hover:-translate-y-1 hover:border-brass-500"><div className="flex items-center justify-between">{icon}<span className="text-xs font-semibold uppercase tracking-[.12em] text-brass-700">{eyebrow}</span></div><h3 className="mt-6 font-display text-3xl leading-tight text-night-950">{title}</h3><p className="mt-3 line-clamp-3 text-sm leading-6 text-night-700">{text}</p><ArrowUpRight className="mt-auto self-end pt-4 text-brass-600 transition group-hover:-translate-y-1 group-hover:translate-x-1 rtl:-scale-x-100"/></a>;
}

export function AbuDhabiPage({locale, id, content}: {locale: AbuDhabiLocale; id: AbuDhabiPageId | 'hub'; content: AbuDhabiContent}) {
  const ui = content.ui;
  const page: AbuDhabiPageContent = id==='hub'?content.hub:content.pages[id];
  const entry = id==='hub'?abuDhabiHub:abuDhabiPages[id];
  const sources = entry.sources;
  const cite = (source: string) => { const index = sources.indexOf(source as AbuDhabiSourceId); return index>=0?index+1:undefined; };
  const r = (text: string) => <Rich text={text} locale={locale} cite={cite} sourceLabel={ui.sources}/>;
  const eyebrow = id==='hub'?ui.guide:ui[abuDhabiPages[id].kind];
  const pendingText = page.practicalInfo?.replace(new RegExp(`^${ui.pending}:\\s*`),'');
  const titleOf = (key: AbuDhabiLinkKey) => key==='hub'?content.hub.h1:key==='dubai-hub'||key==='dubai-abu-dhabi-6n'?null:content.pages[key].h1;
  const related = entry.related.map(key=>({key,title:titleOf(key)})).filter((item): item is {key: AbuDhabiLinkKey; title: string} => Boolean(item.title));
  const location = abuDhabiLocation(id);
  const waHref = whatsappUrl(locale,page.whatsappContext);

  return <main id="main-content" className="bg-sand-50">
    <article>
      <header className="relative overflow-hidden bg-night-950 px-6 py-20 text-sand-100 lg:px-10 lg:py-28"><div className="absolute -end-24 top-0 size-80 rounded-full bg-brass-500/10 blur-3xl"/><div className="relative mx-auto max-w-content">
        <nav aria-label="Breadcrumb" className="text-sm text-sand-100/55"><a href={routePath(locale,'home')}>{ui.home}</a><span className="px-2">/</span><a href={routePath(locale,'destinations')}>{ui.destinations}</a><span className="px-2">/</span>{id==='hub'?<span>{content.cityName}</span>:<><a href={destinationPath(locale,'abu-dhabi')}>{content.cityName}</a><span className="px-2">/</span><span>{page.h1}</span></>}</nav>
        <p className="mb-5 mt-10 text-xs font-bold uppercase tracking-[0.18em] text-brass-400">{eyebrow}</p>
        <h1 className="max-w-5xl font-display text-5xl leading-[0.98] sm:text-6xl lg:text-7xl">{r(page.h1)}</h1>
        {page.intro&&<p className="mt-7 max-w-3xl text-base leading-7 text-sand-200 sm:text-lg">{r(page.intro)}</p>}
      </div></header>

      <div className="mx-auto grid max-w-content gap-12 px-6 py-14 lg:grid-cols-[minmax(0,780px)_300px] lg:px-10 lg:py-20">
        <div className="min-w-0 space-y-12">
          {page.sections?.map(section=><section key={section.heading}><h2 className="font-display text-4xl leading-tight text-ink-900">{r(section.heading)}</h2><div className="mt-5 space-y-5">{section.paragraphs?.map((paragraph,index)=><p key={index} className="text-[17px] leading-8 text-ink-700">{r(paragraph)}</p>)}</div>{section.items&&<ul className="mt-5 space-y-3">{section.items.map((item,index)=><li key={index} className="flex gap-3 text-[16px] leading-7 text-ink-700"><Check className="mt-1.5 size-4 shrink-0 text-brass-700"/><span>{r(item)}</span></li>)}</ul>}{section.table&&<div className="mt-7 overflow-x-auto rounded-lg border border-black/10"><table className="w-full min-w-[640px] border-collapse bg-white text-start text-sm"><thead className="bg-night-800 text-sand-100"><tr>{section.table.headers.map(header=><th key={header} className="p-4 text-start">{header}</th>)}</tr></thead><tbody>{section.table.rows.map((row,rowIndex)=><tr key={rowIndex} className="border-t border-black/10">{row.map((cell,cellIndex)=><td key={cellIndex} className="p-4 align-top leading-6 text-ink-700">{r(cell)}</td>)}</tr>)}</tbody></table></div>}</section>)}

          {page.outline&&<section><h2 className="font-display text-4xl leading-tight text-ink-900">{ui.outline}</h2><div className="relative mt-6 space-y-4 border-s border-brass-500/30 ps-7">{page.outline.map(step=><div key={step.label} className="relative rounded-sm border border-night-900/10 bg-white p-6 before:absolute before:-start-[33px] before:top-7 before:size-3 before:rounded-full before:bg-brass-500"><p className="text-xs font-bold uppercase tracking-[.12em] text-brass-700">{r(step.label)}</p><p className="mt-2 text-[16px] leading-7 text-ink-700">{r(step.text)}</p></div>)}</div>{page.notes&&<p className="mt-6 text-sm leading-6 text-night-700">{r(page.notes)}</p>}</section>}

          {(pendingText||page.visitTip||page.audience)&&<div className="grid gap-5 md:grid-cols-2">
            {pendingText&&<aside className="rounded-lg border border-brass-500/30 bg-brass-50 p-6 md:col-span-2"><div className="flex flex-wrap items-center gap-3"><Info className="size-5 text-brass-700"/><h2 className="text-xs font-bold uppercase tracking-[.12em] text-brass-800">{ui.practicalInfo}</h2><span className="rounded-full bg-night-950 px-3 py-1 text-[11px] font-bold uppercase tracking-[.1em] text-brass-300">{ui.pending}</span></div><p className="mt-3 text-sm leading-6 text-night-700">{r(pendingText)}</p></aside>}
            {page.visitTip&&<aside className="rounded-lg border border-night-900/10 bg-white p-6"><Lightbulb className="text-brass-600"/><h2 className="mt-4 font-display text-2xl text-ink-900">{ui.visitTip}</h2><p className="mt-3 text-sm leading-6 text-ink-700">{r(page.visitTip)}</p></aside>}
            {page.audience&&<aside className="rounded-lg bg-night-950 p-6 text-sand-100"><Users className="text-brass-400"/><h2 className="mt-4 font-display text-2xl">{ui.audience}</h2><p className="mt-3 text-sm leading-6 text-sand-200"><Rich text={page.audience} locale={locale} cite={cite} sourceLabel={ui.sources}/></p></aside>}
          </div>}

          {id==='hub'&&<>
            <section><h2 className="font-display text-4xl text-ink-900">{ui.attractions}</h2><div className="mt-7 grid gap-5 sm:grid-cols-2">{abuDhabiIdsByKind('attraction').map(item=><Card key={item} href={abuDhabiPath(locale,item)} eyebrow={ui.attraction} title={content.pages[item].h1} text={content.pages[item].metaDescription} icon={<MapPin className="text-brass-600"/>}/>)}</div></section>
            <section><h2 className="font-display text-4xl text-ink-900">{ui.itineraries}</h2><div className="mt-7 grid gap-5 sm:grid-cols-2">{abuDhabiIdsByKind('itinerary').map(item=><Card key={item} href={abuDhabiPath(locale,item)} eyebrow={ui.itinerary} title={content.pages[item].h1} text={content.pages[item].metaDescription} icon={<CalendarDays className="text-brass-600"/>}/>)}</div></section>
            <section><h2 className="font-display text-4xl text-ink-900">{ui.articles}</h2><div className="mt-7 grid gap-5 sm:grid-cols-2">{abuDhabiIdsByKind('article').map(item=><Card key={item} href={abuDhabiPath(locale,item)} eyebrow={ui.article} title={content.pages[item].h1} text={content.pages[item].metaDescription} icon={<Info className="text-brass-600"/>}/>)}</div></section>
          </>}

          {page.faq&&page.faq.length>0&&<section className="border-t border-black/10 pt-12"><h2 className="font-display text-4xl text-ink-900">{ui.faq}</h2><div className="mt-7 space-y-6">{page.faq.map(item=><details key={item.question} className="rounded-lg border border-black/10 bg-white p-6"><summary className="cursor-pointer font-semibold text-ink-900">{r(item.question)}</summary><p className="mt-4 leading-7 text-ink-700">{r(item.answer)}</p></details>)}</div></section>}

          <section className="border-t border-black/10 pt-12"><h2 className="font-display text-4xl text-ink-900">{ui.sources}</h2><ol className="mt-6 space-y-4">{sources.map((source,index)=>{const item=abuDhabiSources[source];return <li key={source} id={`fonte-${index+1}`} className="scroll-mt-24 text-sm leading-6 text-ink-700"><span className="font-semibold text-ink-900">[{index+1}] <bdi>{item.name}</bdi>.</span> <a href={item.url} target="_blank" rel="noopener noreferrer" className="break-all text-brass-700 underline underline-offset-4"><bdi>{item.url}</bdi><ExternalLink className="ms-1 inline size-3.5"/></a> {item.updatedAt&&<>{ui.sourceUpdated} <time dateTime={item.updatedAt}>{item.updatedAt.split('-').reverse().join('/')}</time>. </>}{ui.sourceConsulted} <time dateTime={item.consultedAt}>{item.consultedAt.split('-').reverse().join('/')}</time>.</li>;})}</ol></section>
        </div>

        <aside className="space-y-5 lg:sticky lg:top-24 lg:self-start">
          <div className="rounded-xl bg-night-900 p-6 text-sand-100"><h2 className="font-display text-3xl leading-tight">{ui.ctaTitle}</h2><WhatsAppLink href={waHref} location={`${location}_sidebar`} className="mt-6 w-full px-6 py-4">{ui.cta}</WhatsAppLink></div>
          {related.length>0&&<nav aria-label={ui.related} className="rounded-xl border border-black/10 bg-white p-6"><h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-brass-700">{ui.related}</h2><div className="mt-4 space-y-1">{related.map(item=><a key={item.key} href={abuDhabiLinkPath(locale,item.key)} className="flex min-h-11 items-center justify-between gap-3 border-b border-black/5 py-3 text-sm font-semibold text-ink-900 hover:text-brass-700"><span><Isolated text={item.title} rtl={locale==='ar'}/></span><ArrowUpRight className="size-4 shrink-0 rtl:-scale-x-100"/></a>)}</div></nav>}
        </aside>
      </div>
    </article>
    <section className="bg-gradient-to-r from-night-950 to-brass-700 py-16 text-center text-sand-50"><div className="mx-auto max-w-2xl px-6"><h2 className="font-display text-4xl">{ui.ctaTitle}</h2><WhatsAppLink href={waHref} location={location} className="mt-7">{ui.cta}</WhatsAppLink></div></section>
  </main>;
}
