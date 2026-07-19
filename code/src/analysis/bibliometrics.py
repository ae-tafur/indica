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


def fetch_work_metrics(doi, mailto=None, timeout=10, max_retries=3):
    """
    Queries OpenAlex for a single DOI and returns citation metrics.

    Parameters:
    doi (str): DOI of the article (any common format is accepted)
    mailto (str): Optional email address to use OpenAlex's "polite pool"
        (faster and more reliable rate limits). See
        https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication
    timeout (int): Request timeout in seconds
    max_retries (int): Number of retries on transient failures

    Returns:
    dict: Citation metrics (empty dict if the DOI could not be resolved)
    """
    doi_clean = clean_doi(doi)
    if not doi_clean:
        return {}

    params = {"mailto": mailto} if mailto else {}
    url = OPENALEX_WORKS_URL.format(doi=doi_clean)

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                open_access = data.get("open_access", {}) or {}
                concepts = data.get("concepts", []) or []
                return {
                    "openalex_id": data.get("id", ""),
                    "cited_by_count": data.get("cited_by_count", 0),
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
                logger.warning("Rate limited by OpenAlex, waiting before retry...")
                time.sleep(2 * (attempt + 1))
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


def enrich_with_citations(df, doi_column="doi", mailto=None, sleep_between=0.15):
    """
    Adds citation metrics (cited_by_count, oa_status, concepts, etc.) to a
    DataFrame of articles by querying the OpenAlex API for each unique DOI.

    IMPORTANT: run this on a DOI-deduplicated DataFrame (one row per article)
    to avoid inflating citation totals.

    Parameters:
    df (pd.DataFrame): DataFrame with a DOI column (ideally deduplicated)
    doi_column (str): Name of the DOI column
    mailto (str): Optional email to use OpenAlex's polite pool
    sleep_between (float): Delay (seconds) between requests to be nice to the API

    Returns:
    pd.DataFrame: Original DataFrame with additional citation metric columns
    """
    df = df.copy()
    unique_dois = df[doi_column].dropna().unique()
    unique_dois = [d for d in unique_dois if clean_doi(d)]

    logger.info(f"Fetching citation metrics for {len(unique_dois)} unique DOIs from OpenAlex...")

    metrics_by_doi = {}
    for i, doi in enumerate(unique_dois, start=1):
        metrics_by_doi[doi] = fetch_work_metrics(doi, mailto=mailto)
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


def fetch_author_metrics(author_name, affiliation=None, mailto=None, timeout=10):
    """
    Searches OpenAlex for an author by name (optionally filtered by
    affiliation/institution) and returns their h-index, i10-index, total
    works and total citations.

    Parameters:
    author_name (str): Full name of the author
    affiliation (str): Optional institution name to disambiguate the author
    mailto (str): Optional email for OpenAlex polite pool
    timeout (int): Request timeout in seconds

    Returns:
    dict: Author-level metrics (empty dict if the author was not found)
    """
    if not author_name or pd.isna(author_name):
        return {}

    params = {"search": author_name, "per_page": 1}
    if mailto:
        params["mailto"] = mailto
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
            "h_index": summary.get("h_index", 0),
            "i10_index": summary.get("i10_index", 0),
            "works_count": author.get("works_count", 0),
            "cited_by_count_total": author.get("cited_by_count", 0),
            "affiliation_openalex": last_institution.get("display_name", ""),
        }
    except requests.RequestException as e:
        logger.warning(f"Connection error searching author '{author_name}': {e}")
        return {}


def enrich_authors_with_metrics(df_authors, name_column="author", affiliation=None,
                                mailto=None, sleep_between=0.2):
    """
    Adds h-index, i10-index, total works and total citations for each unique
    author in the DataFrame, using the OpenAlex Authors API.

    Parameters:
    df_authors (pd.DataFrame): DataFrame with one row per author (e.g. from
        `analysis.utilities.process_authors_dataframe`)
    name_column (str): Column containing author names
    affiliation (str): Optional institution name to disambiguate authors
        (recommended, since author names can be ambiguous)
    mailto (str): Optional email for OpenAlex polite pool
    sleep_between (float): Delay (seconds) between requests

    Returns:
    pd.DataFrame: Original DataFrame with additional author-level metric columns
    """
    df_authors = df_authors.copy()
    unique_authors = df_authors[name_column].dropna().unique()

    logger.info(f"Fetching author metrics for {len(unique_authors)} unique authors from OpenAlex...")

    metrics_by_author = {}
    for i, author in enumerate(unique_authors, start=1):
        metrics_by_author[author] = fetch_author_metrics(author, affiliation=affiliation, mailto=mailto)
        if i % 10 == 0:
            logger.info(f"  Processed {i}/{len(unique_authors)} authors...")
        time.sleep(sleep_between)

    metrics_df = pd.DataFrame.from_dict(metrics_by_author, orient="index").reset_index()
    metrics_df = metrics_df.rename(columns={"index": name_column})

    df_authors = pd.merge(df_authors, metrics_df, on=name_column, how="left")

    return df_authors


def build_author_summary(df_authors_with_metrics, name_column="author"):
    """
    Builds a one-row-per-author summary table combining local article counts
    with OpenAlex bibliometric indicators (h-index, i10-index, total works
    and citations).

    Parameters:
    df_authors_with_metrics (pd.DataFrame): Output of `enrich_authors_with_metrics`
    name_column (str): Column containing author names

    Returns:
    pd.DataFrame: One row per author, sorted by h-index (descending)
    """
    metric_cols = [c for c in [
        "h_index", "i10_index", "works_count", "cited_by_count_total",
        "affiliation_openalex", "openalex_author_id"
    ] if c in df_authors_with_metrics.columns]

    agg_dict = {col: "first" for col in metric_cols}
    agg_dict["tittle"] = "nunique" if "tittle" in df_authors_with_metrics.columns else None
    agg_dict = {k: v for k, v in agg_dict.items() if v is not None}

    summary = df_authors_with_metrics.groupby(name_column).agg(agg_dict).reset_index()
    summary = summary.rename(columns={"tittle": "articulos_en_indica"})

    if "h_index" in summary.columns:
        summary = summary.sort_values("h_index", ascending=False)

    return summary

