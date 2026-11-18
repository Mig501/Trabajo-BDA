# Banco de preguntas de evaluación — Wikipedia científica (BDA)

**Estado: 60 preguntas CANDIDATAS con evidencia literal en el corpus. No son todavía 60 preguntas definitivamente validadas.** Se conserva aparte el piloto P01–P05, usado durante el desarrollo.

## Resultados obtenidos con el corpus subido

- SHA-256 del corpus: `12a4486e2ba6fde7c9548751306fceb4870794c6fda36276880144cf45f99304`.
- Total corpus: **3.600 documentos**, **28.640 chunks** contados en la auditoría anterior.
- **60 candidatas** (50 TEST y 10 DEV), cada una con un documento distinto y una frase que incluye su respuesta textual. Esto último se ha verificado automáticamente sobre el texto exacto de la revisión guardada.
- TEST: ES→ES **20**, EN→EN **20**, ES→EN **5**, EN→ES **5**. DEV: 5 ES→ES y 5 EN→EN.
- Temas en TEST: física **12**, matemáticas **13**, química **12**, astronomía **13**.
- En tres candidatas cross (T43, T44 y T48) se ha detectado la **cadena literal de la respuesta en documentos del idioma de consulta**. Una coincidencia puede ser irrelevante, pero obliga a inspeccionar el contexto. El resto tampoco se considera validado sin inspección semántica.
- La selección está **curada manualmente**, no es aleatoria ni una estimación estadística de dificultad; se debe explicar así en la memoria. La asignación temática/idiomática sí fue predefinida.

## Archivos

- `data/evaluacion/banco_v1/preguntas_candidatas.csv`: las 60 preguntas, respuesta, URL, `document_id`, `revision_id`, texto de evidencia y estados de auditoría.
- `data/evaluacion/banco_v1/preguntas_TEST.csv`: copia de las 50 candidatas de prueba (reservadas para evaluar **solo después** del ajuste en DEV).
- `data/evaluacion/banco_v1/preguntas_DEV.csv`: las 10 preguntas de desarrollo.
- `data/evaluacion/banco_v1/auditoria_literal.csv`: coincidencias exactas de respuestas cross en el idioma de consulta; **no valida exclusividad**.
- `data/evaluacion/banco_v1/plantilla_revision_manual.csv`: decisiones de un revisor sobre cada pregunta (sin rellenar).
- `data/evaluacion/banco_v1/informe_banco.json`: conteos y advertencias.
- `scripts/crear_banco_preguntas.py`: reconstruye el banco contra el corpus congelado y comprueba sus evidencias.
- `scripts/revisar_banco_preguntas.py`: calcula el tramo de chunks que contiene las evidencias, consulta la caché vectorial previa sobre las **10 DEV** y genera una lista de **40 fragmentos en el idioma de consulta para cada pregunta cross**. No evalúa las 50 TEST.

## Cómo usarlo en Windows PowerShell

Extraer el ZIP en la **raíz del repositorio**, manteniendo `scripts/`, `data/` y `docs/`. Los 60 registros generados ya están incluidos, así que **no hay que reconstruirlos** para el siguiente paso.

El script de auditoría semántica anterior debe haber dejado una caché válida en `data/evaluacion/semantic/` con:

- `embeddings_e5.npy`
- `chunks_indexados.jsonl`
- `manifest_embeddings.json`

Ejecutar con el entorno Conda `Advanced_DBs` activado:

```powershell
python scripts/revisar_banco_preguntas.py --corpus data/corpus_wikipedia_ciencia/corpus_candidato.jsonl --preguntas data/evaluacion/banco_v1/preguntas_candidatas.csv --semantic-cache data/evaluacion/semantic --out data/evaluacion/banco_v1/revision --top-cross 40 --top-dev 10
```

Salidas:

- `data/evaluacion/banco_v1/revision/preguntas_con_gold_provisional.csv`: ID de chunk propuesto por offsets del tokenizador. **Hay que comprobar manualmente qué chunk(s) contienen evidencia suficiente**.
- `data/evaluacion/banco_v1/revision/revision_crosslingual_semantica.csv`: **400 fragmentos** (10 preguntas × 40 resultados del idioma de la pregunta). Editar las columnas `contains_sufficient_answer` y `review_notes` después de examinarlos. Si alguno responde suficientemente, se descarta o reformula la pregunta y se repite la revisión.
- `data/evaluacion/banco_v1/revision/resumen_dev.csv` y `top_dev.csv`: recuperación vectorial de las 10 preguntas DEV.
- `data/evaluacion/banco_v1/revision/informe_revision.json`: métricas provisionales y conteos; **no son resultados finales de TEST**.

**Envíame en la siguiente iteración:** `informe_revision.json`, `resumen_dev.csv` y `revision_crosslingual_semantica.csv` (puedes comprimir este último). Revisaremos las diez preguntas cross, marcaremos las inválidas y, si es necesario, generaremos sustitutas. El ensayo final de 50 preguntas queda reservado para la indexación PostgreSQL/pgvector y las comparaciones vectorial/FTS/híbrida.

## Criterios de revisión

1. Pregunta concreta que no incluya la respuesta; sin cálculos ni definiciones generales.
2. Evidencia textual suficiente, respuesta correcta y sin ambigüedad; no confundir una mención de la respuesta con el hecho pedido.
3. Revisar los campos `gold_chunk_ids` y todas las posibles fuentes relevantes, no solo el documento elegido.
4. En cross, auditar *todo el corpus del idioma de la pregunta*, incluidas paráfrasis, otros artículos y transliteraciones; la lista top-40 es solo una primera criba.
5. En TEST, no retocar el ranking ni los parámetros basándose en sus resultados: usar solo DEV para ajustes. Tras fijar parámetros y revisar etiquetas, ejecutar TEST una vez y conservar las métricas.
