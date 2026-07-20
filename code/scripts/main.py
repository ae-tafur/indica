import sys
import os
import logging
from pathlib import Path
import argparse
import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get the project root directory and setup paths
def get_project_root():
    try:
        # When running as a script
        return Path(__file__).parent.parent.parent.absolute()
    except NameError:
        # When running in IPython/Jupyter
        return Path.cwd().parent.parent.absolute()

PROJECT_ROOT = get_project_root()

# Setup path constants for different directories
PATHS = {
    'CODE': PROJECT_ROOT / 'code',
    'SRC': PROJECT_ROOT / 'code' / 'src',
    'DATA': PROJECT_ROOT / 'data',
    'CONFIG': PROJECT_ROOT / 'config',
    'RESULTS': PROJECT_ROOT / 'results',
    'DATABASE': PROJECT_ROOT / 'database'
}

# Add the code and src directories to Python's path
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PATHS['SRC']))

def setup_environment():
    """Setup the environment and verify all required directories exist"""
    for path in PATHS.values():
        if not path.exists():
            logger.info(f"Creating directory: {path}")
            path.mkdir(parents=True, exist_ok=True)

def create_databases(database_type=None, force_reprocess=False):
    """Step 1: Create and setup databases

    Parameters:
    database_type (str): 'homologation', 'publindex', 'scopus', or None for all
    force_reprocess (bool): If True, reprocess all files even if CSVs exist
    """
    try:
        from preprocessing.extract_table import extract_table_from_pdf
        from preprocessing.generate_databases import (generate_homologation_database,
                                                      generate_publindex_database,
                                                      generate_scopus_database)

        logger.info("Starting database creation process...")

        database_path = PATHS['DATABASE']

        # Homologation database
        if database_type in [None, 'homologation']:
            logger.info("Creating homologation database...")
            raw_folder = PATHS['DATA'] / 'raw' / 'homologation'
            processed_folder = PATHS['DATA'] / 'processed' / 'homologation'
            processed_folder.mkdir(parents=True, exist_ok=True)

            # Process all PDF, XLS, and XLSX files
            import glob
            pdf_files = list(raw_folder.glob('*.pdf'))
            xls_files = list(raw_folder.glob('*.xls')) + list(raw_folder.glob('*.xlsx'))

            logger.info(f"Found {len(pdf_files)} PDF files and {len(xls_files)} XLS/XLSX files")

            # Process PDF files
            for pdf_file in pdf_files:
                try:
                    output_name = f"revistas_homologadas_{pdf_file.stem}.csv"
                    output_csv = processed_folder / output_name

                    # Skip if already processed (unless force_reprocess is True)
                    if output_csv.exists() and not force_reprocess:
                        logger.info(f"Skipping {pdf_file.name} - CSV already exists (use --force-reprocess to override)")
                        continue

                    file_size_mb = pdf_file.stat().st_size / (1024 * 1024)
                    logger.info(f"Processing {pdf_file.name} ({file_size_mb:.1f}MB)...")
                    extract_table_from_pdf(pdf_file, processed_folder, output_file_name=output_name)
                except Exception as e:
                    logger.error(f"Failed to process {pdf_file.name}: {str(e)}")

            # Process XLS/XLSX files
            for xls_file in xls_files:
                try:
                    output_name = f"revistas_homologadas_{xls_file.stem}.csv"
                    output_path = processed_folder / output_name

                    # Skip if already processed (unless force_reprocess is True)
                    if output_path.exists() and not force_reprocess:
                        logger.info(f"Skipping {xls_file.name} - CSV already exists (use --force-reprocess to override)")
                        continue

                    logger.info(f"Processing {xls_file.name}...")

                    # Read Excel file
                    if xls_file.suffix == '.xlsx':
                        df = pd.read_excel(xls_file, engine='openpyxl')
                    else:
                        df = pd.read_excel(xls_file)

                    # Normalize column names to lowercase
                    df.columns = [str(c).strip().lower() for c in df.columns]

                    # Check if required columns are present
                    required_cols = ['issn', 'journal', 'categoria', 'vigencia']
                    if not all(col in df.columns for col in required_cols):
                        logger.warning(f"File {xls_file.name} is missing required columns. Expected: {required_cols}, Found: {list(df.columns)}")
                        continue

                    # Rename to standardized names
                    df = df.rename(columns={
                        'categoria': 'category_publindex',
                        'vigencia': 'year_publindex'
                    })

                    # Remove rows where all values are NaN
                    df = df.dropna(how='all')

                    # Keep only required columns in correct order
                    df = df[['journal', 'issn', 'category_publindex', 'year_publindex']]

                    # Save to CSV
                    df.to_csv(output_path, index=False, encoding='utf-8')
                    logger.info(f"Saved {output_name} with {len(df)} rows")

                except Exception as e:
                    logger.error(f"Failed to process {xls_file.name}: {str(e)}")

            # Generate database from all processed CSVs
            generate_homologation_database(processed_folder, database_path)
            logger.info("✅ Homologation database created successfully")

        # Publindex database
        if database_type in [None, 'publindex']:
            logger.info("Creating Publindex database...")
            generate_publindex_database(database_path)
            logger.info("✅ Publindex database created successfully")

        # Scopus database
        if database_type in [None, 'scopus']:
            logger.info("Creating Scopus database...")
            url = "https://downloads.ctfassets.net/o78em1y1w4i4/7xtaTxNiNcWRTeZkV86eNy/710bfd3c7f7c7c9c88eeb3638ba4be43/ext_list_Jun_2026.xlsx"
            generate_scopus_database(url, database_path)
            logger.info("✅ Scopus database created successfully")

        logger.info("Database creation completed successfully")
    except ImportError as e:
        logger.error(f"Error importing database module: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error creating database: {str(e)}")
        raise

