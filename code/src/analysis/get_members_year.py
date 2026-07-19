import re
import os
import glob
import datetime
import pandas as pd
import matplotlib.pyplot as plt
from collections import defaultdict

def generar_reporte_integrantes(archivo, nombre_grupo):
    """
    Genera un reporte de integrantes a partir de un archivo de texto.
    """

    # Carpeta destino: 'results' al mismo nivel que 'data'
    carpeta_data = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(archivo))))  # path_folder padre de 'data'
    carpeta_destino = os.path.join(carpeta_data, "results")
    os.makedirs(carpeta_destino, exist_ok=True)

    # Leer líneas del archivo
    with open(archivo, "r", encoding="utf-8") as f:
        lineas = f.readlines()

    # Paso 1: encontrar todos los años para determinar el último año real
    anios_detectados = []
    for linea in lineas:
        match_rango = re.search(r'(\d{4})/\d\s*-\s*(\d{4})/\d', linea)
        match_actual = re.search(r'(\d{4})/\d\s*-\s*Actual\b', linea)

        if match_rango:
            anios_detectados.extend([int(match_rango.group(1)), int(match_rango.group(2))])
        elif match_actual:
            anios_detectados.append(int(match_actual.group(1)))
    
    if not anios_detectados:
        print("No se detectaron años válidos.")
        return

    # Usar el año actual para usar como año_fin en los "Actual"
    anio_max = datetime.datetime.now().year

    # Paso 2: construir la tabla resumen
    datos = []
    for i, linea in enumerate(lineas, start=1):
        linea = linea.strip()

        match_rango = re.search(r'(\d{4})/(\d{1,2})\s*-\s*(\d{4})/(\d{1,2})', linea)
        match_actual = re.search(r'(\d{4})/(\d{1,2})\s*-\s*Actual\b', linea)
        match_solo_actual = re.search(r'-\s*Actual\b', linea)

        if match_rango:
            anio_inicio = int(match_rango.group(1))
            anio_fin = int(match_rango.group(3))
            activo = "Sí" if anio_inicio <= anio_max <= anio_fin else "No"
        elif match_actual:
            anio_inicio = int(match_actual.group(1))
            anio_fin = anio_max
            activo = "Sí"
        elif match_solo_actual:
            anio_inicio = "Desconocido"
            anio_fin = anio_max
            activo = "Sí"
        else:
            anio_inicio = "No detectado"
            anio_fin = "No detectado"
            activo = "No"

        datos.append({
            "Línea": i,
            "Texto": linea,
            "Año inicio": anio_inicio,
            "Año fin": anio_fin,
            "Activo en último año ({})".format(anio_max): activo
        })

    # Crear DataFrame
    df = pd.DataFrame(datos)

    # Guardar archivo CSV
    # csv_out = f"integrante_{nombre_grupo}_resumen_hasta{anio_max}.csv"
    # df.to_csv(csv_out, index=False)

    # Mostrar resumen de activos en último año
    activos = df[df[f"Activo en último año ({anio_max})"] == "Sí"]
    print(activos)
    print(f"\nTotal de integrantes activos en {nombre_grupo}: {len(activos)}")

    # Reconstruir el conteo de integrantes por año desde el DataFrame
    conteo_anios = defaultdict(int)

    for _, row in df.iterrows():
        inicio = row["Año inicio"]
        fin = row["Año fin"]

        if isinstance(inicio, int) and isinstance(fin, int):
            for anio in range(inicio, fin + 1):
                conteo_anios[anio] += 1

    # Ordenar los años
    anios = sorted(conteo_anios.keys())
    valores = [conteo_anios[a] for a in anios]

    # Detectar el último año presente en los datos
    anio_max = max(anios)

    # Colores del gráfico
    colores = ['#515151'] * len(anios)
    colores[anios.index(anio_max)] = '#019904' # Último año en verde

    # ---------------- Gráfico completo ----------------

    # Crear gráfico
    plt.figure(figsize=(12, 6))
    bars = plt.bar(anios, valores, color=colores)

    # Añadir etiquetas de valor a cada barra
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width() / 2, height + 0.05,
                str(height), ha ='center', va = 'bottom', fontsize = 9)

    # Ajuste para dejar espacio en la parte inferior
    plt.subplots_adjust(bottom = 0.3)

    # Anotación con flecha curva a la última barra (ligeramente a la izquierda)
    ultimo_x = anios[-1]
    ancho_barra = 0.8  # Valor por defecto de matplotlib
    desplazamiento = ancho_barra * 0.4  # Ajusta este valor si quieres más/menos desplazamiento

    plt.annotate(
        "Integrantes\nactivos",
        xy = (ultimo_x - desplazamiento, valores[-1]),
        xytext = (ultimo_x, valores[-1] + max(valores) * 0.075),
        arrowprops = dict(
            arrowstyle = '->',
            color = "#000000",
            lw = 1,
            connectionstyle = "arc3,rad = 0.3"
        ),
        ha = 'center',
        fontsize = 9,
        color = "#000000"
    )

    # Personalización de ejes y título
    plt.xlabel("Año", fontweight='bold')
    plt.ylabel("Número de integrantes activos", fontweight='bold')
    plt.title(f"{nombre_grupo}: Integrantes por año")
    plt.figtext(
        0.01,  # Posición horizontal (izquierda)
        0.01,  # Posición vertical (debajo del gráfico)
        "Datos para todos los miembros del grupo de investigación, no solo del programa",
        wrap=True,
        ha='left',
        fontsize=9,
    )
    plt.xticks(anios)
    plt.tight_layout()

    # Guardar como PDF (vectorial)
    plt.savefig(os.path.join(carpeta_destino, f"{nombre_grupo}_integrantes_hasta{anio_max}.pdf"), format="pdf")

    # ---------------- Gráfico últimos 5 años ----------------

    # Filtrar últimos 5 años
    ultimos_anios = anios[-5:]
    ultimos_valores = [conteo_anios[a] for a in ultimos_anios]
    ultimos_colores = ['#515151'] * 5
    ultimos_colores[-1] = '#019904'  # Último año automáticamente en verde

    # Crear gráfico
    plt.figure(figsize=(10, 5))
    bars5 = plt.bar(ultimos_anios, ultimos_valores, color=ultimos_colores)

    # Añadir etiquetas de valor a cada barra
    for bar in bars5:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width() / 2, height + 0.05,
                str(height), ha='center', va='bottom', fontsize=9)

    # Ajuste para dejar espacio en la parte inferior
    plt.subplots_adjust(bottom = 0.3)

    # Añadir etiquetas de valor a cada barra
    plt.xlabel("Año", fontweight='bold')
    plt.ylabel("Número de integrantes activos", fontweight='bold')
    plt.title(f"{nombre_grupo}: Últimos 5 años de vinculación")
    plt.figtext(
        0.01,  # Posición horizontal (izquierda)
        0.01,  # Posición vertical (debajo del gráfico)
        "Datos para todos los miembros del grupo de investigación, no solo del programa",
        wrap=True,
        ha='left',
        fontsize=9,
    )
    plt.xticks(ultimos_anios)
    plt.tight_layout()

    # Guardar como PDF (vectorial)
    plt.savefig(os.path.join(carpeta_destino, f"{nombre_grupo}_integrantes_ultimos5_hasta{anio_max}.pdf"), format="pdf")

    print(f"\n✅ Reporte generado para el grupo '{nombre_grupo}' hasta {anio_max}.")
    # print(f" - {csv_out}")
    print(f" - {nombre_grupo}_integrantes_hasta{anio_max}.pdf")
    print(f" - {nombre_grupo}_ultimos5_hasta{anio_max}.pdf")
    print(f"Los archivos se guardaron en: {carpeta_destino}")

