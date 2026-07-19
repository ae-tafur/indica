import os
import glob
import logging
import pandas as pd
import requests
import re
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def join_csvs_from_path(csv_files):
    """
    Joins all .csv files from the given directory into a single DataFrame.
    Adds a column with the source filename (cleaned).

    Parameters:
    csv_files: Path or list of paths to CSV files (can include wildcards)

    Returns:
    pd.DataFrame: Combined DataFrame from all CSV files with filename column
    """
    # Handle single path
    if isinstance(csv_files, (str, Path)):
        pattern = str(csv_files)
        if '*' in pattern:
            files = glob.glob(pattern)
        elif os.path.isdir(pattern):
            files = glob.glob(os.path.join(pattern, "*.csv"))
        else:
            files = [pattern]
    else:
        files = [str(f) if isinstance(f, Path) else f for f in csv_files]

    if not files:
        return pd.DataFrame()

    dfs = []
    for f in files:
        df = pd.read_csv(f)
        # Extract filename without path and .csv extension
        filename = os.path.basename(f).replace('.csv', '')
        # If filename contains wildcard pattern, extract the relevant part
        if '*' in str(csv_files):
            parts = filename.split('_')
            filename = parts[0] if parts else filename
        df['filename'] = filename
        dfs.append(df)

    return pd.concat(dfs, ignore_index=True)

def normalize_doi(doi):
    """
    Normalizes a DOI string for comparison purposes: lowercases it and
    removes common URL prefixes and surrounding whitespace.
    Also validates that it looks like a real DOI (starts with 10.)

    Parameters:
    doi: DOI value (can be NaN/None)

    Returns:
    str or None: normalized DOI, or None if not a valid DOI
    """
    if pd.isna(doi):
        return None
    doi = str(doi).strip()
    if not doi or doi.lower() in ('no disponible', 'nan', 'none', 'doi:', ''):
        return None

    # Remove URL prefixes
    doi = doi.lower()
    for prefix in ('https://doi.org/', 'http://dx.doi.org/', 'doi.org/', 'doi:'):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]

    doi = doi.strip('/ ')

    # Validate DOI format: must start with "10." followed by numbers
    # ISSNs like "0122-8706" should NOT be considered valid DOIs
    if not doi or not doi.startswith('10.'):
        return None

    # Must have at least one slash or number after "10."
    if len(doi) < 5:
        return None

    return doi or None


def normalize_title(title):
    """
    Normaliza un título para comparación: elimina comillas iniciales/finales,
    espacios extra, puntuación, acentos y convierte a minúsculas.

    Parameters:
    title: Título del artículo

    Returns:
    str: Título normalizado
    """
    if pd.isna(title):
        return ""

    # Convertir a string
    title = str(title).strip()

    # Eliminar comillas al inicio y final de TODO tipo (dobles, simples, tipográficas)
    # Incluye comillas unicode y múltiples iteraciones
    while True:
        old_title = title
        # Eliminar comillas y espacios al inicio
        title = re.sub(r'^[\s\"\'\'\"\"\`\´\u2018\u2019\u201C\u201D]+', '', title)
        # Eliminar comillas y espacios al final
        title = re.sub(r'[\s\"\'\'\"\"\`\´\u2018\u2019\u201C\u201D]+$', '', title)
        if title == old_title:
            break

    # Convertir a minúsculas
    title = title.lower()

    # Normalizar unicode (remover acentos): NFD descompone, luego filtra diacríticos
    title = unicodedata.normalize('NFD', title)
    title = ''.join(char for char in title if unicodedata.category(char) != 'Mn')

    # Eliminar puntuación y caracteres especiales
    title = re.sub(r'[^\w\s]', ' ', title)

    # Colapsar múltiples espacios en uno solo
    title = re.sub(r'\s+', ' ', title)

    return title.strip()


def titles_are_similar(title1, title2, threshold=0.9):
    """
    Compara dos títulos usando SequenceMatcher para determinar si son similares.

    Parameters:
    title1: Primer título
    title2: Segundo título
    threshold: Umbral de similitud (0-1), por defecto 0.9

    Returns:
    bool: True si los títulos son similares
    """
    norm1 = normalize_title(title1)
    norm2 = normalize_title(title2)

    if not norm1 or not norm2:
        return False

    similarity = SequenceMatcher(None, norm1, norm2).ratio()
    return similarity >= threshold


