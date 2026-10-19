"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.locales = void 0;
exports.isLocale = isLocale;
// Stub of the site's i18n/routing.ts (same locales), without next-intl.
exports.locales = ['pt', 'en', 'es', 'ar', 'hi', 'ru', 'de'];
function isLocale(value) { return typeof value === 'string' && exports.locales.includes(value); }
