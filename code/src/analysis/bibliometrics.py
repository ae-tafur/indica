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

logger = logging.getLogger(__name__)

OPENALEX_WORKS_URL = "https://api.openalex.org/works/https://doi.org/{doi}"
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


def fetch_work_metrics(doi, mailto=None, api_key=None, timeout=10, max_retries=3):
    """
    Queries OpenAlex for a single DOI and returns citation metrics.

    Parameters:
    doi (str): DOI of the article (any common format is accepted)
    mailto (str): Optional email address to use OpenAlex's "polite pool"
        (faster and more reliable rate limits). See
        https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication
    api_key (str): Optional API key for higher rate limits (100k/day vs 100/day)
        Get your free key at https://openalex.org/
    timeout (int): Request timeout in seconds
    max_retries (int): Number of retries on transient failures

    Returns:
    dict: Citation metrics (empty dict if the DOI could not be resolved)
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
                open_access = data.get("open_access", {}) or {}
                concepts = data.get("concepts", []) or []

                # Get FWCI from citation metrics (available since 2024 in OpenAlex)
                fwci = None
                biblio = data.get("biblio", {})
                if biblio:
                    # FWCI is sometimes in citation_normalized_percentile or similar fields
                    # OpenAlex provides various citation metrics
                    fwci = data.get("fwci")  # Field-Weighted Citation Impact

                return {
                    "openalex_id": data.get("id", ""),
                    "cited_by_count": data.get("cited_by_count", 0),
                    "fwci": fwci if fwci is not None else "",
                    "referenced_works_count": len(data.get("referenced_works", []) or []),
                    "is_oa": open_access.get("is_oa", False),
                    "oa_status": open_access.get("oa_status", ""),
                    "concepts": ", ".join(c.get("display_name", "") for c in concepts[:5]),
                    "publication_year_openalex": data.get("publication_year", ""),
                }
            elif resp.status_code == 404:
                logger.warning(f"DOI not found in OpenAlex: {doi_clean}")
                return {}
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

    return {}


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


def enrich_with_citations(df, doi_column="doi", mailto=None, api_key=None, sleep_between=0.5):
    """
    Adds citation metrics (cited_by_count, oa_status, concepts, etc.) to a
    DataFrame of articles by querying the OpenAlex API for each unique DOI.

    IMPORTANT: run this on a DOI-deduplicated DataFrame (one row per article)
    to avoid inflating citation totals.

    Parameters:
    df (pd.DataFrame): DataFrame with a DOI column (ideally deduplicated)
    doi_column (str): Name of the DOI column
    mailto (str): Optional email to use OpenAlex's polite pool
    api_key (str): Optional API key for higher rate limits (recommended)
    sleep_between (float): Delay (seconds) between requests to be nice to the API
        (default 0.5s, increase if getting rate limited)

    Returns:
    pd.DataFrame: Original DataFrame with additional citation metric columns
    """
    df = df.copy()
    unique_dois = df[doi_column].dropna().unique()
    unique_dois = [d for d in unique_dois if clean_doi(d)]

    logger.info(f"Fetching citation metrics for {len(unique_dois)} unique DOIs from OpenAlex...")
    if not api_key:
        logger.warning("No API key provided - you may experience rate limiting. "
                      "Get a free key at https://openalex.org/ for 100k requests/day")

    metrics_by_doi = {}
    for i, doi in enumerate(unique_dois, start=1):
        metrics_by_doi[doi] = fetch_work_metrics(doi, mailto=mailto, api_key=api_key)
        if i % 25 == 0:
            logger.info(f"  Processed {i}/{len(unique_dois)} DOIs...")
        time.sleep(sleep_between)

    if not metrics_by_doi:
        logger.warning("No citation metrics were retrieved.")
        return df

    metrics_df = pd.DataFrame.from_dict(metrics_by_doi, orient="index").reset_index()
    metrics_df = metrics_df.rename(columns={"index": doi_column})

    df = pd.merge(df, metrics_df, on=doi_column, how="left")
    if "cited_by_count" in df.columns:
        df["cited_by_count"] = df["cited_by_count"].fillna(0).astype(int)

    return df


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

