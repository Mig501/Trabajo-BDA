#!/usr/bin/env python3
"""Exploración PILOTO de PolyUniMath y PhysicsEval (sin descargar corpus completo).

Obtiene segmentos de filas situados en posiciones aleatorias por la API pública
Dataset Viewer de Hugging Face. NO es una muestra final representativa del RAG.

Documentación del API: https://huggingface.co/docs/dataset-viewer
"""

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://datasets-server.huggingface.co"
SOURCES = {
    "math_es": ("friederrr/PolyUniMath", "es", "math"),
    "math_en": ("friederrr/PolyUniMath", "en", "math"),
    "physics_en": ("IUTVanguard/PhysicsEval", "en", "physics"),
}


def fetch(session, endpoint, params):
    """Small retry policy for temporary remote errors; fail on other errors."""
    last_error = None
    for attempt in range(4):
        try:
            resp = session.get(f"{API}/{endpoint}", params=params, timeout=75)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}: {resp.text[:250]}")
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            last_error = e
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Fallo consultando {endpoint} para {params.get('dataset')}: {last_error}")


def split_info(session, dataset):
    data = fetch(session, "splits", {"dataset": dataset})
    all_splits = [x for x in data.get("splits", []) if x.get("split") == "train"]
    if not all_splits:
        raise RuntimeError(f"No se encontró split 'train' en {dataset}: {data.get('splits')}")
    entry = next((x for x in all_splits if x.get("config") == "default"), all_splits[0])
    return entry["config"], entry["split"]


