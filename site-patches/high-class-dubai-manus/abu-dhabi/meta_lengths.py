"""Lista o tamanho de meta title/description por página e idioma (tabela para o PR)."""
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent / 'files'
for loc in ['en', 'pt', 'es', 'ar']:
    data = json.loads((root / f'content/{loc}/abu-dhabi.json').read_text())
    pages = {'hub': data['hub'], **data['pages']}
    lt = [len(p['metaTitle']) for p in pages.values()]
    ld = [len(p['metaDescription']) for p in pages.values()]
    print(f'{loc}: title {min(lt)}-{max(lt)} | description {min(ld)}-{max(ld)}')