def process_data():
    """Step 2: Process the data"""
    try:
        import requests
        from tempfile import NamedTemporaryFile
        from preprocessing.extract_table import extract_tables_from_html
        from preprocessing.process_articles_data import get_articles_data
        from preprocessing.enrich_articles import enrich_articles_data
        from analysis.utilities import (join_csvs_from_path,
                                        deduplicate_articles_by_doi,
                                        build_missing_info_report)

        logger.info("Starting data processing...")

        # ----------------------------- GrupLAC Data Processing -----------------------------
        logger.info("Processing GrupLAC data...")
        groups_info_file = PATHS['DATA'] / 'raw' / 'gruplac' / 'research_groups_data.csv'
        groups_info = pd.read_csv(groups_info_file)
        output_path_html = PATHS['DATA'] / 'processed'
        data_blocks_path = output_path_html / 'data_blocks_gruplac'

        for _, row in groups_info.iterrows():
            group_name = row['research_group']
            url = row['url_to_gruplac']

            logger.info(f"Processing group: {group_name}")

            try:
                response = requests.get(url)
                response.raise_for_status()

                with NamedTemporaryFile(mode='w', suffix='.html', encoding='latin-1', delete=False) as temp_file:
                    temp_file.write(response.text)
                    temp_path = Path(temp_file.name)

                try:
                    extract_tables_from_html(temp_path, output_path_html, group_name)
                    logger.info(f"✅ Successfully extracted tables for group: {group_name}")
                finally:
                    temp_path.unlink()

            except requests.RequestException as e:
                logger.error(f"Failed to download HTML for group {group_name}: {str(e)}")
            except Exception as e:
                logger.error(f"Failed to process group {group_name}: {str(e)}")

        # ----------------------------- Articles Data Processing -----------------------------
        logger.info("Processing articles data...")
        articles_html_files = list(data_blocks_path.glob("*_articulos.html"))
        output_articles_path = PATHS['RESULTS'] / 'tables'

        # ------------------- Step 1: Extract and process articles from HTML -------------------
        for html_file in articles_html_files:
            group_name = html_file.stem.replace("_articulos", "")
            logger.info(f"Processing articles for group: {group_name}")
            try:
                # Extract articles from HTML to CSV
                get_articles_data(html_file, group_name, output_articles_path)

                # Enrich with database information
                file_to_enrich = output_articles_path / f"{group_name}_articles.csv"
                enrich_articles_data(file_to_enrich, PATHS['DATABASE'], output_articles_path)

                # Deduplicate within this group
                enriched_file = output_articles_path / f"{group_name}_articles_enriched.csv"
                if enriched_file.exists():
                    logger.info(f"Deduplicating within group: {group_name}")
                    df_group = pd.read_csv(enriched_file)
                    df_group_clean, _ = deduplicate_articles_by_doi(
                        df_group,
                        similarity_threshold=0.86,
                        mode='intra_group',
                        generate_report=False
                    )
                    df_group_clean.to_csv(enriched_file, index=False)
                    logger.info(f"✅ {group_name}: {len(df_group)} → {len(df_group_clean)} articles after intra-group deduplication")

            except Exception as e:
                logger.error(f"Failed to process articles for group {group_name}: {str(e)}")

        # ------------------- Step 2: Inter-group consolidation -------------------
        # Consolidate all cleaned group files and merge duplicates across groups
        # (preserving filename information to show which groups reported each article)
        logger.info("Consolidating enriched articles and detecting cross-group duplicates...")
        enriched_pattern = output_articles_path / "*_articles_enriched.csv"
        all_enriched = join_csvs_from_path(str(enriched_pattern))

        if all_enriched.empty:
            logger.warning("No enriched articles found to consolidate. Skipping consolidation step.")
        else:
            # Deduplicación inter-grupos: fusiona filename cuando el mismo artículo está en múltiples grupos
            consolidated, duplicates_report = deduplicate_articles_by_doi(
                all_enriched,
                similarity_threshold=0.86,
                mode='inter_group'
            )

            consolidated_path = output_articles_path / "articles_consolidated.csv"
            consolidated.to_csv(consolidated_path, index=False)
            logger.info(f"✅ Saved consolidated, DOI-deduplicated articles: {consolidated_path}")

            # Save duplicates report if generated
            if duplicates_report is not None and not duplicates_report.empty:
                duplicates_path = output_articles_path / "duplicates_removed_report.csv"
                duplicates_report.to_csv(duplicates_path, index=False)
                logger.info(f"📋 Saved duplicates report: {duplicates_path} ({len(duplicates_report)} duplicates detailed)")
            else:
                logger.info("No duplicates were found or removed.")

            # ------------------- Missing information report -------------------
            # Flags articles missing key fields (DOI, authors, ISSN, title,
            # journal, Publindex category), both in detail and summarized per
            # research group. This makes it easy to request each
            # author/group to review and complete their records in GrupLAC,
            # and serves as a guide for downstream analyses and reports.
            reports_path = PATHS['RESULTS'] / 'reports'
            reports_path.mkdir(parents=True, exist_ok=True)

            df_missing_detail, df_missing_summary = build_missing_info_report(consolidated)

            detail_path = reports_path / "missing_information_detail.csv"
            df_missing_detail.to_csv(detail_path, index=False)
            logger.info(f"✅ Saved missing information detail report: {detail_path} "
                       f"({len(df_missing_detail)} articles with incomplete data)")

            summary_path = reports_path / "missing_information_summary_by_group.csv"
            if not df_missing_summary.empty:
                df_missing_summary.to_csv(summary_path, index=False)
                logger.info(f"✅ Saved missing information summary by group: {summary_path}")
            else:
                logger.info("No missing information found across any research group.")

        logger.info("Data processing completed successfully")

    except Exception as e:
        logger.error(f"Error in data processing: {str(e)}")
        raise

