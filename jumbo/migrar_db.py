import pandas as pd
import sqlite3
import os

# Configuración
ARCHIVO_EXCEL = "productos.xls"
ARCHIVO_DB = "productos.db"

print(f"🚀 Iniciando migración inteligente...")

try:
    # 1. Detectar la hoja correcta (la que tenga la columna 'Imagen')
    xl = pd.ExcelFile(ARCHIVO_EXCEL)
    hoja_correcta = None
    
    for hoja in xl.sheet_names:
        df_temp = pd.read_excel(ARCHIVO_EXCEL, sheet_name=hoja, nrows=1)
        if 'Imagen' in df_temp.columns or 'imagen' in df_temp.columns:
            hoja_correcta = hoja
            break
    
    if not hoja_correcta:
        # Si ninguna tiene 'Imagen', usamos la primera pero avisamos
        print("⚠️ ADVERTENCIA: No se encontró columna 'Imagen' en ninguna hoja. Usando la primera.")
        hoja_correcta = xl.sheet_names[0]
    
    print(f"📄 Usando hoja: '{hoja_correcta}'")
    
    # 2. Leer datos
    df = pd.read_excel(ARCHIVO_EXCEL, sheet_name=hoja_correcta, dtype=str)
    
    # 3. Limpieza de columnas (quitar espacios en nombres)
    df.columns = df.columns.str.strip()
    
    # 4. Mapeo de columnas
    mapa = {
        'Sección': 'seccion',
        'SAP': 'sap',
        'Código Barra Principal': 'ean',
        'nombre_producto': 'nombre',
        'STOCK \n11-09-2025': 'stock',
        'Unidad de Medida Base (UMB)': 'umb',
        'Precio Venta': 'precio',
        'Imagen': 'imagen_url'
    }
    
    # Crear columnas faltantes vacías para evitar errores
    for col_excel in mapa.keys():
        if col_excel not in df.columns:
            df[col_excel] = ""

    df = df.rename(columns=mapa)
    df_final = df[list(mapa.values())].copy()

    # Limpieza de valores
    df_final = df_final.fillna('')
    df_final['ean'] = df_final['ean'].str.replace(r'\.0$', '', regex=True).str.strip()
    df_final['sap'] = df_final['sap'].str.replace(r'\.0$', '', regex=True).str.strip()

    # 5. Guardar en SQLite
    conn = sqlite3.connect(ARCHIVO_DB)
    cursor = conn.cursor()
    
    # Recrear tabla productos
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
    
    # Insertar productos
    data = list(df_final.itertuples(index=False, name=None))
    cursor.executemany('''
        INSERT INTO productos (seccion, sap, ean, nombre, stock, umb, precio, imagen_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', data)
    
    # Asegurar tablas de sistema (Usuarios y Vencimientos)
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
    
    # Índices para velocidad
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ean ON productos (ean)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sap ON productos (sap)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nombre ON productos (nombre)")

    conn.commit()
    conn.close()
    print(f"✅ ¡ÉXITO! {len(df_final)} productos migrados a '{ARCHIVO_DB}'.")

except Exception as e:
    print(f"❌ ERROR FATAL: {e}")