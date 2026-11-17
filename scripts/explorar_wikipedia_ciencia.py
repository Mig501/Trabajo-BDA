#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto reproducible de Wikipedia para un RAG documental ES/EN.

Descubre candidatos mediante categorías científicas, muestrea títulos con una
semilla fija, obtiene el texto mediante MediaWiki Action API y guarda evidencias
y estadísticas. No presupone ni certifica la exclusividad cross-lingual.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ImportError:
    raise SystemExit('Falta requests. Instala: python -m pip install requests')

# Las categorías se fijan ANTES de observar resultados, para justificar el marco
# temático. Las que no existan se anotan como advertencias, no se sustituyen.
CATEGORIES = {
    'es': {
        'fisica': ['Categoría:Físicos', 'Categoría:Historia de la física'],
        'matematicas': ['Categoría:Matemáticos', 'Categoría:Historia de las matemáticas'],
        'quimica': ['Categoría:Químicos', 'Categoría:Historia de la química'],
        'astronomia': ['Categoría:Astrónomos', 'Categoría:Historia de la astronomía'],
    },
    'en': {
        'fisica': ['Category:Physicists', 'Category:History of physics'],
        'matematicas': ['Category:Mathematicians', 'Category:History of mathematics'],
        'quimica': ['Category:Chemists', 'Category:History of chemistry'],
        'astronomia': ['Category:Astronomers', 'Category:History of astronomy'],
    },
}
DROP_SECTIONS = re.compile(
    r'(?m)^==\s*(?:References|External links|Further reading|Notes|Bibliography|'
    r'Referencias|Enlaces externos|Bibliograf[ií]a|Notas|Lecturas adicionales|'
    r'Ver tambi[eé]n|See also)\s*==\s*$'
)
DROP_PLAIN_SECTIONS = re.compile(
    r'(?mi)^(?:References|External links|Further reading|Bibliography|'
    r'Referencias|Enlaces externos|Bibliograf[ií]a|Lecturas adicionales|Notas)\s*$'
)
LIST_TITLE = re.compile(r'^(?:lista\s+de|list\s+of|anexo:|annex:|índice\s+de|index\s+of)', re.I)
MATH_SYMBOLS = set('∫∑∏√≈≠≤≥∞∂∇⊂⊆∈∉∩∪∀∃∴')
FIELDS = [
    'document_id', 'language', 'topic', 'title', 'wikidata_id', 'page_id',
    'revision_id', 'revision_timestamp', 'url', 'source_category',
    'source_type', 'words', 'letters_ratio', 'formula_line_ratio',
    'license', 'retrieved_at_utc', 'text',
]


def normalize_text(text: str) -> str:
    text = unicodedata.normalize('NFC', text or '')
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\xa0', ' ')
    text = re.sub(r'(?m)[ \t]+$', '', text)
    text = DROP_SECTIONS.split(text, maxsplit=1)[0]
    text = DROP_PLAIN_SECTIONS.split(text, maxsplit=1)[0]
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def quality(text: str, title: str, min_words: int) -> tuple[str, dict]:
    text = normalize_text(text)
    words = len(text.split())
    visible = [c for c in text if not c.isspace()]
    letters_ratio = sum(c.isalpha() for c in visible) / max(1, len(visible))
    lines = [x.strip() for x in text.splitlines() if x.strip() and not x.strip().startswith('==')]
    equation_like = sum(
        bool(re.search(r'(?:\\(?:frac|sum|int)|[∫∑∏√∂∇]|(?:^|\s)[a-zA-Z]\s*=|\$[^$]+\$)', ln))
        or sum(c in MATH_SYMBOLS for c in ln) >= 2
        for ln in lines
    )
    formula_line_ratio = equation_like / max(1, len(lines))
    stats = {'words': words, 'letters_ratio': round(letters_ratio, 3),
             'formula_line_ratio': round(formula_line_ratio, 3)}
    if LIST_TITLE.search(title):
        return 'lista_o_anexo', stats
    if words < min_words:
        return 'demasiado_corto', stats
    if letters_ratio < 0.66:
        return 'exceso_no_textual', stats
    if formula_line_ratio > 0.20:
        return 'exceso_formulas', stats
    if len(text) > 250000:
        return 'demasiado_largo', stats
    return 'ok', stats


class WikimediaAccessBlocked(Exception):
    """No reintentar masivamente cuando el servicio bloquea o limita acceso."""


