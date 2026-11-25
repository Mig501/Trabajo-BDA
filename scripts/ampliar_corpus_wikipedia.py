#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ampliación INCREMENTAL del corpus científico BDA.

Conserva literalmente cada documento del corpus original (incluidos texto,
revisión, idioma y QID), añade documentos del inventario congelado y genera
una salida nueva. No modifica la selección original ni el inventario.

Fases:
  plan    Revisión local de cobertura (sin peticiones de red).
  extend  Descarga, filtra, conserva los anteriores y añade documentos.
  count   Cuenta chunks REALES con tokenizer E5 del corpus ampliado.

Se necesita junto a preparar_corpus_wikipedia.py y explorar_wikipedia_ciencia.py.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from explorar_wikipedia_ciencia import WikiAPI, WikimediaAccessBlocked, write_csv
from preparar_corpus_wikipedia import (
    TOPICS, LANGUAGES, CORPUS_COLS, CANDIDATE_COLS, AUDIT_COLS,
    row_from_page, integer_hash, proportional_sample,
)

BASE_SHA_KNOWN = '12a4486e2ba6fde7c9548751306fceb4870794c6fda36276880144cf45f99304'
RESULT_COLS = AUDIT_COLS + ['source', 'retrieval']


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def atomic_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def read_jsonl(path: Path):
    with path.open(encoding='utf-8-sig') as f:
        for line_no, line in enumerate(f, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f'JSONL inválido en {path}:{line_no}: {e}') from e


