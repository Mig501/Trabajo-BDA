#!/usr/bin/env python3
"""Exploración reproducible de un corpus RAG sobre vehículos militares.

Fuente: MediaWiki Action API (Wikipedia en español e inglés).
NO realiza la ingesta completa, ni consulta FineWiki directamente.
Requiere: requests. Uso: python explorar_corpus_militar.py --contact https://tu-sitio-o-perfil
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import random
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ImportError:
    raise SystemExit("Falta requests: instala la biblioteca en tu entorno bdav.")

# Categorías raíz comprobadas en las Wikipedia correspondientes (noviembre 2026).
ROOTS = {
    "es": [
        ("Categoría:Carros de combate", "vehiculos_terrestres"),
        ("Categoría:Aeronaves militares", "aeronaves"),
        ("Categoría:Buques de guerra", "buques"),
        ("Categoría:Helicópteros militares", "helicopteros"),
    ],
    "en": [
        ("Category:Tanks", "vehiculos_terrestres"),
        ("Category:Military aircraft", "aeronaves"),
        ("Category:Warships", "buques"),
        ("Category:Military helicopters", "helicopteros"),
    ],
}

# Excluimos subcategorías claramente ajenas a tipos/modelos de vehículos.
# NO es una clasificación perfecta: una auditoría manual seguirá siendo necesaria.
EXCLUDE_SUBCAT = re.compile(
    r"(?:museum|operator|pilot|squadron|regiment|air force personnel|"
    r"battle|disaster|accident|video game|fictional|film|"
    r"museo|operador|piloto|escuadr[oó]n|regimiento|"
    r"batalla|accidente|videojuego|ficci[oó]n|pel[ií]cula)",
    re.IGNORECASE,
)


def args_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventario y muestra preliminar de Wikipedia para BDA, sin embeddings."
    )
    parser.add_argument(
        "--contact", required=True,
        help="URL pública o email de contacto para el User-Agent de Wikimedia.",
    )
    parser.add_argument("--max-depth", type=int, default=2,
                        help="Niveles máximos de subcategorías (por defecto: 2).")
    parser.add_argument("--max-categories", type=int, default=40,
                        help="Máximo de categorías exploradas POR IDIOMA (por defecto: 40).")
    parser.add_argument("--sample-per-language", type=int, default=120,
                        help="Artículos candidatos aleatorios por idioma (por defecto: 120).")
    parser.add_argument("--min-words", type=int, default=150,
                        help="Longitud mínima para conservar un artículo (por defecto: 150).")
    parser.add_argument("--delay", type=float, default=0.75,
                        help="Segundos entre solicitudes API (por defecto: 0.75).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("resultados_exploracion_militar"))
    args = parser.parse_args()
    if args.max_depth < 0 or args.max_categories < 1 or args.sample_per_language < 1:
        parser.error("Comprueba --max-depth, --max-categories y --sample-per-language.")
    if args.min_words < 0 or args.delay < 0.35:
        parser.error("--min-words debe ser >=0 y --delay >=0.35 para evitar exceso de solicitudes.")
    if "@" not in args.contact and not args.contact.startswith(("https://", "http://")):
        parser.error("--contact debe ser una dirección de email o una URL pública.")
    return args


class MediaWiki:
    def __init__(self, contact: str, delay: float):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"BDA-MilitaryCorpusExplorer/0.1 ({contact}) python-requests",
            "Accept": "application/json",
        })
        self.delay = delay
        self.last_call = 0.0

    def get(self, lang: str, **params):
        endpoint = f"https://{lang}.wikipedia.org/w/api.php"
        all_params = {
            "action": "query", "format": "json", "formatversion": "2", **params,
        }
        for attempt in range(5):
            since = time.monotonic() - self.last_call
            if since < self.delay:
                time.sleep(self.delay - since)
            self.last_call = time.monotonic()
            try:
                response = self.session.get(endpoint, params=all_params, timeout=35)
                if response.status_code in (429, 503):
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        pause = min(90.0, max(5.0, float(retry_after)))
                    except ValueError:
                        pause = min(90.0, 5.0 * (2 ** attempt))
                    print(f"  API {response.status_code}: pausa de {pause:g} s", flush=True)
                    time.sleep(pause)
                    continue
                response.raise_for_status()
                data = response.json()
                if "error" in data:
                    raise RuntimeError(f"Error de la API: {data['error']}")
                return data
            except (requests.RequestException, ValueError) as exc:
                if attempt == 4:
                    raise RuntimeError(f"No se pudo consultar {endpoint}: {exc}") from exc
                time.sleep(min(30, 2 ** attempt))
        raise RuntimeError(f"La API rechazó varias veces las solicitudes: {endpoint}")

    def category_members(self, lang: str, category: str):
        """Devuelve TODOS los miembros de una categoría consultada, con paginación."""
        results = []
        continuation = {}
        while True:
            kw = {
                "list": "categorymembers", "cmtitle": category,
                "cmtype": "page|subcat", "cmlimit": "500",
                "cmprop": "ids|title|type",
            }
            kw.update(continuation)
            data = self.get(lang, **kw)
            results.extend(data.get("query", {}).get("categorymembers", []))
            continuation = data.get("continue", {})
            if not continuation.get("cmcontinue"):
                return results

    def full_plaintext(self, lang: str, page_id: int) -> dict | None:
        """Consulta el texto COMPLETO, nunca solo la introducción.

        La API TextExtracts permite múltiples extracciones solamente con exintro;
        por eso se utiliza una solicitud por artículo.
        """
        data = self.get(
            lang, prop="extracts|info", pageids=str(page_id),
            **{"explaintext": "1", "exsectionformat": "wiki", "inprop": "url"},
        )
        pages = data.get("query", {}).get("pages", [])
        if not pages:
            return None
        page = pages[0]
        if page.get("missing") or not page.get("extract"):
            return None
        return page


def discover(api: MediaWiki, lang: str, max_depth: int, max_categories: int,
             rng: random.Random):
    """Recorrido limitado por categorías; el inventario resultante NO es exhaustivo."""
    todo = deque((root, 0, group, root) for root, group in ROOTS[lang])
    seen_cats = set()
    pages = {}
    while todo and len(seen_cats) < max_categories:
        category, depth, group, root = todo.popleft()
        if category in seen_cats or EXCLUDE_SUBCAT.search(category):
            continue
        seen_cats.add(category)
        members = api.category_members(lang, category)
        subs = []
        for m in members:
            if m.get("ns") == 0:
                pid = m.get("pageid")
                if pid is None:
                    continue
                if pid not in pages:
                    pages[pid] = {
                        "page_id": pid, "language": lang, "title": m.get("title", ""),
                        "group": group, "root_category": root, "found_category": category,
                    }
            elif m.get("ns") == 14 and depth < max_depth:
                candidate = m.get("title", "")
                if candidate not in seen_cats and not EXCLUDE_SUBCAT.search(candidate):
                    subs.append((candidate, depth + 1, group, root))
        rng.shuffle(subs)
        todo.extend(subs)
        print(f"  {lang} | categorías {len(seen_cats):>3}/{max_categories} | "
              f"candidatos únicos {len(pages):>5} | {category}", flush=True)
    return pages, len(seen_cats), bool(todo)


def save_csv(path: Path, rows: list, fields: list):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)


def build_report(counts: dict, min_words: int) -> dict:
    estimate = {"languages": {}, "min_words": min_words}
    total_docs = total_chunks = 0.0
    for lang, s in sorted(counts.items()):
        tested = s["tested"]
        valid = s["valid"]
        candidate_count = s["candidate_count"]
        p = (valid / tested) if tested else 0
        avg_words_valid = (s["words_total"] / valid) if valid else 0
        # Los documentos no válidos aportan cero chunks.
        chunks_per_candidate = (s["chunks_total"] / tested) if tested else 0
        estimated_docs = candidate_count * p
        estimated_chunks = candidate_count * chunks_per_candidate
        total_docs += estimated_docs
        total_chunks += estimated_chunks
        estimate["languages"][lang] = {
            **s,
            "valid_fraction": round(p, 4),
            "mean_words_valid": round(avg_words_valid, 1),
            "estimated_valid_documents": round(estimated_docs),
            "estimated_chunks_approx": round(estimated_chunks),
        }
    estimate["estimated_documents_approx"] = round(total_docs)
    estimate["estimated_chunks_approx"] = round(total_chunks)
    for item in estimate["languages"].values():
        item["estimated_share_chunks_percent"] = round(
            100 * (item["estimated_chunks_approx"] / total_chunks), 1
        ) if total_chunks else 0
    return estimate


def summary(report: dict, args: argparse.Namespace) -> str:
    lines = [
        "EXPLORACIÓN PRELIMINAR DEL CORPUS MILITAR (Wikipedia API)",
        "=" * 68,
        "IMPORTANTE: sólo se han recorrido ciertas categorías hasta una profundidad",
        "y un límite definidos. No es una búsqueda exhaustiva de toda Wikipedia.",
        "Los chunks son APROXIMADOS (~180 palabras), no usan tokenizer E5.",
        "El objetivo es decidir si merece la pena continuar, no validar el corpus.",
        "",
        f"Profundidad: {args.max_depth}; máximo categorías/idioma: {args.max_categories}",
        f"Muestreo intentado: {args.sample_per_language}/idioma; mínimo palabras: {args.min_words}",
        "",
    ]
    for lang, x in report["languages"].items():
        lines.extend([
            f"IDIOMA: {lang}",
            f"  Categorías visitadas:      {x['categories_visited']}",
            f"  Artículos candidatos:      {x['candidate_count']:,}",
            f"  Artículos examinados:      {x['tested']:,}",
            f"  Artículos válidos muestra: {x['valid']:,}",
            f"  Media palabras/válido:    {x['mean_words_valid']:,.0f}",
            f"  Documentos estimados:     {x['estimated_valid_documents']:,}",
            f"  Chunks estimados (~):     {x['estimated_chunks_approx']:,}",
            f"  Peso estimado en chunks: {x['estimated_share_chunks_percent']:.1f}%",
            "",
        ])
    lines.extend([
        f"TOTAL DOCUMENTOS ESTIMADOS: {report['estimated_documents_approx']:,} "
        f"(mínimo 1.000)",
        f"TOTAL CHUNKS ESTIMADOS (~): {report['estimated_chunks_approx']:,} "
        f"(mínimo 25.000; recomendado ~50.000)",
        "",
        "Interpretación:",
        "- Las estimaciones extrapolan únicamente a categorías visitadas, no a todo el tema.",
        "- Artículos mal clasificados deben excluirse tras una auditoría manual.",
        "- Los porcentajes por idioma son estimados; el script oficial los medirá con E5.",
        "- Si el resultado es insuficiente, ampliar categorías o alcance JUSTIFICADAMENTE.",
        "- La muestra CSV es de Wikipedia API, no de FineWiki; no mezclar fuentes",
        "  para la propuesta sin volver a validar la muestra definitiva.",
        "- El texto está sujeto a las licencias aplicables de Wikipedia (CC BY-SA/GFDL);",
        "  conservar URLs, atribuciones y revisar las condiciones de reutilización.",
    ])
    return "\n".join(lines) + "\n"


def main():
    args = args_parser()
    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    api = MediaWiki(args.contact, args.delay)
    print("Explorando categorías y subcategorías (en y es)...", flush=True)
    all_candidates = []
    inventory = {}
    counts = {}
    for lang in ("es", "en"):
        print(f"\n== {lang.upper()} ==", flush=True)
        pages, visited, truncated = discover(
            api, lang, args.max_depth, args.max_categories, rng
        )
        inventory[lang] = pages
        counts[lang] = {
            "candidate_count": len(pages), "categories_visited": visited,
            "more_categories_pending": truncated,
            "tested": 0, "valid": 0, "words_total": 0, "chunks_total": 0,
        }
        for item in pages.values():
            row = {**item, "url":
                   f"https://{lang}.wikipedia.org/wiki/{quote(item['title'].replace(' ', '_'))}"}
            all_candidates.append(row)
    save_csv(
        args.out / "inventario_candidatos.csv", all_candidates,
        ["language", "page_id", "title", "url", "group", "root_category", "found_category"],
    )
    print(f"\nInventario guardado: {args.out / 'inventario_candidatos.csv'}", flush=True)

    samples = []
    audit = []
    for lang in ("es", "en"):
        candidates = list(inventory[lang].values())
        rng.shuffle(candidates)
        chosen = candidates[:args.sample_per_language]
        print(f"\nDescargando {len(chosen)} artículos aleatorios ({lang})...", flush=True)
        for n, item in enumerate(chosen, 1):
            response = api.full_plaintext(lang, item["page_id"])
            body = html.unescape(response.get("extract", "")).strip() if response else ""
            title = response.get("title", item["title"]) if response else item["title"]
            clean = re.sub(r"\n{3,}", "\n\n", body)
            text = f"{title}\n\n{clean}" if clean else ""
            words = len(text.split())
            valid = words >= args.min_words
            counts[lang]["tested"] += 1
            if valid:
                counts[lang]["valid"] += 1
                counts[lang]["words_total"] += words
                counts[lang]["chunks_total"] += math.ceil(words / 180)
                samples.append({
                    "text": text, "language": lang, "title": title,
                    "url": response.get("fullurl", "") if response else "",
                    "page_id": item["page_id"], "group": item["group"],
                    "root_category": item["root_category"],
                    "found_category": item["found_category"],
                    "words": words, "source": "Wikipedia Action API (TextExtracts)",
                    "license": "Wikipedia: verify CC BY-SA / GFDL terms",
                })
            audit.append({
                "language": lang, "page_id": item["page_id"], "title": title,
                "group": item["group"], "words": words,
                "valid_length": int(valid), "has_extract": int(bool(body)),
            })
            if n % 20 == 0 or n == len(chosen):
                print(f"  {lang}: {n}/{len(chosen)} textos revisados", flush=True)

    save_csv(
        args.out / "muestra.csv", samples,
        ["text", "language", "title", "url", "page_id", "group", "root_category",
         "found_category", "words", "source", "license"],
    )
    save_csv(
        args.out / "auditoria_muestra.csv", audit,
        ["language", "page_id", "title", "group", "words", "valid_length", "has_extract"],
    )
    report = build_report(counts, args.min_words)
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["source"] = "Wikipedia API (current text; not FineWiki snapshot)"
    report["parameters"] = {
        "max_depth": args.max_depth, "max_categories": args.max_categories,
        "sample_per_language": args.sample_per_language,
        "min_words": args.min_words, "seed": args.seed,
    }
    (args.out / "informe.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    desc = summary(report, args)
    (args.out / "resumen.txt").write_text(desc, encoding="utf-8")
    print("\n" + desc, flush=True)
    print(f"Archivos en: {args.out.resolve()}")
    print("Siguiente: revisar inventario y muestra antes de ejecutar check_project.py")
    if len(samples) < 50:
        print("AVISO: menos de 50 documentos válidos; amplía la exploración.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Interrumpido por el usuario. No se inventaron datos.")
    except (RuntimeError, requests.RequestException) as err:
        raise SystemExit(f"ERROR: {err}")
