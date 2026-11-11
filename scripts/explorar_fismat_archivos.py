#!/usr/bin/env python3
"""Piloto BDA física/matemáticas: muestreo desde archivos del Hub, SIN Dataset Viewer.

- Descarga algunos shards de PolyUniMath (Parquet) y test.json de PhysicsEval.
- Recorre localmente los registros y selecciona muestra aleatoria por depósito.
- NO representa automáticamente todo PolyUniMath: sólo los shards descargados.
- NO sustituye check_project.py ni valida la licencia de fuentes originales.
"""

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_MATH = 'friederrr/PolyUniMath'
REPO_PHYS = 'IUTVanguard/PhysicsEval'
GROUPS = ('math_es', 'math_en', 'physics_en')


def as_str(x):
    if x is None:
        return ''
    if isinstance(x, str):
        return x.strip()
    return str(x).strip()


def normalise(row, group, location):
    domain = 'math' if group.startswith('math_') else 'physics'
    lang = 'es' if group == 'math_es' else 'en'
    if domain == 'math' and as_str(row.get('lang')).lower() != lang:
        return None
    problem = as_str(row.get('problem'))
    solution = as_str(row.get('solution') if domain == 'math' else row.get('elaborated_solution_steps'))
    if not problem or not solution:
        return None
    answer = row.get('answer') if domain == 'math' else row.get('final_answers_in_brief')
    if isinstance(answer, list):
        answer = '; '.join(map(str, answer))
    answer = as_str(answer)
    text = '\n\n'.join(s for s in [
        ('## Problema\n' + problem),
        ('## Solución\n' + solution),
        ('## Respuesta\n' + answer) if answer else '',
    ] if s)
    unique = as_str(row.get('id') if domain == 'math' else row.get('Problem_ID')) or location
    source = REPO_MATH if domain == 'math' else REPO_PHYS
    return {
        'document_id': f'{domain}_{lang}_{unique}',
        'source_dataset': source,
        'source_url': f'https://huggingface.co/datasets/{source}',
        'source_row': location,
        'language': lang,
        'domain': domain,
        'topic': as_str(row.get('math_type') if domain == 'math' else row.get('category')),
        'difficulty': as_str(row.get('score_university') if domain == 'math' else row.get('problem_difficulty')),
        'source_material': as_str(row.get('dataset') if domain == 'math' else row.get('source')),
        'source_doc': as_str(row.get('doc_id') if domain == 'math' else row.get('source')),
        'question_type': as_str(row.get('question_type')) if domain == 'math' else 'problem',
        'solution_validity': as_str(row.get('solution_is_valid')) if domain == 'math' else 'sin_etiqueta',
        'text': text,
        'words': len(text.split()),
        'approx_chunks_180w': max(1, math.ceil(len(text.split()) / 180)),
        'question_preview': problem.replace('\n', ' ')[:180],
    }


class Reservoir:
    def __init__(self, target, rng, min_words):
        self.target = target
        self.rng = rng
        self.min_words = min_words
        self.rows = []
        self.valid_seen = 0
        self.rejections = Counter()
        self.ids = set()
        self.hashes = set()

    def add(self, item):
        if item is None:
            self.rejections['sin_solucion_o_idioma'] += 1
            return
        if item['words'] < self.min_words:
            self.rejections['demasiado_corto'] += 1
            return
        id_ = item['document_id']
        fp = hashlib.sha256(item['text'].encode('utf-8')).hexdigest()
        if id_ in self.ids or fp in self.hashes:
            self.rejections['duplicado'] += 1
            return
        self.ids.add(id_)
        self.hashes.add(fp)
        self.valid_seen += 1
        if len(self.rows) < self.target:
            self.rows.append(item)
        else:
            i = self.rng.randrange(self.valid_seen)
            if i < self.target:
                self.rows[i] = item


def parquet_records(path):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError('Falta pyarrow: pip install pyarrow') from exc
    pf = pq.ParquetFile(path)
    required = ['id', 'lang', 'problem', 'solution', 'answer', 'math_type', 'score_university',
                'dataset', 'doc_id', 'question_type', 'solution_is_valid']
    present = set(pf.schema_arrow.names)
    cols = [x for x in required if x in present]
    if not {'problem', 'solution', 'lang'}.issubset(present):
        raise RuntimeError(f'Columnas inesperadas en {path}: faltan problem/solution/lang')
    n = 0
    for batch in pf.iter_batches(batch_size=1000, columns=cols):
        for r in batch.to_pylist():
            yield n, r
            n += 1