def validate_doi_url(doi, use_api=True):
    """
    Valida si un DOI funciona usando múltiples estrategias:
    1. API oficial de DOI.org (más confiable)
    2. Requests HTTP directos con headers de navegador

    Parameters:
    doi: DOI a validar (puede ser URL completa o solo el identificador)
    use_api: Si usar el API de DOI.org (más confiable pero requiere conexión)

    Returns:
    bool: True si el DOI es válido y accesible
    """
    if pd.isna(doi) or not doi:
        return False

    # Normalizar DOI a URL completa y extraer el identificador
    doi_str = str(doi).strip()
    if doi_str.lower() in ('no disponible', 'nan', 'none', ''):
        return False

    # Extraer el DOI puro (sin URL)
    bare_doi = doi_str
    if 'doi.org/' in doi_str:
        bare_doi = doi_str.split('doi.org/')[-1]
    elif doi_str.startswith('doi:'):
        bare_doi = doi_str[4:].strip()

    bare_doi = bare_doi.strip('/ ')

    # Estrategia 1: Usar API de DOI.org (más confiable)
    if use_api:
        try:
            api_url = f"https://api.crossref.org/works/{bare_doi}"
            headers_api = {
                'User-Agent': 'INDICA/1.0 (mailto:research@example.com)',
            }
            response = requests.get(api_url, headers=headers_api, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Verificar que el mensaje contiene el DOI
                if data.get('status') == 'ok' and 'message' in data:
                    return True
        except Exception as e:
            # Si falla el API, continuar con otras estrategias
            logger.debug(f"API validation failed for {bare_doi}: {e}")
            pass

    # Estrategia 2: Request HTTP directo con headers de navegador
    full_doi_url = f"https://doi.org/{bare_doi}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,es;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    }

    # Intentar HEAD primero (más rápido)
    try:
        response = requests.head(full_doi_url, headers=headers, allow_redirects=True, timeout=10)
        if 200 <= response.status_code < 400:
            return True
    except:
        pass

    # Si HEAD falla, intentar GET
    try:
        response = requests.get(full_doi_url, headers=headers, allow_redirects=True, timeout=10)
        if 200 <= response.status_code < 400:
            return True
    except:
        pass

    # Estrategia 3: Intentar con dx.doi.org (servicio alternativo más antiguo)
    try:
        alt_url = f"http://dx.doi.org/{bare_doi}"
        response = requests.get(alt_url, headers=headers, allow_redirects=True, timeout=10)
        if 200 <= response.status_code < 400:
            return True
    except:
        pass

    return False


def search_article_in_openalex(title, authors=None):
    """
    Busca un artículo en OpenAlex API usando el título y opcionalmente autores.
    OpenAlex es una base de datos abierta de publicaciones académicas.

    Parameters:
    title: Título del artículo a buscar
    authors: Autores del artículo (opcional, mejora precisión)

    Returns:
    dict or None: Información del artículo encontrado (incluyendo DOI, título, etc.) o None si no se encuentra
    """
    if pd.isna(title) or not title:
        return None

    try:
        # Normalizar título para búsqueda
        search_title = str(title).strip()

        # Construir query para OpenAlex
        # Usamos filter en lugar de search para mayor precisión
        base_url = "https://api.openalex.org/works"

        # Parámetros de búsqueda
        params = {
            'filter': f'title.search:{search_title}',
            'per-page': 5,  # Top 5 resultados
            'mailto': 'research@example.com'  # Requerido por OpenAlex para tasa de uso mejorada
        }

        headers = {
            'User-Agent': 'INDICA/1.0 (mailto:research@example.com)'
        }

        response = requests.get(base_url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])

            if not results:
                return None

            # Tomar el primer resultado (más relevante)
            best_match = results[0]

            # Calcular similitud entre título buscado y título encontrado
            found_title = best_match.get('title', '')
            norm_search = normalize_title(search_title)
            norm_found = normalize_title(found_title)

            similarity = SequenceMatcher(None, norm_search, norm_found).ratio()

            # Solo aceptar si la similitud es alta (>85%)
            if similarity < 0.85:
                logger.debug(f"OpenAlex: Similitud baja ({similarity:.2%}) entre '{search_title}' y '{found_title}'")
                return None

            # Extraer información útil
            article_info = {
                'title': found_title,
                'doi': best_match.get('doi', '').replace('https://doi.org/', '') if best_match.get('doi') else None,
                'publication_year': best_match.get('publication_year'),
                'cited_by_count': best_match.get('cited_by_count', 0),
                'openalex_id': best_match.get('id'),
                'similarity': similarity
            }

            logger.info(f"   ✓ OpenAlex encontró coincidencia ({similarity:.1%} similitud): {found_title[:60]}...")
            if article_info['doi']:
                logger.info(f"     DOI en OpenAlex: {article_info['doi']}")

            return article_info

    except Exception as e:
        logger.debug(f"Error buscando en OpenAlex: {e}")
        return None

    return None


