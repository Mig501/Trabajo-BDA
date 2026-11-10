# BDA — RAG sobre vehículos militares reales

Proyecto individual de Bases de Datos Avanzadas. Tema provisional: historia y tecnología de vehículos militares reales (inspirado en War Thunder), usando fuentes abiertas.

## Estructura

- `scripts/explorar_corpus_militar.py`: explora categorías de Wikipedia y obtiene una muestra con su auditoría.
- `scripts/check_project.py`: script **original del profesor**, sin modificar.
- `docs/README_exploracion.md`: guía del script exploratorio.
- `docs/README_check_project.md`: README **original del profesor**, sin modificar.
- `docs/propuesta/`: propuesta para el laboratorio 8.
- `data/exploracion/`: resultados iniciales (inventario, muestra, auditoría e informe).
- `data/muestras/`: muestra definitiva y representativa para la propuesta.
- `data/corpus/`: documentos definitivos, cuando se valide la temática.
- `results/validacion/`: salida de `check_project.py`.
- `results/evaluacion/`: resultados experimentales futuros.
- `src/`: módulos del RAG (ingesta, retrieval y evaluación) en etapas posteriores.

## Paso actual: exploración preliminar

Desde la raíz del proyecto y con el entorno `BDA` activado, ejecutar:

```powershell
python scripts/explorar_corpus_militar.py --contact "https://github.com/blooraayy" --out data/exploracion
```

Se necesita `requests` y acceso a Internet. La URL de contacto puede sustituirse por una página o correo propio. La exploración escribe los cinco archivos en `data/exploracion/`:

- `inventario_candidatos.csv`
- `muestra.csv`
- `auditoria_muestra.csv`
- `informe.json`
- `resumen.txt`

**Antes de lanzar el script del profesor**, revisar los candidatos y garantizar que la muestra definitiva representa al corpus, incluida la distribución de **chunks** entre español e inglés. La exploración usa Wikipedia API actual y no FineWiki. Una muestra obtenida de Wikipedia API no valida automáticamente un corpus basado en FineWiki.

## Paso posterior: comprobación oficial

Leer primero `docs/README_check_project.md`. La muestra definitiva en CSV/JSONL debe tener `text` y `language` y entre 50 y 500 documentos. Elegir `--total-docs` basándose en el inventario real y confirmar los prefijos según la ficha del modelo. Para E5 Base, por ejemplo:

```powershell
python scripts/check_project.py --sample data/muestras/muestra_final.csv --model intfloat/multilingual-e5-base --total-docs 5000 --query-prefix "query: " --passage-prefix "passage: " > results/validacion/check_project.txt
```

El valor `5000` es **solo ilustrativo**, no un recuento demostrado. El script requiere `sentence-transformers>=5.6`; ver su README.

## Estado del proyecto

La selección temática, distribución lingüística y volumen documental siguen **pendientes de medición**. Por ahora no hay un RAG ni se han generado embeddings.
