import type {AbuDhabiContent} from '@/content/types';
import type {AbuDhabiLocale} from '@/lib/routes';

export async function getAbuDhabiContent(locale: AbuDhabiLocale): Promise<AbuDhabiContent> {
  return (await import(`@/content/${locale}/abu-dhabi.json`)).default as AbuDhabiContent;
}