def merge_duplicate_rows(df, group_col, mode='inter_group'):
    """
    Fusiona filas duplicadas: en modo inter_group, combina los valores de 'filename',
    en modo intra_group, simplemente elimina duplicados.

    Parameters:
    df: DataFrame con duplicados agrupados por group_col
    group_col: Columna por la cual están agrupados los duplicados (_doi_normalized o _title_normalized)
    mode: 'inter_group' (fusiona filename) o 'intra_group' (elimina)

    Returns:
    DataFrame sin duplicados
    """
    if mode == 'intra_group':
        # Modo simple: eliminar duplicados, mantener el más completo
        return df.drop_duplicates(subset=[group_col], keep='first')

    # Modo inter_group: fusionar información de filename
    if 'filename' not in df.columns:
        # Si no hay columna filename, comportarse como intra_group
        return df.drop_duplicates(subset=[group_col], keep='first')

    # Agrupar por la columna de deduplicación y fusionar filenames
    result_rows = []
    for group_val, group in df.groupby(group_col):
        if pd.isna(group_val) or group_val == '':
            # No agrupar valores vacíos/nulos
            result_rows.extend(group.to_dict('records'))
            continue

        if len(group) == 1:
            # Solo una fila, no hay que fusionar
            result_rows.append(group.iloc[0].to_dict())
        else:
            # Múltiples filas: tomar la primera (más completa) y fusionar filenames
            merged_row = group.iloc[0].to_dict()

            # Combinar todos los filenames únicos
            filenames = []
            for idx, row in group.iterrows():
                fn = row.get('filename', '')
                if pd.notna(fn) and fn:
                    # Puede que ya venga con múltiples separados por coma
                    filenames.extend([f.strip() for f in str(fn).split(',')])

            # Eliminar duplicados y ordenar
            unique_filenames = sorted(set(f for f in filenames if f))
            merged_row['filename'] = ', '.join(unique_filenames)

            result_rows.append(merged_row)

    return pd.DataFrame(result_rows)


