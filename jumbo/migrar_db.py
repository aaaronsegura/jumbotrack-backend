import pandas as pd
import sqlite3
import os

# --- Configuración ---
ARCHIVO_EXCEL = "productos.xls"
ARCHIVO_DB = "productos.db"
HOJA = "Hoja1"

# Nombres exactos de tus columnas en el Excel
COL_EAN = 'Código Barra Principal'
COL_PRODUCTO = 'nombre_producto'

print(f"  Iniciando migración de '{ARCHIVO_EXCEL}' a '{ARCHIVO_DB}'...")

try:
    # Leemos todo como texto para evitar problemas de formato iniciales
    df = pd.read_excel(ARCHIVO_EXCEL, sheet_name=HOJA, dtype=str)
    print(f"  Excel leído. Filas encontradas: {len(df)}")
except Exception as e:
    print(f"  ERROR al leer Excel: {e}")
    exit()

print("🧹 Limpiando datos...")
df.columns = df.columns.str.strip()

if COL_EAN not in df.columns or COL_PRODUCTO not in df.columns:
    print(f"  ERROR: No encuentro las columnas '{COL_EAN}' o '{COL_PRODUCTO}'")
    exit()

# Limpieza profunda de EAN y Nombres
# Quitamos '.0', espacios, y convertimos vacíos a None
df['ean_limpio'] = df[COL_EAN].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
df['ean_limpio'] = df['ean_limpio'].replace({'nan': None, 'None': None, '<NA>': None, '': None})

df['producto_limpio'] = df[COL_PRODUCTO].astype(str).str.strip()
df['producto_limpio'] = df['producto_limpio'].replace({'nan': None, 'None': None, '<NA>': None, '': None})

# Eliminamos filas que no tengan EAN o Nombre válido
df_final = df.dropna(subset=['ean_limpio', 'producto_limpio'])
print(f"  Datos limpios. Filas válidas: {len(df_final)}")

print(f"  Guardando en '{ARCHIVO_DB}'...")
try:
    conn = sqlite3.connect(ARCHIVO_DB)
    df_final.to_sql('productos', conn, if_exists='replace', index=False)
    
    # Índices para velocidad
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ean ON productos (ean_limpio)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nombre ON productos (producto_limpio)")
    conn.commit()
    conn.close()
    print("\n ¡MIGRACIÓN EXITOSA! ")
except Exception as e:
    print(f" ERROR al guardar en DB: {e}")