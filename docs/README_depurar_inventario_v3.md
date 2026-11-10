# Depuración v3 del inventario militar — proyecto BDA

## Objetivo

Clasificar **provisionalmente** los artículos candidatos descubiertos en `explorar_corpus_militar_v2.py` usando metadatos de Wikipedia/Wikidata y preparar una **auditoría manual estratificada**. Todavía no hay ingesta en PostgreSQL, ni se generan embeddings.

El problema que resuelve: la v2 encontró aproximadamente 36.638 chunks en un inventario de más de 5.000 candidatos, pero esa estimación incluía artículos sobre satélites, personajes, películas y otros temas. Es necesario filtrar antes de presentar el corpus al profesor.

## Qué hace la versión 3

1. Lee `data/exploracion_v2/inventario_candidatos.csv` (el **inventario completo** de v2, no su `revision_manual.csv`).
2. Consulta mediante API el identificador Wikidata de cada página (`wikibase_item`), y sus descripciones en inglés y español.
3. Clasifica por **descripción** como `incluir_provisional`, `excluir_provisional` o `revisar`. Si la descripción no es suficientemente clara, **no fuerza una clasificación**. También hay falsos positivos/negativos: no es una certificación de relevancia.
4. Prepara una muestra aleatoria y estratificada por idioma, grupo y estado, para revisar manualmente casos incluidos, excluidos y ambiguos.
5. Guarda las respuestas en archivos de caché, de modo que una auditoría corregida no requiera nuevas consultas a Wikimedia.

**Importante**: Este script utiliza las **descripciones** de Wikidata, no un razonador exhaustivo de la jerarquía `instance of`/`subclass of`. Por ello, la auditoría humana es necesaria.

## Ejecución desde la raíz de `BDA-military-rag`

Activa el entorno habitual `bdav` y comprueba que `requests` está instalado. La primera ejecución consultará Wikimedia; necesita conexión a Internet.

```powershell
python scripts/depurar_inventario_v3.py --inventario data/exploracion_v2/inventario_candidatos.csv --out data/exploracion_v3 --contact "https://github.com/Mig501/Trabajo-BDA" --informe-v2 data/exploracion_v2/informe.json
```

`--contact` solo se utiliza para identificar las solicitudes a Wikimedia, **no accede a GitHub**. El programa envía las consultas por lotes, introduce una pausa y respeta indicaciones de reintento de las APIs. Las consultas pueden tardar, según la conexión y la disponibilidad del servicio. Si se interrumpe, vuelve a ejecutar el comando: la caché conserva los lotes terminados.

**No ejecutes la versión 2 otra vez**, salvo que hayas perdido su inventario completo. Debe existir `data/exploracion_v2/inventario_candidatos.csv`. Si solo conservas los tres archivos de resultados que compartiste, vuelve a tu carpeta local de ejecución: el archivo de inventario se generó allí.

## Archivos generados

| Archivo | Contenido |
|---|---|
| `inventario_clasificado.csv` | Todas las entradas, con descripción Wikidata, estado provisional y razón |
| `preseleccion_provisional.csv` | Entradas con evidencia textual favorable, **todavía no validadas** |
| `pendientes_revision.csv` | Entradas sin información suficiente o con indicios contradictorios |
| `muestra_para_revision.csv` | Muestra estratificada para revisar manualmente (columna `decision_manual`) |
| `resumen_v3.txt` | Resumen de cifras por idioma, sin confundirlas con chunks reales |
| `informe_v3.json` | Estadísticas por idioma y grupo; incluye, si se aporta v2, indicadores orientativos |
| `cache_page_qids.json`, `cache_wikidata_descriptions.json` | Respuestas de APIs para no repetir consultas |

## Revisión manual

Abre `muestra_para_revision.csv` (una copia independiente si prefieres trabajar en Excel). Para cada artículo revisado, anota en la columna `decision_manual`:

- `incluir`: describe un modelo, familia, clase o tecnología de un vehículo militar dentro de nuestro alcance.
- `excluir`: trata de personas, películas, satélites, vehículos civiles u otros temas fuera del alcance.
- Déjalo vacío: no se ha revisado todavía.

**Conserva una copia** del CSV editado, por ejemplo `data/exploracion_v3/decisiones_manual.csv`, porque ejecutar de nuevo la depuración vuelve a generar `muestra_para_revision.csv`.

Para aplicar las correcciones sin consultar Internet otra vez:

```powershell
python scripts/depurar_inventario_v3.py --inventario data/exploracion_v2/inventario_candidatos.csv --out data/exploracion_v3 --contact "https://github.com/Mig501/Trabajo-BDA" --informe-v2 data/exploracion_v2/informe.json --offline --decisiones data/exploracion_v3/decisiones_manual.csv
```

Puedes usar la misma estructura para añadir decisiones manuales de cualquier artículo que no haya salido en la muestra; basta con columnas `language`, `page_id` y `decision_manual`.

## Cómo interpretar el volumen

El script **no descarga ni tokeniza el texto de los miles de artículos**. Los valores opcionales que reescalan las estimaciones de v2 usando la proporción de artículos seleccionados **no son recuentos reales de chunks** ni intervalos de confianza. No los uses como cifras definitivas de la propuesta.

Para confirmar que llegamos a los **25.000 chunks y los 1.000 documentos**, en el siguiente paso necesitaremos obtener el texto real del inventario depurado, preparar una muestra representativa de **50–500 documentos** con las proporciones adecuadas **por chunks**, y ejecutar el `check_project.py` oficial con el modelo de embeddings elegido. Si nuestra fuente definitiva es FineWiki, esa muestra debe extraerse de FineWiki; si es Wikipedia API actual, debe venir de esa fuente. No mezclar versiones.

## Licencias y procedencia

- Wikidata (metadatos estructurados): CC0.
- Texto Wikipedia: comprobar la licencia de cada página y conservar título, URL, autoría/atribuciones y versión/fecha.
- No se utiliza contenido propietario del videojuego War Thunder.

## Límites

- Los patrones de clasificación son **heurísticas conservadoras**, no una verificación completa de la ontología de Wikidata.
- Una página relevante puede quedar `revisar` por carecer de descripción, y una irrelevante puede quedar `incluir_provisional` si su descripción induce a error.
- Un documento puede describir una clase de vehículos y no un vehículo individual; ambos pueden ser citables, pero deben seguir el alcance acordado.
- No completa por sí solo los metadatos obligatorios del proyecto ni genera las cinco preguntas de evaluación.