def deduplicate_articles_by_doi(df, doi_column='doi', title_column='tittle',
                                journal_column='journal', authors_column='authors',
                                similarity_threshold=0.86, validate_dois=True,
                                generate_report=True, use_openalex=True,
                                mode='inter_group'):
    """
    Deduplicates articles across the whole dataset with advanced duplicate detection:

    1. Normaliza títulos (elimina comillas, espacios, puntuación)
    2. Elimina duplicados por DOI (cuando el DOI es válido)
    3. Para mismo título con DOIs diferentes: valida cuál DOI funciona
    4. Para artículos sin DOI: usa similitud de títulos (threshold configurable)
    5. Mantiene el registro más completo (más autores) cuando hay duplicados

    Parameters:
    df (pd.DataFrame): Combined articles DataFrame
    doi_column (str): Name of the DOI column
    title_column (str): Name of the article title column
    journal_column (str): Name of the journal column
    authors_column (str): Name of the authors column
    similarity_threshold (float): Threshold for title similarity (0-1), default 0.86
    validate_dois (bool): Whether to validate DOIs via HTTP requests
    generate_report (bool): Whether to generate a detailed report of removed duplicates
    use_openalex (bool): Whether to use OpenAlex API for validation
    mode (str): 'intra_group' elimina duplicados, 'inter_group' fusiona info de grupos

    Returns:
    tuple: (df_unique, duplicates_report) where:
        - df_unique: DataFrame with one row per unique article
        - duplicates_report: DataFrame with details of removed duplicates (or None)
    """
    df = df.copy()
    n_before = len(df)

    # Lista para almacenar información sobre duplicados eliminados
    duplicates_info = [] if generate_report else None

    # Normalizar DOIs y títulos
    df['_doi_normalized'] = df[doi_column].apply(normalize_doi) if doi_column in df.columns else None
    df['_title_normalized'] = df[title_column].apply(normalize_title) if title_column in df.columns else ""
    df['_autores_len'] = df[authors_column].fillna('').str.len()

    # Limpiar títulos en el DataFrame: eliminar comillas al inicio/final (sin normalizar acentos/puntuación)
    def clean_title_for_display(title):
        """Limpia título para visualización: solo elimina comillas extremas, mantiene el resto"""
        if pd.isna(title):
            return title
        title = str(title).strip()
        # Eliminar comillas al inicio y final iterativamente
        while True:
            old_title = title
            title = re.sub(r'^[\"\'\'\"\"\`\´\u2018\u2019\u201C\u201D\s]+', '', title)
            title = re.sub(r'[\"\'\'\"\"\`\´\u2018\u2019\u201C\u201D\s]+$', '', title)
            if title == old_title:
                break
        return title.strip()

    df[title_column] = df[title_column].apply(clean_title_for_display)

    logger.info(f"Iniciando deduplicación avanzada de {n_before} artículos...")

    # PASO 1: Manejar artículos CON DOI
    has_doi = df['_doi_normalized'].notna()
    df_with_doi = df[has_doi].copy()
    df_without_doi = df[~has_doi].copy()

    if not df_with_doi.empty:
        logger.info(f"Procesando {len(df_with_doi)} artículos con DOI...")

        # Detectar mismo título con DOIs diferentes
        title_groups = df_with_doi.groupby('_title_normalized')
        conflicting_titles = []

        for title_norm, group in title_groups:
            if len(group['_doi_normalized'].unique()) > 1 and title_norm:
                # Mismo título, múltiples DOIs
                logger.info(f"⚠️  Título con múltiples DOIs detectado: '{group.iloc[0][title_column][:60]}...'")

                if validate_dois:
                    # Validar cada DOI
                    valid_dois = []
                    doi_validation_results = {}

                    for idx, row in group.iterrows():
                        doi_val = row[doi_column]
                        is_valid = validate_doi_url(doi_val)
                        doi_validation_results[idx] = is_valid

                        if is_valid:
                            valid_dois.append(idx)
                            logger.info(f"   ✓ DOI válido: {doi_val}")
                        else:
                            logger.info(f"   ✗ DOI inválido: {doi_val}")

                    # Mantener solo los registros con DOI válido
                    if valid_dois:
                        # Si solo hay un DOI válido, eliminar los demás
                        if len(valid_dois) == 1:
                            indices_to_remove = group.index[~group.index.isin(valid_dois)]
                            conflicting_titles.extend(indices_to_remove)

                            # Registrar duplicados eliminados
                            if generate_report:
                                kept_idx = valid_dois[0]
                                for idx in indices_to_remove:
                                    duplicates_info.append({
                                        'titulo_eliminado': group.loc[idx, title_column],
                                        'doi_eliminado': group.loc[idx, doi_column],
                                        'revista_eliminada': group.loc[idx, journal_column],
                                        'autores_eliminados': group.loc[idx, authors_column],
                                        'grupo_eliminado': group.loc[idx, 'filename'] if 'filename' in group.columns else 'N/A',
                                        'titulo_mantenido': group.loc[kept_idx, title_column],
                                        'doi_mantenido': group.loc[kept_idx, doi_column],
                                        'grupo_mantenido': group.loc[kept_idx, 'filename'] if 'filename' in group.columns else 'N/A',
                                        'razon': f'DOI inválido (mismo título, DOI diferente)',
                                        'doi_valido': 'No'
                                    })
                        else:
                            # Si hay MÚLTIPLES DOIs válidos, verificar si alguno es prefijo de otro
                            # Ejemplo: "10.22490/" es prefijo de "10.22490/21456453.992"
                            valid_doi_strings = []
                            valid_doi_map = {}  # doi_normalizado -> índice

                            for idx in valid_dois:
                                doi_norm = group.loc[idx, '_doi_normalized']
                                valid_doi_strings.append(doi_norm)
                                valid_doi_map[doi_norm] = idx

                            # Ordenar por longitud (más largos primero)
                            valid_doi_strings_sorted = sorted(valid_doi_strings, key=len, reverse=True)

                            # Identificar DOIs que son prefijos de otros
                            dois_to_remove = set()
                            for i, doi_long in enumerate(valid_doi_strings_sorted):
                                for doi_short in valid_doi_strings_sorted[i+1:]:
                                    # Si doi_short es prefijo de doi_long
                                    if doi_long.startswith(doi_short):
                                        dois_to_remove.add(doi_short)
                                        logger.info(
                                            f"   ⚠️  DOI incompleto detectado: {doi_short} "
                                            f"es prefijo de {doi_long}"
                                        )

                            # Eliminar registros con DOIs incompletos (prefijos)
                            if dois_to_remove:
                                for doi_short in dois_to_remove:
                                    idx_to_remove = valid_doi_map[doi_short]
                                    conflicting_titles.append(idx_to_remove)
                                    valid_dois.remove(idx_to_remove)

                                    if generate_report:
                                        # Buscar el DOI más largo que lo contiene
                                        kept_doi = None
                                        kept_idx = None
                                        for doi_long in valid_doi_strings_sorted:
                                            if doi_long.startswith(doi_short) and doi_long != doi_short:
                                                kept_doi = doi_long
                                                kept_idx = valid_doi_map[doi_long]
                                                break

                                        duplicates_info.append({
                                            'titulo_eliminado': group.loc[idx_to_remove, title_column],
                                            'doi_eliminado': group.loc[idx_to_remove, doi_column],
                                            'revista_eliminada': group.loc[idx_to_remove, journal_column],
                                            'autores_eliminados': group.loc[idx_to_remove, authors_column],
                                            'grupo_eliminado': group.loc[idx_to_remove, 'filename'] if 'filename' in group.columns else 'N/A',
                                            'titulo_mantenido': group.loc[kept_idx, title_column] if kept_idx else 'N/A',
                                            'doi_mantenido': group.loc[kept_idx, doi_column] if kept_idx else 'N/A',
                                            'grupo_mantenido': group.loc[kept_idx, 'filename'] if kept_idx and 'filename' in group.columns else 'N/A',
                                            'razon': f'DOI incompleto (prefijo de otro DOI más completo)',
                                            'doi_valido': 'Sí (pero incompleto)'
                                        })

                            # Si después de eliminar prefijos aún quedan múltiples DOIs válidos
                            if len(valid_dois) > 1:
                                # Verificar si son duplicados exactos (mismo DOI, diferente caso)
                                unique_dois_lower = set()
                                dois_case_sensitive = {}

                                for idx in valid_dois:
                                    doi_norm = group.loc[idx, '_doi_normalized']
                                    doi_lower = doi_norm.lower()

                                    if doi_lower in unique_dois_lower:
                                        # Duplicado con diferente mayúsculas/minúsculas
                                        # Mantener el primero que encontramos
                                        conflicting_titles.append(idx)
                                        logger.info(
                                            f"   ⚠️  DOI duplicado (diferente capitalización): {doi_norm}"
                                        )
                                    else:
                                        unique_dois_lower.add(doi_lower)
                                        dois_case_sensitive[doi_lower] = idx

                                # Actualizar valid_dois después de eliminar duplicados de capitalización
                                valid_dois = list(dois_case_sensitive.values())

                            # Si TODAVÍA quedan múltiples DOIs válidos diferentes
                            if len(valid_dois) > 1:
                                logger.warning(
                                    f"   ⚠️  Múltiples DOIs válidos y diferentes detectados para el mismo título. "
                                    f"Se mantienen todos ({len(valid_dois)} registros) ya que cada DOI "
                                    f"puede representar un artículo diferente (versión, corrección, etc.)"
                                )
                                # No agregar nada a conflicting_titles, mantener todos
                    else:
                        # Si ningún DOI es válido, mantener el más completo
                        logger.warning(f"   ⚠️  Ningún DOI es válido, manteniendo el registro más completo")
                        kept = group.nlargest(1, '_autores_len', keep='first')
                        indices_to_remove = group.index[~group.index.isin(kept.index)]
                        conflicting_titles.extend(indices_to_remove)

                        # Registrar duplicados eliminados
                        if generate_report:
                            kept_idx = kept.index[0]
                            for idx in indices_to_remove:
                                duplicates_info.append({
                                    'titulo_eliminado': group.loc[idx, title_column],
                                    'doi_eliminado': group.loc[idx, doi_column],
                                    'revista_eliminada': group.loc[idx, journal_column],
                                    'autores_eliminados': group.loc[idx, authors_column],
                                    'grupo_eliminado': group.loc[idx, 'filename'] if 'filename' in group.columns else 'N/A',
                                    'titulo_mantenido': group.loc[kept_idx, title_column],
                                    'doi_mantenido': group.loc[kept_idx, doi_column],
                                    'grupo_mantenido': group.loc[kept_idx, 'filename'] if 'filename' in group.columns else 'N/A',
                                    'razon': 'Ningún DOI válido (mantenido registro más completo)',
                                    'doi_valido': 'No'
                                })

        # Eliminar registros con DOIs inválidos cuando hay conflicto
        if conflicting_titles:
            logger.info(f"Eliminando {len(conflicting_titles)} registros con DOIs conflictivos/inválidos")
            df_with_doi = df_with_doi.drop(index=conflicting_titles)

        # Ordenar por longitud de autores (más completo primero)
        df_with_doi = df_with_doi.sort_values('_autores_len', ascending=False)

        # Registrar duplicados por DOI antes de eliminar
        if generate_report:
            doi_groups = df_with_doi.groupby('_doi_normalized')
            for doi_norm, group in doi_groups:
                if len(group) > 1:
                    kept_idx = group.index[0]  # Ya está ordenado por _autores_len
                    for idx in group.index[1:]:
                        duplicates_info.append({
                            'titulo_eliminado': group.loc[idx, title_column],
                            'doi_eliminado': group.loc[idx, doi_column],
                            'revista_eliminada': group.loc[idx, journal_column],
                            'autores_eliminados': group.loc[idx, authors_column],
                            'grupo_eliminado': group.loc[idx, 'filename'] if 'filename' in group.columns else 'N/A',
                            'titulo_mantenido': group.loc[kept_idx, title_column],
                            'doi_mantenido': group.loc[kept_idx, doi_column],
                            'grupo_mantenido': group.loc[kept_idx, 'filename'] if 'filename' in group.columns else 'N/A',
                            'razon': 'DOI duplicado (mismo artículo reportado por múltiples autores/grupos)',
                            'doi_valido': 'Sí'
                        })

        # Eliminar/fusionar duplicados por DOI según el modo
        df_with_doi = merge_duplicate_rows(df_with_doi, '_doi_normalized', mode=mode)

        if mode == 'inter_group':
            logger.info(f"Después de deduplicación por DOI: {len(df_with_doi)} artículos únicos (filenames fusionados)")
        else:
            logger.info(f"Después de deduplicación por DOI: {len(df_with_doi)} artículos únicos")

    # PASO 2: Manejar artículos SIN DOI (usar similitud de títulos)
    if not df_without_doi.empty:
        logger.info(f"Procesando {len(df_without_doi)} artículos sin DOI...")

        # Normalizar títulos y eliminar duplicados exactos
        df_without_doi = df_without_doi.sort_values('_autores_len', ascending=False)

        # Registrar y eliminar duplicados exactos por título normalizado
        if generate_report:
            title_groups = df_without_doi.groupby('_title_normalized')
            for title_norm, group in title_groups:
                if len(group) > 1 and title_norm:
                    kept_idx = group.index[0]  # Ya está ordenado por _autores_len
                    for idx in group.index[1:]:
                        duplicates_info.append({
                            'titulo_eliminado': group.loc[idx, title_column],
                            'doi_eliminado': 'No disponible',
                            'revista_eliminada': group.loc[idx, journal_column],
                            'autores_eliminados': group.loc[idx, authors_column],
                            'grupo_eliminado': group.loc[idx, 'filename'] if 'filename' in group.columns else 'N/A',
                            'titulo_mantenido': group.loc[kept_idx, title_column],
                            'doi_mantenido': 'No disponible',
                            'grupo_mantenido': group.loc[kept_idx, 'filename'] if 'filename' in group.columns else 'N/A',
                            'razon': 'Título exactamente igual (sin DOI)',
                            'doi_valido': 'N/A'
                        })

        exact_before = len(df_without_doi)
        df_without_doi = merge_duplicate_rows(df_without_doi, '_title_normalized', mode=mode)
        exact_removed = exact_before - len(df_without_doi)
        if exact_removed > 0:
            if mode == 'inter_group':
                logger.info(f"Fusionados {exact_removed} artículos con título exactamente igual (filenames combinados)")
            else:
                logger.info(f"Eliminados {exact_removed} duplicados exactos por título")

        # Buscar títulos similares (fuzzy matching)
        indices_to_remove = set()
        indices_kept = {}  # Mapea índice eliminado -> índice mantenido
        processed = set()

        for idx1, row1 in df_without_doi.iterrows():
            if idx1 in processed or idx1 in indices_to_remove:
                continue

            title1 = row1['_title_normalized']
            if not title1:
                continue

            for idx2, row2 in df_without_doi.iterrows():
                if idx2 <= idx1 or idx2 in indices_to_remove:
                    continue

                title2 = row2['_title_normalized']
                if not title2:
                    continue

                # Calcular similitud
                similarity = SequenceMatcher(None, title1, title2).ratio()

                if similarity >= similarity_threshold:
                    # Títulos similares encontrados
                    logger.info(f"Títulos similares ({similarity:.2%}): "
                              f"'{row1[title_column][:50]}...' vs '{row2[title_column][:50]}...'")

                    # Validar con OpenAlex si están disponibles y si son el mismo artículo
                    are_same_article = True  # Por defecto asumimos que son el mismo
                    validation_method = 'similitud de título'

                    if use_openalex and similarity < 0.95:  # Solo validar si no son casi idénticos
                        # Buscar ambos títulos en OpenAlex
                        openalex1 = search_article_in_openalex(row1[title_column])
                        openalex2 = search_article_in_openalex(row2[title_column])

                        # Si ambos están en OpenAlex y tienen DOI diferentes, son artículos distintos
                        if (openalex1 and openalex2 and
                            openalex1.get('doi') and openalex2.get('doi') and
                            openalex1['doi'] != openalex2['doi']):
                            are_same_article = False
                            validation_method = 'OpenAlex (DOIs diferentes)'
                            logger.info(f"   ⚠️  OpenAlex indica que son artículos DIFERENTES:")
                            logger.info(f"      - '{row1[title_column][:50]}...' → DOI: {openalex1['doi']}")
                            logger.info(f"      - '{row2[title_column][:50]}...' → DOI: {openalex2['doi']}")

                    if are_same_article:
                        # Mantener el más completo (ya está ordenado por _autores_len)
                        indices_to_remove.add(idx2)
                        indices_kept[idx2] = idx1
                        processed.add(idx2)

                        # En modo inter_group, fusionar filenames en row1
                        if mode == 'inter_group' and 'filename' in df_without_doi.columns:
                            fn1 = df_without_doi.at[idx1, 'filename']
                            fn2 = row2.get('filename', '')

                            filenames = []
                            if pd.notna(fn1) and fn1:
                                filenames.extend([f.strip() for f in str(fn1).split(',')])
                            if pd.notna(fn2) and fn2:
                                filenames.extend([f.strip() for f in str(fn2).split(',')])

                            unique_filenames = sorted(set(f for f in filenames if f))
                            df_without_doi.at[idx1, 'filename'] = ', '.join(unique_filenames)

                        # Registrar duplicado
                        if generate_report:
                            duplicates_info.append({
                                'titulo_eliminado': row2[title_column],
                                'doi_eliminado': 'No disponible',
                                'revista_eliminada': row2[journal_column],
                                'autores_eliminados': row2[authors_column],
                                'grupo_eliminado': row2['filename'] if 'filename' in row2 else 'N/A',
                                'titulo_mantenido': row1[title_column],
                                'doi_mantenido': 'No disponible',
                                'grupo_mantenido': df_without_doi.at[idx1, 'filename'] if 'filename' in df_without_doi.columns else 'N/A',
                                'razon': f'Título similar ({similarity:.1%} similitud, validado por {validation_method})',
                                'doi_valido': 'N/A'
                            })
                    else:
                        logger.info(f"   ✓ Manteniendo ambos artículos (validados como diferentes)")

            processed.add(idx1)

        if indices_to_remove:
            if mode == 'inter_group':
                logger.info(f"Fusionando {len(indices_to_remove)} artículos similares (filenames combinados)")
            else:
                logger.info(f"Eliminando {len(indices_to_remove)} duplicados por similitud de título")
            df_without_doi = df_without_doi.drop(index=list(indices_to_remove))

        logger.info(f"Después de deduplicación sin DOI: {len(df_without_doi)} artículos únicos")

    # PASO 2.5: Eliminar artículos SIN DOI que tienen el mismo título que artículos CON DOI
    if not df_with_doi.empty and not df_without_doi.empty:
        logger.info("Verificando duplicados entre artículos con DOI y sin DOI...")

        # Obtener títulos normalizados de artículos CON DOI
        titles_with_doi = set(df_with_doi['_title_normalized'].dropna())

        # Identificar artículos SIN DOI que tienen el mismo título que uno CON DOI
        indices_to_remove_no_doi = []
        for idx, row in df_without_doi.iterrows():
            title_norm = row['_title_normalized']
            if title_norm and title_norm in titles_with_doi:
                # Este artículo sin DOI tiene el mismo título que uno con DOI
                indices_to_remove_no_doi.append(idx)

                # Buscar el artículo con DOI correspondiente
                matching_with_doi = df_with_doi[df_with_doi['_title_normalized'] == title_norm].iloc[0]

                if generate_report:
                    duplicates_info.append({
                        'titulo_eliminado': row[title_column],
                        'doi_eliminado': 'No disponible',
                        'revista_eliminada': row[journal_column],
                        'autores_eliminados': row[authors_column],
                        'grupo_eliminado': row['filename'] if 'filename' in row else 'N/A',
                        'titulo_mantenido': matching_with_doi[title_column],
                        'doi_mantenido': matching_with_doi[doi_column],
                        'grupo_mantenido': matching_with_doi['filename'] if 'filename' in matching_with_doi else 'N/A',
                        'razon': 'Mismo título (prioridad a artículo con DOI)',
                        'doi_valido': 'N/A'
                    })

        if indices_to_remove_no_doi:
            logger.info(f"Eliminando {len(indices_to_remove_no_doi)} artículos sin DOI que duplican títulos con DOI")
            df_without_doi = df_without_doi.drop(index=indices_to_remove_no_doi)

    # PASO 3: Combinar resultados
    df_unique = pd.concat([df_with_doi, df_without_doi], ignore_index=True)

    # Limpiar columnas temporales
    df_unique = df_unique.drop(columns=['_doi_normalized', '_title_normalized', '_autores_len'])

    n_after = len(df_unique)
    n_removed = n_before - n_after

    logger.info(
        f"✅ Deduplicación completada: {n_before} artículos → {n_after} únicos "
        f"({n_removed} duplicados eliminados, {n_removed/n_before*100:.1f}%)"
    )

    # Crear DataFrame con el reporte de duplicados
    duplicates_report = None
    if generate_report and duplicates_info:
        duplicates_report = pd.DataFrame(duplicates_info)
        logger.info(f"📋 Reporte de duplicados generado con {len(duplicates_report)} registros")

    return df_unique, duplicates_report


