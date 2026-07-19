import os
import pandas as pd
import matplotlib.pyplot as plt

carpeta_data = '/Users/ae.tafur/Documents/Training/09_tasks_professor/unicesar/05_comite_de_investigacion/indica'
carpeta_destino = os.path.join(carpeta_data, 'results')
# Read the CSV file
df = pd.read_csv(os.path.join(carpeta_data, 'data/semilleros/data_semilleros.csv'))

# Plot the data
plt.figure(figsize = (8, 5))
plt.plot(df['year'], df['members'],
         marker='o',
         markersize = 8,
         color = '#019904',
         linewidth = 2)
plt.xlabel('Año', fontweight='bold')
plt.ylabel('Integrantes', fontweight='bold')
plt.title('Historico Integrantes Semilleros - Microbiología')
plt.tight_layout()

# Guardar como PDF (vectorial)
plt.savefig(os.path.join(carpeta_destino, "historico_integrantes_semilleros.pdf"), format="pdf")

plt.show()