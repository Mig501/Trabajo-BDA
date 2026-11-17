# BDA — Corpus candidato de Wikipedia científica (ES / EN)

## Propósito

Revisión de la propuesta tras el feedback del profesor: corpus **narrativo y documental** sobre historia científica, con fuentes y evidencias citables en lugar de problemas matemáticos resolubles de memoria por un LLM.

El programa procesa Wikipedia **en vivo** con MediaWiki Action API, **no** Parquet ni shards de Hugging Face. Se evita escoger arbitrariamente archivos y se documenta el marco de muestreo: categorías científicas explícitas, recorrido en anchura (BFS) de profundidad limitada, listado de categorías examinadas y muestra aleatoria con semilla fija **dentro del inventario descubierto**. La población NO es toda Wikipedia; un recorrido acotado por categorías presenta sesgos. Las categorías incompletas por tope de miembros se excluyen por completo del inventario, para no introducir selección sistemática por orden alfabético.

## Instalación

Copiar ambos scripts en `scripts/` del repositorio, manteniéndolos en la misma carpeta:

- `scripts/explorar_wikipedia_ciencia.py` (dependencia del piloto)
- `scripts/preparar_corpus_wikipedia.py` (nuevo)

Dependencia:

```powershell
python -m pip install requests
```

No requiere embeddings ni acceso a GPU hasta ejecutar `check_project.py`.

## Fase 1 — descubrir y congelar el inventario

Desde la raíz del proyecto:

```powershell
python scripts/preparar_corpus_wikipedia.py --phase discover --out data/corpus_wikipedia_ciencia --per-language 1400 --depth 2 --max-categories-per-topic 45 --members-per-category 3000 --seed 42 --contact "https://github.com/Mig501/Trabajo-BDA"
```

Genera `resumen_descubrimiento.txt`, `informe_descubrimiento.json`, `inventario_descubierto.csv`, `categorias_exploradas.csv` y caché de categorías. **Antes de pasar a la fase 2**, comprobar `candidate_counts` en `informe_descubrimiento.json`. Si hay pocos candidatos en alguna combinación de idioma/tema, no se garantizan los 1.400 documentos por idioma. Un inventario de ~350 por tema es insuficiente tras filtrar: es preferible tener bastante más, p. ej. 600–800 por tema.

`--depth 2` y el máximo de 45 categorías por combinación idioma/tema son **límites explícitos del marco**, no una selección representativa de toda Wikipedia. Si no alcanzan, se puede aumentar, pero se debe registrar el motivo. No cambiar estos límites una vez iniciado `build` sobre un inventario sin crear una nueva versión del experimento.

## Fase 2 — construir la colección

```powershell
python scripts/preparar_corpus_wikipedia.py --phase build --out data/corpus_wikipedia_ciencia --per-language 1400 --sample-size 300 --min-words 250 --seed 42 --contact "https://github.com/Mig501/Trabajo-BDA"
```

Se intenta conseguir **2.800 artículos** (1.400 por idioma), estratificados entre física, matemáticas, química y astronomía, mediante permutación aleatoria reproducible de los identificadores del inventario. Se filtran páginas demasiado cortas, listas, desambiguaciones, excesos de fórmulas y duplicados. Se conserva solo una versión por Wikidata ID en el corpus, cuando esa ID existe. Se registra la URL, ID de página, revisión, idioma, tema y categoría que motivó la inclusión.

Si alguna categoría carece de candidatos suficientes, las otras áreas del mismo idioma pueden compensar el déficit; se registra la distribución final. No se asegura el total hasta medir los resultados. Es posible que algunos artículos seleccionados requieran revisión manual de relevancia histórica.

### Reanudación y límites de las peticiones

La caché de páginas queda en `data/corpus_wikipedia_ciencia/cache/pages/` y permite relanzar exactamente el mismo comando sin volver a descargar lo que ya se obtuvo correctamente. Si quieres limitar el número de páginas descargadas **en una ejecución de prueba**, añadir por ejemplo `--max-fetch-per-run 50`. El resultado de esa ejecución será **parcial**. Para completar después, volver a ejecutar sin dicho argumento.

