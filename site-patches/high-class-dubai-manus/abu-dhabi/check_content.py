"""Checa o conteúdo de Abu Dhabi do kit (ou do repo do site, se passado como argumento).

Uso: python3 -I check_content.py [raiz]   (padrão: ./files ao lado deste script)
Sai com código 1 se houver erro. Avisos não bloqueiam.
"""
import json
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent / 'files'
LOCALES = ['en', 'pt', 'es', 'ar']
errors, warnings = [], []

routes = (root / 'lib/routes.ts').read_text()
registry = (root / 'lib/abu-dhabi.ts').read_text()

ids = re.findall(r"'([a-z0-9-]+)'", re.search(r'export type AbuDhabiPageId = ([^;]+);', routes).group(1))
slug_block = re.search(r'export const abuDhabiSlugs[^{]*\{(.+?)\n\};', routes, re.S).group(1)
slugs = {}
for loc in LOCALES:
    line = re.search(rf'^\s*{loc}:\{{(.+)\}},?$', slug_block, re.M).group(1)
    slugs[loc] = dict(re.findall(r"'?([a-z0-9-]+)'?:'([^']+)'", line))
    if sorted(slugs[loc]) != sorted(ids):
        errors.append(f'{loc}: slugs não cobrem exatamente os {len(ids)} ids')
    if len(set(slugs[loc].values())) != len(slugs[loc]):
        errors.append(f'{loc}: slug duplicado')

entries = {}
for m in re.finditer(r"^\s*'?([a-z0-9-]+)'?:\{kind:'(\w+)',sources:\[([^\]]*)\],pending:\[([^\]]*)\],related:\[([^\]]*)\],indexable:(true|false)", registry, re.M):
    entries[m.group(1)] = {'kind': m.group(2), 'sources': re.findall(r"'(\w+)'", m.group(3)), 'related': re.findall(r"'([a-z0-9-]+)'", m.group(5)), 'indexable': m.group(6) == 'true'}
hub = re.search(r'export const abuDhabiHub[^=]*= \{sources:\[([^\]]*)\]', registry)
entries['hub'] = {'kind': 'hub', 'sources': re.findall(r"'(\w+)'", hub.group(1)), 'related': [], 'indexable': True}
if sorted(k for k in entries if k != 'hub') != sorted(ids):
    errors.append('registro lib/abu-dhabi.ts não cobre exatamente os ids de routes.ts')
link_keys = set(ids) | {'hub', 'dubai-hub', 'dubai-abu-dhabi-6n'}
for key, entry in entries.items():
    for rel in entry['related']:
        if rel not in link_keys:
            errors.append(f'registro {key}: related inválido {rel}')

def texts(page):
    out = [page.get(k) for k in ('h1', 'intro', 'practicalInfo', 'visitTip', 'audience', 'notes') if page.get(k)]
    for s in page.get('sections', []):
        out.append(s['heading'])
        out += s.get('paragraphs', []) + s.get('items', [])
        if s.get('table'):
            out += s['table']['headers'] + [c for row in s['table']['rows'] for c in row]
    for step in page.get('outline', []):
        out += [step['label'], step['text']]
    for q in page.get('faq', []):
        out += [q['question'], q['answer']]
    return out

titles, descriptions = {}, {}
counts = {}
for loc in LOCALES:
    data = json.loads((root / f'content/{loc}/abu-dhabi.json').read_text())
    if data['locale'] != loc:
        errors.append(f'{loc}: campo locale = {data["locale"]}')
    if sorted(data['pages']) != sorted(ids):
        errors.append(f'{loc}: páginas no JSON diferentes dos ids')
    pending = data['ui']['pending']
    pages = {'hub': data['hub'], **data['pages']}
    counts[loc] = len(pages)
    for key, page in pages.items():
        where = f'{loc}/{key}'
        title, desc = page['metaTitle'], page['metaDescription']
        if not title.endswith(' | High Class'):
            errors.append(f'{where}: metaTitle sem " | High Class"')
        if 'High Class Dubai' in title:
            errors.append(f'{where}: metaTitle com "High Class Dubai"')
        limit_t, limit_d = (60, 160)
        if len(title) > limit_t:
            (warnings if loc == 'ar' else errors).append(f'{where}: metaTitle com {len(title)} caracteres')
        if len(desc) > limit_d:
            (warnings if loc == 'ar' else errors).append(f'{where}: metaDescription com {len(desc)} caracteres')
        if title in titles:
            errors.append(f'{where}: metaTitle repetido de {titles[title]}')
        if desc in descriptions:
            errors.append(f'{where}: metaDescription repetida de {descriptions[desc]}')
        titles[title], descriptions[desc] = where, where
        if not page.get('whatsappContext'):
            errors.append(f'{where}: sem whatsappContext')
        info = page.get('practicalInfo')
        if entries.get(key, {}).get('kind') in ('attraction', 'hub') and not info:
            errors.append(f'{where}: atração sem practicalInfo')
        if info and not info.startswith(pending + ':'):
            errors.append(f'{where}: practicalInfo não começa com "{pending}:"')
        body = ' '.join(texts(page))
        for marker in set(re.findall(r'\[(S\d+|I1)\]', body)):
            if marker not in entries[key]['sources']:
                errors.append(f'{where}: cita [{marker}] sem registrar a fonte no lib/abu-dhabi.ts')
        for marker in entries[key]['sources']:
            if f'[{marker}]' not in body:
                warnings.append(f'{where}: fonte {marker} registrada mas não citada no texto')
        for link in re.findall(r'\[\[([a-z0-9-]+)\|', body):
            if link not in link_keys:
                errors.append(f'{where}: link interno inválido [[{link}|…]]')
        for other in ('TO BE CONFIRMED', 'A CONFIRMAR', 'POR CONFIRMAR', 'قيد التأكيد'):
            if other != pending and other in body:
                errors.append(f'{where}: marcador de outro idioma "{other}"')
        if re.search(r'Yas Waves', body):
            errors.append(f'{where}: "Yas Waves" no texto público')
        if re.search(r'\b(AED|USD|R\$|US\$|€)\s?\d', body) or re.search(r'\d{1,2}[:h]\d{2}', body):
            errors.append(f'{where}: possível preço ou horário no texto')
        if re.search(r'\b(IA|AI|inteligência artificial|artificial intelligence|bot)\b', body, re.I):
            errors.append(f'{where}: menção a IA/bot')
        if body.count('**') % 2:
            errors.append(f'{where}: negrito ** desbalanceado')

print(f'páginas por idioma: {counts}  (hub + {len(ids)} páginas)')
print(f'indexáveis: {sum(1 for k, e in entries.items() if k != "hub" and e["indexable"])} de {len(ids)} por idioma; noindex: {[k for k, e in entries.items() if not e["indexable"]]}')
for w in warnings:
    print('AVISO', w)
for e in errors:
    print('ERRO', e)
print('OK' if not errors else f'{len(errors)} erro(s)')
sys.exit(1 if errors else 0)