def generate_results(analysis_type=None, mailto=None, affiliation=None, api_key=None):
    """Step 3: Generate results

    Parameters:
    analysis_type (str): 'authors', 'areas', 'gran_areas', 'timeline', 'bibliometrics', or None for all
    mailto (str): Optional email used for OpenAlex's polite pool (bibliometrics only)
    affiliation (str): Optional institution name to disambiguate authors (bibliometrics only)
    api_key (str): Optional OpenAlex API key for higher rate limits (bibliometrics only)
    """
    try:
        from analysis.utilities import (join_csvs_from_path,
                                        process_authors_dataframe,
                                        count_articles_by_groups,
                                        deduplicate_articles_by_doi,
                                        expand_multi_group_articles)
        from analysis.bibliometrics import (enrich_with_citations,
                                            enrich_authors_with_metrics,
                                            build_author_summary)
        from visualization.visualize_data import (plot_articles_by_year_category,
                                                  plot_author_categories,
                                                  plot_top_authors_by_h_index,
                                                  plot_top_authors_by_2yr_citedness,
                                                  plot_sankey_area_group,
                                                  plot_heatmap_granarea_group,
                                                  plot_treemap_granarea,
                                                  plot_journals_analysis,
                                                  plot_language_distribution,
                                                  plot_open_access_distribution,
                                                  plot_countries_distribution)
        import matplotlib.pyplot as plt

        logger.info("Starting data visualization...")
        tables_path = PATHS['RESULTS'] / 'tables'
        figures_path = PATHS['RESULTS'] / 'figures'
        reports_path = PATHS['RESULTS'] / 'reports'
        figures_path.mkdir(parents=True, exist_ok=True)
        reports_path.mkdir(parents=True, exist_ok=True)

        # Prefer the consolidated, DOI-deduplicated table generated as a
        # standard step of `--process-data` (articles_consolidated.csv). This
        # guarantees every analysis (timeline, authors, areas, bibliometrics)
        # counts each article exactly once, regardless of how many
        # co-authors/groups reported it in GrupLAC. If it doesn't exist yet
        # (e.g. running --analysis without a prior --process-data run),
        # fall back to joining and deduplicating on the fly.
        consolidated_path = tables_path / "articles_consolidated.csv"
        if consolidated_path.exists():
            logger.info(f"Loading consolidated articles table: {consolidated_path}")
            articles_data = pd.read_csv(consolidated_path, dtype=str)
        else:
            logger.warning(
                "articles_consolidated.csv not found. Run '--process-data' to generate the "
                "standard consolidated/deduplicated table. Falling back to joining and "
                "deduplicating the per-group enriched files on the fly."
            )
            articles_data_path = tables_path / '*_articles_enriched.csv'
            articles_data = join_csvs_from_path(str(articles_data_path))
            if not articles_data.empty:
                articles_data, _ = deduplicate_articles_by_doi(articles_data, generate_report=False)

        if articles_data.empty:
            logger.warning("No enriched articles data found. Skipping visualization.")
            return

        # Expand multi-group articles for visualizations only
        # Articles reported by multiple groups (e.g., "CINBIOS, BIOTECGEN") are expanded
        # into separate rows so each group gets counted independently in the plots
        logger.info("Expanding multi-group articles for visualization...")
        articles_data_expanded = expand_multi_group_articles(articles_data, filename_column='filename')
        logger.info(f"Expanded {len(articles_data)} articles to {len(articles_data_expanded)} rows for visualization")

        # Timeline Analysis (all years and last 10 years)
        if analysis_type in [None, 'timeline']:
            logger.info("Generating timeline analysis...")

            fig1 = plot_articles_by_year_category(articles_data, 'year', 'category_publindex', group='category_publindex')
            fig1.savefig(figures_path / "articles_by_year_all_groups.pdf", format="pdf")
            logger.info("✅ Saved: articles_by_year_all_groups.pdf")

            current_year = pd.to_numeric(articles_data['year']).max()
            last_10_years = articles_data[pd.to_numeric(articles_data['year']) >= current_year - 9]
            fig2 = plot_articles_by_year_category(last_10_years, 'year', 'category_publindex', group='category_publindex')
            fig2.savefig(figures_path / "articles_by_year_all_groups_last_10_years.pdf", format="pdf")
            logger.info("✅ Saved: articles_by_year_all_groups_last_10_years.pdf")

            # Generate timeline stats report
            timeline_stats = articles_data.groupby(['year', 'category_publindex']).size().reset_index(name='count')
            timeline_pivot = timeline_stats.pivot(index='year', columns='category_publindex', values='count').fillna(0)
            # Reorder columns by category order
            category_order = ['A1', 'A2', 'B', 'C', 'D', 'No Disponible']
            available_cats = [cat for cat in category_order if cat in timeline_pivot.columns]
            timeline_pivot = timeline_pivot[available_cats]
            timeline_pivot['Total'] = timeline_pivot.sum(axis=1)
            timeline_pivot.index.name = 'year'
            timeline_pivot.to_csv(reports_path / 'timeline_stats.csv')
            logger.info("✅ Saved: reports/timeline_stats.csv")

        # Authors Analysis
        if analysis_type in [None, 'authors']:
            logger.info("Generating authors analysis...")

            # Load department authors list
            authors_dept_path = PATHS['DATABASE'] / 'authors_dpto_micro.csv'
            if authors_dept_path.exists():
                authors_dept = pd.read_csv(authors_dept_path, encoding='utf-8-sig')
                # Normalize author names for matching
                authors_dept['Autor'] = authors_dept['Autor'].str.strip()
                dept_author_list = authors_dept['Autor'].tolist()
                logger.info(f"Loaded {len(dept_author_list)} authors from department list")

                # Process authors and filter by department list
                df_authors, df_authors_grouped = process_authors_dataframe(articles_data, year_column='year', authors_column='authors')

                # Filter to only include authors in department list
                df_authors_filtered = df_authors[df_authors['author'].isin(dept_author_list)]
                logger.info(f"Filtered authors: {len(df_authors)} → {len(df_authors_filtered)} (department members only)")

                if len(df_authors_filtered) > 0:
                    author_category_stats = count_articles_by_groups(df_authors_filtered, 'author', 'category_publindex')
                    fig3 = plot_author_categories(author_category_stats, y_name='Authors', group='Category')
                    fig3.savefig(figures_path / "articles_by_author_all_groups.pdf", format="pdf")
                    logger.info("✅ Saved: articles_by_author_all_groups.pdf")

                    # Generate author stats report
                    author_category_stats.index.name = 'author'
                    author_category_stats.to_csv(reports_path / 'author_stats.csv')
                    logger.info("✅ Saved: reports/author_stats.csv")

                    # Additional author summary
                    author_summary = df_authors_filtered.groupby('author').agg({
                        'year': ['min', 'max', 'count'],
                        'category_publindex': lambda x: x.mode()[0] if len(x.mode()) > 0 else 'N/A'
                    }).reset_index()
                    author_summary.columns = ['author', 'first_year', 'last_year', 'total_articles', 'most_common_category']
                    author_summary = author_summary.sort_values('total_articles', ascending=False)
                    author_summary.to_csv(reports_path / 'author_summary.csv', index=False)
                    logger.info("✅ Saved: reports/author_summary.csv")
                else:
                    logger.warning("⚠️  No articles found for department authors - skipping visualization")
            else:
                logger.warning(f"⚠️  Department authors file not found: {authors_dept_path} - generating for all authors")
                df_authors, df_authors_grouped = process_authors_dataframe(articles_data, year_column='year', authors_column='authors')
                author_category_stats = count_articles_by_groups(df_authors, 'author', 'category_publindex')
                fig3 = plot_author_categories(author_category_stats, y_name='Authors', group='Category')
                fig3.savefig(figures_path / "articles_by_author_all_groups.pdf", format="pdf")
                logger.info("✅ Saved: articles_by_author_all_groups.pdf")

                # Generate author stats report (all authors)
                author_category_stats.index.name = 'author'
                author_category_stats.to_csv(reports_path / 'author_stats.csv')
                logger.info("✅ Saved: reports/author_stats.csv")

        # Areas Analysis
        if analysis_type in [None, 'areas']:
            logger.info("Generating areas analysis...")

            # Bar chart by area (using expanded data)
            filename_area_stats = count_articles_by_groups(articles_data_expanded, 'area', 'filename')
            fig6 = plot_author_categories(filename_area_stats, top_n=20, y_name='Areas', group='Research Group')
            fig6.savefig(figures_path / "articles_by_group_and_area_bars.pdf", format="pdf")
            logger.info("✅ Saved: articles_by_group_and_area_bars.pdf")

            # Generate area stats report
            filename_area_stats.index.name = 'area'
            filename_area_stats.to_csv(reports_path / 'area_by_group_stats.csv')
            logger.info("✅ Saved: reports/area_by_group_stats.csv")

            # Area summary (total across all groups)
            area_summary = articles_data_expanded.groupby('area').size().reset_index(name='total_articles')
            area_summary = area_summary.sort_values('total_articles', ascending=False)
            area_summary.to_csv(reports_path / 'area_summary.csv', index=False)
            logger.info("✅ Saved: reports/area_summary.csv")

        # Grand Areas Analysis
        if analysis_type in [None, 'gran_areas']:
            logger.info("Generating grand areas analysis...")

            # Heatmap by gran area and group (using expanded data)
            fig5 = plot_heatmap_granarea_group(articles_data_expanded, granarea_col='gran_area', group_col='filename')
            fig5.savefig(figures_path / "articles_by_group_and_gran_area.pdf", format="pdf")
            logger.info("✅ Saved: articles_by_group_and_gran_area.pdf (Heatmap)")
            
            # Treemap by gran area (using non-expanded data - one row per article)
            fig5_treemap = plot_treemap_granarea(articles_data, granarea_col='gran_area')
            fig5_treemap.savefig(figures_path / "articles_by_gran_area_treemap.pdf", format="pdf")
            logger.info("✅ Saved: articles_by_gran_area_treemap.pdf (Treemap)")

            # Generate gran area stats report
            granarea_stats = articles_data_expanded.groupby(['gran_area', 'filename']).size().reset_index(name='count')
            granarea_pivot = granarea_stats.pivot(index='gran_area', columns='filename', values='count').fillna(0)
            granarea_pivot['Total'] = granarea_pivot.sum(axis=1)
            granarea_pivot.index.name = 'gran_area'
            granarea_pivot.to_csv(reports_path / 'gran_area_by_group_stats.csv')
            logger.info("✅ Saved: reports/gran_area_by_group_stats.csv")

            # Gran area summary
            granarea_summary = articles_data_expanded.groupby('gran_area').size().reset_index(name='total_articles')
            granarea_summary = granarea_summary.sort_values('total_articles', ascending=False)
            granarea_summary.to_csv(reports_path / 'gran_area_summary.csv', index=False)
            logger.info("✅ Saved: reports/gran_area_summary.csv")

        # Bibliometrics Analysis (citations + author h-index via OpenAlex)
        # NOTE: Not included in the default None/'all' run since it makes
        # many external API calls and can take a while. Request it explicitly
        # with --analysis bibliometrics.
        if analysis_type == 'bibliometrics':
            logger.info("Generating bibliometrics analysis (this queries the OpenAlex API "
                       "and may take a while depending on the number of articles/authors)...")

            # `articles_data` here is already the consolidated, DOI-deduplicated
            # table (articles_consolidated.csv, generated by --process-data, or
            # the on-the-fly fallback above), so citation counts and h-index
            # are computed on one row per unique article.

            # Article-level citation metrics with title validation and fallback
            articles_with_citations, search_info = enrich_with_citations(
                articles_data, 
                doi_column='doi', 
                title_column='tittle',
                title_similarity_threshold=0.7,
                use_title_fallback=True,
                mailto=mailto, 
                api_key=api_key
            )
            
            # Consolidate metrics columns (remove duplicates from different search methods)
            # Keep only one set of metrics regardless of search method
            metrics_to_consolidate = [
                'openalex_id', 'openalex_title', 'cited_by_count', 'fwci',
                'referenced_works_count', 'is_oa', 'oa_status', 'concepts',
                'publication_year_openalex', 'title_similarity', 'openalex_doi',
                'openalex_authors', 'openalex_institutions', 'openalex_countries',
                'language', 'oa_url', 'any_repository_has_fulltext', 'citation_apa_openalex'
            ]

            # Remove any duplicate columns that might have been created
            cols_to_drop = [col for col in articles_with_citations.columns
                           if col.endswith('_title') and col.replace('_title', '') in metrics_to_consolidate]
            if cols_to_drop:
                articles_with_citations = articles_with_citations.drop(columns=cols_to_drop)

            # Rename doi_validation_status to data_source for clarity
            if 'doi_validation_status' in articles_with_citations.columns:
                articles_with_citations = articles_with_citations.rename(
                    columns={'doi_validation_status': 'openalex_data_source'}
                )
                # Simplify values for clarity
                articles_with_citations['openalex_data_source'] = articles_with_citations['openalex_data_source'].replace({
                    'valid': 'doi',
                    'found_by_title': 'title',
                    'title_mismatch': 'not_found',
                    'not_found': 'not_found',
                    'error': 'not_found'
                })

            # Consolidate citation_apa: prioritize OpenAlex citation over original
            if 'citation_apa' in articles_with_citations.columns and 'citation_apa_openalex' in articles_with_citations.columns:
                # Use OpenAlex citation if available, otherwise keep original
                articles_with_citations['citation_apa'] = articles_with_citations['citation_apa_openalex'].fillna(
                    articles_with_citations['citation_apa']
                )
                # Drop the OpenAlex-specific column to avoid confusion
                articles_with_citations = articles_with_citations.drop(columns=['citation_apa_openalex'])
                logger.info("✓ Consolidated citation_apa column (prioritizing OpenAlex data)")
            elif 'citation_apa_openalex' in articles_with_citations.columns:
                # If no original citation_apa, rename OpenAlex version
                articles_with_citations = articles_with_citations.rename(
                    columns={'citation_apa_openalex': 'citation_apa'}
                )
            
            articles_with_citations.to_csv(tables_path / "articles_with_citations.csv", index=False)
            logger.info("✅ Saved: articles_with_citations.csv")
            
            # Save search info report
            if not search_info.empty:
                search_info.to_csv(reports_path / "openalex_search_info.csv", index=False)
                logger.info(f"✅ Saved: reports/openalex_search_info.csv")
                
                # Report on problematic cases
                problems = search_info[~search_info["validation_status"].isin(["valid", "found_by_title"])]
                if not problems.empty:
                    logger.warning(f"⚠️  {len(problems)} articles not found in OpenAlex")
                    logger.info("   Check reports/openalex_search_info.csv for details")
            else:
                logger.info("✅ All articles processed successfully")

            if 'cited_by_count' in articles_with_citations.columns and articles_with_citations['cited_by_count'].sum() > 0:
                # Create table report instead of figure (titles are too long for plot axes)
                top_cited = articles_with_citations.nlargest(20, 'cited_by_count')[
                    ['tittle', 'authors', 'year', 'journal', 'cited_by_count', 'doi']
                ].copy()
                top_cited = top_cited.reset_index(drop=True)
                top_cited.index = top_cited.index + 1  # Start index at 1
                top_cited.to_csv(reports_path / 'top_cited_articles.csv')
                logger.info("✅ Saved: reports/top_cited_articles.csv")
            else:
                logger.warning("No citation data could be retrieved from OpenAlex; skipping top cited articles report.")

            # Author-level metrics (h-index, i10-index, total works/citations)
            # Filter by department authors only and merge with ORCID data
            authors_dept_path = PATHS['DATABASE'] / 'authors_dpto_micro.csv'
            if authors_dept_path.exists():
                authors_dept = pd.read_csv(authors_dept_path, encoding='utf-8-sig')
                authors_dept['Autor'] = authors_dept['Autor'].str.strip()

                # Check if ORCID column exists
                has_orcid = 'ORCID' in authors_dept.columns
                if has_orcid:
                    logger.info(f"Loaded {len(authors_dept)} authors from department list (with ORCID data)")
                else:
                    logger.info(f"Loaded {len(authors_dept)} authors from department list (no ORCID data)")

                dept_author_list = authors_dept['Autor'].tolist()

                df_authors, _ = process_authors_dataframe(articles_data, year_column='year', authors_column='authors')
                df_authors_filtered = df_authors[df_authors['author'].isin(dept_author_list)]
                logger.info(f"Filtered authors for bibliometrics: {len(df_authors)} → {len(df_authors_filtered.author.unique())} unique department authors")

                # Merge with ORCID data if available
                if has_orcid:
                    df_authors_filtered = pd.merge(
                        df_authors_filtered,
                        authors_dept[['Autor', 'ORCID']],
                        left_on='author',
                        right_on='Autor',
                        how='left'
                    )
                    df_authors_filtered = df_authors_filtered.drop(columns=['Autor'])

                    # Count authors with ORCID
                    orcid_count = df_authors_filtered['ORCID'].notna().sum()
                    logger.info(f"Authors with ORCID: {orcid_count}/{len(df_authors_filtered)} ({orcid_count/len(df_authors_filtered)*100:.1f}%)")

                df_authors_with_metrics = enrich_authors_with_metrics(
                    df_authors_filtered,
                    name_column='author',
                    orcid_column='ORCID' if has_orcid else None,
                    affiliation=affiliation,
                    mailto=mailto,
                    api_key=api_key
                )
            else:
                logger.warning(f"⚠️  Department authors file not found: {authors_dept_path} - using all authors")
                df_authors, _ = process_authors_dataframe(articles_data, year_column='year', authors_column='authors')
                df_authors_with_metrics = enrich_authors_with_metrics(
                    df_authors, name_column='author', affiliation=affiliation, mailto=mailto, api_key=api_key
                )

            # Build author summary with all metrics (h-index, i10-index, 2yr_mean_citedness, etc.)
            author_summary = build_author_summary(
                df_authors_with_metrics,
                name_column='author',
                orcid_column='ORCID' if 'ORCID' in df_authors_with_metrics.columns else None
            )
            author_summary.to_csv(tables_path / "author_summary_h_index.csv", index=False)
            logger.info("✅ Saved: author_summary_h_index.csv")

            # Generate bibliometric reports
            # Article-level bibliometric stats
            if 'cited_by_count' in articles_with_citations.columns:
                article_biblio_stats = articles_with_citations[['tittle', 'doi', 'year', 'cited_by_count', 'fwci',
                                                                 'openalex_id', 'is_oa', 'oa_status']].copy()
                article_biblio_stats = article_biblio_stats.sort_values('cited_by_count', ascending=False)
                article_biblio_stats.to_csv(reports_path / 'article_bibliometrics.csv', index=False)
                logger.info("✅ Saved: reports/article_bibliometrics.csv")

            # Author-level bibliometric stats (detailed report)
            if 'h_index' in author_summary.columns:
                # Select all available bibliometric columns
                biblio_cols = ['author']
                optional_cols = ['ORCID', 'orcid', 'display_name', 'h_index', 'i10_index', 
                               '2yr_mean_citedness', 'works_count', 'cited_by_count_total', 
                               'affiliation_openalex', 'articulos_en_indica']
                biblio_cols.extend([col for col in optional_cols if col in author_summary.columns])
                
                author_biblio_stats = author_summary[biblio_cols].copy()
                author_biblio_stats = author_biblio_stats.sort_values('h_index', ascending=False)
                author_biblio_stats.to_csv(reports_path / 'author_bibliometrics.csv', index=False)
                logger.info("✅ Saved: reports/author_bibliometrics.csv")

            if 'h_index' in author_summary.columns and author_summary['h_index'].notna().any():
                fig8 = plot_top_authors_by_h_index(author_summary, top_n=20, metric='h_index')
                fig8.savefig(figures_path / "top_authors_by_h_index.pdf", format="pdf")
                logger.info("✅ Saved: top_authors_by_h_index.pdf")
            else:
                logger.warning("No h-index data could be retrieved from OpenAlex; skipping h-index plot.")

            if '2yr_mean_citedness' in author_summary.columns and author_summary['2yr_mean_citedness'].notna().any():
                fig9 = plot_top_authors_by_2yr_citedness(author_summary, top_n=20, metric='2yr_mean_citedness')
                fig9.savefig(figures_path / "top_authors_by_2yr_citedness.pdf", format="pdf")
                logger.info("✅ Saved: top_authors_by_2yr_citedness.pdf")
            else:
                logger.warning("No 2yr_mean_citedness data could be retrieved from OpenAlex; skipping 2yr citedness plot.")
            
            # Journals analysis (articles and citations per journal)
            if 'journal' in articles_with_citations.columns and 'cited_by_count' in articles_with_citations.columns:
                fig10 = plot_journals_analysis(articles_with_citations, journal_col='journal', 
                                              citations_col='cited_by_count', top_n=20)
                fig10.savefig(figures_path / "top_journals_articles_citations.pdf", format="pdf")
                logger.info("✅ Saved: top_journals_articles_citations.pdf")
                
                # Generate journal stats report
                journal_stats = articles_with_citations.groupby('journal').agg({
                    'cited_by_count': ['count', 'sum', 'mean']
                }).reset_index()
                journal_stats.columns = ['journal', 'num_articles', 'total_citations', 'avg_citations_per_article']
                journal_stats = journal_stats.sort_values('total_citations', ascending=False)
                journal_stats.to_csv(reports_path / 'journal_bibliometrics.csv', index=False)
                logger.info("✅ Saved: reports/journal_bibliometrics.csv")
            else:
                logger.warning("Journal or citation data not available; skipping journals analysis.")
            
            # Language distribution
            if 'language' in articles_with_citations.columns:
                fig11 = plot_language_distribution(articles_with_citations, language_col='language')
                fig11.savefig(figures_path / "articles_by_language.pdf", format="pdf")
                logger.info("✅ Saved: articles_by_language.pdf")
            else:
                logger.warning("Language data not available; skipping language distribution plot.")
            
            # Open Access distribution
            if 'is_oa' in articles_with_citations.columns:
                fig12 = plot_open_access_distribution(articles_with_citations, oa_col='is_oa')
                fig12.savefig(figures_path / "articles_by_open_access.pdf", format="pdf")
                logger.info("✅ Saved: articles_by_open_access.pdf")
                
                # OA status breakdown report
                if 'oa_status' in articles_with_citations.columns:
                    oa_status_counts = articles_with_citations['oa_status'].value_counts().reset_index()
                    oa_status_counts.columns = ['oa_status', 'count']
                    oa_status_counts.to_csv(reports_path / 'open_access_status.csv', index=False)
                    logger.info("✅ Saved: reports/open_access_status.csv")
            else:
                logger.warning("Open Access data not available; skipping OA distribution plot.")
            
            # Countries distribution
            if 'openalex_countries' in articles_with_citations.columns:
                fig13 = plot_countries_distribution(articles_with_citations, countries_col='openalex_countries', top_n=15)
                fig13.savefig(figures_path / "articles_by_country.pdf", format="pdf")
                logger.info("✅ Saved: articles_by_country.pdf")
                
                # Generate countries report
                all_countries = []
                for countries_str in articles_with_citations['openalex_countries'].dropna():
                    if countries_str:
                        countries_list = [c.strip() for c in str(countries_str).split(';')]
                        all_countries.extend(countries_list)
                
                if all_countries:
                    country_counts = pd.Series(all_countries).value_counts().reset_index()
                    country_counts.columns = ['country_code', 'num_articles']
                    country_counts.to_csv(reports_path / 'countries_distribution.csv', index=False)
                    logger.info("✅ Saved: reports/countries_distribution.csv")
            else:
                logger.warning("Country data not available; skipping countries distribution plot.")
            
            # Institutions report
            if 'openalex_institutions' in articles_with_citations.columns:
                all_institutions = []
                for institutions_str in articles_with_citations['openalex_institutions'].dropna():
                    if institutions_str:
                        institutions_list = [i.strip() for i in str(institutions_str).split(';')]
                        all_institutions.extend(institutions_list)
                
                if all_institutions:
                    institution_counts = pd.Series(all_institutions).value_counts().reset_index()
                    institution_counts.columns = ['institution', 'num_articles']
                    institution_counts.to_csv(reports_path / 'institutions_distribution.csv', index=False)
                    logger.info("✅ Saved: reports/institutions_distribution.csv")
            else:
                logger.warning("Institution data not available; skipping institutions report.")

            # ============ Bibliometric Analysis for Last 5 Years ============
            logger.info("Generating bibliometric analysis for last 5 years...")

            # Filter articles from last 5 years
            if 'year' in articles_with_citations.columns:
                current_year = pd.to_numeric(articles_with_citations['year'], errors='coerce').max()
                if pd.notna(current_year):
                    last_5_years = articles_with_citations[
                        pd.to_numeric(articles_with_citations['year'], errors='coerce') >= current_year - 4
                    ]
                    logger.info(f"Filtered last 5 years ({int(current_year)-4}-{int(current_year)}): {len(last_5_years)} articles")

                    # Top cited articles (last 5 years)
                    if 'cited_by_count' in last_5_years.columns and last_5_years['cited_by_count'].sum() > 0:
                        top_cited_5y = last_5_years.nlargest(20, 'cited_by_count')[
                            ['tittle', 'authors', 'year', 'journal', 'cited_by_count', 'doi']
                        ].copy()
                        top_cited_5y = top_cited_5y.reset_index(drop=True)
                        top_cited_5y.index = top_cited_5y.index + 1
                        top_cited_5y.to_csv(reports_path / 'top_cited_articles_last_5_years.csv')
                        logger.info("✅ Saved: reports/top_cited_articles_last_5_years.csv")

                    # Journals analysis (last 5 years)
                    if 'journal' in last_5_years.columns and 'cited_by_count' in last_5_years.columns:
                        fig10_5y = plot_journals_analysis(last_5_years, journal_col='journal',
                                                         citations_col='cited_by_count', top_n=20)
                        fig10_5y.savefig(figures_path / "top_journals_articles_citations_last_5_years.pdf", format="pdf")
                        logger.info("✅ Saved: top_journals_articles_citations_last_5_years.pdf")

                        journal_stats_5y = last_5_years.groupby('journal').agg({
                            'cited_by_count': ['count', 'sum', 'mean']
                        }).reset_index()
                        journal_stats_5y.columns = ['journal', 'num_articles', 'total_citations', 'avg_citations_per_article']
                        journal_stats_5y = journal_stats_5y.sort_values('total_citations', ascending=False)
                        journal_stats_5y.to_csv(reports_path / 'journal_bibliometrics_last_5_years.csv', index=False)
                        logger.info("✅ Saved: reports/journal_bibliometrics_last_5_years.csv")

                    # Language distribution (last 5 years)
                    if 'language' in last_5_years.columns:
                        fig11_5y = plot_language_distribution(last_5_years, language_col='language')
                        fig11_5y.savefig(figures_path / "articles_by_language_last_5_years.pdf", format="pdf")
                        logger.info("✅ Saved: articles_by_language_last_5_years.pdf")

                    # Open Access distribution (last 5 years)
                    if 'is_oa' in last_5_years.columns:
                        fig12_5y = plot_open_access_distribution(last_5_years, oa_col='is_oa')
                        fig12_5y.savefig(figures_path / "articles_by_open_access_last_5_years.pdf", format="pdf")
                        logger.info("✅ Saved: articles_by_open_access_last_5_years.pdf")

                    # Countries distribution (last 5 years)
                    if 'openalex_countries' in last_5_years.columns:
                        fig13_5y = plot_countries_distribution(last_5_years, countries_col='openalex_countries', top_n=15)
                        fig13_5y.savefig(figures_path / "articles_by_country_last_5_years.pdf", format="pdf")
                        logger.info("✅ Saved: articles_by_country_last_5_years.pdf")

                        all_countries_5y = []
                        for countries_str in last_5_years['openalex_countries'].dropna():
                            if countries_str:
                                countries_list = [c.strip() for c in str(countries_str).split(';')]
                                all_countries_5y.extend(countries_list)

                        if all_countries_5y:
                            country_counts_5y = pd.Series(all_countries_5y).value_counts().reset_index()
                            country_counts_5y.columns = ['country_code', 'num_articles']
                            country_counts_5y.to_csv(reports_path / 'countries_distribution_last_5_years.csv', index=False)
                            logger.info("✅ Saved: reports/countries_distribution_last_5_years.csv")
                else:
                    logger.warning("Could not determine current year; skipping last 5 years analysis.")
            else:
                logger.warning("Year column not available; skipping last 5 years analysis.")

        logger.info("Visualization completed successfully")
        plt.close('all')

    except Exception as e:
        logger.error(f"Error in generating results: {str(e)}")
        raise

