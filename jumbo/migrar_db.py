import pandas as pd
import sqlite3
import os

# --- Configuración ---
ARCHIVO_EXCEL = "productos.xls"
ARCHIVO_DB = "productos.db"
HOJA = "Hoja2"  # <--- ¡CAMBIO IMPORTANTE! Antes decía "Hoja1"

print(f"🚀 Iniciando migración de '{ARCHIVO_EXCEL}' (Hoja: {HOJA}) a '{ARCHIVO_DB}'...")

try:
    # Leemos el Excel como texto
    df = pd.read_excel(ARCHIVO_EXCEL, sheet_name=HOJA, dtype=str)
    print(f"✅ Excel leído. Filas encontradas: {len(df)}")
except Exception as e:
    print(f"❌ ERROR al leer Excel: {e}")
    # Intenta listar las hojas disponibles para ayudar a depurar
    try:
        xl = pd.ExcelFile(ARCHIVO_EXCEL)
        print(f"   Hojas disponibles en el archivo: {xl.sheet_names}")
    except:
        pass
    exit()

print("🧹 Limpiando datos...")
df.columns = df.columns.str.strip()

# --- MAPEO DE COLUMNAS ---
column_mapping = {
    'Sección': 'seccion',
    'SAP': 'sap',
    'Código Barra Principal': 'ean',
    'nombre_producto': 'nombre',
    'STOCK \n11-09-2025': 'stock',
    'Unidad de Medida Base (UMB)': 'umb',
    'Precio Venta': 'precio',
    'Imagen': 'imagen_url' # Esta columna solo existe en la Hoja2
}

# Verificar columnas
missing_cols = []
for col_excel in column_mapping.keys():
    if col_excel not in df.columns:
        missing_cols.append(col_excel)

if missing_cols:
    print(f"⚠️ ADVERTENCIA CRÍTICA: No encuentro estas columnas en '{HOJA}': {missing_cols}")
    print(f"   Columnas encontradas: {list(df.columns)}")
else:
    print("✅ Todas las columnas encontradas, incluyendo 'Imagen'.")

# Renombrar y filtrar
# (Si alguna columna falta, esto fallaría, así que aseguramos que existan aunque sea vacías)
for col in missing_cols:
    df[col] = ""

df = df.rename(columns=column_mapping)
df_final = df[list(column_mapping.values())].copy()

# Limpieza
df_final['ean'] = df_final['ean'].str.replace(r'\.0$', '', regex=True).str.strip()
df_final['sap'] = df_final['sap'].str.replace(r'\.0$', '', regex=True).str.strip()
df_final = df_final.fillna('')

print(f"📦 Datos procesados: {len(df_final)} productos.")

try:
    conn = sqlite3.connect(ARCHIVO_DB)
    cursor = conn.cursor()
    
    # Reiniciar tabla productos
    cursor.execute("DROP TABLE IF EXISTS productos")
    cursor.execute('''
        CREATE TABLE productos (
            ean TEXT PRIMARY KEY,
            sap TEXT,
            nombre TEXT,
            seccion TEXT,
            stock TEXT,
            umb TEXT,
            precio TEXT,
            imagen_url TEXT,
            condicion_alimentaria TEXT DEFAULT 'Normal'
        )
    ''')
    
    # Insertar datos
    data_to_insert = list(df_final.itertuples(index=False, name=None))
    cursor.executemany('''
        INSERT INTO productos (seccion, sap, ean, nombre, stock, umb, precio, imagen_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', data_to_insert)

    # Índices
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ean ON productos (ean)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sap ON productos (sap)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nombre ON productos (nombre)")
    
    # Tablas adicionales (Usuarios y Vencimientos)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS vencimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ean TEXT,
        nombre_producto TEXT,
        fecha_vencimiento TEXT,
        usuario_email TEXT,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
    print("\n🎉 ¡MIGRACIÓN EXITOSA! Base de datos actualizada con Hoja 2.")

except Exception as e:
    print(f"❌ ERROR SQL: {e}")