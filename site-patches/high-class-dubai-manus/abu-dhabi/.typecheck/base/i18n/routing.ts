// Stub of the site's i18n/routing.ts (same locales), without next-intl.
export const locales = ['pt', 'en', 'es', 'ar', 'hi', 'ru', 'de'] as const;
export type Locale = (typeof locales)[number];
export function isLocale(value: string | undefined): value is Locale { return typeof value === 'string' && locales.includes(value as Locale); }
