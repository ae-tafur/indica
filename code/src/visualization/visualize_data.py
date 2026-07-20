import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from visualization.chart_style import (
    get_publindex_colors,
    get_categorical_colors,
    PALETA_PUBLINDEX,
    PALETA_SECUENCIAL_VERDE,
    COLOR_ROJO,
    COLOR_VERDE_PRINCIPAL
)


def plot_articles_by_year_category(df, x, y, group=None):
    """
    Creates a two-panel plot with line plot (Panel A) and 100% stacked bar plot (Panel B).

    Parameters:
    df (pd.DataFrame): Input DataFrame
    x (str): Name of the column for x-axis (typically year)
    y (str): Name of the column for categorization
    group (str, optional): Name of the column to be counted/grouped. If None, uses y column.

    Returns:
    matplotlib.figure.Figure: The plot figure for further customization
    """
    # Validate columns exist
    if x not in df.columns or y not in df.columns:
        raise KeyError(f"Columns {x} or {y} not found in DataFrame")

    # If group is not specified, use the y column
    group = y if group is None else group

    # Process x-axis data
    df = df.copy()
    df[x] = pd.to_numeric(df[x], errors='coerce')
    df = df.dropna(subset=[x])
    df[x] = df[x].astype(int)

    # Group and pivot data
    df_grouped = df.groupby([x, y]).size().reset_index(name='count')
    pivot_df = df_grouped.pivot(index=x, columns=y, values='count').fillna(0)

    # Define category order
    category_order = ['A1', 'A2', 'B', 'C', 'D', 'No Disponible']

    # Reorder columns to match category order
    available_categories = [cat for cat in category_order if cat in pivot_df.columns]
    pivot_df = pivot_df[available_categories]

    # Create figure with two vertical panels
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 12))

    # Get colors for categories
    colors = get_publindex_colors(pivot_df.columns.tolist())

    # Panel A: Line plot with points showing number of articles by year and category
    for idx, col in enumerate(pivot_df.columns):
        ax1.plot(pivot_df.index, pivot_df[col], marker='o', label=col,
                linewidth=2, markersize=6, color=colors[idx])

    ax1.set_xlabel('Year', fontweight='bold', fontsize=12)
    ax1.set_ylabel('Number of Articles', fontweight='bold', fontsize=12)
    ax1.legend(title='Category', bbox_to_anchor=(1.05, 1), loc='upper left')
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(axis='both', labelsize=10)

    # Panel B: 100% stacked bar plot
    pivot_df_pct = pivot_df.div(pivot_df.sum(axis=1), axis=0) * 100
    pivot_df_pct.plot(kind='bar', stacked=True, ax=ax2, width=0.8, color=colors)

    ax2.set_xlabel('Year', fontweight='bold', fontsize=12)
    ax2.set_ylabel('Percentage (%)', fontweight='bold', fontsize=12)
    ax2.legend(title='Category', bbox_to_anchor=(1.05, 1), loc='upper left')
    ax2.tick_params(axis='x', labelsize=10, rotation=0)
    ax2.tick_params(axis='y', labelsize=10)
    ax2.set_ylim(0, 100)

    # Add panel letters outside the plot area
    fig.text(0.02, 0.98, 'A', fontsize=16, fontweight='bold', va='top', ha='left')
    fig.text(0.02, 0.48, 'B', fontsize=16, fontweight='bold', va='top', ha='left')

    # Set x-ticks to show every 2 years
    if len(pivot_df.index) > 10:
        ax2.set_xticks(range(0, len(pivot_df.index), 2))
        ax2.set_xticklabels(pivot_df.index[::2], rotation=45)

    plt.tight_layout()
    return fig