El programa hace llamadas en serie, utiliza un User-Agent de contacto y una pausa configurable (`--delay` por defecto 0,4 s). En caso de HTTP 429 hay que respetar `Retry-After`, evitar reintentos en bucle e intentar más tarde. Wikipedia aplica límites de API (2026); consultar: https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits

## Archivos de salida

| Archivo | Para qué sirve |
|---|---|
| `inventario_descubierto.csv` | Población de candidatos y procedencia antes del filtrado |
| `categorias_exploradas.csv` | Categorías examinadas y truncamientos |
| `informe_descubrimiento.json` | Parámetros, tamaños y limitaciones del descubrimiento |
| `resumen_descubrimiento.txt` | Resumen del inventario |
| `corpus_candidato.jsonl` | Documentos con texto completo y metadatos |
| `inventario_corpus.csv` | Trazabilidad de los documentos seleccionados, sin texto |
| `auditoria_filtrado.csv` | Registros rechazados y sus motivos |
| `muestra_check_project.csv` | Muestra aleatoria de 300 documentos para el profesor |
| `trazabilidad_muestra.csv` | Referencias e identificadores de los documentos de muestra |
| `candidatos_crosslingual.csv` | **Solo candidatos**, NO preguntas cross-lingual verificadas |
| `colisiones_entidad.csv` | Colisiones Wikidata restantes (normalmente ninguna entre aceptados) |
| `informe_corpus.json` y `resumen_corpus.txt` | Estadísticas y alertas |

## Revisión oficial de requisitos

**No** ejecutar la validación si el informe está en estado `PARCIAL` o el número final de documentos es insuficiente. Tras completarse el corpus, crear una carpeta de resultados y ejecutar el script **original del profesor** desde la raíz:

```powershell
New-Item -ItemType Directory -Force results/validacion | Out-Null
python scripts/check_project.py --sample data/corpus_wikipedia_ciencia/muestra_check_project.csv --model intfloat/multilingual-e5-base --total-docs 2800 --query-prefix "query: " --passage-prefix "passage: " > results/validacion/check_project_wikipedia.txt
```

Cambiar `--total-docs 2800` por la cantidad **real** del informe si es distinta. Una muestra de 300 documentos permite una **estimación** con tokenizador, no el recuento real de todo el corpus. Para la memoria hay que copiar la salida completa. Conservar `sentence-transformers>=5.6` y las versiones compatibles de `transformers` y `huggingface-hub` del entorno Conda existente.

## Preguntas documentales y cross-lingual

Para cada pregunta: registrar texto de consulta, idioma, respuesta, documento de referencia, URL, revisión y frase o pasaje que respalda la respuesta. No usar ejercicios de cálculo que el LLM resolvería sin consultar fuentes. Para etiquetar **cross-lingual** hace falta verificar que **todos los documentos** relevantes que contienen la respuesta están solo en la lengua contraria a la pregunta. La eliminación de equivalentes por Wikidata ID no basta: otros artículos pueden repetir el hecho. Buscar en el idioma de consulta por nombre y variantes, y comparar búsqueda léxica y vectorial antes de validar la pregunta.

## Atribución y limitaciones

Wikipedia está disponible bajo condiciones de licencia y atribución que dependen de la página y de sus contribuciones; conservar enlaces, identificadores de revisión, historial y atribuciones apropiadas. No dar por hecho que cada texto proceda de una única licencia idéntica. La colección es educativa y la selección de categorías no establece calidad factual de todas las páginas: auditar manualmente los documentos y evitar textos con afirmaciones dudosas no contextualizadas.

## Pruebas incluidas

`test_preparar_corpus_offline.py` construye 128 registros artificiales en memoria, prueba descubrimiento, construcción, selección estratificada, muestra y reutilización de la caché. No realiza ninguna petición de red ni certifica la disponibilidad en Wikipedia real.
