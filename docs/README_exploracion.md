# BDA — Exploración piloto de Física y Matemáticas

Este paso **solo evalúa la viabilidad** de utilizar problemas resueltos de dos fuentes:

- [PolyUniMath](https://huggingface.co/datasets/friederrr/PolyUniMath) (matemáticas, varios idiomas): 4,29 millones de filas declaradas; formato Parquet; licencia declarada CC BY-NC 4.0.
- [PhysicsEval](https://huggingface.co/datasets/IUTVanguard/PhysicsEval) (física en inglés): 19.609 filas; JSON; licencia declarada CC BY-SA 4.0.

**Aviso de licencias:** ambos conjuntos incluyen material procedente de otros textos, incluidos PDFs y libros. La licencia indicada en la ficha del dataset no garantiza por sí sola la autorización de todos los documentos de origen. Revisar atribución, procedencia y condiciones antes de fijar el corpus.

## 1. Organización

```text
BDA-fisica-matematicas/
├── README.md
├── scripts/
│   ├── explorar_fismat.py
│   └── check_project.py           # ORIGINAL del profesor; no modificar
├── docs/
│   ├── README_exploracion.md
│   └── README_check_project.md    # ORIGINAL del profesor
├── data/
│   └── exploracion_fismat/        # resultados nuevos
└── results/
    └── validacion/
```

## 2. Requisitos

Desde la raíz del proyecto, en tu entorno `bdav`:

```powershell
pip install requests
```

El script usa la **API pública del Dataset Viewer** de Hugging Face. No descarga completos los datasets de 5,23 GB y 302 MB. Para obtener un pequeño número de filas, consulta bloques cortos en posiciones aleatorias.

## 3. Primera ejecución (piloto)

```powershell
python scripts/explorar_fismat.py --contact "https://github.com/Mig501/Trabajo-BDA" --out data/exploracion_fismat
```

Por defecto intenta obtener 300 documentos válidos:

- 120 problemas de **matemáticas en español** de PolyUniMath.
- 60 problemas de **matemáticas en inglés** de PolyUniMath.
- 120 problemas de **física en inglés** de PhysicsEval.

Cada documento contiene **problema, solución y respuesta**, si esta última está disponible; se descartan las filas sin problema o sin solución, así como los textos de menos de 60 palabras. Se conservan identificadores y metadatos para una futura evaluación de la relevancia documental.

Si deseas una prueba más ligera:

```powershell
python scripts/explorar_fismat.py --math-es 40 --math-en 20 --physics-en 40 --contact "https://github.com/Mig501/Trabajo-BDA" --out data/prueba_rapida
```

## 4. Archivos de salida

```text
data/exploracion_fismat/
├── resumen.txt                 # indicadores legibles
├── informe.json                # estadísticas detalladas, avisos API
├── auditoria.csv               # identificadores, longitudes, materias y procedencia
└── muestra_exploratoria.csv    # documentos reales, columna text y language
```

Pásame primero **`resumen.txt`, `informe.json` y `auditoria.csv`**, y si puedes también `muestra_exploratoria.csv`. Así podremos medir si las soluciones son útiles y cuántos documentos de cada fuente harían falta.

## 5. Lo que sí y lo que no valida esta prueba

**Sí:** texto real, presencia de soluciones, longitudes, metadatos y ejemplos que permitan redactar preguntas de evaluación.

**No:** volumen de los datasets completos, distribución real por idioma, cumplimiento de 25.000 chunks o viabilidad definitiva.

La muestra es **exploratoria y estratificada por fuente/idioma** (y procede de bloques cortos en posiciones aleatorias), no una muestra aleatoria simple representativa del corpus definitivo. El número aproximado de chunks se estima usando 180 palabras por chunk, no el tokenizador E5. **No uses esta muestra directamente en el `check_project.py` del profesor para justificar el corpus final.**

La API `/filter` puede operar sobre solo una parte de un dataset grande. El informe registra `api_partial`; si vale `true`, no extrapoles sus recuentos a los 4,29 millones de PolyUniMath. Si falla o limita consultas, necesitaremos otro método (Parquet por fragmentos/streaming) antes de seleccionar el corpus.

## 6. Siguiente fase

Con las medias medidas, elegiremos una composición viable (número de problemas matemáticos en español, matemáticos en inglés y físicos en inglés), construiremos una muestra final aleatoria con la misma distribución de **chunks** y ejecutaremos `check_project.py` usando los prefijos indicados por la tarjeta del modelo (`query: ` y `passage: ` para E5).

Fuentes técnicas de la API: https://huggingface.co/docs/dataset-viewer/rows y https://huggingface.co/docs/dataset-viewer/filter.
