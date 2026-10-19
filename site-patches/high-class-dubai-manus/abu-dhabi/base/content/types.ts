import type {DestinationId, ItineraryId, ServiceId} from '@/lib/routes';

export type MetaContent = {title: string; description: string};
export type PageSection = {title: string; text: string};

export type DubaiSource = {name: string; url: string; consultedAt: string};
export type DubaiQuickGuideItem = {key: string; title: string; value: string; detail: string; sourceName: string; sourceUrl: string; consultedAt: string; pending: boolean; notes?: string; sources?: DubaiSource[]};
export type DubaiArticleTable = {headers: string[]; rows: string[][]};
export type DubaiArticleSection = {heading: string; paragraphs: string[]; table?: DubaiArticleTable};
export type DubaiArticleContent = {
  slug: string;
  locale: 'pt' | 'en' | 'es' | 'ar';
  title: string;
  description: string;
  publishedAt: string;
  updatedAt: string;
  category: string;
  readingTime: string;
  eyebrow: string;
  summary: string[];
  updatedNotice: string;
  sections: DubaiArticleSection[];
  faq: {question: string; answer: string}[];
  sources: DubaiSource[];
  relatedServices: ServiceId[];
  relatedArticle: string;
  contactCta: string;
  pendingFacts: string[];
};

export type ServiceContent = {
  id: ServiceId;
  title: string;
  pillar: string;
  phrase: string;
  forWhom: string;
  included: string[];
  organization: string;
  faq: {question: string; answer: string}[];
};

export type SiteContent = {
  about: {meta: MetaContent; eyebrow: string; title: string; intro: string; sections: PageSection[]; office: PageSection; cta: string};
  servicesIndex: {meta: MetaContent; eyebrow: string; title: string; intro: string; filters: string[]};
  business: {meta: MetaContent; eyebrow: string; title: string; intro: string; blocks: string[]; fairsTitle: string; fairColumns: string[]; fairs: {event: string; dates: string; sector: string; location: string}[]; workTitle: string; workText: string};
  experiences: {meta: MetaContent; eyebrow: string; title: string; intro: string; cards: string[]};
  dubai: {meta: MetaContent; eyebrow: string; title: string; intro: string; faqs: {question: string; answer: string}[]};
  contact: {meta: MetaContent; eyebrow: string; title: string; text: string; whatsappTitle: string; emailLabel: string; addressLabel: string; hoursLabel: string; hours: string; socialsLabel: string; formTitle: string};
  privacy: {meta: MetaContent; eyebrow: string; title: string; intro: string; sections: PageSection[]};
  services: ServiceContent[];
};

export type FleetVehicle = {
  model: string;
  pax: number | string;
  bagsSeats: string;
  bagsFolded: string | null;
  use: string | null;
};

export type HotelProfile = {profile: string; category: string; examples: string[]};
export type Attraction = {id: string; name: string; place: string; region: string; duration: string; audience: string; notes: string; category: string; seasonal: boolean};
export type Destination = {slug:DestinationId;name:string;summary:string;highlights:string[];operation:string};

export type CatalogContent = {
  meta: MetaContent;
  fleet: {intro:string;rule:string;owned: FleetVehicle[]; partners: FleetVehicle[]};
  hotels: {intro:string;minimumNights:{itinerary:string;nights:number}[];profiles: HotelProfile[];questions:string[];roomTypes:{name:string;group:string;description:string}[]};
  attractions: Attraction[];
  destinations: Destination[];
};

export type Itinerary = {
  slug: ItineraryId;
  title: string;
  audience: string;
  nights: string;
  priceMode: 'consultation';
  priceRange: string;
  summary: string;
  days: {day: string; title: string; description: string}[];
  includes: string[];
  excludes: string[];
  policy: string;
};

export type LegalPageContent = {meta: MetaContent; sections: {title: string; paragraphs: string[]}[]};

export type JourneysContent = {
  itineraries: Itinerary[];
  agency: {title: string; description: string; registration: PageSection; commission: PageSection; rates: PageSection; materials: PageSection; whatsappGroup: PageSection; cta: string};
  events: {title: string; description: string; company: string; license: string; services: string[]; process: string};
  dubaiNow: {title: string; intro: string; data: {label: string; value: string}[]; source: {name: string; date: string; url: string}; notice: string};
  legal: {privacy: LegalPageContent; terms: LegalPageContent; cancellation: LegalPageContent; cookies: LegalPageContent};
};