def read_str(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def clean_lines(*values):
    return "\n\n".join(x for x in (read_str(v) for v in values) if x)


def normalize(record, group, row_id):
    dataset, language, domain = SOURCES[group]
    if domain == "math":
        if record.get("lang") != language:
            return None
        question, solution = read_str(record.get("problem")), read_str(record.get("solution"))
        if not question or not solution:
            return None
        answer = read_str(record.get("answer"))
        text = clean_lines("## Problema\n" + question, "## Solución\n" + solution,
                           "## Respuesta\n" + answer if answer else "")
        topic = read_str(record.get("math_type"))
        difficulty = read_str(record.get("score_university"))
        source_material = read_str(record.get("dataset"))
        question_type = read_str(record.get("question_type"))
        source_doc = read_str(record.get("doc_id"))
        rec_id = read_str(record.get("id")) or str(row_id)
        valid_tag = read_str(record.get("solution_is_valid"))
    else:
        question = read_str(record.get("problem"))
        solution = read_str(record.get("elaborated_solution_steps"))
        if not question or not solution:
            return None
        answers = record.get("final_answers_in_brief")
        answer = "; ".join(map(str, answers)) if isinstance(answers, list) else read_str(answers)
        text = clean_lines("## Problema\n" + question, "## Solución explicada\n" + solution,
                           "## Respuesta\n" + answer if answer else "")
        topic = read_str(record.get("category"))
        difficulty = read_str(record.get("problem_difficulty"))
        source_material = read_str(record.get("source"))
        question_type = "problem"
        source_doc = source_material
        rec_id = read_str(record.get("Problem_ID")) or str(row_id)
        valid_tag = "sin_etiqueta"
    word_count = len(text.split())
    return {
        "document_id": f"{domain}_{language}_{rec_id}",
        "source_dataset": dataset,
        "source_url": f"https://huggingface.co/datasets/{dataset}",
        "source_row": row_id,
        "language": language,
        "domain": domain,
        "topic": topic,
        "difficulty": difficulty,
        "source_material": source_material,
        "source_doc": source_doc,
        "question_type": question_type,
        "solution_validity": valid_tag,
        "text": text,
        "words": word_count,
        "approx_chunks_180w": max(1, math.ceil(word_count / 180)),
        "question_preview": question.replace("\n", " ")[:180],
    }


def sample_group(session, group, target, *, rng, min_words, chunk_size=5,
                 max_requests=250, api_mode="auto", rows_block_size=100):
    """Get a random-block *pilot* sample; use `/rows` if `/filter` fails.

    `/filter` supports fast language-specific sampling but can temporarily fail.
    In `/rows` mode, we sample the unfiltered split and reject other languages.
    Neither method is a final, representative sample for check_project.py.
    """
    dataset, language, domain = SOURCES[group]
    config, split = split_info(session, dataset)
    common = {"dataset": dataset, "config": config, "split": split}
    where = {"where": f'"lang"=\'{language}\''} if domain == "math" else {}
    can_filter = bool(where)
    mode = "filter" if (can_filter and api_mode != "rows") else "rows"
    partial = False
    fallback_reason = ""

    def initialize(mode_to_use):
        endpoint = mode_to_use
        extra = where if mode_to_use == "filter" else {}
        first = fetch(session, endpoint, {**common, **extra, "offset": 0, "length": 1})
        n = first.get("num_rows_total")
        if not isinstance(n, int) or n < 1:
            raise RuntimeError(f"API sin num_rows_total en {endpoint} para {group}")
        return n, bool(first.get("partial", False))

    try:
        population, partial = initialize(mode)
    except RuntimeError as exc:
        if not (can_filter and api_mode == "auto" and mode == "filter"):
            raise
        fallback_reason = str(exc)
        print(f"AVISO: /filter falló para {group}; probando /rows sin filtro. "
              f"Causa: {fallback_reason[:180]}", file=sys.stderr, flush=True)
        mode = "rows"
        population, partial = initialize(mode)

    selected, seen, blocks_seen = [], set(), set()
    fingerprints = set()
    rejected = Counter()
    requests_done = 0
    while len(selected) < target and requests_done < max_requests:
        start = rng.randint(0, max(0, population - 1))
        size = chunk_size if mode == "filter" else rows_block_size
        block = min(size, population - start)
        if block < 1 or (mode, start, block) in blocks_seen:
            continue
        blocks_seen.add((mode, start, block))
        extra = where if mode == "filter" else {}
        try:
            response = fetch(session, mode, {**common, **extra, "offset": start, "length": block})
        except RuntimeError as exc:
            if not (can_filter and api_mode == "auto" and mode == "filter"):
                raise
            fallback_reason = str(exc)
            print(f"AVISO: /filter falló en {group} tras {requests_done} bloques; "
                  "continuando con /rows.", file=sys.stderr, flush=True)
            mode = "rows"
            population, new_partial = initialize(mode)
            partial = partial or new_partial
            continue
        requests_done += 1
        partial = partial or bool(response.get("partial", False))
        for entry in response.get("rows", []):
            row_data = entry.get("row", {})
            row_index = entry.get("row_idx", start)
            identity = read_str(row_data.get("id") or row_data.get("Problem_ID")) or str(row_index)
            if identity in seen:
                rejected["duplicado_id"] += 1
                continue
            seen.add(identity)
            normalized = normalize(row_data, group, row_index)
            if normalized is None:
                rejected["sin_texto_solucion_o_idioma"] += 1
                continue
            if normalized["words"] < min_words:
                rejected["corto"] += 1
                continue
            fp = hashlib.sha256(normalized["text"].encode("utf-8")).hexdigest()
            if fp in fingerprints:
                rejected["texto_duplicado"] += 1
                continue
            fingerprints.add(fp)
            selected.append(normalized)
            if len(selected) == target:
                break
        print(f"  {group}: {len(selected)}/{target} válidos; "
              f"peticiones={requests_done}; modo=/{mode}", flush=True)
        time.sleep(0.12)
    if len(selected) < target:
        print(f"AVISO: {group} sólo obtuvo {len(selected)}/{target} documentos. "
              "La API puede estar fallando o no haber registros suficientes en las posiciones consultadas.",
              file=sys.stderr)
    info = {"dataset": dataset, "language": language, "domain": domain,
            "eligible_rows_reported_by_api": population if mode == "filter" else None,
            "population_total_rows_api": population,
            "population_scope": "language_filtered_rows" if mode == "filter" else "all_dataset_rows",
            "api_partial": partial, "api_requests": requests_done,
            "api_mode_final": mode, "filter_fallback_reason": fallback_reason,
            "rejected": dict(rejected), "requested": target, "accepted": len(selected),
            "sampling": "bloques_cortos_de_posicion_aleatoria_exploratorio"}
    if partial:
        print(f"AVISO: {group}: API parcial. NO extrapolar a todo el dataset.", file=sys.stderr)
    return selected, info


def report(rows, populations, out):
    groups = []
    for group, info in populations.items():
        selection = [r for r in rows if r["domain"] == SOURCES[group][2]
                     and r["language"] == SOURCES[group][1]]
        n = len(selection)
        words = [r["words"] for r in selection]
        chunks = [r["approx_chunks_180w"] for r in selection]
        groups.append({**info,
                       "sample_words_total": sum(words),
                       "sample_chunks_approx": sum(chunks),
                       "mean_words_per_doc": round(statistics.mean(words), 1) if n else None,
                       "median_words_per_doc": statistics.median(words) if n else None,
                       "mean_approx_chunks_per_doc": round(statistics.mean(chunks), 2) if n else None,
                       "missing_topic": sum(not r["topic"] for r in selection),
                       "missing_difficulty": sum(not r["difficulty"] for r in selection),
                       "missing_source_material": sum(not r["source_material"] for r in selection)})
    by_language = {}
    chunks_total = sum(r["approx_chunks_180w"] for r in rows)
    for language in ("es", "en"):
        chosen = [r for r in rows if r["language"] == language]
        chunks = sum(r["approx_chunks_180w"] for r in chosen)
        by_language[language] = {"documents": len(chosen), "chunks_approx": chunks,
                                 "share_in_pilot_chucks_percent": round(100*chunks/chunks_total, 1) if chunks_total else 0}
    data = {
        "warning": "PILOTO; NO es corpus final ni muestra representativa para check_project.py. "
                   "Chunks sólo aproximados por palabras; la API puede ser parcial.",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "total_documents_sample": len(rows), "total_approx_chunks_sample": chunks_total,
        "by_group": groups, "by_language": by_language,
        "licenses_reported": {"PolyUniMath": "CC BY-NC 4.0", "PhysicsEval": "CC BY-SA 4.0"},
        "license_warning": "Las fuentes originales (PDFs/libros) requieren revisión independiente.",
    }
    (out / "informe.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    text = ["EXPLORACIÓN PILOTO — FÍSICA Y MATEMÁTICAS", "NO es check_project.py ni un corpus validado.",
            f"Documentos reales obtenidos: {len(rows)}", f"Chunks aproximados en la muestra: {chunks_total}", ""]
    for g in groups:
        text.extend((f"{g['dataset']} | {g['language']}: {g['accepted']}/{g['requested']} válidos",
                     f"  Media palabras: {g['mean_words_per_doc']} | mediana: {g['median_words_per_doc']}",
                     f"  Media chunks aprox.: {g['mean_approx_chunks_per_doc']}",
                     f"  API parcial: {g['api_partial']} | modo final: {g['api_mode_final']} | filas en ámbito: {g['population_total_rows_api']}",
                     f"  Metadatos faltantes: tema={g['missing_topic']}, dificultad={g['missing_difficulty']}, procedencia={g['missing_source_material']}", ""))
    for lang, g in by_language.items():
        text.append(f"{lang}: {g['documents']} documentos, {g['chunks_approx']} chunks (~{g['share_in_pilot_chucks_percent']} % en la muestra)")
    text.extend(("", "IMPORTANTE: proporciones estratificadas para explorar 3 grupos, no representar el corpus final.",
                 "A continuación habrá que fijar proporciones de documentos por grupo e idioma,",
                 "obtener una muestra aleatoria representativa y ejecutar el check_project.py oficial.",
                 "Revisar licencias/procedencia de textos de libros y PDFs originales."))
    (out / "resumen.txt").write_text("\n".join(text)+"\n", encoding="utf-8")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/exploracion_fismat")
    parser.add_argument("--math-es", type=int, default=120)
    parser.add_argument("--math-en", type=int, default=60)
    parser.add_argument("--physics-en", type=int, default=120)
    parser.add_argument("--min-words", type=int, default=60)
    parser.add_argument("--api-mode", choices=["auto", "filter", "rows"], default="auto",
                        help="auto: intenta /filter y pasa a /rows si falla; filter: solo /filter; rows: solo /rows")
    parser.add_argument("--max-requests", type=int, default=250,
                        help="máximo de bloques por grupo (por defecto 250)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--contact", default="", help="URL pública o email para identificación User-Agent")
    args = parser.parse_args(argv)
    if any(n < 0 for n in (args.math_es, args.math_en, args.physics_en)):
        parser.error("Las cantidades de documentos no pueden ser negativas.")
    if args.math_es + args.math_en + args.physics_en < 1:
        parser.error("Solicita al menos un documento.")
    if args.math_es + args.math_en + args.physics_en > 500:
        parser.error("Esta exploración está limitada a 500 documentos.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    agent = f"BDA-PhysicsMathPilot/1.0 ({args.contact or 'academic research'})"
    session = requests.Session()
    session.headers.update({"User-Agent": agent, "Accept": "application/json"})
    all_rows, populations = [], {}
    rng = random.Random(args.seed)
    for group, requested in (("math_es", args.math_es), ("math_en", args.math_en), ("physics_en", args.physics_en)):
        if requested < 1:
            continue
        print(f"\nBuscando {group} ({requested} documentos válidos)...", flush=True)
        try:
            rows, info = sample_group(session, group, requested, rng=rng, min_words=args.min_words,
                                      api_mode=args.api_mode, max_requests=args.max_requests)
        except Exception as exc:
            print(f"ERROR obteniendo {group}: {exc}", file=sys.stderr)
            if not all_rows:
                raise SystemExit(1) from exc
            break
        all_rows.extend(rows)
        populations[group] = info
    if not all_rows:
        raise SystemExit("No se consiguieron textos válidos. No se generan muestras.")
    all_rows.sort(key=lambda x: (x["source_dataset"], x["language"], x["document_id"]))
    cols = list(all_rows[0].keys())
    with (out / "muestra_exploratoria.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(all_rows)
    with (out / "auditoria.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[c for c in cols if c != "text"])
        w.writeheader()
        for r in all_rows:
            w.writerow({k:v for k,v in r.items() if k != "text"})
    summary = report(all_rows, populations, out)
    print("\n" + (out / "resumen.txt").read_text(encoding="utf-8"))
    print(f"Archivos guardados en: {out.resolve()}")
    if any(i["api_partial"] for i in populations.values()):
        print("ATENCIÓN: al menos una consulta sólo cubre parte del dataset indexado.")
    return summary


if __name__ == "__main__":
    main()
