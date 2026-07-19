# INDICA — INDicadores de Investigación, Ciencia y Academia

Herramienta de línea de comandos (CLI) para descargar, procesar, enriquecer y analizar
datos de producción científica de grupos de investigación colombianos, a partir de
información de **GrupLAC**, **Publindex** y **Scopus**.

## Características

- 📥 **Actualización individual de bases de datos**: Homologación, Publindex y Scopus,
  cada una se puede regenerar de forma independiente.
- 🔄 **Procesamiento de datos de GrupLAC**: descarga los datos públicos de los grupos
  de investigación y extrae los artículos publicados.
- 📈 **Enriquecimiento de artículos**: cruza cada artículo con las bases de datos de
  Publindex/Scopus/Homologación para asignar categoría, área OCDE y gran área.
- 🔗 **Deduplicación avanzada (estándar del pipeline)**: al ejecutar `--process-data`,
  se recupera el DOI aunque no se haya diligenciado el campo correspondiente
  (algunos autores lo pegan en otro campo, p. ej. en "autores"), y se genera
  automáticamente una **tabla consolidada única** (`articles_consolidated.csv`)
  deduplicada por DOI y similitud de títulos:
  - ✅ Normaliza títulos (elimina comillas, espacios, puntuación)
  - ✅ Detecta títulos similares sin DOI (≥98% similitud configurable)
  - ✅ Valida DOIs mediante Crossref API (rechaza ISSNs como "0122-8706")
  - ✅ Cuando mismo título tiene DOIs diferentes, valida cuál funciona
  - ✅ Prioridad a artículos con DOI sobre los que no tienen
  - ✅ Conserva el registro más completo (más autores)
  - 📋 **Genera reporte detallado** (`duplicates_removed_report.csv`) de cada duplicado eliminado
- 📋 **Reporte de información faltante**: identifica automáticamente qué
  artículos no tienen DOI, autores, ISSN, título, revista o categoría
  Publindex, tanto en detalle como resumido por grupo de investigación, para
  facilitar solicitar la corrección a cada autor/grupo y servir de guía antes
  de escribir informes o hacer análisis bibliométricos.
