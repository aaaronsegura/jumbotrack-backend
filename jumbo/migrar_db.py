import pandas as pd
import sqlite3
import os
import sys

# Configuración
ARCHIVO_EXCEL = "productos.xls"
ARCHIVO_DB = "productos.db"

def log(msg):
    print(f"[MIGRACION] {msg}")

log(f"🚀 Iniciando regeneración de base de datos...")

if not os.path.exists(ARCHIVO_EXCEL):
    log(f"❌ ERROR: No encuentro el archivo '{ARCHIVO_EXCEL}' en la carpeta actual.")
else:
    log("✅ Archivo Excel encontrado.")

try:
    conn = sqlite3.connect(ARCHIVO_DB)
    cursor = conn.cursor()

    # 1. ELIMINAR TABLAS VIEJAS (Para empezar limpio)
    cursor.execute("DROP TABLE IF EXISTS productos")
    
    # 2. CREAR TABLA PRODUCTOS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
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

    # 3. PROCESAR EXCEL (Si existe)
    if os.path.exists(ARCHIVO_EXCEL):
        xl = pd.ExcelFile(ARCHIVO_EXCEL)
        hoja_correcta = None
        
        # Buscar hoja con imágenes
        for hoja in xl.sheet_names:
            try:
                df_temp = pd.read_excel(ARCHIVO_EXCEL, sheet_name=hoja, nrows=1)
                cols = [str(c).strip() for c in df_temp.columns]
                if 'Imagen' in cols or 'imagen' in cols:
                    hoja_correcta = hoja
                    break
            except:
                continue
        
        if not hoja_correcta:
            hoja_correcta = xl.sheet_names[0] # Fallback a la primera
            log("⚠️ No se detectó columna Imagen, usando primera hoja.")

        log(f"📄 Leyendo hoja: {hoja_correcta}")
        
        df = pd.read_excel(ARCHIVO_EXCEL, sheet_name=hoja_correcta, dtype=str)
        df.columns = df.columns.str.strip()
        
        # Mapeo seguro
        mapa = {
            'Sección': 'seccion', 'SAP': 'sap', 'Código Barra Principal': 'ean',
            'nombre_producto': 'nombre', 'STOCK \n11-09-2025': 'stock',
            'Unidad de Medida Base (UMB)': 'umb', 'Precio Venta': 'precio', 'Imagen': 'imagen_url'
        }
        
        # Rellenar columnas faltantes
        for col in mapa.keys():
            if col not in df.columns:
                df[col] = ""
        
        df = df.rename(columns=mapa)
        df_final = df[list(mapa.values())].copy()
        df_final = df_final.fillna('')
        
        # Limpiar IDs
        df_final['ean'] = df_final['ean'].str.replace(r'\.0$', '', regex=True)
        df_final['sap'] = df_final['sap'].str.replace(r'\.0$', '', regex=True)

        # Insertar
        data = list(df_final.itertuples(index=False, name=None))
        cursor.executemany('''
            INSERT OR REPLACE INTO productos (seccion, sap, ean, nombre, stock, umb, precio, imagen_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', data)
        log(f"📦 Productos importados: {len(data)}")

    # 4. CREAR TABLA USUARIOS (Crucial para el registro)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')

    # 5. CREAR TABLA ALERTAS
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
    log("✅ Base de datos lista y actualizada.")

except Exception as e:
    log(f"❌ ERROR FATAL EN MIGRACIÓN: {e}")