def analyze_duplicates_report():
    """Analyze the duplicates report and generate statistics"""
    from analysis.utilities import normalize_title, normalize_doi

    report_path = PATHS['RESULTS'] / 'tables' / 'duplicates_removed_report.csv'

    if not report_path.exists():
        logger.error(f"Duplicates report not found: {report_path}")
        logger.info("Run '--process-data' first to generate the duplicates report")
        return

    logger.info("=" * 80)
    logger.info("ANALYZING DUPLICATES REPORT")
    logger.info("=" * 80)

    df = pd.read_csv(report_path)

    if df.empty:
        logger.info("✅ No duplicates were found or removed.")
        return

    logger.info(f"\n📌 Total duplicates removed: {len(df)}")

    # Summary by reason
    logger.info("\n📋 Duplicates by detection type:")
    logger.info("-" * 80)
    razon_counts = df['razon'].value_counts()
    for razon, count in razon_counts.items():
        logger.info(f"  • {razon}: {count} ({count/len(df)*100:.1f}%)")

    # Summary by group
    if 'grupo_eliminado' in df.columns:
        logger.info("\n🏢 Top 10 groups with removed duplicates:")
        logger.info("-" * 80)
        grupo_counts = df['grupo_eliminado'].value_counts().head(10)
        for grupo, count in grupo_counts.items():
            logger.info(f"  • {grupo}: {count}")

    # Invalid DOIs
    invalid_dois = df[df['doi_valido'] == 'No']
    if not invalid_dois.empty:
        logger.info(f"\n⚠️  Articles with invalid DOIs detected: {len(invalid_dois)}")
        logger.info("-" * 80)
        logger.info("\nFirst 5 cases of invalid DOIs:")
        for idx, row in invalid_dois.head().iterrows():
            logger.info(f"\n  Title: {row['titulo_eliminado'][:70]}...")
            logger.info(f"  Invalid DOI: {row['doi_eliminado']}")
            logger.info(f"  Group: {row['grupo_eliminado']}")

    # Similar titles
    similar_titles = df[df['razon'].str.contains('similar', case=False, na=False)]
    if not similar_titles.empty:
        logger.info(f"\n🔍 Similar titles detected (without DOI): {len(similar_titles)}")
        logger.info("-" * 80)
        logger.info("\nFirst 3 cases of similar titles:")
        for idx, row in similar_titles.head(3).iterrows():
            logger.info(f"\n  Removed: {row['titulo_eliminado'][:60]}...")
            logger.info(f"  Kept: {row['titulo_mantenido'][:60]}...")
            logger.info(f"  Reason: {row['razon']}")

    # Save detailed summary
    summary_path = PATHS['RESULTS'] / 'tables' / 'duplicates_summary.txt'
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("DETAILED DUPLICATES REPORT\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total duplicates: {len(df)}\n\n")

        f.write("DUPLICATES BY TYPE:\n")
        f.write("-" * 80 + "\n")
        for razon, count in razon_counts.items():
            f.write(f"{razon}: {count} ({count/len(df)*100:.1f}%)\n")

        f.write("\n\nCOMPLETE LIST OF DUPLICATES:\n")
        f.write("=" * 80 + "\n\n")

        for idx, row in df.iterrows():
            f.write(f"DUPLICATE #{idx+1}\n")
            f.write(f"Reason: {row['razon']}\n")
            f.write(f"Removed title: {row['titulo_eliminado']}\n")
            f.write(f"Removed DOI: {row['doi_eliminado']}\n")
            f.write(f"Removed group: {row['grupo_eliminado']}\n")
            f.write(f"Kept title: {row['titulo_mantenido']}\n")
            f.write(f"Kept DOI: {row['doi_mantenido']}\n")
            f.write(f"Kept group: {row['grupo_mantenido']}\n")
            f.write("-" * 80 + "\n\n")

    logger.info(f"\n💾 Detailed summary saved: {summary_path}")
    logger.info("\n" + "=" * 80)
    logger.info("✅ Analysis completed")
    logger.info("=" * 80)