def plot_author_categories(author_category_stats, top_n=20, y_name='', group='category'):
    """
    Creates a static horizontal bar plot showing articles per category for top authors.

    Parameters:
    author_category_stats (pd.DataFrame): Pivot table from count_articles_by_groups
    top_n (int): Number of top authors to display

    Returns:
    matplotlib.figure.Figure
    """

    # Get top N authors by total and sort index in reverse order
    df_plot = author_category_stats.head(top_n).iloc[::-1]

    # Create figure and axis
    fig, ax = plt.subplots(figsize=(12, 8))

    # Define category order for Publindex categories
    category_order = ['A1', 'A2', 'B', 'C', 'D', 'No Disponible']

    # Check if this is Publindex category data or other grouped data
    columns_to_plot = [col for col in df_plot.columns if col != 'total']
    is_publindex_data = any(cat in columns_to_plot for cat in category_order)

    if is_publindex_data:
        # Reorder to match category order
        available_categories = [cat for cat in category_order if cat in columns_to_plot]
        colors = get_publindex_colors(available_categories)
        df_plot[available_categories].plot(kind='barh',
                                           stacked=True,
                                           ax=ax,
                                           width=0.8,
                                           color=colors)
    else:
        # Use generic categorical colors for other data (e.g., research groups)
        n_categories = len(columns_to_plot)
        colors = get_categorical_colors(n_categories)
        df_plot[columns_to_plot].plot(kind='barh',
                                      stacked=True,
                                      ax=ax,
                                      width=0.8,
                                      color=colors)

    # Customize plot
    ax.tick_params(axis='x', labelsize=11)
    ax.tick_params(axis='y', labelsize=11)
    plt.title(f'Top {top_n} {y_name} by {group}')
    plt.xlabel('Number of Articles', fontweight='bold', fontsize=12)
    plt.ylabel(f'{y_name}', fontweight='bold', fontsize=12)
    plt.legend(title=f'{group}', bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()

    return fig


def plot_top_authors_by_h_index(author_summary, top_n=20, metric='h_index',
                                name_column='author'):
    """
    Creates a static horizontal bar plot showing the top authors ranked by a
    bibliometric indicator (by default, the h-index retrieved from OpenAlex).

    Parameters:
    author_summary (pd.DataFrame): One row per author, with a metric column
        (e.g. output of `analysis.bibliometrics.build_author_summary`)
    top_n (int): Number of top authors to display
    metric (str): Column name to rank/plot (e.g. 'h_index', 'i10_index',
        'works_count', 'cited_by_count_total')
    name_column (str): Column with author names

    Returns:
    matplotlib.figure.Figure
    """
    df_plot = (
        author_summary
        .dropna(subset=[metric])
        .sort_values(metric, ascending=False)
        .head(top_n)
        .iloc[::-1]
    )

    fig, ax = plt.subplots(figsize=(10, 8))
    colors = get_categorical_colors(1)  # Always use first color for single category
    ax.barh(df_plot[name_column], df_plot[metric], color=colors[0])

    ax.tick_params(axis='x', labelsize=11)
    ax.tick_params(axis='y', labelsize=11)
    plt.title(f'Top {top_n} Authors by {metric.replace("_", " ").title()}')
    plt.xlabel(metric.replace('_', ' ').title(), fontweight='bold', fontsize=12)
    plt.ylabel('Author', fontweight='bold', fontsize=12)
    plt.tight_layout()

    return fig


def plot_top_authors_by_2yr_citedness(author_summary, top_n=20, 
                                     metric='2yr_mean_citedness',
                                     name_column='author'):
    """
    Creates a static horizontal bar plot showing the top authors ranked by 
    2-year mean citedness (average citations in the last 2 years).

    Parameters:
    author_summary (pd.DataFrame): One row per author, with 2yr_mean_citedness column
        (e.g. output of `analysis.bibliometrics.build_author_summary`)
    top_n (int): Number of top authors to display
    metric (str): Column name to rank/plot (default: '2yr_mean_citedness')
    name_column (str): Column with author names

    Returns:
    matplotlib.figure.Figure
    """
    df_plot = (
        author_summary
        .dropna(subset=[metric])
        .sort_values(metric, ascending=False)
        .head(top_n)
        .iloc[::-1]
    )

    fig, ax = plt.subplots(figsize=(10, 8))
    colors = get_categorical_colors(1)  # Always use first color for single category
    ax.barh(df_plot[name_column], df_plot[metric], color=colors[0])

    ax.tick_params(axis='x', labelsize=11)
    ax.tick_params(axis='y', labelsize=11)
    plt.title(f'Top {top_n} Authors by 2-Year Mean Citedness', fontweight='bold', fontsize=13)
    plt.xlabel('2-Year Mean Citedness', fontweight='bold', fontsize=12)
    plt.ylabel('Author', fontweight='bold', fontsize=12)
    plt.tight_layout()

    return fig


def plot_sankey_area_group(df, area_col='area', group_col='filename', top_n=10):
    """
    Creates a grouped bar plot showing distribution of articles from research groups to areas (top 10).
    This is a simplified alternative to Sankey diagram that doesn't require plotly.

    Parameters:
    df (pd.DataFrame): Input DataFrame with area and group columns
    area_col (str): Column name for areas
    group_col (str): Column name for research groups
    top_n (int): Number of top areas to include

    Returns:
    matplotlib.figure.Figure: The plot figure
    """
    # Prepare data
    df_clean = df[[group_col, area_col]].dropna()

    # Get top N areas by article count
    top_areas = df_clean[area_col].value_counts().head(top_n).index.tolist()
    df_clean = df_clean[df_clean[area_col].isin(top_areas)]

    # Count articles per group-area combination
    flow_counts = df_clean.groupby([group_col, area_col]).size().reset_index(name='count')

    # Pivot for grouped bar chart
    pivot_data = flow_counts.pivot(index=area_col, columns=group_col, values='count').fillna(0)

    # Sort by total
    pivot_data['total'] = pivot_data.sum(axis=1)
    pivot_data = pivot_data.sort_values('total', ascending=True).drop(columns='total')

    # Create figure
    fig, ax = plt.subplots(figsize=(14, 10))

    # Get colors for research groups
    n_groups = len(pivot_data.columns)
    colors = get_categorical_colors(n_groups)

    # Create grouped horizontal bars
    pivot_data.plot(kind='barh', ax=ax, width=0.8, color=colors)

    ax.set_xlabel('Number of Articles', fontweight='bold', fontsize=12)
    ax.set_ylabel('Area', fontweight='bold', fontsize=12)
    ax.set_title(f'Articles Distribution: Top {top_n} Areas by Research Group',
                 fontweight='bold', fontsize=14, pad=20)
    ax.legend(title='Research Group', bbox_to_anchor=(1.05, 1), loc='upper left')
    ax.tick_params(axis='both', labelsize=10)
    ax.grid(axis='x', alpha=0.3)

    plt.tight_layout()
    return fig


def plot_heatmap_granarea_group(df, granarea_col='gran_area', group_col='filename'):
    """
    Creates a heatmap showing the number of articles per gran_area and research group.

    Parameters:
    df (pd.DataFrame): Input DataFrame
    granarea_col (str): Column name for gran areas
    group_col (str): Column name for research groups

    Returns:
    matplotlib.figure.Figure: The plot figure
    """
    # Prepare data
    df_clean = df[[group_col, granarea_col]].dropna()

    # Create pivot table
    heatmap_data = df_clean.groupby([granarea_col, group_col]).size().unstack(fill_value=0)

    # Create heatmap
    fig, ax = plt.subplots(figsize=(12, 8))

    # Create custom colormap from institutional green palette
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list('institutional_green',
                                             PALETA_SECUENCIAL_VERDE)

    # Use seaborn for better-looking heatmap
    sns.heatmap(heatmap_data, annot=True, fmt='d', cmap=cmap,
                linewidths=0.5, cbar_kws={'label': 'Number of Articles'},
                ax=ax)

    ax.set_title('Articles by Gran Area and Research Group', fontweight='bold', fontsize=14, pad=20)
    ax.set_xlabel('Research Group', fontweight='bold', fontsize=12)
    ax.set_ylabel('Gran Area', fontweight='bold', fontsize=12)
    ax.tick_params(axis='x', labelsize=10, rotation=45)
    ax.tick_params(axis='y', labelsize=10, rotation=0)

    plt.tight_layout()
    return fig


def plot_treemap_granarea(df, granarea_col='gran_area', value_col=None):
    """
    Creates a treemap showing the distribution of articles by gran_area.
    Uses squarify library for treemap visualization.

    Parameters:
    df (pd.DataFrame): Input DataFrame
    granarea_col (str): Column name for gran areas
    value_col (str): Column to count (if None, counts rows)

    Returns:
    matplotlib.figure.Figure: The plot figure
    """
    import squarify
    
    # Prepare data
    if value_col:
        area_counts = df.groupby(granarea_col)[value_col].sum().sort_values(ascending=False)
    else:
        area_counts = df[granarea_col].value_counts()
    
    # Remove NaN
    area_counts = area_counts[area_counts.index.notna()]
    
    if area_counts.empty:
        # Return empty figure if no data
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.text(0.5, 0.5, 'No data available', ha='center', va='center')
        return fig
    
    # Prepare labels with counts and percentages
    total = area_counts.sum()
    labels = [f"{area}\n{count} ({count/total*100:.1f}%)" 
             for area, count in area_counts.items()]
    
    # Create figure
    fig, ax = plt.subplots(figsize=(14, 10))
    
    # Get colors
    n_areas = len(area_counts)
    colors = get_categorical_colors(n_areas)
    
    # Create treemap
    squarify.plot(sizes=area_counts.values, 
                 label=labels, 
                 color=colors,
                 alpha=0.8,
                 text_kwargs={'fontsize': 10, 'weight': 'bold'},
                 ax=ax)
    
    ax.set_title('Articles Distribution by Gran Area', 
                fontweight='bold', fontsize=14, pad=20)
    ax.axis('off')
    
    plt.tight_layout()
    return fig


def plot_language_distribution(df, language_col='language'):
    """
    Creates a donut chart showing the distribution of articles by publication language.

    Parameters:
    df (pd.DataFrame): Input DataFrame with language data
    language_col (str): Column name for language

    Returns:
    matplotlib.figure.Figure: The plot figure
    """
    # Prepare data
    df_clean = df[df[language_col].notna()].copy()

    if df_clean.empty:
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.text(0.5, 0.5, 'No language data available', ha='center', va='center')
        return fig

    # Count articles by language
    lang_counts = df_clean[language_col].value_counts()

    # Convert language codes to names (common ones)
    lang_names = {
        'en': 'English',
        'es': 'Spanish',
        'pt': 'Portuguese',
        'fr': 'French',
        'de': 'German',
        'it': 'Italian',
        'zh': 'Chinese',
        'ja': 'Japanese',
        'ru': 'Russian',
        'ar': 'Arabic',
    }

    lang_counts.index = [lang_names.get(code, code.upper()) for code in lang_counts.index]

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8))

    # Get colors
    n_langs = len(lang_counts)
    colors = get_categorical_colors(n_langs)

    # Create donut chart
    wedges, texts, autotexts = ax.pie(
        lang_counts.values,
        labels=lang_counts.index,
        autopct='%1.1f%%',
        colors=colors,
        startangle=90,
        wedgeprops=dict(width=0.5, edgecolor='white'),
        textprops={'fontsize': 11, 'weight': 'bold'}
    )

    # Improve percentage text readability
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontsize(10)

    # Add center text showing total articles
    total = lang_counts.sum()
    ax.text(0, 0, f'{total}\nArticles',
           ha='center', va='center', fontsize=16, fontweight='bold')

    ax.set_title('Articles Distribution by Language',
                fontweight='bold', fontsize=14, pad=20)

    plt.tight_layout()
    return fig


