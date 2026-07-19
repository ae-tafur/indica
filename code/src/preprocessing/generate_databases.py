import os
import re
import glob
import logging
import requests
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Standardized field names (English)
STANDARD_FIELD_NAMES = {
    'type': 'type',
    'title': 'tittle',
    'journal': 'journal',
    'country': 'country',
    'year': 'year',
    'issn': 'issn',
    'info_biblio': 'vol_fasc_pag',
    'doi': 'doi',
    'authors': 'authors',
    'category': 'category',
    'name': 'name',
    'num': 'num',
    'vigencia': 'vigencia'
}

def extract_years(vigencia_str):
    """
    Extract all years (start and end) as a list from the validity period.

    Examples:
    - "Agosto 2023 - Diciembre 2023" -> [2023]
    - "Diciembre 2023 - Marzo 2024" -> [2023, 2024]
    - "2023" -> [2023]
    """
    if isinstance(vigencia_str, str):
        years = re.findall(r'\b(20\d{2})\b', vigencia_str)
        if len(years) == 0:
            return []
        elif len(years) == 1:
            return [int(years[0])]
        elif len(years) >= 2:
            start = int(years[0])
            end = int(years[1])
            # If same year, return only once
            if start == end:
                return [start]
            # If spans multiple years, return range
            return list(range(start, end + 1))
    return []

def get_category_priority(category):
    """
    Return priority for category (lower number = higher priority).
    A1 > A2 > B > C
    """
    category_str = str(category).strip().upper()
    priority_map = {'A1': 1, 'A2': 2, 'B': 3, 'C': 4}
    return priority_map.get(category_str, 999)  # Unknown categories get lowest priority

def fetch_all_socrata_rows(base_url, limit=100000):
    offset = 0
    dfs = []
    while True:
        url = f"{base_url}?$limit={limit}&$offset={offset}"
        df = pd.read_csv(url, dtype=str)
        if df.empty:
            break
        dfs.append(df)
        offset += limit
    return pd.concat(dfs, ignore_index=True)

def generate_homologation_database(input_folder, database_path, save_csv=False):
    """
    Merges multiple CSV files into a single table and adds a 'YEAR' column if it is in the file name.

    Parameters:
    - input_folder: path where the CSV files by year are located.
    - database_path: path where the final Parquet and csv file will be saved.
    - save_csv: boolean flag to determine if CSV file should be saved alongside Parquet (default: False)

    Returns:
    - the database as a pandas DataFrame
    """

    files = glob.glob(os.path.join(input_folder, "*.csv"))
    if not files:
        raise ValueError(f"No CSV files found in {input_folder}")
    logger.info(f"Found {len(files)} CSV files to process")

    tables = []
    required_columns = ['journal', 'issn', 'category_publindex', 'year_publindex']

    for file_path in files:
        try:
            logger.info(f"Processing file: {file_path}")
            df = pd.read_csv(file_path, low_memory=False, dtype=str)

            # Convert all column names to lowercase for consistency
            df.columns = [c.lower() for c in df.columns]

            # Check if all required columns are present
            missing_cols = [col for col in required_columns if col not in df.columns]
            if missing_cols:
                logger.warning(f"File {file_path} is missing required columns {missing_cols} - skipping")
                continue

            # Remove rows where all values are NaN
            df = df.dropna(how='all')

            # Extract years from year_publindex column (ensure it's string)
            df["AÑOS_RANGO"] = df["year_publindex"].astype(str).apply(extract_years)

            # Skip files that result in empty year ranges
            if df["AÑOS_RANGO"].apply(len).sum() == 0:
                logger.warning(f"No valid years found in {file_path} - skipping")
                continue

            # Expand rows by each year
            df_expanded = df.explode("AÑOS_RANGO")

            # Drop the original year_publindex column and rename AÑOS_RANGO
            df_expanded = df_expanded.drop(columns=['year_publindex'])
            df_expanded = df_expanded.rename(columns={"AÑOS_RANGO": "year_publindex"})

            # Keep only required columns
            df_expanded = df_expanded[['journal', 'issn', 'category_publindex', 'year_publindex']]

            tables.append(df_expanded)
            logger.info(f"Successfully processed {file_path}")

        except Exception as e:
            logger.error(f"Error processing {file_path}: {str(e)}")
            continue

    if not tables:
        raise ValueError("No valid data found in any of the CSV files")

    # Join all tables
    logger.info("Concatenating all processed tables")
    df_final = pd.concat(tables, ignore_index=True)

    # Expand multiple ISSNs (separated by semicolon) into separate rows
    logger.info("Expanding multiple ISSNs into separate rows")
    df_final = df_final.assign(issn=df_final['issn'].str.split(';')).explode('issn')
    df_final['issn'] = df_final['issn'].str.strip()

    # Remove duplicates: for same ISSN and year, keep the highest category
    logger.info("Removing duplicates and keeping highest category per ISSN-year")
    df_final['category_priority'] = df_final['category_publindex'].apply(get_category_priority)
    df_final = df_final.sort_values('category_priority')  # Sort by priority (lowest number first = highest category)
    df_final = df_final.drop_duplicates(subset=['issn', 'year_publindex'], keep='first')  # Keep first (highest priority)
    df_final = df_final.drop(columns=['category_priority'])  # Remove helper column

    # Convert year_publindex to string format (remove .0 from floats)
    # This is more efficient than converting on every enrichment
    logger.info("Converting year_publindex to string format")
    df_final['year_publindex'] = df_final['year_publindex'].fillna(-1).astype(int).astype(str).replace('-1', '')

    # Sort by year
    df_final = df_final.sort_values(by="year_publindex")

    # Delete columns period type before saving
    for col in df_final.columns:
        if isinstance(df_final[col].dtype, pd.PeriodDtype):
            df_final[col] = df_final[col].astype(str)

    # Save as parquet file (default)
    output_parquet = os.path.join(database_path, "homologation_database.parquet")
    df_final.to_parquet(output_parquet, index=False)
    logger.info(f"Parquet file saved to: {output_parquet}")
    logger.info(f"Columns: {list(df_final.columns)}")

    # Optionally save as CSV
    if save_csv:
        output_csv = os.path.join(database_path, "homologation_database.csv")
        df_final.to_csv(output_csv, index=False)
        logger.info(f"CSV file saved to: {output_csv}")

    return df_final