- 📚 **Análisis bibliométrico** (vía [OpenAlex](https://openalex.org), API gratuita
  sin necesidad de clave):
  - Número de citas por artículo y fuentes que lo citan
  - Índice H, i10-index, número de obras y citas totales por autor
- 📊 **Generación de análisis y visualizaciones** (gráficos estáticos en PDF):
  - Línea de tiempo de artículos por año y categoría (histórico y últimos 10 años)
  - Artículos por autor
  - Artículos por grupo y área de conocimiento
  - Artículos por grupo y gran área de conocimiento
  - Top artículos más citados y top autores por índice H

## Requisitos

- Python 3.9+
- pandas
- matplotlib
- requests
- openpyxl
- pdfplumber / camelot (o la librería usada en `extract_table.py` para leer PDFs)

## Instalación

```bash
git clone <repository-url>
cd indica
pip install -r requirements.txt
```

## Estructura del proyecto

```
indica/
├── code/
│   ├── scripts/
│   │   └── main.py                 # Punto de entrada CLI
│   └── src/
│       ├── preprocessing/
│       │   ├── extract_table.py           # Extracción de tablas desde PDF/HTML
│       │   ├── generate_databases.py      # Generación de bases de datos (Homologación/Publindex/Scopus)
│       │   ├── process_articles_data.py   # Procesamiento de artículos desde bloques GrupLAC
│       │   └── enrich_articles.py         # Enriquecimiento de artículos con las bases de datos
│       ├── analysis/
│       │   ├── utilities.py               # Funciones de agregación, depuración por DOI y orden de autores
│       │   ├── bibliometrics.py           # Citas y métricas de autor (h-index) vía OpenAlex
│       │   └── get_members_year.py        # Integrantes por año/grupo
│       └── visualization/
│           ├── visualize_data.py          # Gráficos (líneas de tiempo, barras por autor/área/h-index)
│           └── data_research_labs.py
├── config/                          # Archivos de configuración
├── data/
│   ├── raw/
│   │   ├── gruplac/                 # research_groups_data.csv (grupos y URLs de GrupLAC)
│   │   ├── homologation/            # PDF de revistas homologadas
│   │   └── semilleros/
│   └── processed/
│       ├── data_blocks_gruplac/     # HTML descargado y bloques extraídos por grupo
│       └── homologation/            # CSV extraído del PDF de homologación
├── database/
│   ├── homologation_database.parquet
│   ├── publindex_database.parquet
│   ├── scopus_database.parquet
│   ├── scopus_database.csv
│   ├── area_ocde.csv
│   ├── autores_depto.csv
│   └── manual_ocde_issn.csv
├── results/
│   ├── figures/                     # Gráficos generados (PDF)
│   ├── tables/                      # Tablas por grupo, tabla consolidada (DOI) y tablas bibliométricas
│   └── reports/                     # Reportes de información faltante (por artículo y por grupo)
├── docs/
└── README.md
```

## Uso del CLI

Toda la herramienta se ejecuta desde `code/scripts/main.py`. Para ver la ayuda:

```bash
python code/scripts/main.py --help
```

### Ejecución completa (pipeline end-to-end)

Crea/actualiza todas las bases de datos, procesa los datos de GrupLAC y genera todos
los análisis:

```bash
python code/scripts/main.py --all
```

### Actualizar bases de datos de forma individual

Cada base de datos se puede regenerar por separado, sin afectar las demás:

```bash
# Actualizar solo la base de Homologación (a partir del PDF)
python code/scripts/main.py --database homologation

# Actualizar solo la base de Publindex
python code/scripts/main.py --database publindex

# Actualizar solo la base de Scopus
python code/scripts/main.py --database scopus

# Actualizar todas las bases de datos
python code/scripts/main.py --database all
```

Para la base de datos de homologación hay dos opciones:

1. Procesar solo archivos nuevos (incremental)

```bash
python code/scripts/main.py --database homologation
```
- ✅ Salta archivos que ya tienen CSV
- ✅ Rápido si ya procesaste varios archivos
- ✅ Continúa donde quedó si hubo interrupción

2. Reprocesar TODO desde cero

```bash
python code/scripts/main.py --database homologation --force-reprocess
```
- ⚠️ Sobrescribe TODOS los CSVs existentes
- ⚠️ Más lento (procesa todo de nuevo, ~20 minutos)
- ✅ Útil si cambiaste alguna información

### Procesar datos de GrupLAC y enriquecer artículos

Descarga la información pública de cada grupo (definido en
`data/raw/gruplac/research_groups_data.csv`), extrae los artículos y los enriquece
con las bases de datos:

```bash
python code/scripts/main.py --process-data
```

Este paso, además de generar un CSV enriquecido por grupo (para trazabilidad),
ejecuta como parte estándar del pipeline:

1. **Recuperación de DOI faltante**: si el campo "DOI:" no fue diligenciado en
   GrupLAC (p. ej. porque el autor lo pegó en otro campo como "Autores"), se
   recupera con una búsqueda de respaldo y se limpia el campo afectado.
2. **Consolidación y deduplicación por DOI**: une los artículos de todos los
   grupos y elimina duplicados usando el DOI como llave única (cuando un
   artículo es reportado por varios coautores/grupos). Cuando hay más de una
   copia del mismo DOI, se conserva la que tenga el listado de autores más
   completo. El resultado se guarda en:
   - `results/tables/articles_consolidated.csv` — tabla única, deduplicada,
     usada por defecto en todos los análisis posteriores (`--analysis ...`).
3. **Reporte de información faltante**: identifica los artículos sin DOI,
   autores, ISSN, título, revista o categoría Publindex, y genera:
   - `results/reports/missing_information_detail.csv` — un registro por
     artículo con información incompleta y el detalle de qué campos faltan.
   - `results/reports/missing_information_summary_by_group.csv` — conteo de
     campos faltantes por grupo de investigación, útil para saber a qué
     grupo/autor solicitar la corrección de su información en GrupLAC antes
     de generar los análisis finales o el informe.

### Generar análisis y visualizaciones

Se pueden generar todos los análisis o solo uno en particular:

```bash
# Generar todos los análisis
python code/scripts/main.py --analysis all

# Línea de tiempo: artículos por año y categoría Publindex
python code/scripts/main.py --analysis timeline

# Artículos por autor
python code/scripts/main.py --analysis authors

# Artículos por grupo y área de conocimiento
python code/scripts/main.py --analysis areas

# Artículos por grupo y gran área de conocimiento
python code/scripts/main.py --analysis gran_areas
```

### Análisis bibliométrico (citas + índice H)

El análisis `bibliometrics` **no se incluye** dentro de `--analysis all` ni de
`--all`, ya que realiza numerosas consultas a la API pública de
[OpenAlex](https://openalex.org) y puede tardar varios minutos según el número
de artículos y autores. Debe solicitarse explícitamente:

```bash
# Deduplicar artículos por DOI y obtener citas + índice H de los autores
python code/scripts/main.py --analysis bibliometrics

# Recomendado: usar tu correo para la "polite pool" de OpenAlex (respuestas más
# rápidas y estables) y el nombre de la institución para desambiguar autores
python code/scripts/main.py --analysis bibliometrics \
    --email tu_correo@ejemplo.com \
    --affiliation "Universidad X"
```

Este análisis:

1. Utiliza la **tabla consolidada y deduplicada por DOI**
   (`results/tables/articles_consolidated.csv`, generada por `--process-data`),

### Herramientas de análisis de duplicados

#### Analizar reporte de duplicados

Después de ejecutar `--process-data`, puedes analizar los duplicados eliminados:

```bash
python code/scripts/main.py --analyze-duplicates
```

Genera:
- Estadísticas por tipo de duplicado
- Top 10 grupos con duplicados
- Lista de DOIs inválidos
- Casos de títulos similares
- Archivo `duplicates_summary.txt` con reporte detallado

#### Corrección de duplicados residuales

Si detectas duplicados adicionales en `articles_consolidated.csv`:

```bash
python code/scripts/main.py --fix-duplicates
```

Esta herramienta:
- Analiza duplicados residuales en el archivo consolidado
- Aplica deduplicación más agresiva (threshold 98%)
- Genera `articles_consolidated_fixed.csv`
- Documenta cada eliminación en `duplicates_fixed_report.csv`
- Muestra instrucciones para reemplazar el archivo original

## Archivos generados importantes

### Durante `--process-data`

1. **`results/tables/articles_consolidated.csv`**
   - Tabla única con todos los artículos deduplicados
   - Un artículo por fila (sin importar cuántos autores/grupos lo reportaron)

2. **`results/tables/duplicates_removed_report.csv`**
   - Reporte detallado de cada duplicado eliminado
   - Incluye: título eliminado/mantenido, DOI, grupo, razón
   - Útil para auditoría y corrección de datos en GrupLAC

3. **`results/reports/missing_information_detail.csv`**
   - Artículos con información faltante (DOI, autores, ISSN, etc.)
   - Por artículo individual

4. **`results/reports/missing_information_summary_by_group.csv`**
   - Resumen de información faltante por grupo de investigación
   - Útil para solicitar correcciones
   de modo que un artículo reportado por varios coautores/grupos en GrupLAC se
   cuenta una sola vez. Si esa tabla no existe todavía, la genera al vuelo
   (uniendo y deduplicando los CSV enriquecidos por grupo).
2. Consulta OpenAlex por cada DOI único para obtener número de citas, si es de
   acceso abierto, y conceptos/áreas temáticas asociadas.
3. Consulta OpenAlex por cada autor único para obtener su **índice H**,
   i10-index, número de obras y citas totales.
4. Genera tablas y gráficos con los resultados.

### Combinaciones útiles

```bash
# Actualizar la base de Scopus y regenerar todos los análisis
python code/scripts/main.py --database scopus --analysis all

# Actualizar Homologación y volver a procesar los datos de GrupLAC
python code/scripts/main.py --database homologation --process-data

# Procesar datos y generar solo el análisis de autores
python code/scripts/main.py --process-data --analysis authors
```

### Modo detallado (verbose)

```bash
python code/scripts/main.py --all --verbose
```

## Parámetros disponibles

| Parámetro              | Valores                                                        | Descripción                                                              |
|------------------------|----------------------------------------------------------------|--------------------------------------------------------------------------|
| `--all`                | flag                                                           | Ejecuta el pipeline completo: bases de datos + procesamiento + análisis  |
| `--database`           | `homologation`, `publindex`, `scopus`, `all`                   | Crea/actualiza una base de datos específica (o todas)                    |
| `--process-data`       | flag                                                           | Descarga y procesa los datos de GrupLAC, enriquece los artículos         |
| `--analyze-duplicates` | flag                                                           | Analiza el reporte de duplicados y genera estadísticas                   |
| `--fix-duplicates`     | flag                                                           | Aplica deduplicación agresiva para corregir duplicados residuales        |
| `--analysis`           | `timeline`, `authors`, `areas`, `gran_areas`, `bibliometrics`, `all` | Genera un análisis/visualización específico. `bibliometrics` **no** se incluye con `all` (debe solicitarse explícitamente) |
| `--email`              | texto (correo)                                                 | Correo para la "polite pool" de OpenAlex (solo `--analysis bibliometrics`) |
| `--affiliation`        | texto (institución)                                            | Institución para desambiguar autores en OpenAlex (solo `--analysis bibliometrics`) |
| `--verbose`, `-v`      | flag                                                           | Activa mensajes de log más detallados                                    |

Si se ejecuta el script sin ningún parámetro, se muestra la ayuda (`--help`).

---

## 📊 Sistema de Deduplicación Avanzada

### Tipos de duplicados detectados

El sistema detecta y elimina automáticamente 5 tipos de duplicados:

1. **DOI duplicado**: Mismo DOI reportado por múltiples autores/grupos (~50 casos típicamente)
2. **DOI inválido**: Mismo título con DOIs diferentes, se valida cuál funciona (~5 casos)
3. **Título exacto sin DOI**: Títulos idénticos después de normalización (~15 casos)
4. **Título similar sin DOI**: Similitud ≥98% sin DOI (~5 casos)
5. **Prioridad DOI**: Mismo título con/sin DOI, se mantiene el que tiene DOI (~15 casos)

### Validación de DOIs

- Usa **Crossref API** (más confiable que HTTP directo)
- Rechaza ISSNs como "0122-8706" que estén en campo DOI
- Valida formato: debe empezar con "10."
- **Detecta DOIs incompletos/prefijos**: Si "10.22490/" es prefijo de "10.22490/21456453.992", mantiene solo el completo
- **Elimina duplicados de capitalización**: "RevFacAgron(LUZ)" y "revFacAgron(LUZ)" se consideran el mismo
- Timeout de 10 segundos por DOI
- Fallback a HTTP y dx.doi.org si API falla

### Normalización de títulos

- Elimina comillas: `"Título"` → `Título`
- Elimina espacios extra: `  Título  ` → `Título`
- Elimina puntuación: `Título: subtítulo` → `Titulo subtitulo`
- Convierte a minúsculas
- Colapsa espacios múltiples

### Casos especiales

**DOIs incompletos (prefijos):**
```
Título: "Aprovechamiento del Lactosuero..."
DOI 1: 10.22490/21456453.992 ✓ (completo)
DOI 2: 10.22490/ ✓ (válido pero incompleto)
→ Se mantiene solo el completo
```

**Múltiples DOIs válidos con mismo título:**
```
Título: "Development of a Buyer Persona..."
DOI 1: 10.62441/nano-ntp.vi.1540 ✓
DOI 2: 10.62441/nano-ntp.v20iS6.87 ✓
→ Se mantienen AMBOS (pueden ser versiones: preprint vs publicado)
```

**Un DOI válido, uno inválido:**
```
Título: "Aislamiento de Microorganismos..."
DOI 1: 10.24054/limentech.v22i1.2867 ✓
DOI 2: 10.24054/1.2867 ✗
→ Se mantiene solo el válido
```

**Mismo título con/sin DOI:**
```
Título: "Calidad Microbiológica..."
Registro 1: CON DOI válido
Registro 2: SIN DOI
→ Se mantiene el que tiene DOI
```

## Archivos de configuración

### `data/raw/gruplac/research_groups_data.csv`

Debe contener, como mínimo, las columnas:

| Columna          | Descripción                       |
|------------------|-----------------------------------|
| `research_group` | Nombre del grupo de investigación |
| `url_to_gruplac` | URL pública de GrupLAC del grupo  |

Ejemplo:

```csv
research_group,url_to_gruplac
BiotecGen,https://scienti.minciencias.gov.co/gruplac/jsp/visualiza/visualizagr.jsp?nro=00000000123456
CINBIOS,https://scienti.minciencias.gov.co/gruplac/jsp/visualiza/visualizagr.jsp?nro=00000000654321
```

### `data/raw/homologation/2022.pdf`

PDF oficial de revistas homologadas, usado para generar `homologation_database.parquet`.

## Bases de datos generadas

| Base de datos | Descripción                                                | Salida                                      |
|---------------|------------------------------------------------------------|---------------------------------------------|
| Homologación  | Revistas homologadas, extraídas desde el PDF oficial       | `database/homologation_database.parquet`    |
| Publindex     | Clasificación de revistas del Sistema Publindex (Colombia) | `database/publindex_database.parquet`       |
| Scopus        | Listado de títulos Scopus con clasificación OCDE           | `database/scopus_database.parquet` / `.csv` |

Bases de datos auxiliares (curación manual y homologación de áreas):
`database/area_ocde.csv`, `database/autores_depto.csv`, `database/manual_ocde_issn.csv`.

## Resultados generados

### `results/tables/` — Tablas

- `<grupo>_articulos.csv` / `<grupo>_articulos_enriched.csv` — Datos crudos y
  enriquecidos por grupo (se conservan íntegros, uno por grupo, para
  trazabilidad; pueden contener el mismo artículo repetido si fue reportado
  por varios coautores/grupos).
- `articles_consolidated.csv` — **Tabla estándar** generada por
  `--process-data`: unión de todos los grupos, deduplicada por DOI. Es la que
  usan por defecto todos los análisis (`--analysis ...`).
- `articles_with_citations.csv` — (solo con `--analysis bibliometrics`) tabla
  consolidada + número de citas, estado de acceso abierto y conceptos/áreas
  temáticas (OpenAlex).
- `authors_with_bibliometric_metrics.csv` — (solo con `--analysis bibliometrics`)
  una fila por autor y artículo, con el orden del autor en la firma
  (`orden_autor`) y sus métricas de OpenAlex.
- `author_summary_h_index.csv` — (solo con `--analysis bibliometrics`) una
  fila por autor con índice H, i10-index, número de obras y citas totales,
  ordenado de mayor a menor índice H.

### `results/reports/` — Reportes de calidad de la información

Generados automáticamente por `--process-data`, a partir de la tabla
consolidada:

- `missing_information_detail.csv` — un registro por artículo con información
  incompleta (sin DOI, autores, ISSN, título, revista o categoría Publindex),
  indicando exactamente qué campos faltan (`campos_faltantes`).
- `missing_information_summary_by_group.csv` — conteo de artículos con campos
  faltantes, agrupado por grupo de investigación (`filename`) y tipo de campo
  faltante. Útil como checklist para solicitar a cada grupo/autor que revise
  y complete su información en GrupLAC, y como guía previa a escribir
  informes o ejecutar análisis bibliométricos.

### `results/figures/` — Gráficos (PDF)

- `articles_by_year_all_groups.pdf` — Artículos por año y categoría Publindex (histórico)
- `articles_by_year_all_groups_last_10_years.pdf` — Artículos por año (últimos 10 años)
- `articles_by_author_all_groups.pdf` — Distribución de artículos por autor
- `articles_by_group_and_area.pdf` — Distribución de artículos por grupo y área
- `articles_by_group_and_gran_area.pdf` — Distribución de artículos por grupo y gran área
- `top_cited_articles.pdf` — Top 20 artículos más citados (solo con `--analysis bibliometrics`)
- `top_authors_by_h_index.pdf` — Top 20 autores por índice H (solo con `--analysis bibliometrics`)


## Logging

La aplicación registra cada paso en consola, incluyendo:

- ✅ Procesos completados exitosamente
- ⚠️ Advertencias (por ejemplo, datos faltantes)
- ❌ Errores durante la ejecución

## Solución de problemas

**"No enriched articles data found"**
Ejecuta primero el procesamiento de datos:
```bash
python code/scripts/main.py --process-data
```

**`ModuleNotFoundError`**
Verifica que instalaste todas las dependencias:
```bash
pip install -r requirements.txt
```

**Error de conexión al descargar la base de Scopus**
Verifica tu conexión a internet. La URL de descarga de Scopus puede cambiar con el tiempo;
revisa la URL vigente en la web de Elsevier/Scopus y actualízala en
`create_databases()` dentro de `code/scripts/main.py`.

**`--analysis bibliometrics` no encuentra citas o índice H para algunos artículos/autores**
Esto ocurre cuando:
- El artículo no tiene DOI o el DOI no está indexado en OpenAlex.
- El nombre del autor es ambiguo (homónimos). Usa `--affiliation` con el nombre
  de la institución para mejorar la desambiguación.
- Se alcanzó un límite de tasa de la API. Usa `--email` para acceder a la
  "polite pool" de OpenAlex, que tiene límites más altos y respuestas más
  estables.

**`articles_consolidated.csv` no existe / está desactualizado**
Esta tabla se genera (o regenera) automáticamente cada vez que ejecutas
`--process-data`. Si solo ejecutas `--analysis ...` sin haber corrido antes
`--process-data`, INDICA construye la tabla consolidada al vuelo (uniendo y
deduplicando los CSV enriquecidos por grupo), pero se recomienda ejecutar
`--process-data` regularmente para mantener también actualizados los reportes
de información faltante (`results/reports/`).

**Muchos artículos aparecen duplicados en los CSV por grupo**
Es esperado: los archivos `results/tables/<grupo>_articulos_enriched.csv` se
mantienen íntegros, uno por grupo, para trazabilidad (un mismo artículo puede
aparecer en varios si fue reportado por distintos coautores/grupos). El
archivo `results/tables/articles_consolidated.csv` es el que contiene la
versión ya depurada por DOI y lista para análisis/reportes.

## Desarrollo

1. Haz un fork del repositorio
2. Crea una rama para tu feature (`git checkout -b feature/nueva-funcionalidad`)
3. Realiza tus cambios y commitea (`git commit -m 'Agrega nueva funcionalidad'`)
4. Sube la rama (`git push origin feature/nueva-funcionalidad`)
5. Abre un Pull Request

## Autores

- Albert Tafur Rangel, Ph.D.

## Soporte

Para reportar problemas o sugerencias, abre un issue en el repositorio.