def plot_open_access_distribution(df, oa_col='is_oa'):
    """
    Creates a donut chart showing the distribution of Open Access vs Closed Access articles.

    Parameters:
    df (pd.DataFrame): Input DataFrame with OA data
    oa_col (str): Column name for Open Access status

    Returns:
    matplotlib.figure.Figure: The plot figure
    """
    # Prepare data
    df_clean = df[df[oa_col].notna()].copy()

    if df_clean.empty:
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.text(0.5, 0.5, 'No Open Access data available', ha='center', va='center')
        return fig

    # Convert to boolean if needed
    df_clean[oa_col] = df_clean[oa_col].astype(bool)

    # Count OA vs Closed - reorder to show Open Access first
    oa_counts = df_clean[oa_col].value_counts().reindex([True, False], fill_value=0)
    labels = ['Open Access' if val else 'Closed Access' for val in oa_counts.index]

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8))

    # Colors: institutional green for OA, institutional red for closed
    colors = [COLOR_VERDE_PRINCIPAL if val else COLOR_ROJO for val in oa_counts.index]

    # Create donut chart
    wedges, texts, autotexts = ax.pie(
        oa_counts.values,
        labels=labels,
        autopct='%1.1f%%',
        colors=colors,
        startangle=90,
        wedgeprops=dict(width=0.5, edgecolor='white'),
        textprops={'fontsize': 12, 'weight': 'bold'}
    )

    # Improve percentage text readability
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontsize(11)

    # Add center text showing total articles
    total = oa_counts.sum()
    ax.text(0, 0, f'{total}\nArticles',
           ha='center', va='center', fontsize=16, fontweight='bold')

    ax.set_title('Articles Distribution by Access Type',
                fontweight='bold', fontsize=14, pad=20)

    plt.tight_layout()
    return fig


