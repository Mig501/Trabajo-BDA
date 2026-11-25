# BDA — Ampliación incremental de Wikipedia científica

## Objetivo

Pasar del corpus ya auditado de **3.600 documentos y 28.640 chunks exactos** a aproximadamente **6.600 documentos** (1.800 ES, 4.800 EN). La proyección es de **~53.100 chunks**, pero **no está garantizada**: depende de que existan suficientes artículos válidos en el inventario original. El programa mide los chunks reales usando E5 al final.

**Ventaja principal:** el programa **no elimina, no reemplaza y no vuelve a descargar** ningún documento del corpus original. Conserva sus textos, identificadores, revisiones y enlaces; añade artículos procedentes del inventario descubierto anteriormente. Por eso no destruye las evidencias de las preguntas ya construidas. La aparición de NUEVAS fuentes alternativas puede, no obstante, cambiar la exclusividad cross-lingual de esas preguntas: habrá que reevaluarlas.

## Instalación

Copiar `scripts/ampliar_corpus_wikipedia.py` a la carpeta `scripts/` del repositorio `Trabajo-BDA` (sin sobrescribir los scripts anteriores).

Se necesitan los scripts existentes `scripts/preparar_corpus_wikipedia.py` y `scripts/explorar_wikipedia_ciencia.py` y sus dependencias (`requests`; `sentence-transformers` para contar tokens).

## Ejecución desde PowerShell (entorno Advanced_DBs)

### 1. Comprobación del inventario, sin internet ni cambios

```powershell
python scripts/ampliar_corpus_wikipedia.py --phase plan --target-es 1800 --target-en 4800
```

Comprueba los candidatos **pendientes** en ES/EN y las cuotas. Las cifras de candidatos son anteriores a los filtros de calidad: no garantizan que todos puedan seleccionarse.

### 2. Ampliación incremental, con caché y límites de descarga

```powershell
python scripts/ampliar_corpus_wikipedia.py --phase extend --target-es 1800 --target-en 4800 --max-new-fetches 1500 --delay 0.5
```

La primera vez puede finalizar con `Estado: PARCIAL` porque el límite por ejecución es 1.500 peticiones **nuevas**. **Repite exactamente el mismo comando** hasta ver `Estado: COMPLETO` o hasta que el inventario se agote. Las páginas aceptadas en ejecuciones anteriores se reutilizan sin modificaciones y las páginas consultadas se guardan en caché.

En caso de error HTTP 429, **no reintentes inmediatamente**. Respeta las restricciones del servicio. Las solicitudes utilizan `User-Agent` con contacto, pausas y `maxlag`.

Si el estado queda `PARCIAL` tras consumir todos los candidatos, comparte el informe para decidir si ampliar justificadamente el inventario, en una ruta distinta.

### 3. Recuento exacto de chunks mediante el tokenizador de E5

Solo cuando el informe de la ampliación indique `COMPLETO`:

```powershell
python scripts/ampliar_corpus_wikipedia.py --phase count --out data/corpus_wikipedia_ciencia/ampliacion_50k --model intfloat/multilingual-e5-base
```

Genera `informe_chunks_reales.json` y `chunks_por_documento.csv`; utiliza la segmentación de **256 tokens totales** y el mismo margen del prefijo `passage: ` que en la auditoría anterior. No calcula embeddings (solo tokeniza).

### 4. Comprobación oficial del profesor

Si el recuento real y los porcentajes por idioma son adecuados:

```powershell
python scripts/check_project.py --sample data/corpus_wikipedia_ciencia/ampliacion_50k/muestra_check_project.csv --model intfloat/multilingual-e5-base --total-docs 6600 --query-prefix "query: " --passage-prefix "passage: " > results/validacion/check_project_wikipedia_ampliado.txt
```

**Importante:** sustituir `6600` por el número real de documentos si no se han alcanzado ambos objetivos. El comprobador hace una estimación a partir de la muestra; `informe_chunks_reales.json` contiene el recuento integral.

## Archivos generados

Todos los resultados se guardan **separadamente**, bajo `data/corpus_wikipedia_ciencia/ampliacion_50k/`:

- `corpus_ampliado.jsonl`: corpus antiguo íntegro más documentos nuevos.
- `resumen_ampliacion.txt` / `informe_ampliacion.json`: estado, cantidades, SHA-256 e incidencias.
- `muestra_check_project.csv`: nueva muestra estratificada de 300 artículos.
- `inventario_corpus.csv`: metadatos de todos los artículos sin el texto.
- `nuevos_documentos.csv`: solo documentos añadidos en esta fase.
- `auditoria_nuevos.csv`: rechazos, razones y procedencia.
- `informe_chunks_reales.json` / `chunks_por_documento.csv`: recuento del tokenizador (tras la fase `count`).
- `cache/pages_by_id/`: versiones descargadas por page ID; permite reanudar.

## Reproducibilidad e integridad

- La semilla es `42` y el origen es el inventario original, **sin redescubrir categorías**.
- Se verifica el SHA-256 del corpus congelado de 3.600 documentos (`12a4486e...f99304`). Si el archivo base cambia, el script se detiene para evitar mezclar versiones.
- El programa revisa duplicados de `document_id`, identificador Wikidata y texto exacto.
- Los textos y metadatos de los 3.600 artículos existentes se conservan **sin modificaciones**.
- Cada documento nuevo conserva su `revision_id` y `revision_timestamp`, que son de edición de Wikipedia y **no** equivalen a año histórico o de descubrimiento.
- Los 50.000 chunks son recomendados, no un requisito mínimo; debe medirse el valor real. La viabilidad de la cuota depende del inventario y los filtros.

## Después de la ampliación

Enriqueceremos `entity_type`, `country`, `event_year`/`event_start_year` y `event_end_year` **con evidencia y procedencia** (por ejemplo Wikidata), distinguiendo tipo de entidad, fecha histórica de un evento, año de nacimiento y fecha de edición. Valores ambiguos o ausentes se dejarán nulos. Finalmente se repetirán la evaluación de las preguntas y la auditoría de exclusividad cross-lingual.