def build_missing_info_report(df, filename_column='filename'):
    """
    Flags articles with missing/incomplete key information (DOI, authors,
    ISSN, title, journal, Publindex category) so it is easy to identify which
    records need to be reviewed/completed by each author or research group,
    and to use as a guide before running bibliometric analyses or writing
    reports.

    Parameters:
    df (pd.DataFrame): Articles DataFrame (ideally already deduplicated by DOI)
    filename_column (str): Column identifying the research group/source file

    Returns:
    tuple: (df_missing_detail, df_missing_summary)
        df_missing_detail: one row per incomplete article, with a
            'campos_faltantes' column listing which key fields are
            missing/invalid.
        df_missing_summary: counts of missing fields per group (filename),
            useful to know which group/author to contact for corrections.
    """
    df = df.copy()

    def is_missing(series):
        return (
            series.isna()
            | series.astype(str).str.strip().str.lower().isin(['', 'no disponible', 'nan', 'none'])
        )

    checks = {
        'sin_doi': 'doi',
        'sin_autores': 'authors',
        'sin_issn': 'issn',
        'sin_titulo': 'tittle',
        'sin_revista': 'journal',
        'sin_categoria_publindex': 'category_publindex',
    }

    missing_flags = pd.DataFrame(index=df.index)
    for flag_name, col in checks.items():
        missing_flags[flag_name] = is_missing(df[col]) if col in df.columns else False

    df['campos_faltantes'] = missing_flags.apply(
        lambda row: ', '.join(
            flag.replace('sin_', '').replace('_', ' ')
            for flag, is_miss in row.items() if is_miss
        ),
        axis=1
    )
    df['tiene_informacion_incompleta'] = missing_flags.any(axis=1)

    id_cols = [c for c in [filename_column, 'tittle', 'journal', 'year', 'authors', 'doi']
              if c in df.columns]
    detail_cols = id_cols + ['campos_faltantes', 'tiene_informacion_incompleta']
    df_missing_detail = df.loc[df['tiene_informacion_incompleta'], detail_cols].copy()

    df_missing_summary = pd.DataFrame()
    if filename_column in df.columns:
        summary_rows = []
        for flag_name in checks:
            counts = missing_flags.groupby(df[filename_column])[flag_name].sum()
            for group, count in counts.items():
                if count > 0:
                    summary_rows.append({
                        filename_column: group,
                        'campo_faltante': flag_name.replace('sin_', ''),
                        'cantidad_articulos': int(count)
                    })
        if summary_rows:
            df_missing_summary = pd.DataFrame(summary_rows).sort_values(
                [filename_column, 'cantidad_articulos'], ascending=[True, False]
            )

    return df_missing_detail, df_missing_summary