def read_csv(path: Path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_jsonl_atomic(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as f:
        for d in rows:
            f.write(json.dumps(d, ensure_ascii=False) + '\n')
    temp.replace(path)


def key_of(row):
    return (str(row['language']), int(row['page_id']))


def base_and_inventory(args):
    base = Path(args.base)
    source = base / 'corpus_candidato.jsonl'
    inventory_path = base / 'inventario_descubierto.csv'
    if not source.is_file() or not inventory_path.is_file():
        raise SystemExit('No están corpus_candidato.jsonl e inventario_descubierto.csv en --base. '
                         'Usa la carpeta de la construcción ORIGINAL de Wikipedia.')
    source_sha = hash_file(source)
    if args.expected_base_sha and source_sha != args.expected_base_sha:
        raise SystemExit(f'El corpus original ha cambiado; se esperaba {args.expected_base_sha} '
                         f'y se obtuvo {source_sha}. No lo sobrescribas: revisa el origen.')
    original = list(read_jsonl(source))
    if len(original) != 3600 and args.expected_base_sha == BASE_SHA_KNOWN:
        raise SystemExit(f'Se esperaban 3600 documentos originales, hay {len(original)}.')
    inventory = read_csv(inventory_path)
    if not inventory:
        raise SystemExit('Inventario original vacío.')
    doc_ids = [r['document_id'] for r in original]
    if len(set(doc_ids)) != len(doc_ids):
        raise SystemExit('El corpus original contiene IDs duplicados.')
    return original, inventory, source_sha, hash_file(inventory_path)



def _validate_inventory_rows(rows, source):
    unique = {}
    for row in rows:
        if row.get('language') not in LANGUAGES or row.get('topic') not in TOPICS:
            raise SystemExit(f'Inventario inválido ({source}): idioma/tema desconocido: {row}')
        if not row.get('title') or not row.get('source_category'):
            raise SystemExit(f'Inventario inválido ({source}): falta título o categoría: {row}')
        try:
            key = key_of(row)
        except (ValueError, TypeError, KeyError) as exc:
            raise SystemExit(f'Inventario inválido ({source}): page_id no válido: {row}') from exc
        if key in unique and unique[key] != row:
            raise SystemExit(f'Inventario ({source}) con dos entradas contradictorias para {key}')
        unique[key] = row
    return unique


def combine_inventory(args, original_inventory):
    """Amplía el marco de selección de forma acumulativa y sin reescribir el original.

    Se preservan literalmente las fichas del primer inventario y las añadidas en
    sesiones anteriores. Las futuras exploraciones solo pueden AÑADIR candidatos.
    El inventario acumulado se guarda de forma atómica junto al corpus extendido.
    """
    out = Path(args.out)
    snapshot = out / 'inventario_extendido_congelado.csv'
    original_map = _validate_inventory_rows(original_inventory, 'original')
    accumulated = dict(original_map)
    if snapshot.exists():
        previous = _validate_inventory_rows(read_csv(snapshot), str(snapshot))
        for key, row in original_map.items():
            if previous.get(key) != row:
                raise SystemExit('El inventario extendido no conserva intacto el inventario original. '
                                 'No se sobrescribirá; revisa el archivo.')
        accumulated.update(previous)

    added = 0
    if args.extra_inventory:
        extra_path = Path(args.extra_inventory)
        if not extra_path.is_file():
            raise SystemExit(f'No existe el inventario adicional: {extra_path}')
        extra = _validate_inventory_rows(read_csv(extra_path), str(extra_path))
        for key, row in extra.items():
            # Si cambian título/tema/categoría de un candidato previo,
            # prevalece SIEMPRE la ficha original congelada.
            if key not in accumulated:
                accumulated[key] = row
                added += 1
        if added or not snapshot.exists():
            out.mkdir(parents=True, exist_ok=True)
            temp = snapshot.with_suffix('.tmp')
            with temp.open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=CANDIDATE_COLS, extrasaction='ignore')
                writer.writeheader()
                for row in sorted(accumulated.values(), key=lambda r: key_of(r)):
                    writer.writerow(row)
            temp.replace(snapshot)
        print(f'Inventario ampliado: {len(original_map):,} candidatos originales + '
              f'{len(accumulated)-len(original_map):,} adicionales '
              f'({added:,} nuevos en esta importación).', flush=True)
    elif snapshot.exists():
        print(f'Reutilizando inventario extendido congelado: {len(accumulated):,} candidatos.', flush=True)
    else:
        print(f'Usando inventario original: {len(accumulated):,} candidatos.', flush=True)
    return list(accumulated.values())


def plan_info(rows, inventory, args):
    present = {key_of(r) for r in rows}
    available = Counter()
    for r in inventory:
        key = key_of(r)
        if key not in present:
            available[(r['language'], r['topic'])] += 1
    counts = Counter(r['language'] for r in rows)
    by_topic = Counter((r['language'], r['topic']) for r in rows)
    targets = {'es': args.target_es, 'en': args.target_en}
    print('PLAN DE AMPLIACIÓN INCREMENTAL — SIN DESCARGAS', flush=True)
    print(f'Actual: ES={counts["es"]}, EN={counts["en"]}; total={len(rows)}', flush=True)
    print(f'Objetivo: ES={args.target_es}, EN={args.target_en}; total={sum(targets.values())}', flush=True)
    for lang in LANGUAGES:
        need = max(0, targets[lang] - counts[lang])
        inventory_left = sum(available[(lang, t)] for t in TOPICS)
        print(f'{lang}: faltan {need} artículos válidos; '
              f'candidatos nuevos en inventario={inventory_left} (sin filtrar)', flush=True)
        if inventory_left < need:
            print(f'  AVISO: inventario {lang} insuficiente incluso antes de filtrar.', flush=True)
        for topic in TOPICS:
            print(f'  {lang}:{topic}: ya hay {by_topic[(lang,topic)]}; '
                  f'candidatos pendientes={available[(lang,topic)]}', flush=True)
    approx = round(targets['es'] * (10446/1400) + targets['en'] * (18194/2200))
    print(f'Proyección orientativa con medias anteriores: ~{approx:,} chunks; '
          'el recuento real se hará con --phase count.', flush=True)
    return counts, available


def validate_params(args, orig_sha, inventory_sha, out):
    manifest = out / 'manifest_ampliacion.json'
    signature = {
        'base_sha256': orig_sha,
        'inventory_sha256': inventory_sha,
        'seed': args.seed,
        'min_words': args.min_words,
        'target_es': args.target_es,
        'target_en': args.target_en,
    }
    if manifest.exists():
        old = read_json(manifest)
        diffs = [k for k, value in signature.items() if old.get(k) != value]
        if diffs:
            raise SystemExit(f'Parámetros/inventario cambiados respecto a la anterior ejecución '
                             f'({", ".join(diffs)}). Usa otra carpeta --out para comparar.')
    else:
        atomic_json(manifest, signature)


def request_by_pageid(api: WikiAPI, lang: str, pid: int):
    """Descarga por ID, no por título, para evitar redirecciones con otro page_id."""
    params = {
        'prop': 'extracts|pageprops|revisions|info',
        'pageids': str(pid), 'explaintext': 1,
        'exsectionformat': 'plain', 'exlimit': 1,
        'ppprop': 'wikibase_item|disambiguation',
        'rvprop': 'ids|timestamp', 'rvlimit': 1,
        'inprop': 'url', 'maxlag': 5,
    }
    for retry in range(3):
        try:
            data = api.get(lang, params)
            pages = data.get('query', {}).get('pages', [])
            if pages:
                page = pages[0]
                if page.get('pageid') not in (None, pid):
                    return {'_api_error': 'ID de página devuelto distinto del consultado'}
                return page
            return {'_api_error': 'Sin página en respuesta API'}
        except RuntimeError as exc:
            if 'maxlag' in str(exc).lower() and retry < 2:
                print('  Wikipedia con retraso de réplicas; pausa de 5 s...', flush=True)
                time.sleep(5)
                continue
            raise
    return {'_api_error': 'Sin respuesta tras reintentos'}


def obtain_page(api, base: Path, candidate, cache_dir: Path, args):
    lang, pid = key_of(candidate)
    # Primero reutilizar la caché de IDs estables de esta ampliación.
    stable = cache_dir / 'pages_by_id' / lang / f'{pid}.json'
    if stable.exists():
        page = read_json(stable)
        if page.get('pageid') == pid:
            return page, 'cache_nueva', False
    # La caché antigua se creó por título y puede apuntar a un redirect de otro ID.
    legacy = base / 'cache' / 'pages' / lang / f'{pid}.json'
    if legacy.exists():
        page = read_json(legacy)
        if page.get('pageid') == pid and '_api_error' not in page:
            return page, 'cache_original', False
    page = request_by_pageid(api, lang, pid)
    if '_api_error' not in page and page.get('pageid') == pid:
        atomic_json(stable, page)
    return page, 'online', True


def build(args):
    original, inventory, orig_sha, inv_sha = base_and_inventory(args)
    if args.target_es < sum(r['language']=='es' for r in original) or args.target_en < sum(r['language']=='en' for r in original):
        raise SystemExit('El objetivo no puede ser inferior al número de documentos originales: no eliminamos documentos.')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    validate_params(args, orig_sha, inv_sha, out)
    inventory = combine_inventory(args, inventory)
    counts, _ = plan_info(original, inventory, args)
    # Reanudación fiable: conservar también los registros NUEVOS ya aceptados,
    # incluyendo sus timestamps y revisiones, sin regenerarlos desde la API.
    previous = out / 'corpus_ampliado.jsonl'
    if previous.exists():
        selected = list(read_jsonl(previous))
        indexed = {r['document_id']: r for r in selected}
        if len(indexed) != len(selected) or any(indexed.get(r['document_id']) != r for r in original):
            raise SystemExit('La salida parcial no conserva exactamente el corpus base; '
                             'no se continuará para evitar pérdida de evidencias.')
        print(f'Reanudando: {len(selected)} documentos conservados de una ejecución anterior.', flush=True)
    else:
        selected = list(original)  # Los originales jamás se reescriben ni reconvierten.
    used_page = {key_of(r) for r in selected}
    used_id = {r['document_id'] for r in selected}
    used_qids = {r['wikidata_id'] for r in selected if r.get('wikidata_id')}
    used_texts = {hashlib.sha256(r['text'].casefold().encode('utf-8')).hexdigest() for r in selected}
    counts = Counter(r['language'] for r in selected)
    strata = Counter((r['language'], r['topic']) for r in selected)
    audit_path = out / 'auditoria_nuevos.csv'
    audit = read_csv(audit_path) if audit_path.exists() else []
    online = 0
    reads = Counter()
    stopped = False
    targets = {'es': args.target_es, 'en': args.target_en}
    pool = defaultdict(list)
    for r in inventory:
        if key_of(r) not in used_page:
            pool[(r['language'], r['topic'])].append(r)
    for k, group in pool.items():
        group.sort(key=lambda x: int(x['page_id']))
        random.Random(args.seed ^ integer_hash('pool:' + ':'.join(k))).shuffle(group)
    # Rechazos de calidad son estables y no deben reaparecer; errores de API
    # transitorios sí se intentarán de nuevo.
    examined = set(used_page)
    examined.update((r['language'], int(r['page_id'])) for r in audit
                    if r.get('reason') not in {'error_api'})

    def add(cand):
        nonlocal online, stopped
        lang, pid = key_of(cand)
        if (lang, pid) in examined:
            return False
        if args.max_new_fetches and online >= args.max_new_fetches:
            # No cortamos ante caché? Por simplicidad detener antes de otra petición.
            # La siguiente ejecución reutiliza todas las páginas descargadas.
            stopped = True
            return False
        examined.add((lang, pid))
        page, src, fetched = obtain_page(api, Path(args.base), cand, out / 'cache', args)
        reads[src] += 1
        if fetched:
            online += 1
        row, reason, words = row_from_page(cand, page, args.min_words)
        if row is not None:
            qid = row.get('wikidata_id')
            digest = hashlib.sha256(row['text'].casefold().encode('utf-8')).hexdigest()
            if row['document_id'] in used_id:
                reason = 'document_id_duplicado'
            elif qid and qid in used_qids:
                reason = 'entidad_wikidata_duplicada'
            elif digest in used_texts:
                reason = 'texto_exactamente_duplicado'
            else:
                selected.append(row)
                used_page.add((lang, pid))
                used_id.add(row['document_id'])
                if qid:
                    used_qids.add(qid)
                used_texts.add(digest)
                counts[lang] += 1
                strata[(lang, row['topic'])] += 1
                if sum(counts.values()) % 100 == 0:
                    print(f'  Aceptados acumulados: {sum(counts.values())} '
                          f'(ES={counts["es"]}, EN={counts["en"]}); '
                          f'nuevas peticiones={online}', flush=True)
                return True
        audit.append({'language':lang,'topic':cand['topic'],'page_id':pid,
                      'title':cand['title'],'reason':reason,'words':words,
                      'source':cand.get('source_category',''),'retrieval':src})
        return False

    api = WikiAPI(args.contact, args.delay, args.timeout)
    try:
        # Intentamos equilibrar el total de cada materia por idioma.
        for lang in LANGUAGES:
            for idx, topic in enumerate(TOPICS):
                goal = targets[lang] // len(TOPICS) + (idx < targets[lang] % len(TOPICS))
                for candidate in pool[(lang, topic)]:
                    if stopped or strata[(lang,topic)] >= goal:
                        break
                    add(candidate)
                print(f'[{lang}:{topic}] seleccionados={strata[(lang,topic)]} '
                      f'cuota={goal} disponibles={len(pool[(lang,topic)])}', flush=True)
                if stopped:
                    break
            if stopped:
                break
        # Compensar cualquier déficit de materia dentro del MISMO idioma.
        if not stopped:
            for lang in LANGUAGES:
                if counts[lang] >= targets[lang]:
                    continue
                remaining = [r for t in TOPICS for r in pool[(lang,t)]
                             if key_of(r) not in examined]
                remaining.sort(key=lambda r: integer_hash(f'{args.seed}|fallback|{lang}|{r["page_id"]}'))
                for candidate in remaining:
                    if stopped or counts[lang] >= targets[lang]:
                        break
                    add(candidate)
    except (WikimediaAccessBlocked, RuntimeError) as exc:
        stopped = True
        print(f'AVISO de acceso a Wikimedia: {exc}. Caché conservada. '
              'No reintentar inmediatamente ante HTTP 429.', flush=True)

    selected.sort(key=lambda x: (x['language'], int(x['page_id'])))
    sample = proportional_sample(selected, args.sample_size, args.seed)
    out_jsonl = out / 'corpus_ampliado.jsonl'
    write_jsonl_atomic(out_jsonl, selected)
    write_csv(out / 'muestra_check_project.csv', sample,
              ['document_id','language','text','title','topic','url'])
    write_csv(out / 'inventario_corpus.csv', selected,
              [c for c in CORPUS_COLS if c != 'text'])
    original_ids = {d['document_id'] for d in original}
    new_rows = [r for r in selected if r['document_id'] not in original_ids]
    write_csv(out / 'nuevos_documentos.csv', new_rows,
              [c for c in CORPUS_COLS if c != 'text'])
    write_csv(out / 'auditoria_nuevos.csv', audit, RESULT_COLS)
    # Integridad: todo documento original está en salida, con exactamente el mismo contenido.
    result_by_id = {r['document_id']: r for r in selected}
    assert all(result_by_id[r['document_id']] == r for r in original)
    assert len(result_by_id) == len(selected)
    all_reached = all(counts[lang] >= targets[lang] for lang in LANGUAGES)
    report = {
        'stage':'extend','status':'COMPLETO' if all_reached else 'PARCIAL',
        'timestamp_utc':datetime.now(timezone.utc).isoformat(),
        'base_sha256':orig_sha,'inventory_sha256':inv_sha,
        'baseline_documents':len(original),'baseline_documents_preserved':len(original),
        'new_documents':len(new_rows),'total_documents':len(selected),
        'target':targets, 'by_language':dict(counts),
        'by_stratum':{f'{lang}:{t}':strata[(lang,t)] for lang in LANGUAGES for t in TOPICS},
        'api_calls_this_run':api.calls,'new_online_reads':online,
        'page_reads':dict(reads),'new_rejections':dict(Counter(x['reason'] for x in audit)),
        'inventory_candidates':len(inventory),
        'unexamined_candidates':sum(1 for r in inventory if key_of(r) not in examined),
        'stopped_by_request_limit_or_api':stopped,
        'output_sha256':hash_file(out_jsonl),
        'warnings':['El recuento exacto de chunks requiere --phase count.',
                    'La exclusividad de las preguntas cross-lingual debe revalidarse tras ampliar el corpus.',
                    'El marco sigue limitado al inventario de categorías que ya se había definido.',
                    'Los metadatos históricos se enriquecerán y auditarán por separado.'],
    }
    atomic_json(out / 'informe_ampliacion.json', report)
    lines = [
        'AMPLIACIÓN INCREMENTAL — WIKIPEDIA CIENTÍFICA',
        f'Estado: {report["status"]}',
        f'Originales conservados sin modificaciones: {len(original):,}',
        f'Nuevos artículos: {len(new_rows):,}',
        f'Total: {len(selected):,} | objetivo: {sum(targets.values()):,}',
        f'Español: {counts["es"]:,}/{targets["es"]:,}',
        f'Inglés: {counts["en"]:,}/{targets["en"]:,}',
        f'Peticiones nuevas esta ejecución: {online:,}',
        f'Ruta corpus: {out_jsonl}',
        'Siguiente: python scripts/ampliar_corpus_wikipedia.py --phase count --out '+str(out),
        'AVISO: sigue pendiente la auditoría de respuestas cross-lingual en el corpus ampliado.',
    ]
    if not all_reached and not stopped and report['unexamined_candidates'] == 0:
        lines.append('INVENTARIO AGOTADO: para continuar, ejecutar un nuevo discover en '
                     'una carpeta SEPARADA y pasar su CSV con --extra-inventory.')
    (out / 'resumen_ampliacion.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'+'\n'.join(lines),flush=True)
    return 0 if all_reached else 1


def count(args):
    out = Path(args.out)
    src = out / 'corpus_ampliado.jsonl'
    if not src.exists():
        raise SystemExit(f'No existe {src}. Ejecuta --phase extend.')
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        raise SystemExit(f'No se puede importar sentence-transformers: {e}') from e
    model = SentenceTransformer(args.model, trust_remote_code=False)
    tok = model.tokenizer
    overhead = len(tok('passage: ')['input_ids'])
    usable = 256 - overhead
    if usable < 1:
        raise ValueError('No hay tokens útiles para el texto')
    by_lang = Counter()
    rows=[]
    for i,d in enumerate(read_jsonl(src),1):
        ids = tok(d['text'], add_special_tokens=False, verbose=False)['input_ids']
        n_chunks=max(1, math.ceil(len(ids)/usable))
        by_lang[d['language']] += n_chunks
        rows.append({'document_id':d['document_id'],'language':d['language'],
                     'topic':d['topic'],'tokens':len(ids),'chunks':n_chunks})
        if i % 500 == 0:
            print(f'  Tokenizados {i:,} documentos...',flush=True)
    n=sum(by_lang.values())
    total_by_lang=Counter(d['language'] for d in rows)
    summary={'source_sha256':hash_file(src),'model':args.model,
             'documents':len(rows),'documents_by_language':dict(total_by_lang),
             'chunk_tokens':256,'passage_prefix':'passage: ',
             'usable_text_tokens':usable,'chunks_total':n,
             'chunks_by_language':dict(by_lang),
             'chunks_share_by_language':{l:round(by_lang[l]/n,5) for l in LANGUAGES},
             'recommended_50000_reached':n>=50000,
             'required_25000_reached':n>=25000,
             'languages_20pct_reached':all(by_lang[l]/n>=.20 for l in LANGUAGES)}
    atomic_json(out/'informe_chunks_reales.json',summary)
    write_csv(out/'chunks_por_documento.csv',rows,
              ['document_id','language','topic','tokens','chunks'])
    print(f'RECUENTO REAL (E5, {usable} tokens útiles): {n:,} chunks',flush=True)
    for lang in LANGUAGES:
        print(f'{lang}: {by_lang[lang]:,} chunks, {100*by_lang[lang]/n:.2f} %',flush=True)
    print('Objetivo recomendado 50.000: '+('ALCANZADO' if n>=50000 else 'AÚN NO'),flush=True)
    return 0 if n>=50000 and summary['languages_20pct_reached'] else 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase', choices=('plan','extend','count'), default='plan')
    p.add_argument('--base', default='data/corpus_wikipedia_ciencia',
                   help='Directorio ORIGINAL con corpus_candidato.jsonl, inventario y caché')
    p.add_argument('--out', default='data/corpus_wikipedia_ciencia/ampliacion_50k')
    p.add_argument('--extra-inventory', default='',
                   help='CSV de un NUEVO discover hecho en otra carpeta. Se combina '
                        'sin tocar el inventario original ni los artículos aceptados.')
    p.add_argument('--target-es', type=int, default=1800)
    p.add_argument('--target-en', type=int, default=4800)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--min-words', type=int, default=250)
    p.add_argument('--sample-size', type=int, default=300)
    p.add_argument('--max-new-fetches', type=int, default=0,
                   help='Número máximo de peticiones nuevas por ejecución; 0 sin límite')
    p.add_argument('--delay', type=float, default=0.5)
    p.add_argument('--timeout', type=float, default=35)
    p.add_argument('--contact', default='https://github.com/Mig501/Trabajo-BDA')
    p.add_argument('--model', default='intfloat/multilingual-e5-base')
    p.add_argument('--expected-base-sha', default=BASE_SHA_KNOWN,
                   help='SHA-256 de los 3600 documentos auditados; vacío desactiva verificación')
    args=p.parse_args()
    if args.target_es<1 or args.target_en<1 or args.min_words<1 or args.sample_size<1:
        p.error('Las cuotas, muestra y mínimo de palabras deben ser positivos.')
    if args.delay<0 or args.timeout<=0 or args.max_new_fetches<0:
        p.error('Parámetros de red inválidos.')
    if args.phase=='count':
        return count(args)
    rows, inventory, _, _ = base_and_inventory(args)
    if args.phase=='plan':
        inventory = combine_inventory(args, inventory)
        prev = Path(args.out) / 'corpus_ampliado.jsonl'
        actual = list(read_jsonl(prev)) if prev.exists() else rows
        plan_info(actual,inventory,args)
        return 0
    return build(args)

if __name__ == '__main__':
    raise SystemExit(main())
