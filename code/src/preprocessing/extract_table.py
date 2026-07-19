import logging
import re
import pandas as pd
from pathlib import Path
from typing import Union, Optional, List, Dict

# Configure logging
logger = logging.getLogger(__name__)

try:
    import pdfplumber
    PDF_LIBRARY = 'pdfplumber'
    logger.info("Using pdfplumber for PDF extraction")
except ImportError:
    import tabula
    PDF_LIBRARY = 'tabula'
    logger.warning("pdfplumber not available, falling back to tabula")

def find_matching_column(columns: List[str], patterns: List[str]) -> Optional[str]:
    """Find column name matching any of the patterns."""
    return next((col for col in columns 
                 if any(pattern in col for pattern in patterns)), None)

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize and validate DataFrame columns."""
    column_patterns = {
        'journal': ['TITULO', 'NOMBRE', 'REVISTA'],
        'issn': ['ISSN'],
        'category_publindex': ['CATEGORIA', 'CATEGORÍA', 'CATEOGRIA', 'INDEX'],
        'year_publindex': ['VIGENCIA']
    }

    # Normalize existing columns
    df.columns = [str(c).strip().upper() for c in df.columns if c]

    # Map columns to standard names
    column_mapping = {}
    for target, patterns in column_patterns.items():
        found = find_matching_column(df.columns, patterns)
        if found:
            column_mapping[found] = target

    # Select only the mapped columns (excludes 'num' column)
    mapped_cols = list(column_mapping.keys())
    if not mapped_cols:
        return pd.DataFrame()  # Return empty if no columns matched

    df_result = df[mapped_cols].rename(columns=column_mapping)

    # Remove rows where all values are NaN
    df_result = df_result.dropna(how='all')

    return df_result

def clean_text(text: str) -> str:
    """Clean text by removing newlines and extra spaces."""
    return str(text).strip().replace('\n', ' ').replace('\r', ' ')

def extract_table_from_pdf(
    file_path: Union[str, Path],
    output_path: Union[str, Path],
    output_file_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Extract homologation tables from PDF and save as CSV.
    Args:
        file_path (Union[str, Path]): Path to the PDF file.
        output_path (Union[str, Path]): Directory to save the output CSV file.
        output_file_name (Optional[str]): Name of the output CSV file. If None, defaults to 'revistas_homologadas_<file_name>.csv'.
    Returns:
        pd.DataFrame: DataFrame containing the extracted and cleaned data.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    logger.info(f"Processing PDF file: {file_path} using {PDF_LIBRARY}")

    try:
        if PDF_LIBRARY == 'pdfplumber':
            # Use pdfplumber for better performance and accuracy
            all_rows = []
            header = None

            def is_header_row(row):
                """Check if row is likely a header row"""
                if not row:
                    return False
                row_str = ' '.join([str(cell).upper() for cell in row if cell])
                # Common header indicators
                header_keywords = ['NO.', 'ISSN', 'TITULO', 'NOMBRE', 'CATEGORIA', 'VIGENCIA', 'CATEOGRIA']
                return any(keyword in row_str for keyword in header_keywords)

            def is_title_row(row):
                """Check if row is a title row (not data)"""
                if not row:
                    return False
                row_str = ' '.join([str(cell).upper() for cell in row if cell])
                # Title row indicators
                title_keywords = ['LISTADO', 'REVISTAS HOMOLOGADAS', 'REVISTAS EXTRANJERAS']
                return any(keyword in row_str for keyword in title_keywords)

            with pdfplumber.open(str(file_path)) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"Processing {total_pages} pages")

                for page_num, page in enumerate(pdf.pages, 1):
                    if page_num % 100 == 0:
                        logger.info(f"Processed {page_num}/{total_pages} pages, extracted {len(all_rows)} rows so far")

                    # Extract tables from this page
                    tables = page.extract_tables()

                    for table in tables:
                        if not table or len(table) == 0:
                            continue

                        for row in table:
                            # Skip title rows
                            if is_title_row(row):
                                continue

                            # Detect header row
                            if is_header_row(row):
                                if header is None:
                                    # First time seeing header, save it
                                    header = row
                                    logger.info(f"Detected header: {header}")
                                # Skip header rows (they repeat on each page)
                                continue

                            # Add data row (only if we've found the header)
                            if header is not None:
                                all_rows.append(row)

            if not all_rows or not header:
                raise ValueError("No tables found in PDF")

            logger.info(f"Extracted total of {len(all_rows)} rows from {total_pages} pages")

            # Create DataFrame from extracted rows
            df_raw = pd.DataFrame(all_rows, columns=header)

        else:
            # Fallback to tabula
            tables = tabula.read_pdf(
                str(file_path),
                pages='all',
                multiple_tables=True,
                lattice=True
            )
            df_raw = pd.concat(tables, ignore_index=True)

        # Save RAW output first (before any processing)
        if output_path:
            output_path = Path(output_path)
            if output_file_name is None:
                output_file_name = f"revistas_homologadas_{file_path.stem}.csv"

            output_file = output_path / output_file_name
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Save raw data first
            df_raw.to_csv(output_file, index=False, encoding='utf-8')
            logger.info(f"Saved RAW CSV file to: {output_file} with {len(df_raw)} rows and columns: {list(df_raw.columns)}")

        # Try to normalize columns (but don't fail if it doesn't work)
        try:
            df = normalize_columns(df_raw)
            df = df.drop_duplicates()

            # Clean text in all columns
            for col in df.columns:
                df[col] = df[col].apply(clean_text)

            # Overwrite with normalized version if successful
            if output_path and len(df) > 0:
                df.to_csv(output_file, index=False, encoding='utf-8')
                logger.info(f"Updated CSV with normalized columns: {list(df.columns)}")

            return df
        except Exception as e:
            logger.warning(f"Could not normalize columns: {str(e)}. Keeping raw data.")
            return df_raw

    except Exception as e:
        logger.error(f"Failed to process PDF: {str(e)}")
        raise


def extract_tables_from_html(
        file_path: Union[str, Path],
        output_path: Union[str, Path],
        group_name: str,
) -> Dict[str, Path]:
    """
    Extract tables from HTML and save them as separate files.

    Args:
        file_path (Union[str, Path]): Path to the HTML file
        output_path (Union[str, Path]): Directory to save the output files
        group_name (str): Name of the research group

    Returns:
        Dict[str, Path]: Dictionary mapping table types to their saved file paths
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"HTML file not found: {file_path}")

    logger.info(f"Processing HTML file: {file_path}")

    try:
        # Read HTML file with Latin-1 encoding
        with open(file_path, "r", encoding="latin-1") as f:
            html = f.read()

        # Setup output directory
        output_dir = output_path / "data_blocks_gruplac"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Define blocks to extract
        blocks = {
            "Integrantes del grupo": f"{group_name}_integrantes.html",
            "Artículos publicados": f"{group_name}_articulos.html",
            "Libros publicados": f"{group_name}_libros.html",
            "Capítulos de libro publicados": f"{group_name}_capitulos_libro.html",
            "Trabajos dirigidos/turor&iacute;as": f"{group_name}_trabajos_dirigidos.html",
            "Jurado/Comisiones evaluadoras de trabajo de grado": f"{group_name}_jurado.html"
        }

        # Extract tables using regex
        tables = re.findall(r'<table.*?>.*?</table>', html, re.DOTALL | re.IGNORECASE)

        # Store results
        results = {}

        # Process each block
        for label, filename in blocks.items():
            block_found = False
            for table in tables:
                if label in table:
                    output_file = output_dir / filename
                    with open(output_file, "w", encoding="utf-8") as out:
                        out.write(table)
                    logger.info(f"Saved table: {filename}")
                    results[label] = output_file
                    block_found = True
                    break  # only save first match

            if not block_found:
                logger.warning(f"No table found for: {label}")

        return results

    except Exception as e:
        logger.error(f"Failed to process HTML: {str(e)}")
        raise
