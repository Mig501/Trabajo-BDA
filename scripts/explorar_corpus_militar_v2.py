#!/usr/bin/env python3
"""Exploración v2 del corpus militar para BDA.

- Equilibra el límite de categorías por grupo y por idioma (no uno global).
- Calcula la extrapolación POR ESTRATO (idioma + grupo).
- Prepara muestra exploratoria y una hoja de revisión manual.
- NO certifica relevancia ni genera una muestra final representativa del corpus.

Requiere requests. Desde la raíz del proyecto:
 python scripts/explorar_corpus_militar_v2.py --contact https://github.com/tu-perfil/tu-repo --out data/exploracion_v2
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
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ImportError:
    raise SystemExit("Necesitas requests en tu entorno bdav.")

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

# Eliminación conservadora de ramas que claramente no contienen fichas técnicas
# de vehículos. Un filtro por títulos NUNCA reemplaza una auditoría humana.
EXCLUDE_SUBCATEGORY = re.compile(
    r"(?:museum|museo|personnel|biograph|people|pilot|piloto|operator|operador|"
    r"squadron|escuadr[oó]n|regiment|regimiento|units\b|unidades\b|"
    r"film|cine\b|pel[ií]cul|fiction|ficci[oó]n|video games?|videojuego|"
    r"television|televisi[oó]n|list of|lists of|listas de|"
    r"battles?\b|batallas?\b|accidents?|accidentes?|disasters?|desastres?|"
    r"memorial|historical reenactment|novelas?\b|literature|literatura)",
    re.IGNORECASE,
)

# Marcadores para REVISAR (no son exclusiones automáticas).
REVIEW_TITLE = re.compile(
    r"(?:^list of\b|^listas? de\b|^categor[ií]a\b|\bfilm\b|\bpel[ií]cula\b|"
    r"\bElvis Presley\b|\bIntelsat\b|\btelevision\b|\btelevisi[oó]n\b)",
    re.IGNORECASE,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Inventario militar estratificado, exploración v2.")
    parser.add_argument("--contact", required=True, help="URL pública o email para User-Agent.")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-categories-per-group", type=int, default=70)
    parser.add_argument("--sample-per-group", type=int, default=40)
    parser.add_argument("--min-words", type=int, default=150)
    parser.add_argument("--delay", type=float, default=.75)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data/exploracion_v2"))
    args = parser.parse_args()
    if not (args.contact.startswith(("https://", "http://")) or "@" in args.contact):
        parser.error("--contact debe ser una URL o un correo de contacto.")
    if args.max_depth < 0 or args.max_categories_per_group < 1 or args.sample_per_group < 1:
        parser.error("Comprueba los límites de exploración.")
    if args.min_words < 0 or args.delay < .35:
        parser.error("--min-words >= 0 y --delay >= 0.35.")
    return args


class MediaWiki:
    def __init__(self, contact, delay):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"BDA-MilitaryCorpusExplorer-v2/0.2 ({contact}) python-requests",
            "Accept": "application/json",
        })
        self.delay = delay
        self.last_call = 0.0

    def get(self, lang, **params):
        url = f"https://{lang}.wikipedia.org/w/api.php"
        kw = {"action": "query", "format": "json", "formatversion": "2", **params}
        for attempt in range(5):
            wait = self.delay - (time.monotonic() - self.last_call)
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.monotonic()
            try:
                r = self.session.get(url, params=kw, timeout=35)
                if r.status_code in (429, 503):
                    header = r.headers.get("Retry-After", "")
                    try:
                        pause = min(90.0, max(5.0, float(header)))
                    except ValueError:
                        pause = min(90.0, 5 * 2**attempt)
                    print(f"  Wikipedia {r.status_code}: pausa indicada {pause:g} segundos", flush=True)
                    time.sleep(pause)
                    continue
                r.raise_for_status()
                body = r.json()
                if "error" in body:
                    raise RuntimeError(f"Error de la API: {body['error']}")
                return body
            except (requests.RequestException, ValueError) as exc:
                if attempt == 4:
                    raise RuntimeError(f"No se pudo consultar {url}: {exc}") from exc
                time.sleep(min(30, 2**attempt))
        raise RuntimeError("La API rechazó varias solicitudes consecutivas.")

    def category_members(self, lang, category):
        results, continuation = [], {}
        while True:
            kw = {"list": "categorymembers", "cmtitle": category,
                  "cmtype": "page|subcat", "cmlimit": "500", "cmprop": "ids|title|type"}
            kw.update(continuation)
            data = self.get(lang, **kw)
            results.extend(data.get("query", {}).get("categorymembers", []))
            continuation = data.get("continue", {})
            if not continuation.get("cmcontinue"):
                return results

    def full_plaintext(self, lang, page_id):
        data = self.get(lang, prop="extracts|info", pageids=str(page_id),
                        **{"explaintext": "1", "exsectionformat": "wiki", "inprop": "url"})
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") or not pages[0].get("extract"):
            return None
        return pages[0]


def discover_group(api, lang, root, group, max_depth, max_categories, rng):
    """Presupuesto independiente por raíz. No promete cobertura exhaustiva."""
    todo = deque([(root, 0)])
    seen = set()
    pages = {}
    while todo and len(seen) < max_categories:
        category, depth = todo.popleft()
        if category in seen or (depth > 0 and EXCLUDE_SUBCATEGORY.search(category)):
            continue
        seen.add(category)
        members = api.category_members(lang, category)
        children = []
        for m in members:
            if m.get("ns") == 0 and m.get("pageid") is not None:
                pid = str(m["pageid"])
                pages.setdefault(pid, {
                    "page_id": pid, "language": lang, "title": m.get("title", ""),
                    "group": group, "root_category": root, "found_category": category,
                })
            elif m.get("ns") == 14 and depth < max_depth:
                child = m.get("title", "")
                if child not in seen and not EXCLUDE_SUBCATEGORY.search(child):
                    children.append((child, depth + 1))
        rng.shuffle(children)
        todo.extend(children)
        if len(seen) % 20 == 0 or (len(seen) == max_categories):
            print(f"    {group}: categorías {len(seen)}, artículos {len(pages)}", flush=True)
    return pages, len(seen), bool(todo)


def save_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_report(stats, min_words):
    # La media no se calcula a partir de una muestra 50/50 por idioma, sino
    # estimando primero cada estrato (idioma x grupo) por separado.
    totals = defaultdict(lambda: {"candidates": 0, "estimated_docs": 0.,
                                  "estimated_chunks": 0., "categories": 0})
    data = []
    for (lang, group), s in sorted(stats.items()):
        tested = s["tested"]
        valid_fraction = s["valid"] / tested if tested else 0.
        chunks_per_candidate = s["chunks_total"] / tested if tested else 0.
        docs_est = s["candidates"] * valid_fraction
        chunks_est = s["candidates"] * chunks_per_candidate
        totals[lang]["candidates"] += s["candidates"]
        totals[lang]["estimated_docs"] += docs_est
        totals[lang]["estimated_chunks"] += chunks_est
        totals[lang]["categories"] += s["categories"]
        data.append({
            "language": lang, "group": group,
            **s,
            "valid_fraction": round(valid_fraction, 4),
            "mean_words_valid": round(s["words_total"] / s["valid"], 1) if s["valid"] else 0,
            "estimated_docs": round(docs_est),
            "estimated_chunks_approx": round(chunks_est),
        })
    all_chunks = sum(v["estimated_chunks"] for v in totals.values())
    return {
        "note": "Sólo estimación de categorías visitadas, antes de auditoría temática; no es check_project.py",
        "by_group": data,
        "by_language": {
            lang: {
                "candidates": int(v["candidates"]),
                "categories_visited": int(v["categories"]),
                "estimated_docs": round(v["estimated_docs"]),
                "estimated_chunks_approx": round(v["estimated_chunks"]),
                "estimated_share_chunks_percent": round(100*v["estimated_chunks"]/all_chunks, 1) if all_chunks else 0,
            } for lang, v in sorted(totals.items())
        },
        "estimated_docs_approx": round(sum(v["estimated_docs"] for v in totals.values())),
        "estimated_chunks_approx": round(all_chunks),
        "min_words": min_words,
    }


def main():
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    api = MediaWiki(args.contact, args.delay)
    inventory, stats, all_candidates = defaultdict(dict), {}, []
    print("Exploración estratificada por idioma y categoría raíz", flush=True)
    for lang in ("es", "en"):
        for root, group in ROOTS[lang]:
            print(f"  {lang} / {group}: {root}", flush=True)
            pages, visited, pending = discover_group(
                api, lang, root, group, args.max_depth,
                args.max_categories_per_group, rng
            )
            # Si un artículo se encuentra por varias raíces, se cuenta sólo una vez.
            duplicate = 0
            for pid, item in pages.items():
                if pid in inventory[lang]:
                    duplicate += 1
                else:
                    inventory[lang][pid] = item
            # Estrato contiene únicamente artículos no observados en un grupo anterior.
            unique = {pid: p for pid, p in pages.items() if inventory[lang][pid] is p}
            stats[(lang, group)] = {
                "candidates": len(unique), "categories": visited,
                "pending_categories": pending, "duplicate_other_groups": duplicate,
                "tested": 0, "valid": 0, "words_total": 0, "chunks_total": 0,
            }
            for item in unique.values():
                all_candidates.append({**item, "url":
                    f"https://{lang}.wikipedia.org/wiki/{quote(item['title'].replace(' ', '_'))}"})
    save_csv(args.out/"inventario_candidatos.csv", all_candidates,
             ["language", "page_id", "title", "url", "group", "root_category", "found_category"])

    sample, audit = [], []
    for lang in ("es", "en"):
        for root, group in ROOTS[lang]:
            items = [p for p in inventory[lang].values() if p["group"] == group]
            chosen = rng.sample(items, min(args.sample_per_group, len(items)))
            print(f"Muestreando {lang}/{group}: {len(chosen)} de {len(items)} artículos", flush=True)
            for index, item in enumerate(chosen, 1):
                response = api.full_plaintext(lang, item["page_id"])
                body = html.unescape(response.get("extract", "")).strip() if response else ""
                title = response.get("title", item["title"]) if response else item["title"]
                clean_body = re.sub(r"\n{3,}", "\n\n", body)
                text = f"{title}\n\n{clean_body}" if body else ""
                words = len(text.split())
                valid = words >= args.min_words
                key = (lang, group)
                stats[key]["tested"] += 1
                if valid:
                    stats[key]["valid"] += 1
                    stats[key]["words_total"] += words
                    stats[key]["chunks_total"] += math.ceil(words/180)
                    sample.append({
                        "text": text, "language": lang, "title": title,
                        "url": response.get("fullurl", "") if response else "",
                        "page_id": item["page_id"], "group": group,
                        "root_category": item["root_category"],
                        "found_category": item["found_category"],
                        "words": words, "source": "Wikipedia Action API (TextExtracts)",
                    })
                flagged = bool(REVIEW_TITLE.search(title))
                audit.append({
                    "language": lang, "page_id": item["page_id"],
                    "title": title, "group": group, "found_category": item["found_category"],
                    "words": words, "valid_length": int(valid),
                    "has_extract": int(bool(body)), "needs_review": int(flagged),
                    "relevant_manual": "", "comments": "",
                })
                if index % 20 == 0:
                    print(f"    {index}/{len(chosen)}", flush=True)

    save_csv(args.out/"muestra_exploratoria.csv", sample,
             ["text", "language", "title", "url", "page_id", "group",
              "root_category", "found_category", "words", "source"])
    save_csv(args.out/"revision_manual.csv", audit,
             ["language", "page_id", "title", "group", "found_category", "words",
              "valid_length", "has_extract", "needs_review", "relevant_manual", "comments"])
    report = build_report(stats, args.min_words)
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["source"] = "Wikipedia API actual; no FineWiki 2025"
    report["parameters"] = {
        "max_depth": args.max_depth,
        "max_categories_per_group": args.max_categories_per_group,
        "sample_per_group": args.sample_per_group,
        "min_words": args.min_words, "seed": args.seed,
    }
    (args.out/"informe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding="utf-8")
    lines = [
        "EXPLORACIÓN MILITAR v2 — DATOS PRELIMINARES",
        "No son cifras validadas con check_project.py ni auditoría de relevancia.",
        "",
        "Grupo              Lang Candidatos Válidos est. Chunks estimados Pendientes",
    ]
    for s in report["by_group"]:
        lines.append(f"{s['group']:<18} {s['language']:<4} {s['candidates']:>8} "
                     f"{s['estimated_docs']:>11} {s['estimated_chunks_approx']:>15} "
                     f"{'sí' if s['pending_categories'] else 'no'}")
    lines.append("")
    for lang, v in report["by_language"].items():
        lines.append(f"{lang}: {v['estimated_docs']} docs; ~{v['estimated_chunks_approx']} chunks "
                     f"({v['estimated_share_chunks_percent']} % de chunks)")
    lines.extend([
        f"TOTAL: {report['estimated_docs_approx']} docs; ~{report['estimated_chunks_approx']} chunks",
        "Revisar 'revision_manual.csv' y excluir documentos ajenos a la temática.",
        "'muestra_exploratoria.csv' NO se debe usar directamente como muestra final del profesor:",
        "está estratificada por grupo, no según las proporciones reales de chunks del corpus.",
    ])
    (args.out/"resumen.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines), flush=True)
    print(f"Archivos generados en: {args.out.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Interrumpido por el usuario.")
    except (RuntimeError, requests.RequestException) as e:
        raise SystemExit(f"ERROR: {e}")
