# Preparación del corpus candidato — BDA (Física y Matemáticas)

## Objetivo

Construir **un corpus candidato real**, no una extrapolación, a partir de los Parquet de `friederrr/PolyUniMath` y del JSON de `IUTVanguard/PhysicsEval`. No utiliza los endpoints `/filter` ni `/rows` del Dataset Viewer. Mantiene los registros y sus metadatos, deduplica preguntas, excluye registros con problemas de calidad evidentes y selecciona una muestra para el `check_project.py` original del profesor.

**No garantiza corrección matemática ni permisos de los materiales originales**. La fuente de PhysicsEval incluye material de libros comerciales; documentar procedencia y condiciones de uso y no redistribuir los textos sin verificar los derechos.

## 1. Dependencias

Desde el entorno `bdav` (Windows / PowerShell):

```powershell
conda activate bdav
pip install -U huggingface_hub pyarrow
```

El comprobador oficial necesita adicionalmente `sentence-transformers>=5.6` y `pandas`:

```powershell
pip install -U "sentence-transformers>=5.6" pandas
```

## 2. Ubicación de archivos

```text
BDA-fisica-matematicas/
├── scripts/
│   ├── preparar_corpus_candidato.py       ← nuevo
│   ├── check_project.py                   ← original del profesor
│   └── explorar_fismat_archivos.py        ← piloto anterior (opcional)
├── docs/
│   ├── README_corpus_candidato.md         ← este documento
│   └── README_check_project.md            ← original del profesor
├── data/
│   └── corpus_candidato/                  ← salida, no subir los textos a GitHub
└── results/
    └── validacion/
```

## 3. Ejecutar (desde la raíz del proyecto)

```powershell
python scripts/preparar_corpus_candidato.py --shards 11,19 --math-es 6000 --math-en 9000 --physics-en 1000 --sample-size 300 --out data/corpus_candidato --contact "https://github.com/Mig501/Trabajo-BDA"
```

Objetivo inicial: 16.000 documentos (6.000 math ES, 9.000 math EN, 1.000 physics EN). Los 2 Parquet previos se reutilizan desde caché si están descargados. PhysicsEval usa **test.json** por defecto (~30 MB), pero `--physics-split train` permite emplear `train.json` (~272 MB). Para corpus académico a largo plazo conviene evaluar si utilizar el split de entrenamiento evita confundir nuestra evaluación con el benchmark del dataset de origen.

**Si faltan matemáticas ES tras filtrar**, repite con más shards (por ejemplo `--shards 11,19,0,1`). Esto implica descargar archivos adicionales. Si faltan problemas de física, revisa `--physics-split train`, considerando el mayor tamaño y las condiciones de uso. No reduzcamos el corpus por debajo de los mínimos obligatorios.

En modo local, si ya tienes los archivos guardados en otras rutas, puedes evitar nuevas descargas con:

```powershell
python scripts/preparar_corpus_candidato.py --math-files "C:\ruta\train-00011-of-00023.parquet" "C:\ruta\train-00019-of-00023.parquet" --physics-file "C:\ruta\test.json" --out data/corpus_candidato
```

## 4. Qué filtra

- Descarta problemas sin enunciado o solución y documentos demasiado cortos (matemáticas: 60 palabras; física: 200 palabras; ajustable por parámetro).
- En PolyUniMath, cuando existen las etiquetas de validez, acepta solamente `Yes`/`valid` y excluye `Problem not solved` y registros señalados como no autocontenidos.
- Descarta caracteres de control dañados y referencias explícitas a figuras no presentes. El filtro es una heurística: puede descartar algunos válidos y aceptar otros incompletos.
- Elimina duplicados exactos por identificador o por enunciado normalizado en cada grupo e idioma.
- Elige aleatoriamente los documentos válidos mediante *reservoir sampling* durante la lectura de los archivos, manteniendo una semilla reproducible.

## 5. Salidas

```text
data/corpus_candidato/
├── corpus_candidato.jsonl       # todos los registros seleccionados, con texto y metadatos
├── inventario_candidato.csv     # metadatos y una vista breve, sin texto completo
├── auditoria_filtrado.csv       # conteo de motivos de descarte por grupo
├── informe_candidato.json      # métricas, parámetros y advertencias
├── resumen_candidato.txt       # resumen humano
├── muestra_check_project.csv   # columnas exactas 'text' y 'language'
└── trazabilidad_muestra.csv     # IDs y procedencia de cada fila de muestra
```

La muestra es aleatoria **estratificada por la proporción de documentos** de cada grupo del corpus elegido, no una selección de los primeros registros. La proporción de chunks puede variar por la longitud de los documentos. **Verifica que se aproxima a la del corpus completo**, y que cada idioma supera el 20 % real tras tokenización.

Si falta algún grupo para alcanzar el objetivo, el script informa de ello y guarda sólo un **corpus provisional incompleto**, sin presentarlo como conforme.

Los números `approx_chunks_180w` son aproximados, no provienen del tokenizador E5.

## 6. Validación con el script del profesor

Una vez que `resumen_candidato.txt` indique que la selección es suficiente y la muestra sea representativa, ejecuta:

```powershell
python scripts/check_project.py --sample data/corpus_candidato/muestra_check_project.csv --model intfloat/multilingual-e5-base --total-docs 16000 --query-prefix "query: " --passage-prefix "passage: " > results/validacion/check_project.txt
```

**Sustituye `16000` por el total real** del informe, si la selección no alcanzó exactamente ese tamaño. No presentes como válidas estimaciones extrapoladas de un corpus incompleto.

Para E5, los prefijos `query: ` y `passage: ` incluyen el espacio final. El modelo se descarga en el primer uso; puede ser grande. Ejecutar en el equipo donde se generarán los embeddings.

No cambies el archivo `check_project.py` del profesor.

### Qué enviar después

`resumen_candidato.txt`, `informe_candidato.json`, `auditoria_filtrado.csv` y, si se ha generado, `trazabilidad_muestra.csv`. No es necesario subir los 16.000 textos completos al chat.

## 7. Requisitos no validados automáticamente

- Licencia efectiva de cada texto de origen (PolyUniMath declara CC BY-NC 4.0 y PhysicsEval CC BY-SA 4.0, pero pueden proceder de obras con condiciones distintas).
- Calidad, exactitud y autocontención de cada problema tras los filtros.
- Preguntas de evaluación: unas 50, al menos 20 % cross-lingual, y cinco en la propuesta con documento concreto.
- La representatividad de los shards muestreados respecto a los 23 de PolyUniMath.
- Metadatos: `domain`, `topic`, `difficulty`, `source_material` y otros; verificar que los campos usados como filtros tengan valores realmente útiles.

**Licencias declaradas y fichas:**
- <https://huggingface.co/datasets/friederrr/PolyUniMath>
- <https://huggingface.co/datasets/IUTVanguard/PhysicsEval>
