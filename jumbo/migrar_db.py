import pandas as pd
import sqlite3
import os
import sys
from datetime import datetime, timedelta

# ==========================================
# ⚙️ REGLAS BASADAS EN TU COLUMNA "RUBRO" (Visto en la foto)
# ==========================================
CONFIGURACION_VIDA_UTIL = {
    "YOGURT": 25,       # Vimos "YOGURTS" en la foto
    "LECHE": 15,        # Vimos "LECHES LIQUIDAS"
    "MANTEQUILLA": 60,  # Vimos "MANTEQUILLAS"
    "QSO": 15,          # Vimos "QSO LAMINADO"
    "POSTRE": 12,       # Vimos "POSTRES REFRIGERAD"
    "HUEVO": 30,        # Vimos "HUEVOS"
    "FIAMBRE": 10,      # Regla general
    "POLLO": 7,         # Regla general
    "CARNE": 7          # Regla general
}
# ==========================================

ARCHIVO_EXCEL = "productos.xls"
ARCHIVO_DB = "productos.db"

def log(msg):
    print(f"[MIGRACION] {msg}")

log(f"🚀 Iniciando Carga Inteligente (Rubro -> Vencimiento)...")

try:
    conn = sqlite3.connect(ARCHIVO_DB)
    cursor = conn.cursor()

    # 1. Limpieza
    cursor.execute("DROP TABLE IF EXISTS productos")
    cursor.execute("DELETE FROM vencimientos WHERE usuario_email = 'sistema@jumbotrack.com'")
    
    # 2. Crear Tablas
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
        # Buscar hoja correcta
        hoja_correcta = xl.sheet_names[0]
        for hoja in xl.sheet_names:
            df_temp = pd.read_excel(ARCHIVO_EXCEL, sheet_name=hoja, nrows=1)
            cols = [str(c).strip().lower() for c in df_temp.columns]
            if 'rubro' in cols or 'imagen' in cols: # Buscamos RUBRO o IMAGEN
                hoja_correcta = hoja
                break
        
        log(f"📄 Usando hoja: {hoja_correcta}")
        df = pd.read_excel(ARCHIVO_EXCEL, sheet_name=hoja_correcta, dtype=str)
        df.columns = df.columns.str.strip()

        # --- MAPEO INTELIGENTE ---
        # "Sección" del Excel -> "seccion" en DB (Para ver el Pasillo P 10)
        # "Rubro" del Excel -> variable temporal para calcular alarmas
        mapa = {
            'Sección': 'seccion', 
            'Rubro': 'rubro_temp', # <--- AQUÍ LEEMOS TU COLUMNA RUBRO
            'SAP': 'sap', 
            'Código Barra Principal': 'ean',
            'nombre_producto': 'nombre', 
            'STOCK \n11-09-2025': 'stock',
            'Unidad de Medida Base (UMB)': 'umb', 
            'Precio Venta': 'precio', 
            'Imagen': 'imagen_url'
        }
        
        # Normalizar DF
        df_clean = pd.DataFrame()
        for col_excel, col_db in mapa.items():
            if col_excel in df.columns:
                df_clean[col_db] = df[col_excel]
            else:
                df_clean[col_db] = ""

        # Limpiezas
        df_clean['ean'] = df_clean['ean'].str.replace(r'\.0$', '', regex=True).str.strip()
        if 'imagen_url' in df_clean.columns:
            df_clean['imagen_url'] = df_clean['imagen_url'].astype(str).str.strip()
        
        # Convertimos Rubro a mayúsculas para comparar fácil (YOGURTS vs Yogurt)
        if 'rubro_temp' in df_clean.columns:
            df_clean['rubro_temp'] = df_clean['rubro_temp'].astype(str).str.upper().str.strip()

        # A. Insertar Productos (Guardamos el Pasillo P 10 en 'seccion')
        data_prod = list(df_clean[['seccion', 'sap', 'ean', 'nombre', 'stock', 'umb', 'precio', 'imagen_url']].fillna('').itertuples(index=False, name=None))
        cursor.executemany('''INSERT OR REPLACE INTO productos 
            (seccion, sap, ean, nombre, stock, umb, precio, imagen_url) VALUES (?,?,?,?,?,?,?,?)''', data_prod)
        log(f"📦 {len(data_prod)} productos cargados.")

        # B. Generar Alarmas Automáticas USANDO RUBRO
        hoy = datetime.now()
        alertas_generadas = 0

        for index, row in df_clean.iterrows():
            rubro_producto = str(row['rubro_temp']) # Ej: "LECHES LIQUIDAS"
            
            dias_vida_util = 0
            # Buscamos coincidencias (ej: si "LECHE" está dentro de "LECHES LIQUIDAS")
            for clave, dias in CONFIGURACION_VIDA_UTIL.items():
                if clave in rubro_producto: 
                    dias_vida_util = dias
                    break
            
            # Si encontramos regla, creamos alarma
            if dias_vida_util > 0:
                fecha_vencimiento = (hoy + timedelta(days=dias_vida_util)).strftime('%Y-%m-%d')
                
                cursor.execute('''
                    INSERT INTO vencimientos (ean, nombre_producto, fecha_vencimiento, usuario_email)
                    VALUES (?, ?, ?, 'sistema@jumbotrack.com')
                ''', (row['ean'], row['nombre'], fecha_vencimiento))
                alertas_generadas += 1

        log(f"🤖 Lógica completada: {alertas_generadas} alertas creadas basadas en RUBRO.")

    conn.commit()
    conn.close()
    log("✅ Base de datos lista.")

except Exception as e:
    log(f"❌ Error crítico: {e}")