#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Corpus candidato reproducible de historia de la ciencia (Wikipedia ES/EN).

Fase discover: inventario de candidatos de categorías predefinidas y BFS acotado.
Fase build: selección estratificada y aleatoria dentro del inventario CONGELADO,
recuperación con caché, filtros, trazabilidad y muestra para check_project.py.

Ni el inventario acotado representa toda Wikipedia ni la ausencia de la versión
interlingüística de un artículo prueba por sí sola exclusividad cross-lingual.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from explorar_wikipedia_ciencia import (CATEGORIES, WikiAPI, WikimediaAccessBlocked,
                                         estimates, quality, write_csv, cross_language_candidates)

TOPICS = ('fisica', 'matematicas', 'quimica', 'astronomia')
LANGUAGES = ('es', 'en')
CORPUS_COLS = [
    'document_id', 'language', 'topic', 'title', 'wikidata_id', 'page_id',
    'revision_id', 'revision_timestamp', 'url', 'source_category',
    'source_categories', 'source_type', 'words', 'letters_ratio',
    'formula_line_ratio', 'license', 'retrieved_at_utc', 'text',
]
CANDIDATE_COLS = ['language', 'page_id', 'title', 'topic', 'source_category',
                  'source_categories', 'topic_candidates']
AUDIT_COLS = ['language', 'topic', 'page_id', 'title', 'reason', 'words']
ZERO_WIDTH = re.compile('[\u200b\u200c\u200d\ufeff\u2060]')
LABELS = {'es': 'español', 'en': 'inglés'}


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def json_file(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def integer_hash(value: str) -> int:
    return int(hashlib.sha256(value.encode('utf-8')).hexdigest()[:15], 16)


def clean_text(raw: str) -> str:
    from explorar_wikipedia_ciencia import normalize_text
    return normalize_text(ZERO_WIDTH.sub('', raw or ''))


def category_path(base: Path, lang: str, name: str, cap: int) -> Path:
    h = hashlib.sha256(f'{lang}|{cap}|{name}'.encode('utf-8')).hexdigest()[:24]
    return base / 'cache' / 'categories' / lang / f'{h}.json'


def category_members(api, out: Path, lang: str, category: str, cap: int):
    path = category_path(out, lang, category, cap)
    if path.exists():
        v = json_file(path)
        return v['members'], v['truncated'], True
    members, truncated = api.category_members(lang, category, cap)
    safe_write_json(path, {'category': category, 'language': lang, 'cap': cap,
                           'truncated': truncated, 'members': members, 'retrieved_at_utc': now()})
    return members, truncated, False


def discover(api, out: Path, args):
    """Marco acotado: categorías iniciales explícitas y BFS por estrato.

    Se DESCARTAN categorías truncadas para evitar su sesgo por orden alfabético.
    Cuando se alcanza el límite de categorías, se conserva el inventario
    completo sólo de las categorías efectivamente consultadas.
    """
    scans, warnings = [], []
    page_catalog = {}
    for lang in LANGUAGES:
        print(f'\n[{lang}] Descubriendo categorías de historia científica...', flush=True)
        frontier = {t: [(c, 0) for c in CATEGORIES[lang][t]] for t in TOPICS}
        seen = {t: set() for t in TOPICS}
        for level in range(args.depth + 1):
            nxt = {t: [] for t in TOPICS}
            for topic in TOPICS:
                current = sorted(set(frontier[topic]), key=lambda z:
                                 (integer_hash(f'{args.seed}|{lang}|{topic}|{z[0]}'), z[0]))
                for cat, lv in current:
                    if len(seen[topic]) >= args.max_categories_per_topic:
                        break
                    key = cat.casefold()
                    if key in seen[topic]:
                        continue
                    seen[topic].add(key)
                    members, truncated, cached = category_members(
                        api, out, lang, cat, args.members_per_category)
                    used = not truncated
                    scans.append({'language': lang, 'topic': topic, 'category': cat,
                                  'depth': lv, 'members_seen': len(members),
                                  'truncated': truncated, 'used_for_selection': used,
                                  'cached': cached})
                    if not members:
                        warnings.append(f'{lang}: categoría vacía/inexistente: {cat}')
                    if truncated:
                        warnings.append(f'{lang}: categoría truncada EXCLUIDA del marco: {cat}')
                        continue
                    for item in members:
                        title, pid, ns = item.get('title'), item.get('pageid'), item.get('ns')
                        if ns == 0 and title and isinstance(pid, int):
                            pk = (lang, pid)
                            if pk not in page_catalog:
                                page_catalog[pk] = {
                                    'language': lang, 'page_id': pid, 'title': title,
                                    '_origins': defaultdict(set),
                                }
                            page_catalog[pk]['_origins'][topic].add(cat)
                        elif ns == 14 and lv < args.depth and title:
                            nxt[topic].append((title, lv + 1))
                if len(seen[topic]) >= args.max_categories_per_topic and nxt[topic]:
                    warnings.append(f'{lang}:{topic}: alcanzado límite de categorías consultadas')
            frontier = nxt
        print(f'  Candidatos únicos del idioma: '
              f'{sum(1 for (lc, _) in page_catalog if lc == lang):,}', flush=True)

    # Asignación exclusiva, determinista y balanceada de temas en caso de
    # pertenecer a múltiples categorías/temas.
    counts = Counter()
    final = []
    for item in sorted(page_catalog.values(), key=lambda x: (x['language'], x['page_id'])):
        origin = item.pop('_origins')
        chosen = min(origin, key=lambda t: (counts[(item['language'], t)], TOPICS.index(t)))
        counts[(item['language'], chosen)] += 1
        item['topic'] = chosen
        item['source_category'] = sorted(origin[chosen])[0]
        item['source_categories'] = ' | '.join(sorted(origin[chosen]))
        item['topic_candidates'] = ' | '.join(t for t in TOPICS if t in origin)
        final.append(item)

    write_csv(out / 'inventario_descubierto.csv', final, CANDIDATE_COLS)
    write_csv(out / 'categorias_exploradas.csv', scans,
              ['language', 'topic', 'category', 'depth', 'members_seen', 'truncated',
               'used_for_selection', 'cached'])
    report = {
        'generated_at_utc': now(), 'stage': 'discover',
        'method': 'Categorías prefijadas + BFS acotado por tema + exclusión de categorías truncadas',
        'source': 'Wikipedia ES/EN, MediaWiki Action API, contenido vivo',
        'parameters': {'depth': args.depth, 'max_categories_per_topic': args.max_categories_per_topic,
                       'members_per_category': args.members_per_category, 'seed': args.seed},
        'candidate_counts': {f'{lang}:{t}': counts[(lang, t)] for lang in LANGUAGES for t in TOPICS},
        'total_unique_candidates': len(final), 'categories_scanned': len(scans),
        'api_calls_this_run': api.calls, 'warnings': warnings,
        'limitations': ['El marco descubierto NO es una muestra de toda Wikipedia.',
                        'Los topes en profundidad y categorías afectan a la cobertura.',
                        'La página puede cambiar tras el descubrimiento: se registrará revision_id.',
                        'La selección posterior se realizará exclusivamente dentro de este inventario guardado.'],
    }
    safe_write_json(out / 'informe_descubrimiento.json', report)
    lines = ['DESCUBRIMIENTO WIKIPEDIA CIENTÍFICA',
             f'Candidatos distintos: {len(final):,}', f'Categorías examinadas: {len(scans):,}']
    lines.extend(f'  {lang}:{t} = {counts[(lang,t)]:,}' for lang in LANGUAGES for t in TOPICS)
    lines += [f'Categorías truncadas, excluidas: {sum(s["truncated"] for s in scans)}',
              f'Advertencias: {len(warnings)}',
              'Este inventario se conserva para justificar la selección.']
    (out / 'resumen_descubrimiento.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines), flush=True)
    return report


def cached_page(api, out, candidate):
    lang = candidate['language']
    pid = int(candidate['page_id'])
    path = out / 'cache' / 'pages' / lang / f'{pid}.json'
    if path.exists():
        return json_file(path), True
    pages = api.pages(lang, [candidate['title']])
    if not pages:
        return {'_api_error': 'Sin página en respuesta API'}, False
    page = pages[0]
    # Errores transitorios no se guardan: se podrán reintentar otro día.
    if '_api_error' not in page:
        safe_write_json(path, page)
    return page, False


def row_from_page(candidate, page, min_words):
    lang = candidate['language']
    title = page.get('title') or candidate['title']
    if '_api_error' in page:
        return None, 'error_api', 0
    if page.get('missing') or page.get('ns') != 0:
        return None, 'pagina_inexistente_o_no_principal', 0
    if 'disambiguation' in page.get('pageprops', {}):
        return None, 'desambiguacion', 0
    pid = page.get('pageid')
    if not isinstance(pid, int) or pid != int(candidate['page_id']):
        return None, 'id_de_pagina_inconsistente', 0
    txt = clean_text(page.get('extract', ''))
    reason, stats = quality(txt, title, min_words)
    if reason != 'ok':
        return None, reason, stats['words']
    rev = (page.get('revisions') or [{}])[0]
    url = page.get('fullurl') or f'https://{lang}.wikipedia.org/wiki/{quote(title.replace(" ", "_"), safe="()")}'
    row = {
        'document_id': f'wiki:{lang}:{pid}', 'language': lang, 'topic': candidate['topic'],
        'title': title, 'wikidata_id': page.get('pageprops', {}).get('wikibase_item', ''),
        'page_id': pid, 'revision_id': rev.get('revid', ''),
        'revision_timestamp': rev.get('timestamp', ''), 'url': url,
        'source_category': candidate['source_category'],
        'source_categories': candidate['source_categories'],
        'source_type': 'Wikipedia; MediaWiki Action API',
        'words': stats['words'], 'letters_ratio': stats['letters_ratio'],
        'formula_line_ratio': stats['formula_line_ratio'],
        'license': 'Wikipedia: consultar licencia, historial y atribución de la revisión fuente',
        'retrieved_at_utc': now(), 'text': txt,
    }
    return row, 'ok', stats['words']


def proportional_sample(rows, n, seed):
    """Muestra aleatoria estratificada proporcional a los DOCUMENTOS finales."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row['language'], row['topic'])].append(row)
    n = min(n, len(rows))
    if n <= 0:
        return []
    exact = {key: n * len(items) / len(rows) for key, items in groups.items()}
    counts = {key: int(v) for key, v in exact.items()}
    for key in sorted(groups, key=lambda k: (-(exact[k] - counts[k]), k))[:n - sum(counts.values())]:
        counts[key] += 1
    chosen = []
    for key in sorted(groups):
        sample_from = sorted(groups[key], key=lambda r: r['document_id'])
        rng = random.Random(seed ^ integer_hash('sample:' + ':'.join(key)))
        chosen.extend(rng.sample(sample_from, counts[key]))
    return sorted(chosen, key=lambda r: r['document_id'])


def build(api, out, args):
    inventory = out / 'inventario_descubierto.csv'
    if not inventory.exists():
        raise SystemExit(f'No existe {inventory}. Primero ejecutar --phase discover.')
    with inventory.open(encoding='utf-8-sig', newline='') as handle:
        candidates = list(csv.DictReader(handle))
    if not candidates:
        raise SystemExit('El inventario está vacío.')
    # Cuotas independientes por idioma; compatibilidad con --per-language original.
    target_by_lang = {
        'es': args.target_es if getattr(args, 'target_es', None) is not None else args.per_language,
        'en': args.target_en if getattr(args, 'target_en', None) is not None else args.per_language,
    }
    # Objetivo equitativo por área; el déficit de un área se puede compensar
    # con las otras del MISMO idioma en una segunda pasada, registrado en informe.
    per_topic = {}
    for lang in LANGUAGES:
        for i, topic in enumerate(TOPICS):
            per_topic[(lang, topic)] = (target_by_lang[lang] // len(TOPICS)
                                        + (i < target_by_lang[lang] % len(TOPICS)))
    groups = defaultdict(list)
    for cand in candidates:
        groups[(cand['language'], cand['topic'])].append(cand)
    for key, pool in groups.items():
        pool.sort(key=lambda x: int(x['page_id']))
        random.Random(args.seed ^ integer_hash('pool:' + ':'.join(key))).shuffle(pool)

    selected = []
    rejections = []
    used_qids = set()
    used_texts = set()
    counts = Counter()
    processed = set()
    counts_request = Counter()
    fetched_online = 0
    max_fetch = args.max_fetch_per_run
    halted = False

    def consider(cand):
        nonlocal fetched_online, halted
        if max_fetch and fetched_online >= max_fetch:
            halted = True
            return
        key = (cand['language'], int(cand['page_id']))
        if key in processed:
            return
        processed.add(key)
        page, hit = cached_page(api, out, cand)
        if not hit:
            fetched_online += 1
        row, reason, words = row_from_page(cand, page, args.min_words)
        counts_request['cached' if hit else 'online'] += 1
        if row:
            qid = row['wikidata_id']
            digest = hashlib.sha256(row['text'].casefold().encode('utf-8')).hexdigest()
            if qid and qid in used_qids:
                reason = 'entidad_wikidata_duplicada'
            elif digest in used_texts:
                reason = 'texto_exactamente_duplicado'
            else:
                used_texts.add(digest)
                if qid:
                    used_qids.add(qid)
                selected.append(row)
                counts[(row['language'], row['topic'])] += 1
                return
        rejections.append({'language': cand['language'], 'topic': cand['topic'],
                           'page_id': cand['page_id'], 'title': cand['title'],
                           'reason': reason, 'words': words})

    # Primera pasada: cuotas por tema. El orden de exploración es una
    # permutación sembrada del inventario *antes* de ver calidad/longitud.
    for lang in LANGUAGES:
        for topic in TOPICS:
            key = (lang, topic)
            for cand in groups[key]:
                if halted or counts[key] >= per_topic[key]:
                    break
                consider(cand)
            print(f'[{lang}:{topic}] objetivo={per_topic[key]} '
                  f'seleccionados={counts[key]} candidatos={len(groups[key])}', flush=True)
            if halted:
                break
        if halted:
            break

    # Segunda pasada: si alguna materia no alcanza su cuota, completar
    # con candidatos restantes de otras materias del mismo idioma.
    if not halted:
        for lang in LANGUAGES:
            deficit = target_by_lang[lang] - sum(counts[(lang, t)] for t in TOPICS)
            if deficit <= 0:
                continue
            fallback = [cand for t in TOPICS for cand in groups[(lang, t)]
                        if (lang, int(cand['page_id'])) not in processed]
            fallback.sort(key=lambda c: integer_hash(f'{args.seed}|fallback|{lang}|{c["page_id"]}'))
            for cand in fallback:
                if halted or deficit <= 0:
                    break
                size_before = len(selected)
                consider(cand)
                if len(selected) > size_before:
                    deficit -= 1

    selected.sort(key=lambda r: (r['language'], int(r['page_id'])))
    sample = proportional_sample(selected, args.sample_size, args.seed)
    with (out / 'corpus_candidato.jsonl').open('w', encoding='utf-8') as f:
        for row in selected:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    write_csv(out / 'inventario_corpus.csv', selected,
              [c for c in CORPUS_COLS if c != 'text'])
    write_csv(out / 'auditoria_filtrado.csv', rejections, AUDIT_COLS)
    write_csv(out / 'muestra_check_project.csv', sample,
              ['document_id', 'language', 'text', 'title', 'topic', 'url'])
    write_csv(out / 'trazabilidad_muestra.csv', sample,
              [c for c in CORPUS_COLS if c != 'text'])
    cross, collision = cross_language_candidates(selected)
    write_csv(out / 'candidatos_crosslingual.csv', cross,
              ['document_id', 'language', 'query_language_to_try', 'title',
               'wikidata_id', 'url', 'words', 'verification_status'])
    write_csv(out / 'colisiones_entidad.csv', collision,
              ['wikidata_id', 'title', 'language', 'document_id'])
    stats = estimates(selected)
    doc_counts = Counter(r['language'] for r in selected)
    reason_counts = Counter(r['reason'] for r in rejections)
    target_achieved = all(doc_counts[lang] >= target_by_lang[lang] for lang in LANGUAGES)
    warnings = []
    if not target_achieved:
        warnings.append('Objetivo de documentos NO alcanzado: ampliar marco, revisar filtros o cuotas.')
    if halted:
        warnings.append('Ejecución parcial limitada por --max-fetch-per-run; reiniciar para continuar.')
    if stats['rough_chunks_total_117_words'] < 25000:
        warnings.append('Menos de 25000 chunks orientativos; NO cumple aún el mínimo estimado.')
    for lang in LANGUAGES:
        if stats['rough_chunk_share'].get(lang, 0) < .20:
            warnings.append(f'{lang}: proporción orientativa de chunks inferior al 20%.')
    warnings += [
        'No se ha verificado exclusividad cross-lingual ni retrieval; candidatos NO son preguntas validadas.',
        'Estimación basada en palabras/117, NO sustituye al recuento del tokenizer con check_project.py.',
        'Wikipedia requiere atribución y revisión de licencia de cada página y su historial.',
        'El inventario depende de categorías seleccionadas y tiene sesgo; NO extrapolar a toda Wikipedia.',
        'La versión de los artículos queda identificada por revision_id y revision_timestamp.',
    ]
    report = {
        'generated_at_utc': now(), 'stage': 'build', 'status': 'COMPLETO' if target_achieved else 'PARCIAL',
        'source': 'Wikipedia actual (MediaWiki Action API)',
        'selection': 'Muestreo estratificado ES/EN x 4 temas, semilla fija; respaldo dentro de idioma',
        'parameters': {'per_language': args.per_language, 'target_by_language': target_by_lang,
                       'sample_size': args.sample_size,
                       'min_words': args.min_words, 'seed': args.seed,
                       'max_fetch_per_run': max_fetch},
        'candidate_counts': {f'{lang}:{t}': len(groups[(lang,t)])
                             for lang in LANGUAGES for t in TOPICS},
        'quota_by_stratum': {f'{lang}:{t}': per_topic[(lang,t)]
                            for lang in LANGUAGES for t in TOPICS},
        'selected_by_stratum': {f'{lang}:{t}': counts[(lang,t)]
                                for lang in LANGUAGES for t in TOPICS},
        'documents_selected': len(selected), 'sample_documents': len(sample),
        'filter_rejection_counts': dict(reason_counts),
        'page_reads_this_run': dict(counts_request),
        'api_calls_this_run': api.calls,
        'estimates': stats, 'target_achieved': target_achieved,
        'cross_language_candidate_count': len(cross),
        'qid_collisions_removed': reason_counts.get('entidad_wikidata_duplicada', 0),
        'warnings': warnings,
    }
    safe_write_json(out / 'informe_corpus.json', report)
    lines = ['CORPUS CANDIDATO WIKIPEDIA CIENTÍFICA — BDA',
             '=' * 55, f'Estado: {report["status"]}',
             f'Documentos: {len(selected):,} de {sum(target_by_lang.values()):,} previstos',
             f'Muestra check_project: {len(sample)}',
             f'Chunks orientativos (117 palabras/chunk): {stats["rough_chunks_total_117_words"]:,} (NO oficial)',
             f'Solicitudes a API en esta ejecución: {api.calls}',
             f'Rechazos: {dict(reason_counts)}']
    lines.extend(f'{lang}: docs={doc_counts[lang]:,}, palabras={stats["words_by_language"].get(lang, 0):,}, '
                 f'chunks≈{stats["rough_chunks_by_language_117_words"].get(lang,0):,}, '
                 f'cuota≈{100*stats["rough_chunk_share"].get(lang,0):.1f}%'
                 for lang in LANGUAGES)
    lines.append('Por temas: ' + ', '.join(f'{lang}:{t}={counts[(lang,t)]}'
                                         for lang in LANGUAGES for t in TOPICS))
    lines.extend(['ADVERTENCIAS:'] + ['  - ' + s for s in warnings])
    (out / 'resumen_corpus.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n' + '\n'.join(lines), flush=True)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase', choices=['discover', 'build', 'all'], default='discover')
    p.add_argument('--out', default='data/corpus_wikipedia_ciencia')
    p.add_argument('--per-language', type=int, default=1400,
                   help='Objetivo de documentos válidos por idioma; defecto 1400')
    p.add_argument('--target-es', type=int, default=None,
                   help='Objetivo de documentos en español (sobrescribe --per-language para es)')
    p.add_argument('--target-en', type=int, default=None,
                   help='Objetivo de documentos en inglés (sobrescribe --per-language para en)')
    p.add_argument('--sample-size', type=int, default=300)
    p.add_argument('--depth', type=int, choices=[0,1,2], default=2)
    p.add_argument('--max-categories-per-topic', type=int, default=45)
    p.add_argument('--members-per-category', type=int, default=3000)
    p.add_argument('--min-words', type=int, default=250)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--delay', type=float, default=0.4)
    p.add_argument('--timeout', type=float, default=35)
    p.add_argument('--max-fetch-per-run', type=int, default=0,
                   help='Máximo de páginas nuevas por ejecución; 0=sin límite. Reanuda por caché.')
    p.add_argument('--contact', default='https://github.com/Mig501/Trabajo-BDA',
                   help='URL o email de contacto para Wikimedia User-Agent')
    args = p.parse_args(argv)
    if min(args.per_language, args.sample_size, args.max_categories_per_topic,
           args.members_per_category, args.min_words) < 1:
        p.error('Los objetivos, límites de categorías, muestra y min-words deben ser positivos.')
    if (args.target_es is not None and args.target_es < 1) or (args.target_en is not None and args.target_en < 1):
        p.error('--target-es y --target-en deben ser positivos.')
    if args.delay < 0 or args.max_fetch_per_run < 0:
        p.error('--delay y --max-fetch-per-run deben ser >= 0.')
    if not args.contact.strip():
        p.error('Se requiere un contacto en User-Agent.')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    api = WikiAPI(args.contact, args.delay, args.timeout)
    try:
        if args.phase in ('discover', 'all'):
            discover(api, out, args)
        if args.phase in ('build', 'all'):
            build(api, out, args)
    except WikimediaAccessBlocked as exc:
        print(f'AVISO: Wikipedia ha limitado o bloqueado el acceso: {exc}')
        print('Se ha conservado la caché; no repetir inmediatamente si hay HTTP 429.')
        return 2
    print(f'\nArchivos guardados en: {out.resolve()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
