# BDA — Physics & Mathematics Educational RAG

Proyecto individual de Bases de Datos Avanzadas. Fase actual: exploración de dos fuentes de problemas resueltos, sin ingesta en PostgreSQL todavía.

Consulta las instrucciones de `docs/README_exploracion.md`.

## Datos previstos (sujetos a validación)

- PolyUniMath: problemas matemáticos multilingües (es/en)
- PhysicsEval: problemas físicos (en)
- Documento: un problema con su solución
- Metadatos potenciales: dominio, temática, dificultad, fuente, tipo de pregunta, idioma

## Mínimos del enunciado

- 25.000 chunks de 256 tokens y 1.000 documentos independientes (se recomiendan 50.000 chunks)
- Dos idiomas; cada uno al menos 20 % de chunks
- Tres metadatos por documento, además del idioma, y al menos uno útil para filtros
- Modelo de embeddings para búsqueda de dimensión <= 1024 y max_seq_length >= 512, sentence-transformers >= 5.6 sin código remoto
- Propuesta hasta dos páginas más salida de `check_project.py`

Esta carpeta incorpora el `check_project.py` original aportado por el profesor. No se ha ejecutado aún con datos reales.
