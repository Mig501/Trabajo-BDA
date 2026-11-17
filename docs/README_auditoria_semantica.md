# Auditoría semántica y línea base de recuperación vectorial — BDA

## Propósito

Usar `intfloat/multilingual-e5-base` sobre **los 28.640 chunks** del corpus congelado de Wikipedia científica, identificar el rango de los chunks de evidencia de las cinco preguntas y generar candidatos del **idioma de la pregunta** para comprobar si contienen respuestas alternativas. **No clasifica automáticamente ninguna pregunta como cross-lingual válida.**

## Preparación

Copiar el script `scripts/auditar_retrieval_semantico.py` al repositorio. Mantener los archivos que ya se han creado:

- `data/corpus_wikipedia_ciencia/corpus_candidato.jsonl`
- `data/evaluacion/preguntas_piloto_v2.csv`
- `data/evaluacion/auditoria/preguntas_auditadas.csv`

En el entorno `Advanced_DBs` (con sentence-transformers 6.1.0 y huggingface-hub compatible):

```powershell
python scripts/auditar_retrieval_semantico.py --corpus data/corpus_wikipedia_ciencia/corpus_candidato.jsonl --preguntas data/evaluacion/preguntas_piloto_v2.csv --auditoria data/evaluacion/auditoria/preguntas_auditadas.csv --out data/evaluacion/semantic --model intfloat/multilingual-e5-base --expected-chunks 28640 --batch-size 32 --top 30 --revision-top 40
```

**No borrar** la carpeta `data/evaluacion/semantic/` después: contiene los embeddings (`embeddings_e5.npy`, unos 88 MB), chunks y manifiesto; el script verificará el hash del corpus y reutilizará la caché en ejecuciones posteriores.

## Archivos de salida

- `informe_semantico.json`: estructura del corpus, métricas exploratorias y resultados de las 5 preguntas.
- `resumen_retrieval.csv`: rango del artículo esperado y **de los chunks de evidencia** en todo el corpus; Hit@5/Hit@10 de cobertura completa y Hit@5 parcial exploratorios.
- `top_global.csv`: primeros 30 chunks de cada búsqueda entre los dos idiomas, con fragmentos para revisión.
- `revision_crosslingual_idioma_pregunta.csv`: los 40 chunks vectorialmente más similares **en el idioma de consulta** para P01 y P02. Incluye columnas editables para anotar si existe otra respuesta.
- `embeddings_e5.npy`, `chunks_indexados.jsonl`, `manifest_embeddings.json`: caché de vectores normalizados y chunks trazables.

## Cómo interpretar resultados

1. Un Hit@5 de **cobertura completa** positivo significa que se recuperan **todos los chunks solapados por la cita de evidencia**, no solo el artículo relacionado. Si la cita cruza dos chunks, recuperar solo uno se informa como Hit@5 parcial. Si no hay índices de evidencia en `preguntas_auditadas.csv`, el script no atribuye Hit@5 automáticamente.
2. Revisar manualmente los 40 primeros candidatos del **idioma de la pregunta** para cada pregunta cross-lingual. Marcar si el fragmento permite responder, aunque no use literalmente los mismos nombres.
3. **No** declarar exclusividad solo porque no haya respuesta entre los 40 primeros: pueden existir otras paráfrasis más abajo. Usar la revisión semántica como cribado y complementarla con variantes léxicas, FTS y, cuando sea necesario, comprobación de fuentes relacionadas.
4. Este script ejecuta búsqueda exacta sobre todos los embeddings, pero **no sustituye** a PostgreSQL/pgvector ni al experimento final de FTS vs vectorial vs híbrido.
5. Seguir el protocolo `docs/protocolo_evaluacion.md` para las 10 preguntas `dev` y 50 preguntas `test` una vez seleccionadas, sin medir el rendimiento definitivo con las cinco del piloto.

## Advertencias técnicas

La segmentación sigue el conteo de la auditoría E5: 256 tokens incluyendo 4 del prefijo y tokens especiales, 252 de texto. El texto de los chunks se reconstruye con `tokenizer.decode`; el recuento de chunks es exacto respecto al tokenizador, pero su texto puede variar ligeramente en espacios y signos respecto al documento original. Si se cambia la ingesta definitiva, hay que recontar e indexar de forma idéntica en todos los métodos.
