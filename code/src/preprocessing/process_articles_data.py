import re
import csv
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Callable, Optional
from bs4 import BeautifulSoup, Tag

# Configure logging
logger = logging.getLogger(__name__)

# Define field patterns and transformations
FIELD_PATTERNS: Dict[str, Tuple[str, Optional[Callable]]] = {
    'type': (r'<strong>(.*?)</strong>', lambda x: x.rstrip(':')),
    'tittle': (r'</strong>\s*([^<]+)<br\s*/?>', None),
    'country': (r'<br\s*/?>\s*([^,]+),', None),
    'journal': (r',\s*([^<]+?)\s+ISSN:', None),
    'issn': (r'ISSN:\s*([0-9Xx\-]+)', None),
    'info_biblio': (
        r'ISSN:\s*[0-9Xx\-]+,\s*(.*?)<strong>DOI:', 
        lambda x: x.replace('<br/>', '').replace('<br>', '')
    ),
    'doi': (r'<strong>DOI:</strong>\s*([^<\s]+)', None),
    'authors': (
        r'Autores:\s*(.*?)\s*</td>', 
        lambda x: re.sub(r'\s*</?br\s*/?>\s*"?', '', x, flags=re.IGNORECASE).title()
    )
}

# Define field name mappings (standardized Spanish names)
FIELD_NAMES = {
    'type': 'type',
    'tittle': 'tittle',
    'journal': 'journal',
    'country': 'country',
    'year': 'year',
    'issn': 'issn',
    'info_biblio': 'vol_fasc_pag',
    'doi': 'doi',
    'authors': 'authors'
}

def extract_field(text: str, pattern: str, transform: Optional[Callable] = None) -> str:
    """
    Extract field using regex pattern and optional transformation.
    
    Args:
        text: Source text to extract from
        pattern: Regex pattern to use
        transform: Optional function to transform the extracted value
        
    Returns:
        Extracted and optionally transformed string
    """
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return ""
    value = match.group(1).strip()
    return transform(value) if transform else value

def extract_year(info_biblio: str) -> str:
    """
    Extract year from bibliographic information.
    
    Args:
        info_biblio: Bibliographic information text
        
    Returns:
        Extracted year or empty string if not found
    """
    year_match = re.search(r'(\d{4})', info_biblio)
    return year_match.group(1) if year_match else ""

def clean_biblio_info(info_biblio: str) -> str:
    """
    Clean and validate bibliographic information.

    Args:
        info_biblio: Raw bibliographic information string

    Returns:
        Cleaned and validated string
    """

    try:
        # Extract volume information if it exists
        vol_match = re.search(r'(vol:.*?)(?:,\s*|$)', info_biblio, re.IGNORECASE)
        if vol_match:
            # Clean up the volume information
            info = vol_match.group(1).strip()
            # Remove trailing comma if exists
            info = info.rstrip(',')
            return info
    except Exception as e:
        logger.warning(f"Error cleaning biblio info '{info_biblio}': {str(e)}")
        return "No Information"


DOI_PATTERN = r'(10\.\d{4,9}/[-._;()/:A-Z0-9]+)'


def standarize_doi(doi: str) -> str:
    """
    Standardize DOI format by extracting the DOI and converting it to a standard URL format.

    Args:
        doi: DOI string that might contain various formats

    Returns:
        Standardized DOI URL or original string if no valid DOI found
    """

    # Extract DOI using regex, removing prefixes like "doi:", "http://dx.doi.org/", etc.
    match = re.search(DOI_PATTERN, str(doi), re.IGNORECASE)
    if match:
        return f"https://doi.org/{match.group(1)}"
    return doi  # Return original if no valid pattern found


def extract_doi_anywhere(text: str) -> str:
    """
    Searches any block of text for a DOI-like pattern.

    Some authors do not fill in the "DOI:" field correctly in GrupLAC and
    instead paste the DOI (or a link containing it) into another field
    (e.g. the authors field, the title, or the bibliographic info). This
    function is used as a fallback to recover the DOI from anywhere in the
    raw article text when the standard extraction fails.

    Args:
        text: Raw text (can include HTML) to search for a DOI

    Returns:
        The bare DOI (without the https://doi.org/ prefix) or empty string
    """
    if not text:
        return ""
    match = re.search(DOI_PATTERN, text, re.IGNORECASE)
    return match.group(1) if match else ""


