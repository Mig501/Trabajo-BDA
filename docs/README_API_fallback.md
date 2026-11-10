# Explorador de Física y Matemáticas — alternativa ante errores del Dataset Viewer

## Qué se ha corregido

La consulta `/filter` del servicio Dataset Viewer de Hugging Face puede devolver errores 500 temporales, entre ellos el mensaje `Authentication check on the Hugging Face Hub failed or timed out`. En modo automático, el explorador prueba primero `/filter` para matemáticas, y, si falla, cambia al endpoint `/rows` y filtra los registros por idioma localmente. Los problemas de física se consultan siempre mediante `/rows`.

Este cambio **no elimina las caídas globales del servicio**: si falla también `/rows` o `/splits`, el script mostrará el error y no se podrá continuar con esa API hasta que se restablezca.

## Uso desde la raíz del proyecto

```powershell
python scripts/explorar_fismat.py --contact "https://github.com/Mig501/Trabajo-BDA" --out data/exploracion_fismat
```

Se puede probar directamente el modo alternativo, sin solicitar `/filter`:

```powershell
python scripts/explorar_fismat.py --api-mode rows --contact "https://github.com/Mig501/Trabajo-BDA" --out data/exploracion_fismat
```

`--api-mode filter` obliga a usar solo el endpoint filtrado y sirve para diagnosticar el problema si se recupera. El valor predeterminado `auto` suele ser preferible. Puede aumentar el máximo de bloques consultados con `--max-requests 300` si el muestreo español obtiene pocos registros.

## Precauciones

- En modo `rows` se leen bloques aleatorios de hasta 100 filas del split sin filtrar; se descartan localmente las de otros idiomas. Puede consumir más consultas y ancho de banda que `/filter`.
- La selección sigue siendo un **piloto exploratorio** y no una muestra representativa del corpus completo para `check_project.py`.
- Si fallan también `/splits` o `/rows`, no se debe cambiar credenciales ni asumir que el repositorio requiere permiso: revisa la disponibilidad del servicio y vuelve a intentar la operación.
- No se ha ejecutado una consulta real desde este entorno; se ha comprobado la sintaxis y el cambio automático con una simulación de respuestas HTTP.