def json_records(path):
    # El archivo de prueba de PhysicsEval pesa unos 30 MB: se puede cargar en memoria.
    with open(path, 'r', encoding='utf-8-sig') as f:
        prefix = f.read(1024).lstrip()
        f.seek(0)
        if prefix.startswith(('[', '{')):
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = None
        else:
            data = None
    if data is None:
        with open(path, encoding='utf-8-sig') as f:
            for i, line in enumerate(f):
                if line.strip():
                    item = json.loads(line)
                    if isinstance(item, dict):
                        yield i, item
        return
    if isinstance(data, dict):
        nested = next((data[k] for k in ('data','test','items','records','examples')
                       if isinstance(data.get(k), list)), None)
        if nested is not None:
            data = nested
        elif all(isinstance(v, dict) for v in data.values()):
            data = list(data.values())
        else:
            raise RuntimeError(f'Estructura JSON no reconocida: {list(data)[:8]}')
    if not isinstance(data, list):
        raise RuntimeError('El JSON de PhysicsEval no contiene lista de problemas')
    for i, r in enumerate(data):
        if isinstance(r, dict):
            yield i, r


def save_csv(path, records, *, with_text=True):
    if not records:
        return
    keys = list(records[0])
    if not with_text:
        keys.remove('text')
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default='data/exploracion_fismat_archivos')
    ap.add_argument('--math-es', type=int, default=120)
    ap.add_argument('--math-en', type=int, default=60)
    ap.add_argument('--physics-en', type=int, default=120)
    ap.add_argument('--shards', default='11,19', help='Indices 0..22 de PolyUniMath; por defecto 11,19 (~304 MB)')
    ap.add_argument('--min-words', type=int, default=60)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--contact', default='', help='Referencia pública del proyecto para identificar las descargas')
    args = ap.parse_args()
    desired = {'math_es':args.math_es, 'math_en':args.math_en, 'physics_en':args.physics_en}
    if min(desired.values()) < 0 or sum(desired.values()) < 1 or sum(desired.values()) > 500:
        ap.error('Los tamaños deben sumar de 1 a 500, sin valores negativos')
    try:
        shards = list(dict.fromkeys(int(x) for x in args.shards.split(',') if x.strip()))
    except ValueError:
        ap.error('--shards acepta índices separados por comas: 11,19')
    if any(x < 0 or x > 22 for x in shards):
        ap.error('Los shards de PolyUniMath van del 0 al 22')
    if any(desired[k] for k in ('math_es', 'math_en')) and not shards:
        ap.error('Se necesita al menos un shard de PolyUniMath')

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SystemExit('Instala huggingface_hub: pip install -U huggingface_hub') from exc

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    res = {g: Reservoir(n, random.Random(rng.randrange(1_000_000_000)), args.min_words)
           for g, n in desired.items() if n}
    downloads, observed = [], Counter()

    for ix in shards:
        if 'math_es' not in res and 'math_en' not in res:
            break
        filename = f'data/train-{ix:05d}-of-00023.parquet'
        print(f'\nDescargando o reutilizando {filename}...', flush=True)
        local = hf_hub_download(repo_id=REPO_MATH, filename=filename, repo_type='dataset')
        downloads.append({'dataset': REPO_MATH, 'file': filename, 'size_bytes': Path(local).stat().st_size})
        for n, row in parquet_records(local):
            lang = as_str(row.get('lang')).lower()
            group = 'math_' + lang
            if group not in res:
                continue
            observed[group] += 1
            norm = normalise(row, group, f'{ix}:{n}')
            res[group].add(norm)
        for group in ('math_es', 'math_en'):
            if group in res:
                print(f'  {group}: {res[group].valid_seen} válidos observados; '
                      f'{len(res[group].rows)} en la muestra', flush=True)

    if 'physics_en' in res:
        print('\nDescargando o reutilizando PhysicsEval/test.json (~30 MB)...', flush=True)
        local = hf_hub_download(repo_id=REPO_PHYS, filename='test.json', repo_type='dataset')
        downloads.append({'dataset': REPO_PHYS, 'file': 'test.json', 'size_bytes': Path(local).stat().st_size})
        for ix, row in json_records(local):
            observed['physics_en'] += 1
            res['physics_en'].add(normalise(row, 'physics_en', f'test:{ix}'))
        print(f'  physics_en: {res["physics_en"].valid_seen} válidos observados; '
              f'{len(res["physics_en"].rows)} en la muestra', flush=True)

    rows = [r for group in GROUPS if group in res for r in res[group].rows]
    if not rows:
        raise SystemExit('No se han obtenido documentos. Revisa los archivos y columnas.')
    rows.sort(key=lambda r: (r['source_dataset'], r['language'], r['document_id']))
    save_csv(out/'muestra_exploratoria.csv', rows)
    save_csv(out/'auditoria.csv', rows, with_text=False)

    summary_groups = {}
    for group in GROUPS:
        if group not in res:
            continue
        r = res[group]
        ws = [i['words'] for i in r.rows]
        chunks = [i['approx_chunks_180w'] for i in r.rows]
        summary_groups[group] = {
            'requested': r.target, 'sampled': len(r.rows), 'eligible_seen_in_downloaded_files': r.valid_seen,
            'rows_with_language_seen': observed[group], 'mean_words': round(statistics.mean(ws),1) if ws else None,
            'median_words': statistics.median(ws) if ws else None,
            'mean_approx_chunks': round(statistics.mean(chunks),2) if chunks else None,
            'rejections': dict(r.rejections),
        }
    data = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Exploración local sólo sobre archivos descargados. NO es muestra aleatoria del dataset completo.',
        'polyunimath_shards': shards,
        'files': downloads,
        'groups': summary_groups,
        'sample_documents': len(rows),
        'sample_approx_chunks': sum(r['approx_chunks_180w'] for r in rows),
        'by_language': {l: {'documents':sum(r['language']==l for r in rows),
                           'approx_chunks':sum(r['approx_chunks_180w'] for r in rows if r['language']==l)}
                        for l in ('es','en')},
        'warnings': [
            'Muestreo aleatorio sólo entre registros de los shards seleccionados; no extrapolar los resultados a todos los 23 shards.',
            'No usar el CSV directamente como muestra de check_project.py sin definir antes el corpus completo y sus proporciones.',
            'Comprobar las licencias de contenidos subyacentes, duplicados y calidad de soluciones.',
        ],
    }
    (out/'informe.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [
        'PILOTO FÍSICA Y MATEMÁTICAS — ARCHIVOS LOCALES',
        'Evita las APIs /rows y /filter del Dataset Viewer.',
        'NO es validación oficial ni muestra representativa de todo PolyUniMath.',
        f'Archivos PolyUniMath: {shards}',
        f'Documentos de la muestra: {len(rows)}',
        f'Chunks aproximados: {data["sample_approx_chunks"]}',
        '',
    ]
    for g, st in summary_groups.items():
        lines.extend([
            f'{g}: {st["sampled"]}/{st["requested"]} documentos muestreados; '
            f'{st["eligible_seen_in_downloaded_files"]} elegibles vistos',
            f'  Palabras medias: {st["mean_words"]} | mediana: {st["median_words"]} | '
            f'chunks medios aprox.: {st["mean_approx_chunks"]}',
        ])
    for l, st in data['by_language'].items():
        lines.append(f'{l}: {st["documents"]} documentos, ~{st["approx_chunks"]} chunks en la muestra')
    lines.extend(['','Siguiente: definir el número real de documentos por grupo e idioma,',
                  'preparar muestra representativa y ejecutar check_project.py.'])
    (out/'resumen.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n' + (out/'resumen.txt').read_text(encoding='utf-8'))
    print(f'Archivos guardados en {out.resolve()}')
    if any(st['sampled'] < st['requested'] for st in summary_groups.values()):
        print('AVISO: Faltan documentos en algún grupo; prueba añadir shards PolyUniMath en --shards.', file=sys.stderr)


if __name__ == '__main__':
    main()
