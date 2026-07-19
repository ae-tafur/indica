"""
Bibliometric analysis utilities for INDICA.

This module uses the OpenAlex API (https://openalex.org) — a free, open,
no-API-key-required alternative to Scopus/Web of Science — to:

- Retrieve citation counts and citation sources for individual articles
  (matched by DOI).
- Retrieve author-level bibliometric indicators (h-index, i10-index, total
  works and citations) by searching for the author's name.

These metrics are meant to be computed AFTER deduplicating articles by DOI
(see `analysis.utilities.deduplicate_articles_by_doi`), so each article is
counted exactly once.
"""

import time
import logging
import requests
import pandas as pd
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

OPENALEX_WORKS_URL = "https://api.openalex.org/works/https://doi.org/{doi}"
OPENALEX_WORKS_SEARCH_URL = "https://api.openalex.org/works"
OPENALEX_AUTHOR_SEARCH_URL = "https://api.openalex.org/authors"
OPENALEX_AUTHOR_ORCID_URL = "https://api.openalex.org/authors/orcid:{orcid}"


def clean_doi(doi):
    """
    Normalizes a DOI value to its bare form (no URL prefix), returning None
    if the value is missing or not a usable DOI.
    """
    if pd.isna(doi):
        return None
    doi = str(doi).strip()
    if not doi or doi.lower() in ("no disponible", "nan", "none"):
        return None
    for prefix in ("https://doi.org/", "http://dx.doi.org/", "doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.strip("/ ") or None


def normalize_title_for_comparison(title):
    """
    Normalizes a title for comparison by removing punctuation, extra spaces,
    and converting to lowercase.
    """
    if pd.isna(title) or not title:
        return ""
    title = str(title).lower()
    # Remove punctuation and special characters
    title = re.sub(r'[^\w\s]', ' ', title)
    # Remove extra whitespace
    title = re.sub(r'\s+', ' ', title)
    return title.strip()


def calculate_title_similarity(title1, title2):
    """
    Calculates the similarity ratio between two titles using SequenceMatcher.
    
    Returns:
    float: Similarity ratio between 0 and 1 (1 = identical)
    """
    norm1 = normalize_title_for_comparison(title1)
    norm2 = normalize_title_for_comparison(title2)
    
    if not norm1 or not norm2:
        return 0.0
    
    return SequenceMatcher(None, norm1, norm2).ratio()


def search_work_by_title(title, title_similarity_threshold=0.7, mailto=None, 
                        api_key=None, timeout=10, max_results=5):
    """
    Searches OpenAlex for a work by title and returns the best match if similarity
    is above threshold.
    
    This is used as a fallback when DOI is missing or invalid.

    Parameters:
    title (str): Title to search for
    title_similarity_threshold (float): Minimum similarity ratio to accept match
    mailto (str): Optional email for OpenAlex polite pool
    api_key (str): Optional API key for higher rate limits
    timeout (int): Request timeout in seconds
    max_results (int): Maximum number of results to check

    Returns:
    dict: Work metrics if match found, empty dict otherwise
    """
    if not title or pd.isna(title):
        return {}
    
    params = {
        "search": title,
        "per_page": max_results
    }
    if mailto:
        params["mailto"] = mailto
    if api_key:
        params["api_key"] = api_key
    
    try:
        resp = requests.get(OPENALEX_WORKS_SEARCH_URL, params=params, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"OpenAlex title search failed ({resp.status_code}) for '{title[:50]}...'")
            return {}
        
        results = resp.json().get("results", [])
        if not results:
            logger.debug(f"No results found for title: {title[:50]}...")
            return {}
        
        # Find best match by title similarity
        best_match = None
        best_similarity = 0.0
        
        for result in results:
            openalex_title = result.get("display_name", "")
            similarity = calculate_title_similarity(title, openalex_title)
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = result
        
        # Check if best match meets threshold
        if best_similarity < title_similarity_threshold:
            logger.debug(
                f"Best match for '{title[:50]}...' has similarity {best_similarity:.2f} "
                f"(below threshold {title_similarity_threshold})"
            )
            return {}
        
        # Extract metrics from best match
        data = best_match
        open_access = data.get("open_access", {}) or {}
        concepts = data.get("concepts", []) or []
        fwci = data.get("fwci")
        
        logger.info(
            f"✓ Found match by title search (similarity: {best_similarity:.2f}): "
            f"{data.get('display_name', '')[:60]}..."
        )
        
        return {
            "openalex_id": data.get("id", ""),
            "openalex_title": data.get("display_name", ""),
            "cited_by_count": data.get("cited_by_count", 0),
            "fwci": fwci if fwci is not None else "",
            "referenced_works_count": len(data.get("referenced_works", []) or []),
            "is_oa": open_access.get("is_oa", False),
            "oa_status": open_access.get("oa_status", ""),
            "concepts": ", ".join(c.get("display_name", "") for c in concepts[:5]),
            "publication_year_openalex": data.get("publication_year", ""),
            "doi_validation_status": "found_by_title",
            "title_similarity": best_similarity,
            "openalex_doi": data.get("doi", ""),
        }
        
    except requests.RequestException as e:
        logger.warning(f"Connection error searching by title '{title[:50]}...': {e}")
        return {}


def fetch_work_metrics(doi, expected_title=None, title_similarity_threshold=0.7, 
                      mailto=None, api_key=None, timeout=10, max_retries=3):
    """
    Queries OpenAlex for a single DOI and returns citation metrics.
    
    Validates that the DOI corresponds to the expected article by comparing titles.
    This prevents incorrect matches when DOIs point to journals or wrong articles.

    Parameters:
    doi (str): DOI of the article (any common format is accepted)
    expected_title (str): Optional expected title of the article for validation
    title_similarity_threshold (float): Minimum similarity ratio (0-1) to accept match (default 0.7)
    mailto (str): Optional email address to use OpenAlex's "polite pool"
        (faster and more reliable rate limits). See
        https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication
    api_key (str): Optional API key for higher rate limits (100k/day vs 100/day)
        Get your free key at https://openalex.org/
    timeout (int): Request timeout in seconds
    max_retries (int): Number of retries on transient failures

    Returns:
    dict: Citation metrics (empty dict if the DOI could not be resolved or title mismatch)
    """
    doi_clean = clean_doi(doi)
    if not doi_clean:
        return {}

    params = {}
    if mailto:
        params["mailto"] = mailto
    if api_key:
        params["api_key"] = api_key
        
    url = OPENALEX_WORKS_URL.format(doi=doi_clean)

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                
                # Validate title if expected_title is provided
                openalex_title = data.get("display_name", "")
                title_valid = True
                title_similarity = None
                
                if expected_title and openalex_title:
                    title_similarity = calculate_title_similarity(expected_title, openalex_title)
                    title_valid = title_similarity >= title_similarity_threshold
                    
                    if not title_valid:
                        logger.warning(
                            f"Title mismatch for DOI {doi_clean} (similarity: {title_similarity:.2f})\n"
                            f"  Expected: {expected_title[:80]}\n"
                            f"  OpenAlex: {openalex_title[:80]}\n"
                            f"  This DOI may point to a journal or wrong article."
                        )
                        return {
                            "doi_validation_status": "title_mismatch",
                            "title_similarity": title_similarity,
                            "expected_title": expected_title,
                            "openalex_title": openalex_title,
                        }
                
                open_access = data.get("open_access", {}) or {}
                concepts = data.get("concepts", []) or []

                # Get FWCI from citation metrics (available since 2024 in OpenAlex)
                fwci = None
                biblio = data.get("biblio", {})
                if biblio:
                    # FWCI is sometimes in citation_normalized_percentile or similar fields
                    # OpenAlex provides various citation metrics
                    fwci = data.get("fwci")  # Field-Weighted Citation Impact

                result = {
                    "openalex_id": data.get("id", ""),
                    "openalex_title": openalex_title,
                    "cited_by_count": data.get("cited_by_count", 0),
                    "fwci": fwci if fwci is not None else "",
                    "referenced_works_count": len(data.get("referenced_works", []) or []),
                    "is_oa": open_access.get("is_oa", False),
                    "oa_status": open_access.get("oa_status", ""),
                    "concepts": ", ".join(c.get("display_name", "") for c in concepts[:5]),
                    "publication_year_openalex": data.get("publication_year", ""),
                    "doi_validation_status": "valid" if title_valid else "title_mismatch",
                }
                
                if title_similarity is not None:
                    result["title_similarity"] = title_similarity
                
                return result
                
            elif resp.status_code == 404:
                logger.warning(f"DOI not found in OpenAlex: {doi_clean}")
                return {"doi_validation_status": "not_found"}
            elif resp.status_code == 429:
                wait_time = 5 * (attempt + 1)
                logger.warning(f"Rate limited by OpenAlex, waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                continue
            else:
                logger.warning(f"OpenAlex request failed ({resp.status_code}) for DOI {doi_clean}")
        except requests.RequestException as e:
            logger.warning(f"Connection error fetching DOI {doi_clean}: {e}")
        time.sleep(1)

    return {"doi_validation_status": "error"}


def fetch_citing_works(doi, mailto=None, timeout=10, per_page=25):
    """
    Retrieves basic information (title, source/journal, year) about the
    works that cite the given DOI, useful to answer "from where is it cited".

    Parameters:
    doi (str): DOI of the article
    mailto (str): Optional email for OpenAlex polite pool
    timeout (int): Request timeout in seconds
    per_page (int): Max number of citing works to retrieve

    Returns:
    list[dict]: List of citing works with title, source and year
    """
    doi_clean = clean_doi(doi)
    if not doi_clean:
        return []

    work_metrics = fetch_work_metrics(doi_clean, mailto=mailto, timeout=timeout)
    openalex_id = work_metrics.get("openalex_id")
    if not openalex_id:
        return []

    params = {"filter": f"cites:{openalex_id.split('/')[-1]}", "per_page": per_page}
    if mailto:
        params["mailto"] = mailto

    try:
        resp = requests.get("https://api.openalex.org/works", params=params, timeout=timeout)
        if resp.status_code != 200:
            return []
        results = resp.json().get("results", [])
        citing = []
        for r in results:
            source = (r.get("primary_location") or {}).get("source") or {}
            citing.append({
                "title": r.get("display_name", ""),
                "source": source.get("display_name", ""),
                "year": r.get("publication_year", ""),
                "doi": r.get("doi", ""),
            })
        return citing
    except requests.RequestException as e:
        logger.warning(f"Connection error fetching citing works for {doi_clean}: {e}")
        return []


def enrich_with_citations(df, doi_column="doi", title_column="tittle", 
                         title_similarity_threshold=0.7, use_title_fallback=True,
                         mailto=None, api_key=None, sleep_between=0.5):
    """
    Adds citation metrics (cited_by_count, oa_status, concepts, etc.) to a
    DataFrame of articles by querying the OpenAlex API.
    
    Strategy:
    1. Try DOI lookup first (if DOI exists and is valid)
    2. Validate DOI result by comparing titles (similarity >= threshold)
    3. If DOI fails or is missing, fallback to title search
    4. Validate title search result (similarity >= threshold)

    IMPORTANT: run this on a DOI-deduplicated DataFrame (one row per article)
    to avoid inflating citation totals.

    Parameters:
    df (pd.DataFrame): DataFrame with DOI and/or title columns
    doi_column (str): Name of the DOI column
    title_column (str): Name of the title column for validation and fallback search
    title_similarity_threshold (float): Minimum similarity (0-1) to accept match (default 0.7)
    use_title_fallback (bool): Use title search when DOI fails (default True)
    mailto (str): Optional email to use OpenAlex's polite pool
    api_key (str): Optional API key for higher rate limits (recommended)
    sleep_between (float): Delay (seconds) between requests to be nice to the API
        (default 0.5s, increase if getting rate limited)

    Returns:
    tuple: (DataFrame with citation metrics, DataFrame with search info)
    """
    df = df.copy()
    
    # Create lookup structures
    doi_title_map = {}
    title_only_articles = []
    
    if title_column and title_column in df.columns:
        for idx, row in df.iterrows():
            doi = row.get(doi_column)
            title = row.get(title_column)
            
            if doi and not pd.isna(doi) and clean_doi(doi):
                if title and not pd.isna(title):
                    doi_title_map[doi] = title
            elif title and not pd.isna(title):
                # Articles without DOI - will search by title
                title_only_articles.append(title)
    
    unique_dois = df[doi_column].dropna().unique() if doi_column in df.columns else []
    unique_dois = [d for d in unique_dois if clean_doi(d)]
    
    logger.info(f"Fetching citation metrics from OpenAlex...")
    logger.info(f"  Articles with DOI: {len(unique_dois)}")
    logger.info(f"  Articles without DOI (title search): {len(set(title_only_articles))}")
    logger.info(f"  Title validation threshold: {title_similarity_threshold}")
    if use_title_fallback:
        logger.info(f"  Title fallback enabled for failed DOI lookups")
    
    if not api_key:
        logger.warning("No API key provided - you may experience rate limiting. "
                      "Get a free key at https://openalex.org/ for 100k requests/day")

    metrics_by_key = {}  # key can be DOI or title
    search_info = []
    
    # Process articles with DOI
    for i, doi in enumerate(unique_dois, start=1):
        expected_title = doi_title_map.get(doi)
        
        # Try DOI lookup first
        metrics = fetch_work_metrics(
            doi, 
            expected_title=expected_title,
            title_similarity_threshold=title_similarity_threshold,
            mailto=mailto, 
            api_key=api_key
        )
        
        validation_status = metrics.get("doi_validation_status", "valid")
        search_method = "doi"
        
        # If DOI failed and we have title, try title search
        if validation_status != "valid" and use_title_fallback and expected_title:
            logger.info(f"  DOI validation failed for '{doi}', trying title search...")
            title_metrics = search_work_by_title(
                expected_title,
                title_similarity_threshold=title_similarity_threshold,
                mailto=mailto,
                api_key=api_key
            )
            
            if title_metrics:
                metrics = title_metrics
                search_method = "title_fallback"
                validation_status = "found_by_title"
        
        metrics_by_key[doi] = metrics
        
        # Track search info
        search_info.append({
            "lookup_key": doi,
            "lookup_type": "doi",
            "search_method": search_method,
            "validation_status": validation_status,
            "expected_title": expected_title,
            "openalex_title": metrics.get("openalex_title", ""),
            "title_similarity": metrics.get("title_similarity", 0),
            "cited_by_count": metrics.get("cited_by_count", 0),
            "openalex_doi": metrics.get("openalex_doi", ""),
        })
        
        if i % 25 == 0:
            logger.info(f"  Processed {i}/{len(unique_dois)} DOIs...")
        time.sleep(sleep_between)
    
    # Process articles without DOI (search by title)
    unique_titles = list(set(title_only_articles))
    for i, title in enumerate(unique_titles, start=1):
        metrics = search_work_by_title(
            title,
            title_similarity_threshold=title_similarity_threshold,
            mailto=mailto,
            api_key=api_key
        )
        
        metrics_by_key[title] = metrics
        
        validation_status = metrics.get("doi_validation_status", "not_found")
        
        search_info.append({
            "lookup_key": title,
            "lookup_type": "title",
            "search_method": "title",
            "validation_status": validation_status,
            "expected_title": title,
            "openalex_title": metrics.get("openalex_title", ""),
            "title_similarity": metrics.get("title_similarity", 0),
            "cited_by_count": metrics.get("cited_by_count", 0),
            "openalex_doi": metrics.get("openalex_doi", ""),
        })
        
        if i % 25 == 0:
            logger.info(f"  Processed {i}/{len(unique_titles)} titles...")
        time.sleep(sleep_between)

    if not metrics_by_key:
        logger.warning("No citation metrics were retrieved.")
        return df, pd.DataFrame()

    # Merge metrics back to dataframe
    # For DOI-based lookups
    if doi_column in df.columns and unique_dois:
        metrics_df_doi = pd.DataFrame.from_dict(
            {k: v for k, v in metrics_by_key.items() if k in unique_dois}, 
            orient="index"
        ).reset_index()
        metrics_df_doi = metrics_df_doi.rename(columns={"index": doi_column})
        df = pd.merge(df, metrics_df_doi, on=doi_column, how="left")
    
    # For title-based lookups (no DOI)
    if title_column in df.columns and unique_titles:
        metrics_df_title = pd.DataFrame.from_dict(
            {k: v for k, v in metrics_by_key.items() if k in unique_titles}, 
            orient="index"
        ).reset_index()
        metrics_df_title = metrics_df_title.rename(columns={"index": title_column})
        
        # Merge only for rows without DOI metrics
        mask_no_doi = df["openalex_id"].isna() if "openalex_id" in df.columns else df[doi_column].isna()
        df_no_doi = df[mask_no_doi].copy()
        df_with_doi = df[~mask_no_doi].copy()
        
        df_no_doi = pd.merge(df_no_doi, metrics_df_title, on=title_column, how="left", suffixes=('', '_title'))
        df = pd.concat([df_with_doi, df_no_doi], ignore_index=True)
    
    # Set cited_by_count to 0 for invalid results
    if "cited_by_count" in df.columns:
        valid_statuses = ["valid", "found_by_title"]
        df.loc[~df["doi_validation_status"].isin(valid_statuses), "cited_by_count"] = 0
        df["cited_by_count"] = df["cited_by_count"].fillna(0).astype(int)
    
    # Create search info DataFrame
    search_info_df = pd.DataFrame(search_info)
    
    if not search_info_df.empty:
        # Summary statistics
        total = len(search_info_df)
        found_by_doi = len(search_info_df[search_info_df["validation_status"] == "valid"])
        found_by_title = len(search_info_df[search_info_df["validation_status"] == "found_by_title"])
        not_found = total - found_by_doi - found_by_title
        
        logger.info(f"\n📊 OpenAlex lookup summary:")
        logger.info(f"  ✓ Found by DOI: {found_by_doi}/{total} ({found_by_doi/total*100:.1f}%)")
        logger.info(f"  ✓ Found by title search: {found_by_title}/{total} ({found_by_title/total*100:.1f}%)")
        logger.info(f"  ✗ Not found: {not_found}/{total} ({not_found/total*100:.1f}%)")

    return df, search_info_df


def fetch_author_metrics_by_orcid(orcid, mailto=None, api_key=None, timeout=10):
    """
    Retrieves author metrics from OpenAlex using ORCID identifier.
    This method is more accurate than searching by name.

    Parameters:
    orcid (str): ORCID identifier (e.g., "0000-0002-1298-3089")
    mailto (str): Optional email for OpenAlex polite pool
    api_key (str): Optional API key for higher rate limits
    timeout (int): Request timeout in seconds

    Returns:
    dict: Author-level metrics (empty dict if the ORCID was not found)
    """
    if not orcid or pd.isna(orcid) or str(orcid).strip() == "":
        return {}

    # Clean ORCID (remove any URL prefix if present)
    orcid_clean = str(orcid).strip()
    if orcid_clean.startswith("https://orcid.org/"):
        orcid_clean = orcid_clean.replace("https://orcid.org/", "")
    elif orcid_clean.startswith("orcid:"):
        orcid_clean = orcid_clean.replace("orcid:", "")

    url = OPENALEX_AUTHOR_ORCID_URL.format(orcid=orcid_clean)
    params = {}
    if mailto:
        params["mailto"] = mailto
    if api_key:
        params["api_key"] = api_key

    try:
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 404:
            logger.warning(f"ORCID not found in OpenAlex: {orcid_clean}")
            return {}
        elif resp.status_code != 200:
            logger.warning(f"OpenAlex author request failed ({resp.status_code}) for ORCID {orcid_clean}")
            return {}

        author = resp.json()
        summary = author.get("summary_stats", {}) or {}
        last_institution = author.get("last_known_institution") or {}

        return {
            "openalex_author_id": author.get("id", ""),
            "orcid": author.get("orcid", ""),
            "display_name": author.get("display_name", ""),
            "h_index": summary.get("h_index", 0),
            "i10_index": summary.get("i10_index", 0),
            "2yr_mean_citedness": summary.get("2yr_mean_citedness", 0),
            "works_count": author.get("works_count", 0),
            "cited_by_count_total": author.get("cited_by_count", 0),
            "affiliation_openalex": last_institution.get("display_name", ""),
        }
    except requests.RequestException as e:
        logger.warning(f"Connection error fetching ORCID {orcid_clean}: {e}")
        return {}


def fetch_author_metrics(author_name, affiliation=None, mailto=None, api_key=None, timeout=10):
    """
    Searches OpenAlex for an author by name (optionally filtered by
    affiliation/institution) and returns their h-index, i10-index, total
    works and total citations.

    NOTE: This method is less accurate than using ORCID. Use
    fetch_author_metrics_by_orcid() when ORCID is available.

    Parameters:
    author_name (str): Full name of the author
    affiliation (str): Optional institution name to disambiguate the author
    mailto (str): Optional email for OpenAlex polite pool
    api_key (str): Optional API key for higher rate limits
    timeout (int): Request timeout in seconds

    Returns:
    dict: Author-level metrics (empty dict if the author was not found)
    """
    if not author_name or pd.isna(author_name):
        return {}

    params = {"search": author_name, "per_page": 1}
    if mailto:
        params["mailto"] = mailto
    if api_key:
        params["api_key"] = api_key
    if affiliation:
        params["filter"] = f"affiliations.institution.display_name.search:{affiliation}"

    try:
        resp = requests.get(OPENALEX_AUTHOR_SEARCH_URL, params=params, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"OpenAlex author search failed ({resp.status_code}) for '{author_name}'")
            return {}

        results = resp.json().get("results", [])
        if not results:
            return {}

        author = results[0]
        summary = author.get("summary_stats", {}) or {}
        last_institution = author.get("last_known_institution") or {}

        return {
            "openalex_author_id": author.get("id", ""),
            "orcid": author.get("orcid", ""),
            "display_name": author.get("display_name", ""),
            "h_index": summary.get("h_index", 0),
            "i10_index": summary.get("i10_index", 0),
            "2yr_mean_citedness": summary.get("2yr_mean_citedness", 0),
            "works_count": author.get("works_count", 0),
            "cited_by_count_total": author.get("cited_by_count", 0),
            "affiliation_openalex": last_institution.get("display_name", ""),
        }
    except requests.RequestException as e:
        logger.warning(f"Connection error searching author '{author_name}': {e}")
        return {}


def enrich_authors_with_metrics(df_authors, name_column="author", orcid_column=None, 
                                affiliation=None, mailto=None, api_key=None, sleep_between=0.5):
    """
    Adds h-index, i10-index, total works and total citations for each unique
    author in the DataFrame, using the OpenAlex Authors API.

    Prioritizes ORCID-based lookup when available, falling back to name-based
    search for authors without ORCID.

    Parameters:
    df_authors (pd.DataFrame): DataFrame with one row per author (e.g. from
        `analysis.utilities.process_authors_dataframe`)
    name_column (str): Column containing author names
    orcid_column (str): Optional column containing ORCID identifiers. If provided,
        ORCID will be used for more accurate author identification
    affiliation (str): Optional institution name to disambiguate authors
        (used only for name-based search fallback)
    mailto (str): Optional email for OpenAlex polite pool
    api_key (str): Optional API key for higher rate limits (recommended)
    sleep_between (float): Delay (seconds) between requests (default 0.5s)

    Returns:
    pd.DataFrame: Original DataFrame with additional author-level metric columns
    """
    df_authors = df_authors.copy()
    
    if not api_key:
        logger.warning("No API key provided - you may experience rate limiting. "
                      "Get a free key at https://openalex.org/ for 100k requests/day")
    
    # Determine which authors to process
    if orcid_column and orcid_column in df_authors.columns:
        logger.info(f"Using ORCID column '{orcid_column}' for author identification")
        
        # Get unique combinations of author name and ORCID
        author_info = df_authors[[name_column, orcid_column]].drop_duplicates()
        
        # Separate authors with and without ORCID
        has_orcid = author_info[author_info[orcid_column].notna() & (author_info[orcid_column] != "")]
        no_orcid = author_info[~author_info.index.isin(has_orcid.index)]
        
        logger.info(f"Fetching metrics for {len(has_orcid)} authors with ORCID...")
        logger.info(f"Fetching metrics for {len(no_orcid)} authors without ORCID (using name search)...")
        
        metrics_list = []
        
        # Fetch by ORCID (more accurate)
        for i, row in has_orcid.iterrows():
            orcid = row[orcid_column]
            author_name = row[name_column]
            metrics = fetch_author_metrics_by_orcid(orcid, mailto=mailto, api_key=api_key)
            metrics[name_column] = author_name
            metrics[orcid_column] = orcid
            metrics_list.append(metrics)
            
            if (len(metrics_list)) % 10 == 0:
                logger.info(f"  Processed {len(metrics_list)}/{len(has_orcid)} authors with ORCID...")
            time.sleep(sleep_between)
        
        # Fetch by name for authors without ORCID
        for i, row in no_orcid.iterrows():
            author_name = row[name_column]
            metrics = fetch_author_metrics(author_name, affiliation=affiliation, mailto=mailto, api_key=api_key)
            metrics[name_column] = author_name
            metrics[orcid_column] = ""
            metrics_list.append(metrics)
            
            if (len(metrics_list) - len(has_orcid)) % 10 == 0:
                logger.info(f"  Processed {len(metrics_list) - len(has_orcid)}/{len(no_orcid)} authors without ORCID...")
            time.sleep(sleep_between)
        
        metrics_df = pd.DataFrame(metrics_list)
        merge_cols = [name_column, orcid_column]
        
    else:
        # Fallback to name-based search only
        logger.info("No ORCID column provided, using name-based search")
        unique_authors = df_authors[name_column].dropna().unique()
        logger.info(f"Fetching author metrics for {len(unique_authors)} unique authors from OpenAlex...")

        metrics_by_author = {}
        for i, author in enumerate(unique_authors, start=1):
            metrics_by_author[author] = fetch_author_metrics(author, affiliation=affiliation, mailto=mailto, api_key=api_key)
            if i % 10 == 0:
                logger.info(f"  Processed {i}/{len(unique_authors)} authors...")
            time.sleep(sleep_between)

        metrics_df = pd.DataFrame.from_dict(metrics_by_author, orient="index").reset_index()
        metrics_df = metrics_df.rename(columns={"index": name_column})
        merge_cols = [name_column]

    df_authors = pd.merge(df_authors, metrics_df, on=merge_cols, how="left")

    return df_authors


def build_author_summary(df_authors_with_metrics, name_column="author", orcid_column=None):
    """
    Builds a one-row-per-author summary table combining local article counts
    with OpenAlex bibliometric indicators (h-index, i10-index, 2yr_mean_citedness,
    total works and citations).

    Parameters:
    df_authors_with_metrics (pd.DataFrame): Output of `enrich_authors_with_metrics`
    name_column (str): Column containing author names
    orcid_column (str): Optional column containing ORCID identifiers

    Returns:
    pd.DataFrame: One row per author, sorted by h-index (descending)
    """
    # Include all author-level metrics, including 2yr_mean_citedness and ORCID
    metric_cols = [c for c in [
        "h_index", "i10_index", "2yr_mean_citedness", "works_count", 
        "cited_by_count_total", "affiliation_openalex", "openalex_author_id",
        "orcid", "display_name"
    ] if c in df_authors_with_metrics.columns]

    # Add ORCID column if specified and exists
    if orcid_column and orcid_column in df_authors_with_metrics.columns and orcid_column not in metric_cols:
        metric_cols.append(orcid_column)

    agg_dict = {col: "first" for col in metric_cols}
    agg_dict["tittle"] = "nunique" if "tittle" in df_authors_with_metrics.columns else None
    agg_dict = {k: v for k, v in agg_dict.items() if v is not None}

    summary = df_authors_with_metrics.groupby(name_column).agg(agg_dict).reset_index()
    summary = summary.rename(columns={"tittle": "articulos_en_indica"})

    if "h_index" in summary.columns:
        summary = summary.sort_values("h_index", ascending=False)

    return summary

