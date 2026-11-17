# Ampliación del corpus Wikipedia científica (v2)

## Motivo

El validador oficial obtuvo **21.905 chunks estimados** en **2.800 documentos**, insuficientes para el mínimo de 25.000. Los otros siete requisitos se superaron. La muestra contiene aproximadamente 6,55 chunks/documento en español y 9,10 en inglés.

En lugar de exigir nuevos documentos españoles, ampliamos **solo el inglés** hasta 2.200: total 3.600 documentos (1.400 ES y 2.200 EN). La proyección es ~29.200 chunks, que **deben verificarse** de nuevo con el tokenizador; las cuotas también dependen de los artículos válidos del inventario. El español conservaría una proporción estimada superior al 20 %.

## Instalación

Sustituye únicamente `scripts/preparar_corpus_wikipedia.py` por el script actualizado de este ZIP. Conserva `scripts/explorar_wikipedia_ciencia.py` sin cambios.

## Comando (PowerShell, desde la raíz del proyecto)

```powershell
python scripts/preparar_corpus_wikipedia.py --phase build --out data/corpus_wikipedia_ciencia --target-es 1400 --target-en 2200 --sample-size 300 --min-words 250 --seed 42
```

Se reutilizan `inventario_descubierto.csv` y la caché existente (`cache/pages/`) del mismo directorio. **No se vuelve a ejecutar `discover`**. El script regenera los resultados finales del directorio, conservando el inventario congelado. Los objetivos independientes quedan registrados en `informe_corpus.json` (parámetro `target_by_language`). El script original sigue siendo compatible con `--per-language`.

## Revalidación oficial

**Solo si `informe_corpus.json` indica estado `COMPLETO` y 3.600 documentos**, ejecuta:

```powershell
python scripts/check_project.py --sample data/corpus_wikipedia_ciencia/muestra_check_project.csv --model intfloat/multilingual-e5-base --total-docs 3600 --query-prefix "query: " --passage-prefix "passage: " > results/validacion/check_project_wikipedia_v2.txt
```

Si selecciona menos documentos, sustituye `3600` por el número real al revalidar. La muestra sigue siendo una estimación y la exclusividad de preguntas cross-lingual continúa pendiente.

## Archivos para revisar

`resumen_corpus.txt`, `informe_corpus.json` y `check_project_wikipedia_v2.txt`. Si no se alcanza la cuota de inglés, revisaremos el motivo en la auditoría de filtrado.