def remove_doi_from_text(text: str, doi: str) -> str:
    """
    Removes a DOI (and common surrounding noise like 'DOI:', urls, brackets)
    from a text field, useful for cleaning fields (e.g. 'autores') where the
    DOI was mistakenly pasted instead of, or along with, the real content.

    Args:
        text: Original text possibly containing the DOI
        doi: The bare DOI to remove

    Returns:
        Cleaned text
    """
    if not text or not doi:
        return text
    pattern = re.compile(
        r'(https?://(dx\.)?doi\.org/)?' + re.escape(doi) + r'|DOI:?\s*',
        re.IGNORECASE
    )
    cleaned = pattern.sub('', text)
    # Collapse any doubled separators left behind by the removal (e.g. ", ,")
    cleaned = re.sub(r'\s*,\s*,\s*', ', ', cleaned)
    cleaned = re.sub(r'\s*;\s*;\s*', '; ', cleaned)
    # Remove leftover separators/whitespace at the start/end of the string
    cleaned = re.sub(r'^[,;\s]+|[,;\s]+$', '', cleaned)
    return cleaned

def process_article(td: Tag) -> Dict[str, str]:
    """
    Process a single article table cell and extract all fields.
    
    Args:
        td: BeautifulSoup Tag object containing article data
        
    Returns:
        Dictionary with extracted article data
    """
    raw_html = str(td)
    article_data = {}

    # Extract all fields using patterns
    for field, (pattern, transform) in FIELD_PATTERNS.items():
        article_data[field] = extract_field(raw_html, pattern, transform)

    # Extract year from bibliographic information
    article_data['year'] = extract_year(article_data.get('info_biblio', ''))

    # Clean and validate bibliographic information
    article_data['info_biblio'] = clean_biblio_info(article_data.get('info_biblio', ''))

    # Fallback: if DOI was not captured with the standard pattern (e.g. the
    # author did not fill the "DOI:" field correctly and pasted it elsewhere),
    # search for a DOI-like pattern anywhere in the raw article HTML.
    if not article_data.get('doi'):
        fallback_doi = extract_doi_anywhere(raw_html)
        if fallback_doi:
            article_data['doi'] = fallback_doi
            logger.info("DOI recovered from fallback search in raw article text")

    # Standardize DOI format
    article_data['doi'] = standarize_doi(article_data.get('doi', ''))

    # If the DOI ended up embedded in the authors field (common when authors
    # paste the DOI instead of properly filling every field), remove it so it
    # does not corrupt the authors list/order.
    if article_data.get('doi') and article_data.get('authors'):
        bare_doi = article_data['doi'].replace('https://doi.org/', '')
        if bare_doi and bare_doi in article_data['authors']:
            article_data['authors'] = remove_doi_from_text(article_data['authors'], bare_doi)

    # Map field names to their display names
    return {FIELD_NAMES[k]: v for k, v in article_data.items()}

def validate_group_name(group_name: str) -> str:
    """
    Validate and sanitize group name for file naming.

    Args:
        group_name: Name of the research group

    Returns:
        Sanitized group name
    """
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', group_name)
    # Limit length
    return sanitized[:100].strip()

def get_articles_data(
    file_path: Path,
    group_name: str,
    output_path: Path
) -> List[Dict[str, str]]:
    """
    Extract article data from HTML file and save to CSV.

    Args:
        file_path: Path to the HTML file
        group_name: Name of the research group
        output_path: Directory to save the output CSV file

    Returns:
        List of dictionaries containing article data

    Raises:
        FileNotFoundError: If input file doesn't exist
        IOError: If there are problems reading/writing files
    """
    file_path = Path(file_path)
    output_path = Path(output_path)

    if not file_path.exists():
        raise FileNotFoundError(f"HTML file not found: {file_path}")

    logger.info(f"Processing articles for group: {group_name}")

    try:
        # Read and parse HTML. Try UTF-8 first, then fallback to Latin-1 if that fails
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as f:
                soup = BeautifulSoup(f.read(), "html.parser")

        # Find all article cells
        article_cells = soup.find_all("td", class_=re.compile(r"^celdas"))
        
        if not article_cells:
            logger.warning(f"No article cells found in {file_path}")
            return []

        # Process articles
        articles = []
        for td in article_cells:
            article_data = process_article(td)
            if any(article_data.values()):
                articles.append(article_data)


        if not articles:
            logger.warning("No valid articles found to process")
            return []

        # Ensure output directory exists
        output_path.mkdir(parents=True, exist_ok=True)

        # Sanitize group name before using it in file name
        safe_group_name = validate_group_name(group_name)

        # Save to CSV
        output_file = output_path / f"{safe_group_name}_articles.csv"
        field_names = list(FIELD_NAMES.values())
        
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=field_names)
            writer.writeheader()
            writer.writerows(articles)

        logger.info(f"Successfully processed {len(articles)} articles and saved to: {output_file}")
        return articles

    except Exception as e:
        logger.error(f"Error processing articles for {group_name}: {str(e)}")
        raise