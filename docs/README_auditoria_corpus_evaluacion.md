# BDA — Auditoría del corpus y preguntas documentales

Este paquete contiene 5 **preguntas piloto** con enunciado, respuesta, cita exacta, URL e identificador/revisión de Wikipedia. No es todavía el test definitivo de 50 preguntas.

## Instalación

Copiar `scripts/auditar_corpus_y_preguntas.py` y `data/evaluacion/preguntas_piloto_v2.csv` a las mismas rutas dentro del repositorio `Trabajo-BDA`. Mantener el corpus en `data/corpus_wikipedia_ciencia/corpus_candidato.jsonl`.

## Auditoría completa con el tokenizador de E5 (recomendada)

En el entorno `Advanced_DBs`, desde la raíz del repositorio:

```powershell
python scripts/auditar_corpus_y_preguntas.py --corpus data/corpus_wikipedia_ciencia/corpus_candidato.jsonl --preguntas data/evaluacion/preguntas_piloto_v2.csv --out data/evaluacion/auditoria --model intfloat/multilingual-e5-base
```

Se reutiliza el modelo E5 descargado previamente. No se recalculan embeddings, solo los IDs de tokens; para obtener los chunks se usa el mismo cálculo de `check_project.py` (256 tokens de límite, menos el prefijo y tokens especiales).

## Alternativa: auditoría sin descargar modelo

```powershell
python scripts/auditar_corpus_y_preguntas.py --sin-tokenizador
```

## Archivos de salida

- `informe_auditoria.json`: integridad del corpus, chunks exactos si se usa tokenizer, proporciones por idioma y estado de preguntas.
- `chunks_por_documento.csv`: cada documento con su número real de chunks (solo con tokenizer).
- `preguntas_auditadas.csv`: evidencia existente, aliases de respuesta, coincidencias literales en el idioma de la pregunta y rango de chunk de evidencia.
- `coincidencias_idioma_pregunta.csv`: detalles de cualquier coincidencia literal en otros documentos.

**Importante:** incluso si una respuesta no aparece literalmente en el idioma de la pregunta, NO se ha probado todavía la exclusividad cross-lingual. Para ello hay que revisar posibles paráfrasis, traducciones y documentos relacionados mediante recuperación vectorial y FTS, seguida de revisión humana. El script nunca da por verificadas esas preguntas.

Las cinco preguntas son propuestas iniciales para el documento del proyecto; la evaluación final de 50 preguntas y sus métricas se realizará posteriormente. No modificar el conjunto de preguntas de test basándose en los resultados finales sin registrar una nueva versión.
