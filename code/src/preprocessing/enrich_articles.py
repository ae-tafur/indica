import os
import logging
import requests
import pandas as pd

# Configure logging
logger = logging.getLogger(__name__)

# Function to capitalize titles without capitalizing certain words
def capitalize_title(tittle):
    if pd.isna(tittle):
        return tittle

    exceptions = {
        'de', 'del', 'la', 'las', 'y', 'en', 'el', 'los', 'una', 'un', 'por', 'con', 'como',
        'of', 'and', 'in', 'on', 'the', 'for', 'at', 'to', 'from', 'by', 'an', 'or', 'as', 'a', 'due',
        'spp', 'DNA', 'RNA', 'et', 'al', 'etc', 'i.e.', 'e.g.', 'vs', 'v', 'cfr', 'cf', 'p. ', 'pp. ', 'vol. ', 'vols. '
    }

    words = tittle.lower().split()
    result = []

    for i, word in enumerate(words):
        if i == 0 or word not in exceptions:
            result.append(word.capitalize())
        else:
            result.append(word)

    return ' '.join(result)

def get_cite_from_doi(doi, estilo="apa"):
    """
    Obtiene la cita bibliográfica desde un DOI usando el estilo especificado.
    Estilos comunes: apa, mla, chicago, harvard, vancouver.
    """
    headers = {
        "Accept": f"text/x-bibliography; style={estilo}"
    }
    # Estandariza el DOI
    if doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    elif doi.startswith("http://dx.doi.org/"):
        doi = doi.replace("http://dx.doi.org/", "")
    elif doi.startswith("doi:"):
        doi = doi.replace("doi:", "")
    elif doi.startswith("doi.org/"):
        doi = doi.replace("doi.org/", "")

    url = f"https://doi.org/{doi}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.text
        else:
            return f"Error {response.status_code}: {response.reason}"
    except requests.RequestException as e:
        return f"Error de conexión: {e}"


def expand_authors_by_manuscript(df, columna_autores='Autores'):
    """
    Expande las filas del DataFrame según los autores separados por coma en `columna_autores`.
    Luego elimina las filas que son idénticas excepto por el autor.
    """
    # Paso 1: Expandir autores a una nueva fila
    df_expanded = df.assign(
        AutorIndividual=df[columna_autores].str.split(',')
    ).explode('AutorIndividual')

    # Paso 2: Limpiar espacios
    df_expanded['AutorIndividual'] = df_expanded['AutorIndividual'].str.strip()

    # Paso 3: Eliminar la columna homologation de autores para no duplicar información
    df_expanded = df_expanded.drop(columns=[columna_autores])

    # Paso 4: Eliminar filas duplicadas
    # Try first with a subset of columns that are likely to be unique
    columns_for_duplicates = ['Título del artículo', 'AutorIndividual', 'Revista']
    df_expanded = df_expanded.drop_duplicates(subset=columns_for_duplicates)

    # In some cases, same journal with different ISSN or but same DOI
    columns_for_duplicates = ['Título del artículo', 'AutorIndividual', 'DOI']
    df_expanded = df_expanded.drop_duplicates(subset=columns_for_duplicates)

    return df_expanded

