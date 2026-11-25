# BDA · Continuar la ampliación tras agotar los candidatos

## Diagnóstico

Si `--phase extend` devuelve 0 peticiones nuevas, estado `PARCIAL` y menos de 6.600 documentos, el script ha revisado el inventario original y no tiene nuevos IDs por consultar. **No borres** el corpus original, `ampliacion_50k/`, `auditoria_nuevos.csv` ni las cachés.

## 1. Sustituir solo el script de ampliación

Copiar `scripts/ampliar_corpus_wikipedia.py` de este ZIP sobre el script del mismo nombre del repositorio. El resto de scripts permanece igual.

## 2. Opcional: medir si ya tienes 50.000 chunks exactos

```powershell
python scripts/ampliar_corpus_wikipedia.py --phase count --out data/corpus_wikipedia_ciencia/ampliacion_50k
```

Si imprime `Objetivo recomendado 50.000: ALCANZADO`, no se necesitan más descargas. Si no, continuar.

## 3. Descubrir **más** categorías en otra carpeta

No ejecutar `discover` sobre `data/corpus_wikipedia_ciencia`, pues sobrescribiría el inventario original.

```powershell
python scripts/preparar_corpus_wikipedia.py --phase discover --out data/corpus_wikipedia_ciencia/descubrimiento_v2 --depth 2 --max-categories-per-topic 110 --members-per-category 3000 --seed 42
```

Esta fase descubre páginas y registra la nueva población candidata. Usa las mismas raíces científicas y la misma semilla, pero eleva el tope de categorías. Queda documentada y no altera los 3.600 artículos iniciales. No garantiza automáticamente suficientes artículos válidos; el texto se filtrará al descargarlo.

## 4. Importar el nuevo inventario y hacer PLAN (sin descargas)

```powershell
python scripts/ampliar_corpus_wikipedia.py --phase plan --target-es 1800 --target-en 4800 --extra-inventory data/corpus_wikipedia_ciencia/descubrimiento_v2/inventario_descubierto.csv
```

El script guardará de manera acumulativa `ampliacion_50k/inventario_extendido_congelado.csv`, con los candidatos originales intactos y solamente los nuevos IDs añadidos. En siguientes ejecuciones se cargará automáticamente. Si sigue sin haber candidatos nuevos, habrá que ampliar el marco temático/profundidad de forma justificada; no repetir el mismo `extend`.

## 5. Continuar las descargas pendientes

```powershell
python scripts/ampliar_corpus_wikipedia.py --phase extend --target-es 1800 --target-en 4800 --max-new-fetches 1500 --delay 0.5
```

El script reanuda los **5.783 documentos** ya guardados y añade otros; nunca rehace los anteriores. Repetir `extend` solo si el estado sigue `PARCIAL` y hay peticiones nuevas/candidatos sin examinar. Si se agota el inventario, se mostrará una indicación explícita.

Cuando termine, contar:

```powershell
python scripts/ampliar_corpus_wikipedia.py --phase count --out data/corpus_wikipedia_ciencia/ampliacion_50k
```

Revisar que se superan 50.000 chunks **reales**, con al menos 20 % de cada idioma. Revalidar las preguntas cross-lingual sobre el corpus ampliado.

## Salvaguardas

- El script compara SHA-256 del corpus original (3.600 documentos) contra el hash conocido.
- Conserva los documentos ya incorporados tal cual (texto, `revision_id`, idioma, metadatos).
- No sobrescribe el primer inventario ni la caché previa.
- El inventario adicional solo puede añadir IDs nuevos; ante colisiones prevalece la ficha previamente congelada.
- El descubrimiento ampliado no convierte el muestreo en una muestra de toda Wikipedia; los límites y categorías deben documentarse.
