import pandas as pd
import sqlite3
import os
import sys
from datetime import datetime, timedelta

# ==========================================
# ⚙️ REGLAS DE NEGOCIO (Buscaremos esto en el NOMBRE del producto)
# ==========================================
CONFIGURACION_VIDA_UTIL = {
    "YOGURT": 25,       
    "LECHE": 15,        
    "MANTEQUILLA": 60,  
    "QUESO": 15,        # Cubre "QUESO", "QSO", "QUESILLO"
    "QSO": 15,
    "POSTRE": 12,       
    "HUEVO": 30,        
    "CAFE": 365,        
    "BEBIDA": 180,      
    "COCA": 180,        # Por si dice Coca Cola
    "NECTAR": 180,      
    "JUGO": 180,
    "TE ": 365,         # Espacio para no confundir con palabras que terminan en te
    "SOPA": 365,       
    "CREMA": 60,
    "ACEITE": 365,      
    "POLLO": 7,         
    "CARNE": 7,         
    "CECINA": 10,
    "VIENESA": 10,
    "JAMON": 10,
    "TURKEY": 10,
    "SALAME": 30
}
# ==========================================

ARCHIVO_EXCEL = "productos.xls"
ARCHIVO_DB = "productos.db"

def log(msg):
    print(f"[MIGRACION] {msg}")

log(f"🚀 Iniciando Carga Inteligente (Estrategia: Análisis de NOMBRE)...")

try:
    conn = sqlite3.connect(ARCHIVO_DB)
    cursor = conn.cursor()

    # 1. Limpieza
    cursor.execute("DROP TABLE IF EXISTS productos")
    cursor.execute("DELETE FROM vencimientos WHERE usuario_email = 'sistema@jumbotrack.com'")
    
    # 2. Tablas
    cursor.execute('''CREATE TABLE IF NOT EXISTS productos (
        ean TEXT PRIMARY KEY, sap TEXT, nombre TEXT, seccion TEXT, stock TEXT, 
        umb TEXT, precio TEXT, imagen_url TEXT, condicion_alimentaria TEXT DEFAULT 'Normal')''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, email TEXT UNIQUE, password_hash TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS vencimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ean TEXT, nombre_producto TEXT, 
        fecha_vencimiento TEXT, usuario_email TEXT, creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # 3. Leer Excel
    if os.path.exists(ARCHIVO_EXCEL):
        xl = pd.ExcelFile(ARCHIVO_EXCEL)
        
        # Forzamos Hoja 2 (Donde están las fotos y nombres)
        nombre_hoja = xl.sheet_names[0]
        if len(xl.sheet_names) > 1:
            nombre_hoja = xl.sheet_names[1]
        
        log(f"📄 Leyendo hoja: {nombre_hoja}")
        df = pd.read_excel(ARCHIVO_EXCEL, sheet_name=nombre_hoja, dtype=str)
        df.columns = df.columns.str.strip()
        
        # Mapeo Hoja 2
        mapa = {
            'Sección': 'seccion', 
            'SAP': 'sap', 
            'Código Barra Principal': 'ean',
            'nombre_producto': 'nombre', # <--- ¡ESTE ES EL DATO CLAVE AHORA!
            'Unidad de Medida Base (UMB)': 'umb', 
            'Precio Venta': 'precio', 
            'Imagen': 'imagen_url'
        }
        
        # Búsqueda de Stock
        col_stock_real = [c for c in df.columns if 'STOCK' in c]
        if col_stock_real: mapa[col_stock_real[0]] = 'stock'

        # Normalizar
        df_clean = pd.DataFrame()
        for col_excel, col_db in mapa.items():
            if col_excel in df.columns:
                df_clean[col_db] = df[col_excel]
            else:
                df_clean[col_db] = ""

        # Limpiezas
        if 'ean' in df_clean.columns:
            df_clean['ean'] = df_clean['ean'].str.replace(r'\.0$', '', regex=True).str.strip()
        if 'imagen_url' in df_clean.columns:
            df_clean['imagen_url'] = df_clean['imagen_url'].astype(str).str.strip()
        if 'nombre' in df_clean.columns:
            df_clean['nombre'] = df_clean['nombre'].astype(str).str.upper().str.strip()

        # A. Guardar Productos
        data_prod = list(df_clean[['seccion', 'sap', 'ean', 'nombre', 'stock', 'umb', 'precio', 'imagen_url']].fillna('').itertuples(index=False, name=None))
        cursor.executemany('''INSERT OR REPLACE INTO productos 
            (seccion, sap, ean, nombre, stock, umb, precio, imagen_url) VALUES (?,?,?,?,?,?,?,?)''', data_prod)
        log(f"📦 {len(data_prod)} productos cargados.")

        # B. Generar Alarmas Automáticas (USANDO EL NOMBRE)
        hoy = datetime.now()
        alertas_generadas = 0

        for index, row in df_clean.iterrows():
            nombre_prod = str(row['nombre']) # Ej: "YOGURT BATIDO FRUTILLA"
            
            dias_vida_util = 0
            
            # Buscamos palabras clave en el nombre
            for clave, dias in CONFIGURACION_VIDA_UTIL.items():
                if clave in nombre_prod: # ¿Dice "YOGURT" en el nombre?
                    dias_vida_util = dias
                    # log(f"🔎 Encontré '{clave}' en '{nombre_prod}' -> {dias} días")
                    break
            
            if dias_vida_util > 0:
                fecha_vencimiento = (hoy + timedelta(days=dias_vida_util)).strftime('%Y-%m-%d')
                cursor.execute('''
                    INSERT INTO vencimientos (ean, nombre_producto, fecha_vencimiento, usuario_email)
                    VALUES (?, ?, ?, 'sistema@jumbotrack.com')
                ''', (row['ean'], row['nombre'], fecha_vencimiento))
                alertas_generadas += 1
        
        log(f"🤖 Lógica completada: {alertas_generadas} alertas creadas analizando NOMBRES.")

    conn.commit()
    conn.close()
    log("✅ Base de datos lista.")

except Exception as e:
    log(f"❌ Error crítico: {e}")
