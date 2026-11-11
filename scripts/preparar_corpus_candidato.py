#!/usr/bin/env python3
"""Construye un corpus CANDIDATO de problemas de matemáticas y física para BDA.

Fuentes: PolyUniMath (shards Parquet) y PhysicsEval (test.json o train.json).
No usa Dataset Viewer ni modifica bases de datos. No certifica licencias ni la
corrección matemática de los problemas. Produce muestra para check_project.py.

Requisitos: pip install huggingface_hub pyarrow
Ejecutar desde la raíz del proyecto. Véase docs/README_corpus_candidato.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import statistics
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_MATH = "friederrr/PolyUniMath"
REPO_PHYS = "IUTVanguard/PhysicsEval"
GROUPS = ("math_es", "math_en", "physics_en")
CHARS_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
FIGURE_DEPENDENT = re.compile(
    r"\b(?:see|refer to|shown in|depicted in|illustrated in|according to|using)\s+(?:the\s+)?"
    r"(?:attached\s+|following\s+|given\s+)?(?:fig(?:ure)?\.?|diagram|picture|image)\b"
    r"|\b(?:fig(?:ure)?\.?|diagram)\s*[A-Z]?\s*\d+(?:[.-]\d+)*\b"
    r"|\b(?:véase|ver|observa|muestra|según)\s+(?:la\s+|el\s+)?(?:figura|diagrama|imagen)\b",
    re.IGNORECASE,
)
UNSOLVED = re.compile(
    r"\b(?:problem not solved|no solution (?:was )?provided|unable to solve|"
    r"cannot solve this problem|solución no disponible|no resuelto)\b",
    re.IGNORECASE,
)
HEADERS = {
    "es": ("Problema", "Opciones", "Solución", "Respuesta"),
    "en": ("Problem", "Options", "Solution", "Answer"),
}


def s(x):
    if x is None:
        return ""
    if isinstance(x, str):
        return x.strip()
    return str(x).strip()


def lang_group(row):
    lang = s(row.get("lang")).lower()
    return "math_" + lang if lang in ("es", "en") else None


def fingerprint(text):
    """Hash de contenido sin diferencias triviales de espacios (sin traducir)."""
    return hashlib.sha256(" ".join(text.split()).casefold().encode("utf-8")).digest()


def word_count(text):
    return len(text.split())


def valid_tag(value):
    """Únicamente etiquetas afirmativas de calidad verificada."""
    return s(value).casefold() in ("yes", "true", "valid", "1")


def test_relevance(problem, solution):
    if CHARS_BAD.search(problem) or CHARS_BAD.search(solution):
        return "caracteres_control"
    if "localid=\"" in problem or "role=\"math\"" in problem:
        return "marcado_matematico_incompleto"
    if FIGURE_DEPENDENT.search(problem):
        return "requiere_figura"
    if UNSOLVED.search(solution[:700]):
        return "solucion_incompleta"
    return None


def normalized_document(row, group, source_row, *, min_math_words, min_physics_words):
    domain, lang = ("math", group[-2:]) if group.startswith("math_") else ("physics", "en")
    problem = s(row.get("problem"))
    solution = s(row.get("solution" if domain == "math" else "elaborated_solution_steps"))
    if not problem or not solution:
        return None, "sin_problema_o_solucion"
    if domain == "math":
        if s(row.get("lang")).lower() != lang:
            return None, "idioma_incorrecto"
        if "solution_is_valid" in row and not valid_tag(row.get("solution_is_valid")):
            return None, "solucion_no_validada"
        if "problem_is_valid" in row and s(row.get("problem_is_valid")) and not valid_tag(row.get("problem_is_valid")):
            return None, "problema_no_validado"
        if s(row.get("self_contained")).casefold() in ("no", "false", "0"):
            return None, "no_autocontenido"
    reason = test_relevance(problem, solution)
    if reason:
        return None, reason

    answer = row.get("answer" if domain == "math" else "final_answers_in_brief")
    if isinstance(answer, list):
        answer = "; ".join(s(x) for x in answer if s(x))
    answer = s(answer)
    options = s(row.get("options")) if domain == "math" else ""
    title_problem, title_options, title_solution, title_answer = HEADERS[lang]
    blocks = [f"## {title_problem}\n{problem}"]
    if options:
        blocks.append(f"## {title_options}\n{options}")
    blocks.append(f"## {title_solution}\n{solution}")
    if answer:
        blocks.append(f"## {title_answer}\n{answer}")
    text = "\n\n".join(blocks)
    words = word_count(text)
    min_words = min_math_words if domain == "math" else min_physics_words
    if words < min_words:
        return None, "texto_demasiado_corto"
    orig_id = s(row.get("id" if domain == "math" else "Problem_ID"))
    if not orig_id:
        orig_id = source_row
    origin = REPO_MATH if domain == "math" else REPO_PHYS
    source_material = s(row.get("dataset" if domain == "math" else "source"))
    metadata = {
        "document_id": f"{domain}:{lang}:{orig_id}",
        "source_dataset": origin,
        "source_url": f"https://huggingface.co/datasets/{origin}",
        "source_row": source_row,
        "language": lang,
        "domain": domain,
        "topic": s(row.get("math_type" if domain == "math" else "category")) or "other",
        "difficulty": s(row.get("score_university" if domain == "math" else "problem_difficulty")),
        "source_material": source_material,
        "source_doc": s(row.get("doc_id")) if domain == "math" else source_material,
        "question_type": s(row.get("question_type")) if domain == "math" else "problem",
        "solution_validity": s(row.get("solution_is_valid")) if domain == "math" else "not_labeled",
        "text": text,
        "words": words,
        "approx_chunks_180w": max(1, math.ceil(words / 180)),
        "question_preview": " ".join(problem.split())[:220],
    }
    return metadata, None


class RandomEligiblePool:
    """Reservoir sampling of unique, filtered entries, with an auditable tally."""
    def __init__(self, target, seed):
        self.target = target
        self.rng = random.Random(seed)
        self.rows = []
        self.eligible = 0
        self.checked = 0
        self.rejected = Counter()
        self.seen_id = set()
        self.seen_problem = set()

    def consume(self, item, reason, problem):
        self.checked += 1
        if reason:
            self.rejected[reason] += 1
            return
        # Same problem in same language is not a new independent document.
        problem_hash = fingerprint(s(problem))
        doc_id = item["document_id"]
        if doc_id in self.seen_id or problem_hash in self.seen_problem:
            self.rejected["duplicado_id_o_enunciado"] += 1
            return
        self.seen_id.add(doc_id)
        self.seen_problem.add(problem_hash)
        self.eligible += 1
        if len(self.rows) < self.target:
            self.rows.append(item)
        else:
            i = self.rng.randrange(self.eligible)
            if i < self.target:
                self.rows[i] = item


def parquet_records(path):
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    needed = [
        "id", "doc_id", "lang", "problem", "solution", "answer", "options",
        "math_type", "score_university", "dataset", "question_type",
        "solution_is_valid", "problem_is_valid", "self_contained",
    ]
    present = set(pf.schema_arrow.names)
    if not {"problem", "solution", "lang"}.issubset(present):
        raise RuntimeError(f"El Parquet {path} no contiene problem/solution/lang")
    columns = [name for name in needed if name in present]
    idx = 0
    for batch in pf.iter_batches(batch_size=1000, columns=columns):
        for row in batch.to_pylist():
            yield idx, row
            idx += 1


def physics_records(path):
    # PhysicsEval (test.json ~30 MB o train.json ~272 MB): JSON array o JSONL.
    with open(path, encoding="utf-8-sig") as f:
        head = f.read(1024).lstrip()
        f.seek(0)
        if head.startswith(("[", "{")):
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = None
        else:
            data = None
    if data is None:
        with open(path, encoding="utf-8-sig") as f:
            for i, line in enumerate(f):
                if line.strip():
                    yield i, json.loads(line)
        return
    if isinstance(data, dict):
        vals = next((data[k] for k in ("data", "test", "train", "items", "records", "examples") if isinstance(data.get(k), list)), None)
        if vals is None:
            vals = list(data.values()) if all(isinstance(v, dict) for v in data.values()) else None
        data = vals
    if not isinstance(data, list):
        raise RuntimeError(f"JSON de PhysicsEval con estructura no admitida: {path}")
    for i, row in enumerate(data):
        if isinstance(row, dict):
            yield i, row


def get_local_or_download(local_filename, repo, hub_filename):
    if local_filename:
        local = Path(local_filename)
        if not local.is_file():
            raise FileNotFoundError(f"No existe el archivo local: {local}")
        return local
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(repo_id=repo, filename=hub_filename, repo_type="dataset"))


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def select_sample(rows, n, seed):
    """Random within each group; target groups proportional to full documents."""
    if n > len(rows):
        raise RuntimeError("La muestra pedida es mayor que el corpus seleccionado")
    rng = random.Random(seed + 777)
    per_group = {g: [r for r in rows if r["domain"] + "_" + r["language"] == g] for g in GROUPS}
    quotas_float = {g: n * len(v) / len(rows) for g, v in per_group.items()}
    quotas = {g: int(quotas_float[g]) for g in GROUPS}
    extra = n - sum(quotas.values())
    ranks = sorted(GROUPS, key=lambda g: quotas_float[g] - quotas[g], reverse=True)
    for g in ranks[:extra]:
        quotas[g] += 1
    output = []
    for g in GROUPS:
        output.extend(rng.sample(per_group[g], quotas[g]))
    rng.shuffle(output)
    return output, quotas


def stats(rows):
    result = {}
    for g in GROUPS:
        subset = [r for r in rows if r["domain"] + "_" + r["language"] == g]
        if not subset:
            result[g] = {"documents": 0, "words": 0, "approx_chunks": 0, "mean_words": None}
            continue
        result[g] = {
            "documents": len(subset),
            "words": sum(r["words"] for r in subset),
            "approx_chunks": sum(r["approx_chunks_180w"] for r in subset),
            "mean_words": round(statistics.mean(r["words"] for r in subset), 1),
        }
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/corpus_candidato")
    ap.add_argument("--math-es", type=int, default=6000)
    ap.add_argument("--math-en", type=int, default=9000)
    ap.add_argument("--physics-en", type=int, default=1000)
    ap.add_argument("--shards", default="11,19", help="Índices de los Parquet de PolyUniMath, 0..22")
    ap.add_argument("--physics-split", choices=("test", "train"), default="test")
    ap.add_argument("--math-files", nargs="*", default=None, help="Parquet locales opcionales; anulan --shards")
    ap.add_argument("--physics-file", default="", help="Archivo PhysicsEval JSON local opcional")
    ap.add_argument("--min-math-words", type=int, default=60)
    ap.add_argument("--min-physics-words", type=int, default=200)
    ap.add_argument("--sample-size", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--contact", default="", help="Referencia informativa: no autentica descargas")
    args = ap.parse_args()

    quotas = {"math_es": args.math_es, "math_en": args.math_en, "physics_en": args.physics_en}
    if any(v < 0 for v in quotas.values()) or sum(quotas.values()) < 1:
        ap.error("La cantidad de documentos debe ser no negativa, y el total >0")
    if not 50 <= args.sample_size <= 500:
        ap.error("--sample-size debe estar entre 50 y 500")
    try:
        shard_ids = list(dict.fromkeys(int(x.strip()) for x in args.shards.split(",") if x.strip()))
    except ValueError:
        ap.error("--shards requiere enteros separados por coma, por ejemplo 11,19")
    if any(x < 0 or x > 22 for x in shard_ids):
        ap.error("Los índices de PolyUniMath están entre 0 y 22")
    if not args.math_files and any(quotas[g] for g in ("math_es", "math_en")) and not shard_ids:
        ap.error("Se necesita al menos un shard de PolyUniMath")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pools = {g: RandomEligiblePool(n, args.seed + i * 103) for i, (g, n) in enumerate(quotas.items()) if n}
    files_info = []

    if "math_es" in pools or "math_en" in pools:
        if args.math_files:
            paths = [(f"local:{i}", get_local_or_download(p, REPO_MATH, "")) for i, p in enumerate(args.math_files)]
        else:
            paths = []
            for index in shard_ids:
                remote = f"data/train-{index:05d}-of-00023.parquet"
                print(f"Descargando o reutilizando {remote} ...", flush=True)
                paths.append((remote, get_local_or_download("", REPO_MATH, remote)))
        for location, path in paths:
            files_info.append({"dataset": REPO_MATH, "file": location, "bytes": path.stat().st_size})
            print(f"Procesando {location} ...", flush=True)
            for row_idx, row in parquet_records(path):
                group = lang_group(row)
                if group not in pools:
                    continue
                item, reason = normalized_document(row, group, f"{location}:{row_idx}",
                    min_math_words=args.min_math_words, min_physics_words=args.min_physics_words)
                pools[group].consume(item, reason, row.get("problem"))
            print("  " + " | ".join(f"{g}: elegibles únicos={p.eligible}, en reserva={len(p.rows)}"
                for g, p in pools.items() if g.startswith("math_")), flush=True)

    if "physics_en" in pools:
        filename = f"{args.physics_split}.json"
        print(f"Descargando o reutilizando PhysicsEval/{filename} ...", flush=True)
        path = get_local_or_download(args.physics_file, REPO_PHYS, filename)
        files_info.append({"dataset": REPO_PHYS, "file": filename if not args.physics_file else args.physics_file,
                           "bytes": path.stat().st_size})
        for row_idx, row in physics_records(path):
            item, reason = normalized_document(row, "physics_en", f"{filename}:{row_idx}",
                min_math_words=args.min_math_words, min_physics_words=args.min_physics_words)
            pools["physics_en"].consume(item, reason, row.get("problem"))
        print(f"  physics_en: elegibles únicos={pools['physics_en'].eligible}, "
              f"en reserva={len(pools['physics_en'].rows)}", flush=True)

    # Always generate a truthful partial candidate if some quotas aren't met.
    selected = [r for g in GROUPS if g in pools for r in pools[g].rows]
    selected.sort(key=lambda r: r["document_id"])
    totals_met = all(g in pools and len(pools[g].rows) == target if target else True for g, target in quotas.items())
    if not selected:
        raise RuntimeError("No se ha encontrado ningún documento que pase los filtros")
    current_stats = stats(selected)
    total_chunks = sum(r["approx_chunks_180w"] for r in selected)
    es_chunks = current_stats["math_es"]["approx_chunks"]
    es_share = es_chunks / total_chunks if total_chunks else 0.0
    en_share = 1.0 - es_share
    eligible_for_sample = len(selected) >= args.sample_size
    sample, sample_quotas = select_sample(selected, args.sample_size, args.seed) if eligible_for_sample else ([], {})
    sample_stats = stats(sample)
    sample_chunks = sum(r["approx_chunks_180w"] for r in sample)
    sample_es_share = sample_stats["math_es"]["approx_chunks"] / sample_chunks if sample_chunks else 0

    corpus_path = out / "corpus_candidato.jsonl"
    with corpus_path.open("w", encoding="utf-8") as f:
        for record in selected:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    write_csv(out / "inventario_candidato.csv", selected,
        ["document_id", "source_dataset", "source_url", "source_row", "language",
         "domain", "topic", "difficulty", "source_material", "source_doc",
         "question_type", "solution_validity", "words", "approx_chunks_180w", "question_preview"])
    if sample:
        write_csv(out / "muestra_check_project.csv", sample, ["text", "language"])
        write_csv(out / "trazabilidad_muestra.csv", sample,
            ["document_id", "language", "domain", "source_dataset", "source_row",
             "source_material", "topic", "difficulty", "question_preview", "words"])

    audit = []
    for g in GROUPS:
        if g not in pools:
            continue
        p = pools[g]
        audit.append({"group": g, "requested": p.target, "eligible_unique": p.eligible,
                      "selected": len(p.rows), "seen": p.checked,
                      **{f"rejected_{reason}": n for reason, n in sorted(p.rejected.items())}})
    fields = ["group", "requested", "eligible_unique", "selected", "seen"] + sorted({k for r in audit for k in r if k.startswith("rejected_")})
    write_csv(out / "auditoria_filtrado.csv", audit, fields)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "descarga directa Hugging Face; sólo archivos analizados",
        "files": files_info,
        "parameters": vars(args),
        "target": quotas,
        "target_composition_met": totals_met,
        "corpus": {"documents": len(selected), "approx_chunks_180w": total_chunks,
                   "es_chunk_share": round(es_share, 4), "en_chunk_share": round(en_share, 4),
                   "groups": current_stats},
        "sample": {"documents": len(sample), "group_quotas": sample_quotas,
                   "approx_chunks_180w": sample_chunks,
                   "es_chunk_share": round(sample_es_share, 4), "groups": sample_stats},
        "audit": audit,
        "checks_preliminary": {
            "documents_ge_1000": len(selected) >= 1000,
            "approx_chunks_ge_25000": total_chunks >= 25000,
            "es_chunks_ge_20pct": es_share >= 0.20,
            "en_chunks_ge_20pct": en_share >= 0.20,
            "sample_size_50_to_500": 50 <= len(sample) <= 500,
        },
        "limitations": [
            "Estimación ~180 palabras/chunk; check_project.py debe medir chunks con el tokenizer E5.",
            "La muestra es aleatoria estratificada por proporción de DOCUMENTOS de cada grupo.",
            "No son muestras de los 23 shards salvo que se procesen todos.",
            "Filtros automáticos no prueban corrección de soluciones ni licencias de obras originales.",
            "Los problemas sin figura se detectan con heurísticas imperfectas: revisar casos manualmente.",
            "No redistribuir el texto original sin comprobar condiciones de los materiales subyacentes.",
        ],
    }
    (out / "informe_candidato.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "CORPUS CANDIDATO DE FÍSICA Y MATEMÁTICAS — BDA",
        "=================================================",
        f"Documentos: {len(selected):,}",
        f"Chunks aproximados (180 palabras/chunk): {total_chunks:,}",
        f"Porcentaje chunks ES/EN aproximado: {es_share:.1%} / {en_share:.1%}",
        f"Objetivos de composición alcanzados: {'SÍ' if totals_met else 'NO'}",
        "",
    ]
    for g in GROUPS:
        if g in pools:
            p = pools[g]
            st = current_stats[g]
            lines.append(f"{g}: objetivo={p.target:,} elegibles={p.eligible:,} "
                         f"seleccionados={st['documents']:,} chunks≈{st['approx_chunks']:,} "
                         f"palabras medias={st['mean_words']}")
    lines += [
        "", f"Muestra para check_project: {len(sample)} documentos | ES≈{sample_es_share:.1%} chunks",
        "AVISO: la proporción de chunks debe contrastarse con la del corpus completo.",
        "AVISO: filtrado automático y recuento aproximado; falta validación del profesorado.",
    ]
    if not totals_met:
        lines.append("FALTAN DOCUMENTOS: añadir más shards con --shards o reducir objetivos sólo si se mantiene el mínimo.")
    if len(selected) < 1000 or total_chunks < 25000 or es_share < 0.20 or en_share < 0.20:
        lines.append("ADVERTENCIA: NO se cumplen todos los mínimos aproximados del enunciado.")
    if not sample:
        lines.append("ADVERTENCIA: no se creó muestra: el corpus candidato tiene menos documentos que --sample-size.")
    (out / "resumen_candidato.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Archivos guardados en: {out.resolve()}")


if __name__ == "__main__":
    main()