def plot_countries_distribution(df, countries_col='openalex_countries', top_n=15):
    """
    Creates a horizontal bar chart showing the distribution of articles by country.

    Parameters:
    df (pd.DataFrame): Input DataFrame with countries data
    countries_col (str): Column name for countries (semicolon-separated)
    top_n (int): Number of top countries to display

    Returns:
    matplotlib.figure.Figure: The plot figure
    """
    # Prepare data - expand semicolon-separated countries
    all_countries = []
    for countries_str in df[countries_col].dropna():
        if countries_str:
            countries_list = [c.strip() for c in str(countries_str).split(';')]
            all_countries.extend(countries_list)

    if not all_countries:
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.text(0.5, 0.5, 'No country data available', ha='center', va='center')
        return fig

    # Count and get top countries
    import pandas as pd
    country_counts = pd.Series(all_countries).value_counts().head(top_n).iloc[::-1]

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8))

    colors = get_categorical_colors(1)
    ax.barh(country_counts.index, country_counts.values, color=colors[0])

    ax.set_xlabel('Number of Articles', fontweight='bold', fontsize=12)
    ax.set_ylabel('Country', fontweight='bold', fontsize=12)
    ax.set_title(f'Top {top_n} Countries by Articles',
                fontweight='bold', fontsize=14, pad=20)
    ax.tick_params(axis='both', labelsize=11)
    ax.grid(axis='x', alpha=0.3)

    plt.tight_layout()
    return fig


