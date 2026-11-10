#!/usr/bin/env python3
"""Depuración documental v3 para el proyecto BDA (SIN ingesta ni embeddings).

Lee el inventario COMPLETO producido por explorar_corpus_militar_v2.py.
Consulta metadatos públicos de Wikipedia/Wikidata por lotes y separa:
  - incluir_provisional: descripción fuerte de un vehículo militar;
  - excluir_provisional: descripción clara de algo fuera del ámbito;
  - revisar: caso ambiguo, sin descripción o sin datos externos.

IMPORTANTE: ninguna etiqueta automática demuestra relevancia. Se precisa auditoría
manual estratificada, y la cifra de chunks se validará con check_project.py.

Sólo requiere Python estándar y requests.
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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError as exc:
    raise SystemExit("Instala requests en el entorno bdav: pip install requests") from exc

# La regla no se basa SOLO en el título o en la categoría de Wikipedia:
# el texto que se clasifica es la descripción en Wikidata (si existe).
VEHICLE_EN = re.compile(
    r"\b(?:main battle tank|(?:medium|light|heavy|amphibious|infantry|cruiser) tank|"
    r"tank destroyer|tankette|armou?red (?:fighting|combat|personnel|recovery|reconnaissance|"
    r"engineering|transport|military) vehicle|infantry fighting vehicle|"
    r"self.propelled (?:artillery|gun|howitzer|anti.aircraft|vehicle)|"
    r"military (?:aircraft|airplane|aeroplane|helicopter|transport aircraft|ship|vessel)|"
    r"(?:fighter|bomber|attack|reconnaissance|patrol|training|transport) aircraft|"
    r"fighter.jet|fighter.bomber|strategic bomber|tactical bomber|"
    r"(?:attack|military|combat|transport) helicopter|"
    r"(?:guided missile )?destroyer|battleship|battlecruiser|"
    r"(?:light |heavy |armou?red |protected )?cruiser|"
    r"(?:guided missile )?frigate|corvette|aircraft carrier|"
    r"submarine|warship|torpedo boat|patrol boat|landing craft|landing ship|"
    r"minesweeper|minehunter|naval vessel|military vehicle|"
    r"military drone|unmanned combat aerial vehicle|combat drone)\b", re.I)
VEHICLE_ES = re.compile(
    r"\b(?:carro de combate|tanque (?:ligero|medio|pesado|anfibio)|tanqueta|"
    r"veh[ií]culo (?:blindado|militar|de combate|de reconocimiento)|"
    r"veh[ií]culo de combate de infanter[ií]a|artiller[ií]a autopropulsada|"
    r"cazacarros|avi[oó]n (?:militar|de combate|de caza|de ataque|bombardero|de transporte militar)|"
    r"caza (?:a reacci[oó]n|militar)|cazabombardero|bombardero|"
    r"helic[oó]ptero (?:militar|de ataque|de combate)|"
    r"destructor|acorazado|crucero (?:de guerra|pesado|ligero|protegido)|"
    r"fragata|corbeta|portaaviones|submarino|buque de guerra|"
    r"buque militar|patrullero naval|dragaminas|lancha torpedera|"
    r"avi[oó]n de reconocimiento|dron militar)\b", re.I)
EXCLUDE_EN = re.compile(
    r"\b(?:politician|footballer|soccer player|musician|singer|actor|actress|"
    r"film|television series|tv series|video game|fictional character|novel|"
    r"person|general|admiral|soldier|military officer|pilot|biography|"
    r"foundation|organization|association|museum|university|"
    r"spacecraft|space probe|artificial satellite|communications satellite|"
    r"planet|asteroid|rocket launch|satellite|space station|"
    r"commercial airliner|passenger aircraft|civilian aircraft|"
    r"ocean liner|passenger ship|cruise ship|merchant ship|cargo ship|"
    r"railway station|airport|town|village|municipality|"
    r"military unit|military formation|army division|naval battle)\b", re.I)
EXCLUDE_ES = re.compile(
    r"\b(?:pol[ií]tico|futbolista|m[uú]sico|cantante|actor|actriz|"
    r"pel[ií]cula|serie de televisi[oó]n|videojuego|personaje ficticio|novela|"
    r"general|almirante|piloto de|biograf[ií]a|"
    r"fundaci[oó]n|organizaci[oó]n|asociaci[oó]n|museo|universidad|"
    r"nave espacial|sonda espacial|sat[eé]lite|estaci[oó]n espacial|"
    r"avi[oó]n comercial|avi[oó]n de pasajeros|avi[oó]n civil|"
    r"transatl[aá]ntico|buque de pasajeros|crucero tur[ií]stico|"
    r"buque mercante|barco mercante|aeropuerto|municipio|"
    r"batalla de|guerra de|unidad militar|divisi[oó]n del ej[eé]rcito)\b", re.I)
# Evita palabras sueltas como "crucero" o "militar" como prueba definitiva.
# El detalle es relevante: algunos barcos museos siguen siendo buques militares.


def parse_args():
    p = argparse.ArgumentParser(description="Auditoría v3: Wikipedia + Wikidata, con revisión manual.")
    p.add_argument("--inventario", type=Path, default=Path("data/exploracion_v2/inventario_candidatos.csv"))
    p.add_argument("--out", type=Path, default=Path("data/exploracion_v3"))
    p.add_argument("--contact", required=True, help="URL o correo para User-Agent Wikimedia.")
    p.add_argument("--informe-v2", type=Path, default=None,
                   help="Opcional: informe.json de v2, para indicador de volumen muy aproximado.")
    p.add_argument("--decisiones", type=Path, default=None,
                   help="CSV con language,page_id,decision_manual (incluir/excluir).")
    p.add_argument("--offline", action="store_true", help="Recalcular desde caché sin consultar APIs.")
    p.add_argument("--batch", type=int, default=40)
    p.add_argument("--delay", type=float, default=0.75)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--review-per-stratum", type=int, default=8,
                   help="Nº de casos al azar por idioma/grupo/resultado para revisión.")
    args = p.parse_args()
    if not (args.contact.startswith(("https://", "http://")) or "@" in args.contact):
        p.error("--contact debe ser una URL o un correo de contacto.")
    if not (1 <= args.batch <= 50) or args.delay < 0.35:
        p.error("--batch entre 1 y 50 y --delay >= 0.35.")
    if args.review_per_stratum < 1:
        p.error("--review-per-stratum debe ser >= 1.")
    return args


def read_csv(path):
    if not path.is_file():
        raise ValueError(f"No existe el CSV: {path}. Revisa la ruta de --inventario.")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, columns):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)


def load_dict(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"La caché no es un diccionario JSON: {path}")
    return data


def save_dict(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


class WikimediaAPI:
    def __init__(self, contact, delay):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": f"BDA-MilitaryCorpusAudit-v3/0.3 ({contact}) python-requests",
            "Accept": "application/json",
        })
        self.delay = delay
        self.last = 0.0

    def get(self, endpoint, **params):
        params.update({"format": "json", "formatversion": "2"})
        for attempt in range(5):
            wait = self.delay - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            try:
                response = self.s.get(endpoint, params=params, timeout=45)
                if response.status_code in (429, 503, 502, 504):
                    try:
                        pause = max(5.0, min(90.0, float(response.headers.get("Retry-After", ""))))
                    except ValueError:
                        pause = min(45.0, 4 * (2 ** attempt))
                    print(f"Respuesta {response.status_code}; pausa {pause:.0f} s", flush=True)
                    time.sleep(pause)
                    continue
                response.raise_for_status()
                body = response.json()
                if "error" in body:
                    raise RuntimeError(f"Error Wikimedia: {body['error']}")
                return body
            except (requests.RequestException, ValueError) as exc:
                if attempt == 4:
                    raise RuntimeError(f"Fallo en {endpoint}: {exc}") from exc
                time.sleep(min(30., 2 ** attempt))
        raise RuntimeError("Agotados reintentos de API")

    def page_qids(self, lang, ids):
        data = self.get(f"https://{lang}.wikipedia.org/w/api.php",
                        action="query", prop="pageprops", ppprop="wikibase_item",
                        pageids="|".join(ids))
        found = {}
        for page in data.get("query", {}).get("pages", []):
            if page.get("pageid") is not None:
                found[str(page["pageid"])] = page.get("pageprops", {}).get("wikibase_item", "")
        return found

    def descriptions(self, qids):
        data = self.get("https://www.wikidata.org/w/api.php", action="wbgetentities",
                        ids="|".join(qids), props="descriptions", languages="en|es")
        result = {}
        for qid, ent in data.get("entities", {}).items():
            if not ent.get("missing"):
                ds = ent.get("descriptions", {})
                result[qid] = {
                    "en": ds.get("en", {}).get("value", ""),
                    "es": ds.get("es", {}).get("value", ""),
                }
        return result


def chunks(seq, size):
    for pos in range(0, len(seq), size):
        yield seq[pos:pos + size]


def enrich(rows, api, qid_cache, desc_cache, offline, batch, path_qids, path_desc):
    for lang in ("es", "en"):
        lang_rows = [r for r in rows if r["language"] == lang]
        missing = [r for r in lang_rows if f"{lang}:{r['page_id']}" not in qid_cache]
        if not offline:
            for i, group in enumerate(chunks(missing, batch), 1):
                ids = [r["page_id"] for r in group]
                ret = api.page_qids(lang, ids)
                for pid in ids:
                    qid_cache[f"{lang}:{pid}"] = ret.get(pid, "")
                save_dict(path_qids, qid_cache)
                if i % 10 == 0:
                    print(f"{lang} Wikipedia: {min(i*batch,len(missing))}/{len(missing)}", flush=True)
    qids = sorted({qid_cache.get(f"{r['language']}:{r['page_id']}", "") for r in rows} - {""})
    missing_qids = [qid for qid in qids if qid not in desc_cache]
    if not offline:
        for i, group in enumerate(chunks(missing_qids, batch), 1):
            got = api.descriptions(group)
            for qid in group:
                desc_cache[qid] = got.get(qid, {"en": "", "es": ""})
            save_dict(path_desc, desc_cache)
            if i % 10 == 0:
                print(f"Wikidata: {min(i*batch,len(missing_qids))}/{len(missing_qids)}", flush=True)
    return qid_cache, desc_cache


def classify(desc_en, desc_es):
    en, es = desc_en.strip(), desc_es.strip()
    pos_en, pos_es = bool(VEHICLE_EN.search(en)), bool(VEHICLE_ES.search(es))
    neg_en, neg_es = bool(EXCLUDE_EN.search(en)), bool(EXCLUDE_ES.search(es))
    if (pos_en or pos_es) and (neg_en or neg_es):
        return "revisar", "Descripción con indicios contradictorios"
    if pos_en or pos_es:
        return "incluir_provisional", "Descripción de Wikidata menciona vehículo militar"
    if neg_en or neg_es:
        return "excluir_provisional", "Descripción de Wikidata apunta fuera del ámbito"
    if not en and not es:
        return "revisar", "Sin descripción de Wikidata"
    return "revisar", "Descripción insuficiente para clasificar con seguridad"


def get_manual(path):
    result = {}
    if path is None:
        return result
    for row in read_csv(path):
        if not all(k in row for k in ("language", "page_id")):
            raise ValueError("El archivo de decisiones necesita language y page_id")
        raw = (row.get("decision_manual") or row.get("relevant_manual") or "").strip().lower()
        if raw in {"incluir", "incluido", "si", "sí", "yes", "1", "true"}:
            result[(row["language"], row["page_id"])] = "incluir"
        elif raw in {"excluir", "excluido", "no", "0", "false"}:
            result[(row["language"], row["page_id"])] = "excluir"
        elif raw:
            raise ValueError(f"Decisión manual desconocida para {row['page_id']}: {raw}")
    return result


def summarise(rows, informe_v2):
    by = defaultdict(Counter)
    for row in rows:
        by[(row["language"], row["group"])][row["estado"]] += 1
    all_states = Counter(row["estado"] for row in rows)
    lang_states = defaultdict(Counter)
    for r in rows:
        lang_states[r["language"]][r["estado"]] += 1
    report = {
        "note": "Preclasificación temática; NO es un corpus definitivo ni una medición de chunks.",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(rows),
        "by_status": dict(all_states),
        "by_language": {k: dict(v) for k,v in sorted(lang_states.items())},
        "by_group": [{"language": a, "group": b, **dict(counts)} for (a,b),counts in sorted(by.items())],
    }
    if informe_v2 and informe_v2.is_file():
        data = json.loads(informe_v2.read_text(encoding="utf-8"))
        report["v2_approximation_warning"] = (
            "Los siguientes valores reescalan medias de v2 con la proporción "
            "de candidatos preseleccionados; NO son un recuento real ni cotas "
            "estadísticas (puede haber sesgo por longitud y categoría).")
        details=[]
        for item in data.get("by_group", []):
            counts=by[(item.get("language", ""),item.get("group", ""))]
            total=sum(counts.values())
            est=float(item.get("estimated_chunks_approx",0))
            lower=est*counts["incluir_provisional"]/total if total else 0.
            possible=est*(counts["incluir_provisional"]+counts["revisar"])/total if total else 0.
            details.append({"language":item.get("language"),"group":item.get("group"),
                            "indicador_inclusion_provisional":round(lower),
                            "indicador_si_ambiguos_validos":round(possible)})
        report["volume_indicators_not_validated"]=details
    return report


def main():
    args=parse_args()
    inventory=read_csv(args.inventario)
    expected={"language","page_id","title","url","group","root_category","found_category"}
    if not inventory or not expected.issubset(set(inventory[0])):
        raise ValueError("Inventario v2 vacío o sin columnas: " + ", ".join(sorted(expected)))
    keys=set()
    unique=[]
    for row in inventory:
        if row["language"] not in {"es","en"} or not row["page_id"].isdigit():
            raise ValueError("Formato de language/page_id inesperado en inventario.")
        key=(row["language"],row["page_id"])
        if key not in keys:
            keys.add(key)
            unique.append(row)
    args.out.mkdir(parents=True,exist_ok=True)
    path_qids=args.out/"cache_page_qids.json"
    path_desc=args.out/"cache_wikidata_descriptions.json"
    qid_cache,desc_cache=load_dict(path_qids),load_dict(path_desc)
    api = None if args.offline else WikimediaAPI(args.contact,args.delay)
    enrich(unique,api,qid_cache,desc_cache,args.offline,args.batch,path_qids,path_desc)
    manual=get_manual(args.decisiones)
    classified=[]
    for row in unique:
        qid=qid_cache.get(f"{row['language']}:{row['page_id']}","")
        ds=desc_cache.get(qid,{}) if qid else {}
        en,es=ds.get("en",""),ds.get("es","")
        status,why=classify(en,es)
        if not qid:
            why="Sin identificador Wikidata" if not args.offline or f"{row['language']}:{row['page_id']}" in qid_cache else "Pendiente de consulta (offline)"
        elif qid not in desc_cache:
            why="Pendiente de descripción (offline)"
        m=manual.get((row["language"],row["page_id"]),"")
        if m:
            status="incluir_provisional" if m=="incluir" else "excluir_provisional"
            why="Decisión manual"; 
        classified.append({**row,"wikidata_id":qid,"wikidata_description_en":en,
                           "wikidata_description_es":es,"estado":status,"motivo":why,
                           "decision_manual":m})
    cols=list(expected) + ["wikidata_id","wikidata_description_en",
           "wikidata_description_es","estado","motivo","decision_manual"]
    # Keep columns in predictable order, independently of set ordering.
    cols=["language","page_id","title","url","group","root_category","found_category",
          "wikidata_id","wikidata_description_en","wikidata_description_es","estado","motivo","decision_manual"]
    write_csv(args.out/"inventario_clasificado.csv",classified,cols)
    write_csv(args.out/"preseleccion_provisional.csv",
              [r for r in classified if r["estado"]=="incluir_provisional"],cols)
    write_csv(args.out/"pendientes_revision.csv",
              [r for r in classified if r["estado"]=="revisar"],cols)
    strata=defaultdict(list)
    for row in classified:
        strata[(row["language"],row["group"],row["estado"])].append(row)
    rng=random.Random(args.seed)
    audit=[]
    for key,group in sorted(strata.items()):
        audit+=rng.sample(group,min(args.review_per_stratum,len(group)))
    # Decision blank to facilitate adding judgments manually in the audit CSV.
    for row in audit:
        row["decision_manual"] = manual.get((row["language"],row["page_id"]),"")
    write_csv(args.out/"muestra_para_revision.csv",audit,cols)
    report=summarise(classified,args.informe_v2)
    report["api_cache"]={"wikipedia_pages_cached":len(qid_cache),
                          "wikidata_entities_cached":len(desc_cache),
                          "offline":args.offline}
    (args.out/"informe_v3.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    counts=Counter(r["estado"] for r in classified)
    text=["AUDITORÍA TEMÁTICA v3 — PRELIMINAR", "No sustituye la auditoría humana ni check_project.py", "",
          f"Artículos únicos analizados: {len(classified)}",
          f"Preseleccionados (provisional): {counts['incluir_provisional']}",
          f"Excluidos (provisional): {counts['excluir_provisional']}",
          f"Pendientes/ambiguos: {counts['revisar']}",
          f"Muestra estratificada para auditoría humana: {len(audit)}", ""]
    for lang in ("es","en"):
        sub=[r for r in classified if r["language"]==lang]
        c=Counter(r["estado"] for r in sub)
        text.append(f"{lang}: {len(sub)} artículos | preseleccionados={c['incluir_provisional']} | "
                    f"excluidos={c['excluir_provisional']} | revisar={c['revisar']}")
    text += ["", "ADVERTENCIAS:",
             "- Wikidata puede carecer de descripción; eso NO implica irrelevancia.",
             "- La preclasificación basada en descripciones puede tener falsos positivos y negativos.",
             "- No hay cifras de palabras/chunks reales de todo el corpus en esta fase.",
             "- No use preseleccion_provisional.csv directamente para la propuesta.",
             "- Audite muestra_para_revision.csv; luego reprocese con --decisiones y --offline."]
    (args.out/"resumen_v3.txt").write_text("\n".join(text)+"\n",encoding="utf-8")
    print("\n".join(text))
    print(f"\nArchivos en: {args.out.resolve()}")

if __name__=="__main__":
    try:
        main()
    except (ValueError,RuntimeError) as err:
        sys.exit(f"ERROR: {err}")