def enrich_articles_data(file_csv, database_path, output_path):
    """
    Enriches article data with information from the Publindex database.
    """
    # Load all the necessary databases
    # Read the publindex database (parquet)
    publindex_path = database_path / 'publindex_database.parquet'
    publindex_db = pd.read_parquet(publindex_path)

    # Read the homologation database (Parquet)
    homologation_path = database_path / 'homologation_database.parquet'
    homologation_db = pd.read_parquet(homologation_path)

    # Read the Scopus database (parquet)
    scopus_path = database_path / 'scopus_database.parquet'
    scopus_db = pd.read_parquet(scopus_path)

    # Read the manual curation for issn and OCDE classification
    manual_curation_path = database_path / 'manual_ocde_issn.csv'
    manual_curation_db = pd.read_csv(manual_curation_path, dtype=str)

    # Read the area and gran area database (csv)
    clasification_path = database_path / 'area_ocde.csv'
    clasification_db = pd.read_csv(clasification_path, dtype=str)

    # ---------------------------------- Publindex - national -----------------------------------
    # Unify all ISSN columns in only one for merge
    publindex_db = pd.melt(
        publindex_db,
        id_vars=['nme_revista_in', 'nme_area', 'nme_gran_area', 'id_clas_rev', 'nro_ano'],
        value_vars=['txt_issn_p', 'txt_issn_e', 'txt_issn_l'],
        var_name='type_issn',
        value_name='issn'
    ).dropna(subset=['issn'])

    publindex_db = publindex_db.drop_duplicates(subset=['issn', 'nro_ano', 'id_clas_rev'])

    # Rename some columns
    publindex_db = publindex_db.rename(columns={'nme_revista_in': 'journal',
                                                'nme_area': 'area',
                                                'nme_gran_area': 'gran_area'})

    # ---------------------------------- Publindex - International  -----------------------------------
    # Note: year_publindex is already in string format in the database
    # Note: ISSNs are already expanded in the database, no need to split here

    # ----------------------------------- Scopus - International --------------------------------------
    # Rename some columns
    scopus_db = scopus_db.rename(columns={
        'all science journal classification codes (asjc)': 'OCDE_clasification_code',
    })

    # adjust the issn and eissn columns
    scopus_db['issn'] = (
        scopus_db['issn']
        .fillna('')
        .astype(str)
        .str.extract(r'(\d{4})(\d{3}[0-9Xx])')
        .fillna('')
        .agg(lambda x: '-'.join(x) if x[0] and x[1] else '', axis=1)
    )
    # Ensure eissn is also in the same format
    scopus_db['eissn'] = (
        scopus_db['eissn']
        .fillna('')
        .astype(str)
        .str.extract(r'(\d{4})(\d{3}[0-9Xx])')
        .fillna('')
        .agg(lambda x: '-'.join(x) if x[0] and x[1] else '', axis=1)
    )

    scopus_db = pd.melt(
        scopus_db,
        id_vars=['source title', 'active or inactive', 'coverage', 'publisher', 'OCDE_clasification_code'],
        value_vars=['issn', 'eissn'],
        var_name='type_issn',
        value_name='issn_melted'
    ).dropna(subset=['issn_melted'])

    scopus_db = scopus_db.rename(columns={'issn_melted': 'issn'})

    # Expand multiple ISSN
    scopus_db = scopus_db.assign(OCDE_clasification_code=scopus_db['OCDE_clasification_code'].str.split(';')).explode('OCDE_clasification_code')
    scopus_db['OCDE_clasification_code'] = scopus_db['OCDE_clasification_code'].str.strip()

    # ------------------------- Merge Publindex International and National, with data -------------------
    # Read the CSV file with article data
    df_art = pd.read_csv(file_csv, dtype=str)

    # Keep original column names (in English), just process the data
    df_art['issn'] = df_art['issn'].str.strip()
    df_art['year'] = df_art['year'].astype(str)

    # Merge for "área" and "gran área" (does not depend on the year)
    # Also add Scopus coverage information
    df_area = scopus_db[['issn', 'OCDE_clasification_code', 'source title', 'coverage']].drop_duplicates(subset=['issn'])
    df_area = df_area.rename(columns={
        'source title': 'journal_scopus',
        'coverage': 'coverage_scopus'
    })
    df_art = pd.merge(df_art, df_area, on='issn', how='left')
    # Merge with manual_curation_db (adds OCDE_clasification_code_y)
    df_art = pd.merge(df_art, manual_curation_db[['issn', 'OCDE_clasification_code']],
                      on='issn', how='left',
                      suffixes=('', '_manual'))

    # Fill missing OCDE_clasification_code with the manual value
    df_art['OCDE_clasification_code'] = df_art['OCDE_clasification_code'].fillna(
        df_art['OCDE_clasification_code_manual'])

    # Drop the extra column
    df_art = df_art.drop(columns=['OCDE_clasification_code_manual'])

    # Merge with clasification_db to get area and gran area
    df_art = pd.merge(df_art, clasification_db, on='OCDE_clasification_code', how='left')

    # Now, for the category only search for the corresponding year
    df_art = pd.merge(df_art,
                      publindex_db[['issn', 'nro_ano', 'id_clas_rev']],
                      left_on=['issn', 'year'],
                      right_on=['issn', 'nro_ano'],
                      how='left')

    # Merge with the homologation database
    # First, find the maximum year available in homologation database
    max_year_homolog = pd.to_numeric(homologation_db['year_publindex'], errors='coerce').max()
    max_year_homolog = int(max_year_homolog)
    logger.info(f"Maximum year in homologation database: {max_year_homolog}")

    # Rename columns from homologation to avoid conflicts
    homolog_data = homologation_db[['issn', 'year_publindex', 'category_publindex']].copy()
    homolog_data = homolog_data.rename(columns={
        'year_publindex': 'year_homolog',
        'category_publindex': 'category_homolog'
    })

    # First merge: exact year match
    df_art = pd.merge(df_art,
                        homolog_data,
                        left_on=['issn', 'year'],
                        right_on=['issn', 'year_homolog'],
                        how='left')

    # Second merge: for articles with years beyond max_year_homolog that don't have a category,
    # use the category from the last available year
    last_year_data = homolog_data[homolog_data['year_homolog'] == str(max_year_homolog)].copy()
    last_year_data = last_year_data.rename(columns={
        'year_homolog': 'year_last_available',
        'category_homolog': 'category_last_available'
    })

    df_art = pd.merge(df_art,
                        last_year_data[['issn', 'category_last_available']],
                        on='issn',
                        how='left')

    # Apply last year category only for articles with year > max_year_homolog and no category yet
    df_art['year_int'] = pd.to_numeric(df_art['year'], errors='coerce')
    mask_future_years = (df_art['year_int'] > max_year_homolog) & (df_art['category_homolog'].isna())
    df_art.loc[mask_future_years, 'category_homolog'] = df_art.loc[mask_future_years, 'category_last_available']
    df_art.loc[mask_future_years, 'year_homolog'] = str(max_year_homolog)

    # Clean to keep only one column with category and year
    # Combine publindex and homologation data (publindex takes priority)
    df_art['category_publindex'] = df_art['id_clas_rev'].combine_first(df_art['category_homolog'])
    df_art['year_publindex'] = df_art['nro_ano'].combine_first(df_art['year_homolog'])

    # Remove duplicates and temporary columns
    df_art.drop(columns=['nro_ano', 'id_clas_rev', 'category_homolog', 'year_homolog',
                         'category_last_available', 'year_int'], inplace=True, errors='ignore')

    # If there is no category, fill with "No Disponible"
    df_art['category_publindex'] = df_art['category_publindex'].fillna("No Disponible")
    df_art['year_publindex'] = df_art['year_publindex'].fillna("No Disponible")

    # Capitalize titles and journal names
    df_art['journal'] = df_art['journal'].apply(capitalize_title)
    df_art['tittle'] = df_art['tittle'].apply(capitalize_title)

    # Fill na in DOI
    df_art['doi'] = df_art['doi'].fillna("No Disponible")

    # Drop same manuscript title

    # Generar cita APA
    def formatear_apa(row):
        authors = row['authors']
        autores_formateados = ', '.join([
			' '.join([w.capitalize() for w in a.strip().split()])
			for a in authors.split(',')
		])
        year = row['year']
        titulo = row['tittle']
        revista = row['journal']
        vol_fasc_pag = row['vol_fasc_pag']
        doi = row['doi']
        return f"{autores_formateados} ({year}). {titulo}. *{revista}*, {vol_fasc_pag}. https://doi.org/{doi}"

    df_art['citation_apa'] = df_art.apply(formatear_apa, axis=1)
    # df_merge_cat['Cita APA'] = df_merge_cat['DOI'].apply(lambda doi: get_cite_from_doi(doi, estilo='apa'))

    # Guardar archivo enriquecido
    base, ext = os.path.splitext(os.path.basename(file_csv))
    output_file_name = output_path / f"{base}_enriched{ext}"
    df_art.to_csv(output_file_name, index=False)
    logger.info(f"Archivo enriquecido guardado en: {output_path}")

    return df_art