def plot_journals_analysis(df, journal_col='journal', citations_col='cited_by_count', top_n=20):
    """
    Creates a dual-axis plot showing:
    - Number of articles per journal (bars)
    - Total citations per journal (line)
    
    Parameters:
    df (pd.DataFrame): Input DataFrame with journal and citations data
    journal_col (str): Column name for journal names
    citations_col (str): Column name for citation counts
    top_n (int): Number of top journals to display

    Returns:
    matplotlib.figure.Figure: The plot figure
    """
    # Prepare data
    df_clean = df[[journal_col, citations_col]].copy()
    df_clean = df_clean[df_clean[journal_col].notna()]
    
    # Convert citations to numeric
    df_clean[citations_col] = pd.to_numeric(df_clean[citations_col], errors='coerce').fillna(0)
    
    # Group by journal
    journal_stats = df_clean.groupby(journal_col).agg({
        citations_col: ['count', 'sum']
    }).reset_index()
    journal_stats.columns = [journal_col, 'num_articles', 'total_citations']
    
    # Sort by number of articles and get top N
    journal_stats = journal_stats.sort_values('num_articles', ascending=False).head(top_n)
    journal_stats = journal_stats.iloc[::-1]  # Reverse for horizontal plot
    
    # Truncate long journal names
    journal_stats['journal_short'] = journal_stats[journal_col].apply(
        lambda x: (x[:50] + '...') if len(str(x)) > 50 else x
    )
    
    # Create figure with dual y-axis
    fig, ax1 = plt.subplots(figsize=(12, 10))
    
    colors = get_categorical_colors(2)
    
    # Plot number of articles (bars)
    ax1.barh(journal_stats['journal_short'], journal_stats['num_articles'], 
            color=colors[0], alpha=0.7, label='Number of Articles')
    ax1.set_xlabel('Number of Articles', fontweight='bold', fontsize=12)
    ax1.set_ylabel('Journal', fontweight='bold', fontsize=12)
    ax1.tick_params(axis='y', labelsize=9)
    ax1.tick_params(axis='x', labelsize=11, labelcolor=colors[0])
    
    # Create second y-axis for citations
    ax2 = ax1.twiny()
    ax2.plot(journal_stats['total_citations'], journal_stats['journal_short'], 
            marker='o', color=colors[1], linewidth=2, markersize=8, label='Total Citations')
    ax2.set_xlabel('Total Citations', fontweight='bold', fontsize=12, color=colors[1])
    ax2.tick_params(axis='x', labelsize=11, labelcolor=colors[1])
    ax2.grid(axis='x', alpha=0.3, linestyle='--')
    
    # Add legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='lower right', fontsize=10)
    
    plt.title(f'Top {top_n} Journals: Articles and Citations', 
             fontweight='bold', fontsize=14, pad=20)
    plt.tight_layout()
    
    return fig
