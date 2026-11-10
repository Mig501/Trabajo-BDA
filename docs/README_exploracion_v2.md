# Exploración del corpus militar v2 — BDA

Esta versión mejora la primera exploración tras examinar los resultados del 10 de noviembre de 2026. **No implementa el RAG ni sustituye a `check_project.py`.**

## Problemas detectados en v1

- Sólo se visitaron 40 categorías por idioma, distribuidas de manera desigual entre tanques, aeronaves, buques y helicópteros.
- Se incluyeron artículos ajenos al objetivo, como `Elvis Presley` (rama `Tank personnel`) y `Stalingrado (película de 1993)`.
- La muestra contenía cantidades casi iguales de artículos españoles e ingleses, pero el inventario estimado no tenía esa distribución. No debe trasladarse directamente a la propuesta.
- Aproximadamente 14.232 chunks: por debajo de los 25.000 mínimos, antes de limpiar artículos irrelevantes.

## Cambios en v2

- Hasta 70 categorías **por tipo de vehículo y por idioma** (8 grupos en total), con profundidad máxima 3 por defecto.
- Excluye ramas claramente no documentales (personal, cine, listados, accidentes, etc.). La exclusión es conservadora: puede mantener falsos positivos y eliminar contenido contextual que no sea imprescindible.
- Examina hasta 40 artículos de cada grupo e idioma. La estimación usa las medias y tasas de aceptación de **cada grupo**, ponderadas por su número de candidatos, no una sola media mezclada.
- Conserva los artículos y las estadísticas en CSV/JSON, con una hoja específica para revisión manual.
- **La muestra de v2 es exploratoria, no representativa en las proporciones del corpus completo. No se debe usar directamente en el comprobador del profesor.**

## Ejecutar (desde la raíz de BDA-military-rag)

```powershell
python scripts/explorar_corpus_militar_v2.py --contact "https://github.com/Mig501/Trabajo-BDA" --out data/exploracion_v2
```

El parámetro `--contact` sólo identifica las solicitudes a la API Wikimedia; no accede a tu cuenta GitHub.

Puedes limitar la exploración, por ejemplo, con `--max-categories-per-group 30 --sample-per-group 20`, o ampliarla con `--max-categories-per-group 100 --sample-per-group 50`. La versión predeterminada ya incrementa notablemente la exploración respecto de v1. La API puede ser lenta: respeta pausas y políticas de Wikimedia.

## Archivos de salida

- `resumen.txt`: estimación por grupo e idioma y total.
- `informe.json`: estadísticas y parámetros de la ejecución.
- `inventario_candidatos.csv`: artículos candidatos, todavía sin validar individualmente.
- `muestra_exploratoria.csv`: textos extraídos; columnas `text` y `language` entre otras.
- `revision_manual.csv`: muestra de títulos, categoría y longitud, con `needs_review`; permite rellenar `relevant_manual` y `comments` manualmente.

### Cómo interpretar

1. Comprobar que hay bastantes artículos en español e inglés y que la suma aproximada de chunks supera holgadamente 25.000.
2. Revisar en `revision_manual.csv` una selección aleatoria de artículos de los ocho grupos. La longitud suficiente (`valid_length=1`) **no equivale** a relevancia temática.
3. Si la muestra contiene artículos sobre personas, películas, unidades o temas fuera de alcance, filtrar categorías o ajustar el ámbito antes de volver a extrapolar.
4. Una vez confirmado el inventario final, extraer una muestra representativa del **corpus final** (50–500 documentos, proporciones por **chunks** según el README del profesor) y ejecutar `check_project.py` usando el tokenizador y prefijos del modelo.

## Límites

- Los chunks siguen siendo aproximaciones de 180 palabras, no una evaluación con el tokenizador E5.
- La API obtiene Wikipedia actual, **no** FineWiki 2025. No se deben mezclar ambas versiones al evaluar la propuesta.
- El inventario es una exploración limitada de categorías; no cubre exhaustivamente Wikipedia. La elección aleatoria de subcategorías puede alterar los resultados.
- La extensión de texto se ha obtenido de la API de Wikipedia; se han de mantener URL/atribución y respetar condiciones de Wikimedia.
- Este programa no certifica las licencias, 3 metadatos obligatorios, el modelo, las 5 preguntas con documentos concretos ni la calidad de recuperación. Todo ello debe documentarse aparte.

## Qué enviar después

Comparte `resumen.txt`, `informe.json` y `revision_manual.csv` de la ejecución v2. Con ellos podemos comparar por grupo, revisar relevancia y decidir cómo crear el corpus definitivo.
