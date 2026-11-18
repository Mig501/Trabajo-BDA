# Banco de evaluación BDA — revisión v2 (18-11-2026)

Contiene las mismas 60 preguntas de v1 (10 DEV y 50 TEST, 10 TEST cross-lingual) salvo dos correcciones:

- **T46:** redacción precisa: la Junta de Gobierno de la UNAM nombró al director, no el instituto. La fuente y respuesta se mantienen.
- **T50:** reemplazada la pregunta autorreferencial sobre un supuesto «título original», que el artículo no acredita, por el departamento y universidad a los que se incorporó Nikolái Delaunay en 1900. Nueva respuesta y evidencia exacta.

Las restantes preguntas y sus referencias no cambian. Las cinco preguntas piloto anteriores no están incluidas.

## Estado de validación

- DEV: 10/10 Hit@5 provisional en la revisión de v1; **no recalculado** en v2 (las 10 preguntas DEV no cambian).
- TEST: **0 evaluadas** para rendimiento. No hacer consultas globales ni ajustar el sistema con TEST antes de la ingesta y el congelamiento del pipeline.
- CROSS: los 400 fragmentos top-40 recuperados en el idioma de consulta se han cribado buscando hechos y nombres relacionados; no se ha hallado evidencia suficiente obvia, pero **esto NO demuestra exclusividad semántica**. La nueva T50 requiere repetir el análisis. No convertir esta clasificación en validación definitiva.

## Repetir auditoría sobre caché E5 sin calcular TEST

Desde la raíz de Trabajo-BDA, con la caché semántica ya creada:

```powershell
python scripts/revisar_banco_preguntas.py --corpus data/corpus_wikipedia_ciencia/corpus_candidato.jsonl --preguntas data/evaluacion/banco_v2/preguntas_candidatas.csv --semantic-cache data/evaluacion/semantic --out data/evaluacion/banco_v2/revision --top-cross 40 --top-dev 10
```

Después, inspeccionar los resultados del idioma de consulta y etiquetar manualmente si alguno contiene la respuesta específica (no solo términos en común). Esta comprobación no sustituye la comparación de recuperación vectorial, FTS e híbrida en PostgreSQL.