def generate_publindex_database(database_path, save_csv=False):
    """
    Get the publindex database from the "Datos Abiertos" website and store it in a .parquet and .csv file.

    Parameters:
    - input_folder: path where the CSV files by year are located.
    - database_path: path where the final Parquet and csv file will be saved.
    - save_csv: boolean flag to determine if CSV file should be saved alongside Parquet (default: False)

    Returns:
    - the database as a pandas DataFrame
    """

    # Download publindex database
    # https://www.datos.gov.co/Ciencia-Tecnolog-a-e-Innovaci-n/Revistas-Indexadas-ndice-Nacional-Publindex/mwmn-inyg/about_data?utm_source=chatgpt.com
    url = "https://www.datos.gov.co/resource/mwmn-inyg.csv"
    logger.info(f"Downloading Publindex database from {url}")

    try:
        df_publindex = fetch_all_socrata_rows(url)
        logger.info(f"Downloaded Publindex database with {len(df_publindex)} rows")
    except Exception as e:
        logger.error(f"Error downloading Publindex database: {str(e)}")
        raise

    # Convert all column names to lowercase for consistency
    df_publindex.columns = [c.lower() for c in df_publindex.columns]

    # Save as parquet file (default)
    output_parquet = os.path.join(database_path, "publindex_database.parquet")
    df_publindex.to_parquet(output_parquet, index=False)
    logger.info(f"Parquet file saved to: {output_parquet}")
    logger.info(f"Columns: {list(df_publindex.columns)}")

    # Optionally save as CSV
    if save_csv:
        output_csv = os.path.join(database_path, "publindex_database.csv")
        df_publindex.to_csv(output_csv, index=False)
        logger.info(f"CSV file saved to: {output_csv}")

    return df_publindex


def generate_scopus_database(url, database_path, save_csv=False):
    """
    Downloads an Excel file with from a
    https://www.elsevier.com/products/scopus/content#4-titles-on-scopus and saves its first sheet as .parquet

    Parameters:
    - url: URL of the Excel file
    - database_path: Folder where to save the CSV file

    Returns:
    - the database as a pandas DataFrame
    """
    try:

        # Download the file
        logger.info(f"Downloading Excel file from {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raises an HTTPError for bad responses

        # Save Excel content to a temporary file
        temp_excel = os.path.join(database_path, "temp.xlsx")
        with open(temp_excel, 'wb') as f:
            f.write(response.content)

        # Read the first sheet of the Excel file
        logger.info("Reading Excel file")
        df = pd.read_excel(temp_excel, sheet_name=0, dtype=str)

        # Convert all column names to lowercase for consistency
        df.columns = [c.lower() for c in df.columns]

        # Save as parquet file (default)
        output_parquet = os.path.join(database_path, "scopus_database.parquet")
        df.to_parquet(output_parquet, index=False)
        logger.info(f"Parquet file saved to: {output_parquet}")
        logger.info(f"Columns: {list(df.columns)}")

        # Optionally save as CSV
        if save_csv:
            output_csv = os.path.join(database_path, "scopus_database.csv")
            df.to_csv(output_csv, index=False)
            logger.info(f"CSV file saved to: {output_csv}")

        # Clean up temporary file
        os.remove(temp_excel)
        logger.info("Temporary files cleaned up")

        return df

    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading file: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        raise