def fix_residual_duplicates():
    """Apply aggressive deduplication to fix residual duplicates"""
    from analysis.utilities import deduplicate_articles_by_doi, normalize_title, normalize_doi

    consolidated_path = PATHS['RESULTS'] / 'tables' / 'articles_consolidated.csv'

    if not consolidated_path.exists():
        logger.error(f"Consolidated file not found: {consolidated_path}")
        logger.info("Run '--process-data' first to generate the consolidated file")
        return

    logger.info("=" * 80)
    logger.info("ANALYZING RESIDUAL DUPLICATES")
    logger.info("=" * 80)

    df = pd.read_csv(consolidated_path, dtype=str)
    logger.info(f"\nTotal articles: {len(df)}")

    # Create normalized columns for analysis
    df['_title_norm'] = df['tittle'].apply(normalize_title)
    df['_doi_norm'] = df['doi'].apply(normalize_doi)

    # Find duplicates by normalized title
    logger.info("\n🔍 Searching for duplicates by normalized title...")
    logger.info("-" * 80)

    title_counts = df['_title_norm'].value_counts()
    duplicates_by_title = title_counts[title_counts > 1]

    if len(duplicates_by_title) > 0:
        logger.info(f"❌ Found {len(duplicates_by_title)} titles with duplicates:")
        logger.info("")

        for title_norm, count in duplicates_by_title.items():
            if title_norm:
                dupes = df[df['_title_norm'] == title_norm]
                logger.info(f"Title (normalized): {title_norm[:60]}...")
                logger.info(f"Occurrences: {count}")
                for idx, row in dupes.iterrows():
                    doi_status = "WITH DOI" if row['_doi_norm'] else "WITHOUT DOI"
                    logger.info(f"  - {doi_status}: {row['doi']}")
                    logger.info(f"    Group: {row.get('filename', 'N/A')}")
                logger.info("")

        # Apply aggressive deduplication
        logger.info("\n🔧 Applying aggressive deduplication (threshold 98%)...")
        logger.info("=" * 80)

        df_original = pd.read_csv(consolidated_path, dtype=str)
        n_before = len(df_original)

        logger.info(f"Articles before: {n_before}")

        df_unique, duplicates_report = deduplicate_articles_by_doi(
            df_original,
            similarity_threshold=0.98,
            validate_dois=False,
            generate_report=True
        )

        n_after = len(df_unique)
        n_removed = n_before - n_after

        logger.info(f"Articles after: {n_after}")
        logger.info(f"Duplicates removed: {n_removed}")

        if n_removed > 0:
            fixed_path = PATHS['RESULTS'] / 'tables' / 'articles_consolidated_fixed.csv'
            df_unique.to_csv(fixed_path, index=False)
            logger.info(f"\n✅ Fixed file saved: {fixed_path}")

            if duplicates_report is not None and not duplicates_report.empty:
                report_path = PATHS['RESULTS'] / 'tables' / 'duplicates_fixed_report.csv'
                duplicates_report.to_csv(report_path, index=False)
                logger.info(f"📋 Fix report saved: {report_path}")

            logger.info("\n💡 To use the fixed file, replace the original:")
            logger.info(f"   cp {fixed_path} {consolidated_path}")
        else:
            logger.info("\n✅ No additional duplicates found")
    else:
        logger.info("✅ No duplicates found by title")

    logger.info("\n" + "=" * 80)


