import {ImageResponse} from 'next/og';
import {headers} from 'next/headers';
import {brandAssets} from '@/content/images';
import {getAbuDhabiContent} from '@/lib/abu-dhabi-content';
import {abuDhabiIdFromSlug, isAbuDhabiLocale} from '@/lib/routes';

export const alt = 'High Class Travel Experiences · Abu Dhabi';
export const size = {width: 1200, height: 630};
export const contentType = 'image/png';

// Neutral Abu Dhabi card for the guide pages (overrides the Dubai card of app/[locale]/opengraph-image.tsx).
// Arabic glyphs are not rendered by the default OG font, so the Arabic pages show the Latin name only.
export default async function OpenGraphImage({params}: {params: Promise<{locale: string; childSlug: string}>}) {
  const {locale, childSlug} = await params;
  const requestHeaders = await headers();
  const host = requestHeaders.get('x-forwarded-host') || requestHeaders.get('host') || 'localhost:3000';
  const protocol = requestHeaders.get('x-forwarded-proto') || (host.includes('localhost') ? 'http' : 'https');
  const absoluteAsset = (path: string) => `${protocol}://${host}${path}`;
  let title = 'Abu Dhabi';
  if (isAbuDhabiLocale(locale) && locale !== 'ar') {
    const id = abuDhabiIdFromSlug(locale, decodeURIComponent(childSlug));
    if (id) title = (await getAbuDhabiContent(locale)).pages[id].h1;
  }

  return new ImageResponse(
    <div style={{width: '100%', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', padding: '74px 82px', background: 'linear-gradient(125deg, #07090F 0%, #121826 62%, #7F6330 140%)', color: '#F3ECDF', direction: 'ltr'}}>
      <img src={absoluteAsset(brandAssets.logo)} width="351" height="66" style={{objectFit: 'contain', alignSelf: 'flex-start'}} />
      <div style={{display: 'flex', flexDirection: 'column', gap: 24}}>
        <div style={{fontSize: 19, color: '#D4B26A', letterSpacing: '0.12em', textTransform: 'uppercase'}}>High Class Travel Experiences</div>
        <div style={{fontSize: 70, lineHeight: 1.05, maxWidth: 980, fontWeight: 500}}>{title}</div>
        <div style={{fontSize: 22, color: '#D3BF9C'}}>Abu Dhabi, UAE</div>
      </div>
    </div>,
    size
  );
}