def expand_multi_group_articles(df, filename_column='filename'):
    """
    Expands articles that belong to multiple groups into separate rows.

    For example, if an article has filename='CINBIOS, BIOTECGEN', it will be
    expanded into two rows: one with filename='CINBIOS' and one with filename='BIOTECGEN'.

    Parameters:
    df (pd.DataFrame): Input DataFrame with potentially multi-group articles
    filename_column (str): Column containing group names (possibly comma-separated)

    Returns:
    pd.DataFrame: Expanded DataFrame with one row per group per article
    """
    df = df.copy()

    # Split filename by comma and expand into multiple rows
    df[filename_column] = df[filename_column].astype(str).str.split(',')
    df_expanded = df.explode(filename_column)

    # Clean whitespace
    df_expanded[filename_column] = df_expanded[filename_column].str.strip()

    # Remove empty values
    df_expanded = df_expanded[df_expanded[filename_column].notna() & (df_expanded[filename_column] != '')]

    return df_expanded.reset_index(drop=True)


def process_authors_dataframe(df, year_column='year', authors_column='authors',
                              title_column='tittle', journal_column='journal'):
    """
    Converts a DataFrame to an authors-focused DataFrame with properly formatted year
    and adds article count per author per year.

    Parameters:
    df (pd.DataFrame): Input DataFrame
    year_column (str): Name of the year column
    authors_column (str): Name of the authors column
    title_column (str): Name of the title column
    journal_column (str): Name of the journal column

    Returns:
    tuple: (processed DataFrame with one row per author, grouped DataFrame with counts)
    """
    # Create copy to avoid modifying original
    df_authors = df.copy()

    # Convert year column
    df_authors[year_column] = pd.to_numeric(df_authors[year_column], errors='coerce')
    df_authors = df_authors.dropna(subset=[year_column])
    df_authors[year_column] = df_authors[year_column].astype(int)

    # Split authors, keeping track of their original order (position) in the
    # authorship list before exploding, so the order is preserved and can be
    # used later (e.g. to identify first/corresponding authors)
    df_authors['author'] = df_authors[authors_column].str.split(',')
    df_authors['orden_autor'] = df_authors['author'].apply(
        lambda authors: list(range(1, len(authors) + 1)) if isinstance(authors, list) else []
    )

    df_authors = df_authors.explode(['author', 'orden_autor'])

    # Clean author names
    df_authors['author'] = df_authors['author'].str.strip()

    # Drop empty authors
    df_authors = df_authors[df_authors['author'].notna() & (df_authors['author'] != '')]
    df_authors = df_authors.drop_duplicates(subset=[title_column, journal_column, 'author'])

    # Create grouped DataFrame with counts
    df_authors_grouped = df_authors.groupby([year_column, 'author']).size().reset_index(name='count')

    return df_authors, df_authors_grouped


def count_articles_by_groups(df, group1, group2, value_name='count'):
    """
    Creates a DataFrame showing counts grouped by two variables with pivot table.

    Parameters:
    df (pd.DataFrame): Input DataFrame
    group1 (str): First grouping column (will be index)
    group2 (str): Second grouping column (will be columns)
    value_name (str): Name for the count column

    Returns:
    pd.DataFrame: Pivot table with counts and totals
    """
    # Group by both variables and count occurrences
    grouped_stats = df.groupby([group1, group2]).size().reset_index(name=value_name)

    # Pivot the table
    pivot_table = grouped_stats.pivot(
        index=group1,
        columns=group2,
        values=value_name
    ).fillna(0)

    # Add total column
    pivot_table['total'] = pivot_table.sum(axis=1)

    # Sort by total descending
    return pivot_table.sort_values('total', ascending=False)

