import pandas as pd
import sqlite3
import os

# --- Configuración ---
ARCHIVO_EXCEL = "productos.xls"
ARCHIVO_DB = "productos.db"
HOJA = "Hoja1"

print(f"🚀 Iniciando migración de '{ARCHIVO_EXCEL}' a '{ARCHIVO_DB}'...")

try:
    # Leemos el Excel como texto (dtype=str) para evitar errores de formato
    df = pd.read_excel(ARCHIVO_EXCEL, sheet_name=HOJA, dtype=str)
    print(f"✅ Excel leído. Filas encontradas: {len(df)}")
except Exception as e:
    print(f"❌ ERROR al leer Excel: {e}")
    exit()

print("🧹 Limpiando datos...")
df.columns = df.columns.str.strip()

# --- MAPEO DE COLUMNAS (Excel -> Base de Datos) ---
# Ajusta los nombres de la izquierda si tu Excel cambia
column_mapping = {
    'Sección': 'seccion',           # Usaremos esto como "Pasillo" o Ubicación
    'SAP': 'sap',
    'Código Barra Principal': 'ean',
    'nombre_producto': 'nombre',
    'STOCK \n11-09-2025': 'stock',  # Asegúrate que este nombre sea EXACTO al del Excel
    'Unidad de Medida Base (UMB)': 'umb',
    'Precio Venta': 'precio',
    'Imagen': 'imagen_url'
}

# Verificar que las columnas existan
for col_excel in column_mapping.keys():
    if col_excel not in df.columns:
        print(f"⚠️ ADVERTENCIA: No encuentro la columna '{col_excel}' en el Excel.")
        # Podríamos crear la columna vacía para que no falle
        df[col_excel] = None

# Renombramos las columnas del DataFrame a las de la DB
df = df.rename(columns=column_mapping)

# Seleccionamos solo las columnas que nos interesan
columnas_finales = list(column_mapping.values())
df_final = df[columnas_finales].copy()

# Limpieza específica
df_final['ean'] = df_final['ean'].str.replace(r'\.0$', '', regex=True).str.strip()
df_final['sap'] = df_final['sap'].str.replace(r'\.0$', '', regex=True).str.strip()

# Rellenar vacíos
df_final = df_final.fillna('')

print(f"📦 Datos listos para guardar. Filas válidas: {len(df_final)}")

try:
    conn = sqlite3.connect(ARCHIVO_DB)
    cursor = conn.cursor()
    
    # 1. Tabla PRODUCTOS (Desde Excel)
    # Borramos y recreamos para asegurar la estructura nueva
    cursor.execute("DROP TABLE IF EXISTS productos")
    
    # Creamos la tabla con la estructura nueva
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
    
    # Insertamos los datos
    # Nota: 'condicion_alimentaria' la dejamos pendiente o la calculamos si tienes reglas
    for _, row in df_final.iterrows():
        cursor.execute('''
            INSERT INTO productos (ean, sap, nombre, seccion, stock, umb, precio, imagen_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (row['ean'], row['sap'], row['nombre'], row['seccion'], row['stock'], row['umb'], row['precio'], row['imagen_url']))

    # Índices para búsqueda rápida
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ean ON productos (ean)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sap ON productos (sap)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nombre ON productos (nombre)")
    
    print("✅ Tabla 'productos' actualizada con IMÁGENES y SAP.")

    # 2. Tabla USUARIOS (Se mantiene igual, pero aseguramos que exista)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    ''')
    print("✅ Tabla 'usuarios' verificada.")

    # 3. NUEVA TABLA: VENCIMIENTOS (Para las alertas manuales)
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
    print("✅ Tabla 'vencimientos' (Sistema de Alertas) lista.")

    conn.commit()
    conn.close()
    print("\n🎉 ¡MIGRACIÓN EXITOSA! La base de datos está lista.")

except Exception as e:
    print(f"❌ ERROR CRÍTICO en la base de datos: {e}")