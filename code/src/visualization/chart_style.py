"""
Chart Style Configuration for INDICA Project

This module defines the institutional color palette validated for color blindness
(protanopia, deuteranopia, and tritanopia) and provides reusable color schemes
for all visualizations in the project.

Usage:
    from visualization.chart_style import PALETA_CATEGORICA, COLOR_GRIS_NEUTRO
"""

# =============================================================================
# INSTITUTIONAL COLOR PALETTE (validated for color blindness)
# =============================================================================

# --- Base colors ---
COLOR_VERDE_CLARO = "#8CCE6B"
COLOR_VERDE_PRINCIPAL = "#42A542"
COLOR_VERDE_OSCURO = "#107B42"
COLOR_AMARILLO = "#FFB703"
COLOR_AZUL = "#1F78B4"
COLOR_AZUL_CLARO = "#A6CEE3"
COLOR_ROJO = "#E31A1C"
COLOR_ROJO_CLARO = "#FB9A99"
COLOR_NARANJA = "#FF7F00"
COLOR_NARANJA_CLARO = "#FDBF6F"
COLOR_MORADO = "#6A3D9A"
COLOR_MORADO_CLARO = "#CAB2D6"
COLOR_GRIS_NEUTRO = "#5A5A5A"   # For "No Disponible" / missing data

# =============================================================================
# COLOR PALETTES FOR DIFFERENT CHART TYPES
# =============================================================================

# --- Sequential palette (for heatmaps or single continuous variable) ---
# Always safe for color blindness (single hue at different intensities)
PALETA_SECUENCIAL_VERDE = [COLOR_VERDE_CLARO, COLOR_VERDE_PRINCIPAL, COLOR_VERDE_OSCURO]

# --- Categorical palette (for comparing UP TO 4 different series/categories) ---
# Maximum separation under color blindness
PALETA_CATEGORICA = [COLOR_VERDE_PRINCIPAL, COLOR_NARANJA, COLOR_MORADO, COLOR_ROJO]

# --- Extended categorical palette (if a 5th category is needed) ---
PALETA_CATEGORICA_EXTENDIDA = PALETA_CATEGORICA + [COLOR_AZUL]

# --- Publindex categories palette ---
# For A1, A2, B, C, and "No Disponible"
PALETA_PUBLINDEX = {
    'A1': COLOR_VERDE_PRINCIPAL,
    'A2': COLOR_VERDE_CLARO,
    'B': COLOR_NARANJA,
    'C': COLOR_MORADO,
    'No Disponible': COLOR_GRIS_NEUTRO
}

# =============================================================================
# USAGE RULES (MANDATORY)
# =============================================================================
"""
1. NEVER use COLOR_AMARILLO and COLOR_NARANJA as categories in the same chart
   (they are almost indistinguishable under color blindness).

2. NEVER use COLOR_VERDE_CLARO and COLOR_MORADO as categories in the same chart.

3. TRY TO NEVER use COLOR_AZUL and COLOR_MORADO as categories in the same chart.

4. COLOR_VERDE_PRINCIPAL and COLOR_VERDE_OSCURO should ONLY be used TOGETHER
   as part of a sequential scale (same variable, different intensity) — never
   as two separate categories for different variables.

5. Any "No Disponible / unclassified / N/A" category MUST ALWAYS use
   COLOR_GRIS_NEUTRO, never a brand color.

6. Don't rely solely on color: add value labels directly on bars/cells
   whenever space permits.
"""

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_publindex_colors(categories):
    """
    Get colors for Publindex categories in the correct order.

    Parameters:
    categories (list): List of category names (e.g., ['A1', 'A2', 'B', 'C', 'No Disponible'])

    Returns:
    list: List of hex color codes matching the input categories
    """
    return [PALETA_PUBLINDEX.get(cat, COLOR_GRIS_NEUTRO) for cat in categories]


def get_categorical_colors(n_categories):
    """
    Get categorical colors for n categories.

    Parameters:
    n_categories (int): Number of categories (max 5)

    Returns:
    list: List of hex color codes
    """
    if n_categories <= 4:
        return PALETA_CATEGORICA[:n_categories]
    elif n_categories == 5:
        return PALETA_CATEGORICA_EXTENDIDA
    else:
        # For more than 5 categories, cycle through the extended palette
        return (PALETA_CATEGORICA_EXTENDIDA * ((n_categories // 5) + 1))[:n_categories]