class WikiAPI:
    def __init__(self, contact: str, delay: float, timeout: float):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'BDA-Ciencia-Wikipedia-Pilot/0.1 ({contact}; educational research)',
            'Accept': 'application/json',
        })
        self.delay = delay
        self.timeout = timeout
        self.calls = 0

    def get(self, lang: str, params: dict) -> dict:
        url = f'https://{lang}.wikipedia.org/w/api.php'
        query = {'format': 'json', 'formatversion': 2, 'action': 'query', **params}
        for attempt in range(4):
            try:
                response = self.session.get(url, params=query, timeout=self.timeout)
                self.calls += 1
                if response.status_code in (401, 403):
                    raise WikimediaAccessBlocked(
                        f'HTTP {response.status_code} desde Wikipedia {lang}: acceso denegado. '
                        'Comprueba el User-Agent, la red o posibles bloqueos; no repetir en bucle.'
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 3:
                        if response.status_code == 429:
                            raise WikimediaAccessBlocked(
                                'Wikipedia devuelve HTTP 429 repetidamente: posponer la ejecución '
                                'y/o aumentar --delay. No insistir con peticiones.'
                            )
                        response.raise_for_status()
                    retry_header = response.headers.get('Retry-After', '')
                    try:
                        wait = max(1.0, min(90.0, float(retry_header)))
                    except ValueError:
                        wait = min(30.0, 2.0 ** (attempt + 1))
                    print(f'  HTTP {response.status_code}; reintentando en {wait:g} s', file=sys.stderr)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                data = response.json()
                if 'error' in data:
                    raise RuntimeError(f'Error API {lang}: {data["error"]}')
                return data
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == 3:
                    raise
                wait = 2.0 ** (attempt + 1)
                print(f'  Error de conexión ({exc}); reintentando en {wait:g} s', file=sys.stderr)
                time.sleep(wait)
            finally:
                if self.delay:
                    time.sleep(self.delay)
        raise RuntimeError(f'No se pudo completar la petición a Wikipedia {lang}')

    def category_members(self, lang: str, category: str, cap: int):
        """Hasta cap miembros por categoría; devuelve (miembros, truncada)."""
        members = []
        token = {}
        while len(members) < cap:
            data = self.get(lang, {
                'list': 'categorymembers', 'cmtitle': category, 'cmtype': 'page|subcat',
                'cmlimit': min(500, cap - len(members)), **token,
            })
            chunk = data.get('query', {}).get('categorymembers', [])
            members.extend(chunk)
            cont = data.get('continue', {})
            if not cont or not chunk:
                return members, False
            token = {k: v for k, v in cont.items() if k in ('cmcontinue', 'continue')}
            if 'cmcontinue' not in token:
                return members, False
        return members, bool(token)

    def pages(self, lang: str, titles: list[str]) -> list[dict]:
        """Obtiene artículos por separado por límite de TextExtracts y revisions.

        Con extracto completo MediaWiki obliga a exlimit=1. También rvlimit
        sobre varias páginas genera invalidparammix. No agrupar estas consultas.
        """
        pages = []
        for title in titles:
            try:
                data = self.get(lang, {
                    'prop': 'extracts|pageprops|revisions|info',
                    'titles': title, 'redirects': 1,
                    'explaintext': 1, 'exsectionformat': 'plain', 'exlimit': 1,
                    'ppprop': 'wikibase_item|disambiguation',
                    'rvprop': 'ids|timestamp', 'rvlimit': 1, 'inprop': 'url',
                })
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                pages.append({'title': title, '_requested_title': title,
                              '_api_error': str(exc)[:180]})
                continue
            for page in data.get('query', {}).get('pages', []):
                page['_requested_title'] = title
                pages.append(page)
        return pages


def discover(api: WikiAPI, lang: str, max_candidates: int,
             depth: int, max_categories: int, members_per_category: int):
    """Descubrimiento por categorías con cuota por tema para evitar monopolios.

    La exploración sigue siendo PARCIAL si se alcanzan límites. Para el corpus
    final se deberá definir un marco completo y estratificar a posteriori.
    """
    topics = list(CATEGORIES[lang])
    quota = max(1, (max_candidates + len(topics) - 1) // len(topics))
    pending = deque()
    # Primero recorremos las categorías principales de todos los temas;
    # después las históricas; posteriormente se incorporan subcategorías.
    for idx in range(max(map(len, CATEGORIES[lang].values()))):
        for topic, seeds in CATEGORIES[lang].items():
            if idx < len(seeds):
                pending.append((seeds[idx], topic, 0))
    seen_categories: set[str] = set()
    candidate_by_title: dict[str, dict] = {}
    counts_by_topic: Counter = Counter()
    warnings = []
    scans = []
    while pending and len(seen_categories) < max_categories:
        category, topic, level = pending.popleft()
        if counts_by_topic[topic] >= quota:
            continue
        if category.lower() in seen_categories:
            continue
        seen_categories.add(category.lower())
        try:
            members, truncated = api.category_members(lang, category, members_per_category)
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            warnings.append(f'{lang}: categoría {category}: {exc}')
            continue
        if not members:
            warnings.append(f'{lang}: categoría sin miembros o inexistente: {category}')
        scans.append({'category': category, 'topic': topic, 'depth': level,
                      'members_seen': len(members), 'category_truncated': truncated})
        for m in members:
            ns = m.get('ns')
            title = m.get('title', '')
            if ns == 0 and title and title not in candidate_by_title:
                if counts_by_topic[topic] < quota:
                    candidate_by_title[title] = {
                        'title': title, 'topic': topic, 'source_category': category}
                    counts_by_topic[topic] += 1
            elif ns == 14 and level < depth:
                pending.append((title, topic, level + 1))
        if all(counts_by_topic[t] >= quota for t in topics):
            break
    if pending or any(s['category_truncated'] for s in scans):
        warnings.append(f'{lang}: descubrimiento parcial por límites del piloto; NO es el total de Wikipedia.')
    if any(counts_by_topic[t] < quota for t in topics):
        warnings.append(f'{lang}: no se alcanzaron las cuotas de candidatos en todos los temas.')
    return list(candidate_by_title.values()), warnings, scans


def sample_documents(api: WikiAPI, lang: str, candidates: list[dict],
                     target: int, min_words: int, seed: int, batch_size: int = 10):
    candidates = sorted(candidates, key=lambda x: x['title'])
    rng = random.Random(seed + (0 if lang == 'es' else 10000))
    rng.shuffle(candidates)
    selected: list[dict] = []
    rejected = []
    seen_ids: set[int] = set()
    retrieved = 0
    for start in range(0, len(candidates), batch_size):
        if len(selected) >= target:
            break
        batch = candidates[start:start + batch_size]
        categories = {item['title']: item for item in batch}
        try:
            pages = api.pages(lang, [item['title'] for item in batch])
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            for item in batch:
                rejected.append({'language': lang, 'title': item['title'],
                                 'reason': f'error_api: {str(exc)[:180]}', 'words': 0})
            continue
        for page in pages:
            title = page.get('title', '')
            original = page.get('_requested_title', title)
            base = categories[original]
            if '_api_error' in page:
                rejected.append({'language': lang, 'title': original,
                                 'reason': 'error_api: ' + page['_api_error'], 'words': 0})
                continue
            if page.get('missing') or page.get('ns') != 0:
                rejected.append({'language': lang, 'title': title,
                                 'reason': 'pagina_inexistente_o_no_principal', 'words': 0})
                continue
            if 'disambiguation' in page.get('pageprops', {}):
                rejected.append({'language': lang, 'title': title,
                                 'reason': 'desambiguacion', 'words': 0})
                continue
            pid = page.get('pageid')
            if pid in seen_ids:
                rejected.append({'language': lang, 'title': title,
                                 'reason': 'pagina_duplicada', 'words': 0})
                continue
            seen_ids.add(pid)
            text = normalize_text(page.get('extract', ''))
            reason, q = quality(text, title, min_words)
            retrieved += 1
            if reason != 'ok':
                rejected.append({'language': lang, 'title': title, 'reason': reason,
                                 'words': q['words']})
                continue
            revision = (page.get('revisions') or [{}])[0]
            url = page.get('fullurl') or f'https://{lang}.wikipedia.org/wiki/{quote(title.replace(" ", "_"), safe="()")}'
            item = {
                'document_id': f'wiki:{lang}:{pid}', 'language': lang,
                'topic': base['topic'], 'title': title,
                'wikidata_id': page.get('pageprops', {}).get('wikibase_item', ''),
                'page_id': pid,
                'revision_id': revision.get('revid', ''),
                'revision_timestamp': revision.get('timestamp', ''),
                'url': url,
                'source_category': base['source_category'],
                'source_type': 'Wikipedia, API MediaWiki (edición actual)',
                'words': q['words'],
                'letters_ratio': q['letters_ratio'],
                'formula_line_ratio': q['formula_line_ratio'],
                'license': 'Ver licencia y atribución en la página fuente (Wikipedia: CC BY-SA; verificar versión)',
                'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                'text': text,
            }
            selected.append(item)
            if len(selected) >= target:
                break
    return selected, rejected, retrieved


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def estimates(rows: list[dict]):
    counts = Counter(d['language'] for d in rows)
    words = Counter()
    approx_chunks = Counter()
    for d in rows:
        lang = d['language']
        words[lang] += int(d['words'])
        # Indicador meramente orientativo. El recuento oficial usa tokenizer.
        approx_chunks[lang] += max(1, (int(d['words']) + 116) // 117)
    total = sum(approx_chunks.values())
    return {
        'documents_by_language': dict(counts),
        'words_by_language': dict(words),
        'rough_chunks_by_language_117_words': dict(approx_chunks),
        'rough_chunks_total_117_words': total,
        'rough_chunk_share': {k: round(v / total, 4) if total else 0
                              for k, v in approx_chunks.items()},
    }


def cross_language_candidates(rows: list[dict]):
    by_qid = defaultdict(set)
    for r in rows:
        if r['wikidata_id']:
            by_qid[r['wikidata_id']].add(r['language'])
    candidates = []
    collisions = []
    for r in rows:
        qid = r['wikidata_id']
        if not qid:
            continue
        if len(by_qid[qid]) == 1:
            candidates.append({
                'document_id': r['document_id'], 'language': r['language'],
                'query_language_to_try': 'en' if r['language'] == 'es' else 'es',
                'title': r['title'], 'wikidata_id': qid, 'url': r['url'],
                'words': r['words'],
                'verification_status': 'SOLO CANDIDATO: no prueba ausencia de otras fuentes',
            })
        else:
            collisions.append({'wikidata_id': qid, 'title': r['title'],
                               'language': r['language'], 'document_id': r['document_id']})
    return candidates, collisions


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', default='data/exploracion_wikipedia_ciencia')
    p.add_argument('--per-language', type=int, default=100,
                   help='Artículos aceptados por idioma (piloto, defecto 100)')
    p.add_argument('--max-candidates', type=int, default=500,
                   help='Candidatos descubiertos como mínimo por idioma (defecto 500)')
    p.add_argument('--max-categories', type=int, default=32)
    p.add_argument('--members-per-category', type=int, default=500)
    p.add_argument('--depth', type=int, default=1, choices=[0, 1, 2])
    p.add_argument('--min-words', type=int, default=250)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--delay', type=float, default=0.25)
    p.add_argument('--timeout', type=float, default=35.0)
    p.add_argument('--contact', default='https://github.com/Mig501/Trabajo-BDA',
                   help='Contacto identificable incluido en User-Agent Wikimedia')
    args = p.parse_args(argv)
    if args.per_language <= 0 or args.max_candidates <= 0 or args.max_categories <= 0 or args.members_per_category <= 0:
        p.error('Los límites deben ser positivos.')
    if not args.contact or args.contact == 'none':
        p.error('--contact debe indicar un correo o URL de contacto válida.')
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    api = WikiAPI(args.contact, args.delay, args.timeout)
    all_rows = []
    all_rejected = []
    notes = []
    categories_report = []
    discover_report = {}
    for lang in ('es', 'en'):
        print(f'\n[{lang.upper()}] Descubriendo artículos en categorías científicas... ', flush=True)
        pool, warnings, scans = discover(
            api, lang, args.max_candidates, args.depth,
            args.max_categories, args.members_per_category,
        )
        notes.extend(warnings)
        categories_report.extend([{'language': lang, **s} for s in scans])
        discover_report[lang] = {'distinct_candidates': len(pool), 'categories_scanned': len(scans)}
        print(f'  Candidatos distintos: {len(pool)}; categorías consultadas: {len(scans)}')
        print(f'[{lang.upper()}] Recuperando muestra aleatoria dentro del marco descubierto... ', flush=True)
        selected, rejected, fetched = sample_documents(
            api, lang, pool, args.per_language, args.min_words, args.seed,
        )
        all_rows.extend(selected)
        all_rejected.extend(rejected)
        print(f'  Aceptados: {len(selected)}/{args.per_language}; ' 
              f'revisados: {fetched}; rechazados: {len(rejected)}')
        if len(selected) < args.per_language:
            notes.append(f'{lang}: no se alcanzó el objetivo de {args.per_language} documentos.')

    cross_candidates, collisions = cross_language_candidates(all_rows)
    stats = estimates(all_rows)
    reasons = Counter(x['reason'] for x in all_rejected)
    by_topic = Counter((x['language'], x['topic']) for x in all_rows)
    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'PILOTO, NO CORPUS DEFINITIVO NI MUESTRA ALEATORIA DE TODA WIKIPEDIA',
        'method': 'Categorías científicas explícitas > BFS acotado > orden aleatorio determinista > filtro textual',
        'source': 'MediaWiki Action API (Wikipedia en vivo, NO wikimedia/wikipedia 20231101)',
        'parameters': vars(args), 'api_requests': api.calls,
        'discovery': discover_report, 'estimates': stats,
        'rejection_reasons': dict(reasons),
        'accepted_by_language_topic': {f'{k[0]}:{k[1]}': v for k, v in sorted(by_topic.items())},
        'cross_language_candidate_count': len(cross_candidates),
        'entity_collision_count': len({c['wikidata_id'] for c in collisions}),
        'warnings': notes + [
            'La exclusividad cross-lingual no está verificada. Hay que comprobar los demás textos y ejecutar retrieval.',
            'Los límites de exploración y la pertenencia a categorías generan sesgo; no extrapolar al total sin definir marco completo.',
            'Las estimaciones de chunks usan 117 palabras/chunk; NO sustituyen check_project.py.',
            'Las licencias de Wikipedia exigen atribución; revisar la versión exacta y las fuentes de cada página.',
        ],
    }
    write_csv(output / 'muestra_documental.csv', all_rows, FIELDS)
    write_csv(output / 'auditoria_filtrado.csv', all_rejected,
              ['language', 'title', 'reason', 'words'])
    write_csv(output / 'categorias_exploradas.csv', categories_report,
              ['language', 'category', 'topic', 'depth', 'members_seen', 'category_truncated'])
    write_csv(output / 'candidatos_crosslingual.csv', cross_candidates,
              ['document_id', 'language', 'query_language_to_try', 'title', 'wikidata_id', 'url', 'words', 'verification_status'])
    write_csv(output / 'colisiones_entidad.csv', collisions,
              ['wikidata_id', 'title', 'language', 'document_id'])
    (output / 'informe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    total = len(all_rows)
    rough_total = stats['rough_chunks_total_117_words']
    summary = [
        'PILOTO WIKIPEDIA CIENTÍFICA — BASES DE DATOS AVANZADAS',
        '=' * 63,
        'Fuente: Wikipedia ES/EN en vivo, MediaWiki Action API (NO Hugging Face Parquet)',
        f'Semilla: {args.seed} | categorías: {args.max_categories}/idioma (máximo) | profundidad: {args.depth}',
        f'Documentos válidos: {total} | mínimo palabras: {args.min_words}',
        f'Peticiones HTTP: {api.calls}',
        f'Chunks orientativos (~117 palabras/chunk): {rough_total} (NO oficial)',
    ]
    for lang in ('es', 'en'):
        doc_count = stats['documents_by_language'].get(lang, 0)
        word_count = stats['words_by_language'].get(lang, 0)
        chunk_count = stats['rough_chunks_by_language_117_words'].get(lang, 0)
        summary.append(f'{lang}: docs={doc_count}, palabras={word_count}, chunks≈{chunk_count}, '
                       f'proporción_chunks≈{100 * stats["rough_chunk_share"].get(lang, 0):.1f}%')
    summary.extend([
        'Temas: ' + ', '.join(f'{k}={v}' for k, v in report['accepted_by_language_topic'].items()),
        f'Candidatos cross-lingual PROVISIONALES: {len(cross_candidates)}',
        f'Entidades (Wikidata ID) presentes en ambos idiomas: {report["entity_collision_count"]}',
        'Rechazos: ' + (', '.join(f'{k}={v}' for k, v in reasons.most_common()) or 'ninguno'),
        '', 'IMPORTANTE: no afirmar todavía viabilidad de 25.000 chunks ni exclusividad cross-lingual.',
        'Revisar informe.json, muestra_documental.csv y candidatos_crosslingual.csv.',
    ])
    (output / 'resumen.txt').write_text('\n'.join(summary) + '\n', encoding='utf-8')
    print('\n' + '\n'.join(summary), flush=True)
    print(f'\nArchivos generados en: {output.resolve()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