# ---------------- Importar y procesar archivos de integrantes ----------------

# Ruta a la path_folder donde están los archivos .html
# CAMBIA ESTA RUTA según tu sistema
# Ejemplos:
# archivo = "C:/Users/TuUsuario/Downloads/CINBIOS_integrantes.html"
# archivo = "/Users/TuUsuario/Downloads/CINBIOS_integrantess.html"
# Asegúrate de que el archivo exista en la ruta especificada
carpeta = "/Users/ae.tafur/Documents/Training/09_tasks_professor/unicesar/05_comite_de_investigacion/indica/data/gruplac/data_blocks_gruplac"  # ← AJUSTA AQUÍ

# Buscar todos los archivos que terminan en "_integrantes.html"
archivos = glob.glob(os.path.join(carpeta, "*_integrantes.html"))

# Recorrer cada archivo encontrado
for ruta_archivo in archivos:
    # Extraer el nombre del archivo (sin path_folder)
    nombre_archivo = os.path.basename(ruta_archivo)
    
    # Extraer nombre del grupo: antes del "_integrantes.html"
    if "_integrantes.html" in nombre_archivo:
        nombre_grupo = nombre_archivo.replace("_integrantes.html", "")
        
        print(f"\n🔍 Procesando grupo: {nombre_grupo}")
        generar_reporte_integrantes(ruta_archivo, nombre_grupo)
    else:
        print(f"⚠️ Archivo con nombre inesperado: {nombre_archivo}")