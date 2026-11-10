# Exploración del corpus de vehículos militares — BDA

Este es un **análisis exploratorio** anterior a la ingesta del RAG. Usa la **API oficial de Wikipedia**, no descarga FineWiki ni ejecuta el modelo de embeddings. El script no permite asegurar por sí solo que se cumplen todos los mínimos del proyecto.

## Qué hace

- Recorre categorías y subcategorías verificadas de Wikipedia en **español e inglés**, hasta una profundidad y un máximo de categorías controlables.
- Construye un inventario de artículos candidatos, deduplicados por identificador dentro de cada idioma.
- Extrae una muestra **aleatoria** de textos completos mediante MediaWiki TextExtracts, en texto plano, sin scraping HTML. Descarta de la muestra los textos demasiado cortos.
- Calcula palabras de los textos de la muestra y estima número de documentos y chunks posibles en las categorías recorridas. **Los chunks son estimaciones de 180 palabras**, no la medición real del tokenizador de `check_project.py`.
- Conserva título, URL, idioma, categoría y grupo documental para permitir una auditoría manual.

## Antes de ejecutarlo

En tu entorno habitual de BDA basta con tener Python 3.10+ y `requests` (ya se usaba en las prácticas). Se requiere conexión a Internet. Necesitas pasar una URL pública o correo de contacto para identificar tu script ante Wikimedia. El valor no se envía a ninguna persona: aparece en la cabecera `User-Agent` de las peticiones API.

## Ejecución inicial (PowerShell, desde esta carpeta)

```powershell
python .\explorar_corpus_militar.py --contact "https://github.com/blooraayy"
```

Puedes sustituir esa URL por una página o correo de contacto de tu elección.

Por defecto: profundidad 2; hasta 40 categorías por idioma; 120 artículos aleatorios examinados por idioma; mínimo 150 palabras por artículo; pausa de 0,75 s entre peticiones y semilla 42. La API puede necesitar varios minutos para responder, dependiendo del tamaño de las categorías y la red.

Para explorar más categorías después de revisar el primer resultado:

```powershell
python .\explorar_corpus_militar.py --contact "https://github.com/blooraayy" --max-depth 3 --max-categories 100 --sample-per-language 150 --out resultados_exploracion_ampliada
```

**No es necesario hacer la segunda ejecución si el primer resultado ya sugiere un cambio de enfoque.** Tampoco hay que ejecutar todavía `check_project.py` sin comprobar antes que la muestra representa el corpus definitivo.

## Resultados producidos

Los archivos se guardan por defecto en `resultados_exploracion_militar/`:

| Archivo | Utilidad |
|---|---|
| `inventario_candidatos.csv` | Artículos identificados, con idioma, título, URL, grupo y categorías. No se han auditado individualmente. |
| `muestra.csv` | Texto de los artículos aceptados, columnas `text` y `language` (además de metadatos). Compatible en estructura con el formato B del profesor. |
| `auditoria_muestra.csv` | Qué textos se descargaron y cuáles se descartaron por longitud. |
| `informe.json` | Estadísticas reproducibles de documentos, palabras y estimaciones por idioma. |
| `resumen.txt` | Interpretación en texto de los resultados. |

## Limitaciones importantes

1. **Categorías:** la exploración tiene un máximo de categorías; el inventario no representa todos los vehículos de Wikipedia. Algunas categorías contienen artículos que no son modelos de vehículo. Audita una muestra de títulos y elimina ramas irrelevantes antes de extrapolar cifras finales.
2. **Estimación de chunks:** ~180 palabras por chunk es solo la aproximación del enunciado. El recuento definitivo será el de `check_project.py` con el tokenizador y prefijos reales del modelo elegido.
3. **Idiomas:** muestrear el mismo número de artículos en ambos idiomas no implica 50 % de chunks en cada uno. Habrá que equilibrar la muestra final conforme al corpus final, no solo conforme al número de artículos.
4. **Fuente y versión:** el texto descargado pertenece a la Wikipedia actual, no a la versión FineWiki de agosto de 2025. Si la fuente final es FineWiki, habrá que extraer y comprobar una muestra de **FineWiki**. Alternativamente podemos fijar como fuente de nuestro corpus la API de Wikipedia, y documentar la fecha de extracción.
5. **Licencia y atribución:** Wikipedia publica texto reutilizable con condiciones CC BY-SA/GFDL. Conserva título, URL y licencia, y consulta las condiciones específicas de atribución y las políticas de la API. No sustituir ni presentar como datos de War Thunder.
6. **Escalabilidad:** para descargar miles de artículos en la ingesta definitiva, será preferible estudiar un dump o dataset preparado, en lugar de lanzar muchas peticiones a la API; Wikimedia recomienda dumps para grandes volúmenes.
7. **Evaluación:** el script no asegura los 3 metadatos definitivos, ni la calidad temática, ni que haya 5 preguntas evaluables. Esos aspectos requieren validación adicional.

**Política de peticiones:** cabecera de contacto identificable, peticiones secuenciales, pausa y respeto del `Retry-After` en respuestas 429/503. Documentación oficial: https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits

## Qué revisar después

Lo primero será compartir `resumen.txt` y, si es posible, `auditoria_muestra.csv`, para analizar si hay suficientes documentos realmente útiles y qué distribución lingüística se obtiene. Después decidiremos si ampliar categorías, incorporar tecnología militar o cambiar la fuente definitiva.