def create_cli_parser():
    """Create and return the CLI argument parser"""
    parser = argparse.ArgumentParser(
        description='INDICA — INDicadores de Investigación, Ciencia y Academia',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all processes
  python main.py --all

  # Process data and analyze duplicates
  python main.py --process-data --analyze-duplicates

  # Fix residual duplicates in consolidated file
  python main.py --fix-duplicates

  # Create only Scopus database
  python main.py --database scopus

  # Create homologation database (incremental - skips already processed files)
  python main.py --database homologation

  # Force reprocess ALL homologation files (overwrites existing CSVs)
  python main.py --database homologation --force-reprocess

  # Generate only authors analysis
  python main.py --analysis authors

  # Deduplicate articles by DOI and fetch citations + author h-index from OpenAlex
  python main.py --analysis bibliometrics --email you@example.com --affiliation "Universidad X"
        """
    )

    # Main execution modes
    mode_group = parser.add_argument_group('Execution Modes')
    mode_group.add_argument(
        '--all',
        action='store_true',
        help='Run all processes: create databases, process data, and generate results'
    )

    # Database operations
    db_group = parser.add_argument_group('Database Operations')
    db_group.add_argument(
        '--database',
        choices=['homologation', 'publindex', 'scopus', 'all'],
        help='Create or update specific database(s)'
    )
    db_group.add_argument(
        '--force-reprocess',
        action='store_true',
        help='Force reprocessing of all files, overwriting existing CSVs (use with --database homologation)'
    )

    # Data processing
    data_group = parser.add_argument_group('Data Processing')
    data_group.add_argument(
        '--process-data',
        action='store_true',
        help='Process and enrich articles data from GrupLAC'
    )
    data_group.add_argument(
        '--analyze-duplicates',
        action='store_true',
        help='Analyze the duplicates report and generate statistics'
    )
    data_group.add_argument(
        '--fix-duplicates',
        action='store_true',
        help='Apply aggressive deduplication to fix residual duplicates in consolidated file'
    )

    # Analysis and visualization
    analysis_group = parser.add_argument_group('Analysis and Visualization')
    analysis_group.add_argument(
        '--analysis',
        choices=['timeline', 'authors', 'areas', 'gran_areas', 'bibliometrics', 'all'],
        help=('Generate specific analysis/visualizations. "bibliometrics" deduplicates '
             'articles by DOI and queries OpenAlex for citation counts and author '
             'h-index (not included when using "all", request it explicitly).')
    )
    analysis_group.add_argument(
        '--email',
        default=None,
        help='Email address used for the OpenAlex "polite pool" (faster/more reliable '
            'API responses) when running --analysis bibliometrics'
    )
    analysis_group.add_argument(
        '--affiliation',
        default=None,
        help='Institution name used to disambiguate authors when querying OpenAlex '
            'for h-index/citations (--analysis bibliometrics)'
    )
    analysis_group.add_argument(
        '--api-key',
        default=None,
        help='OpenAlex API key for higher rate limits (100k/day vs 100/day). '
            'Get your free key at https://openalex.org/'
    )

    # Logging
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    return parser

def main():
    """Main entry point of the application"""
    parser = create_cli_parser()
    args = parser.parse_args()

    # If no arguments provided, show help
    if len(sys.argv) == 1:
        parser.print_help()
        return

    try:
        # Setup environment
        logger.info("Setting up environment...")
        setup_environment()

        # Execute based on arguments
        if args.all:
            logger.info("Running complete pipeline...")
            create_databases()
            process_data()
            generate_results()

        else:
            # Database creation
            if args.database:
                db_type = None if args.database == 'all' else args.database
                create_databases(db_type, force_reprocess=args.force_reprocess)

            # Data processing
            if args.process_data:
                process_data()

            # Duplicates analysis
            if args.analyze_duplicates:
                analyze_duplicates_report()

            # Fix residual duplicates
            if args.fix_duplicates:
                fix_residual_duplicates()

            # Analysis and visualization
            if args.analysis:
                analysis_type = None if args.analysis == 'all' else args.analysis
                generate_results(analysis_type, mailto=args.email, affiliation=args.affiliation, api_key=args.api_key)

        logger.info("✅ Application completed successfully!")

    except KeyboardInterrupt:
        logger.info("\n⚠️ Process interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Application failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()