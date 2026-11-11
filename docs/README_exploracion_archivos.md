# Exploración de Física y Matemáticas — descarga directa (sin Dataset Viewer)

Este script sustituye la **vía de obtención** de datos del piloto que fallaba por HTTP 500/429. No usa `/filter`, `/rows` ni `/splits` de Dataset Viewer. Utiliza archivos publicados en el repositorio de cada dataset y `huggingface_hub` para gestionarlos con caché.

## Instalación (entorno bdav)

```powershell
pip install -U huggingface_hub pyarrow
```

## Ejecutar desde la raíz de BDA-fisica-matematicas

```powershell
python scripts/explorar_fismat_archivos.py --contact "https://github.com/Mig501/Trabajo-BDA" --out data/exploracion_fismat_archivos
```

**Descargas previstas:** dos archivos de PolyUniMath (shards 11 y 19, unos 155 MB y 149 MB, respectivamente), más `test.json` de PhysicsEval (~30 MB): alrededor de **334 MB**. Las cifras son aproximadas y pueden cambiar; los archivos se guardan en la caché de Hugging Face, no en `data/`.

Si falta muestra española, amplía a otros shards (los ya descargados se aprovechan de caché):

```powershell
python scripts/explorar_fismat_archivos.py --shards 11,14,19 --contact "https://github.com/Mig501/Trabajo-BDA" --out data/exploracion_fismat_archivos
```

**Limitación metodológica:** la selección es aleatoria **dentro de los shards descargados**, no del total de PolyUniMath (23 archivos). Es un piloto para comprobar campos, calidad, longitud y accesibilidad. No presentarlo como prueba definitiva del tamaño ni distribución del corpus.

Genera:
- `resumen.txt`: datos básicos y advertencias.
- `informe.json`: estadísticas por procedencia e idioma, así como archivos descargados.
- `auditoria.csv`: longitudes y metadatos sin el texto completo.
- `muestra_exploratoria.csv`: problemas y soluciones reales. No enviarla directamente al comprobador oficial hasta definir la composición real del corpus.

**No descargar todo PolyUniMath** (más de 5 GB) para este piloto. No se usan cuentas de GitHub ni credenciales GitHub. El parámetro `--contact` solo conserva una referencia para identificar la ejecución; en esta versión las solicitudes las realiza el cliente oficial de Hugging Face. El cliente utiliza la sesión/autenticación de Hugging Face si la tienes configurada, pero no la exige para estos repositorios públicos.

**Cautelas de calidad:** algunos problemas matemáticos proceden de PDFs y tienen soluciones incompletas o símbolos corruptos. Revisar etiquetas de validez, duplicados y uso permitido de textos originales (aunque el dataset declare una licencia). PhysicsEval es solo inglés. El tamaño real final debe comprobarse con el tokenizador mediante el `check_project.py` del profesor.
