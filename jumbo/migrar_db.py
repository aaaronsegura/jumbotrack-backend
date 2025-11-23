import pandas as pd
import sqlite3
import os
import sys
from datetime import datetime, timedelta

# ==========================================
# ⚙️ REGLAS DE NEGOCIO (Adaptadas a lo que vi en tu Excel)
# ==========================================
# El sistema busca estas palabras dentro de la columna 'Rubro'
CONFIGURACION_VIDA_UTIL = {
    "YOGURT": 25,       
    "LECHE": 15,        
    "MANTEQUILLA": 60,  
    "QSO": 15,          # Para "QSO LAMINADO"
    "POSTRE": 12,       
    "HUEVO": 30,        
    "CAFE": 365,        # Duran 1 año
    "BEBIDA": 180,      # Para "BEBIDAS DE FANTASIA"
    "NECTAR": 180,      
    "TE": 365,          
    "SOPAS": 365,       
    "ACEITE": 365,      
    "POLLO": 7,         
    "CARNE": 7,         
    "CECINA": 10,
    "VIENESA": 10
}
# ==========================================

ARCHIVO_EXCEL = "productos.xls"
ARCHIVO_DB = "productos.db"

def log(msg):
    print(f"[MIGRACION] {msg}")

log(f"🚀 Iniciando Carga Inteligente (Específica para Hoja 2)...")

try:
    conn = sqlite3.connect(ARCHIVO_DB)
    cursor = conn.cursor()

    # 1. Limpieza total para recargar
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
        
        # --- ESTRATEGIA: IR DIRECTO A LA HOJA 2 ---
        # Tu archivo tiene 2 hojas. La importante es la segunda (índice 1).
        nombre_hoja = xl.sheet_names[0] # Por defecto
        if len(xl.sheet_names) > 1:
            nombre_hoja = xl.sheet_names[1] # Forzamos Hoja 2
        
        log(f"📄 Leyendo hoja objetivo: {nombre_hoja}")
        
        # Leemos todo como texto para evitar errores
        df = pd.read_excel(ARCHIVO_EXCEL, sheet_name=nombre_hoja, dtype=str)
        
        # Limpiamos nombres de columnas (quitamos espacios extra)
        df.columns = df.columns.str.strip()
        
        # Log para ver qué columnas detectó
        log(f"📊 Columnas encontradas: {list(df.columns)}")

        # Mapeo EXACTO basado en tus archivos
        mapa = {
            'Sección': 'seccion',                # P 10, P 09...
            'Rubro': 'rubro_temp',               # YOGURTS, LECHES...
            'SAP': 'sap', 
            'Código Barra Principal': 'ean',
            'nombre_producto': 'nombre', 
            # 'STOCK' puede tener nombres raros, lo manejamos abajo
            'Unidad de Medida Base (UMB)': 'umb', 
            'Precio Venta': 'precio', 
            'Imagen': 'imagen_url'
        }
        
        # Búsqueda inteligente de la columna STOCK (porque tiene un salto de línea raro)
        col_stock_real = [c for c in df.columns if 'STOCK' in c]
        if col_stock_real:
            mapa[col_stock_real[0]] = 'stock' # Usamos el nombre real encontrado

        # Normalizar DF
        df_clean = pd.DataFrame()
        for col_excel, col_db in mapa.items():
            if col_excel in df.columns:
                df_clean[col_db] = df[col_excel]
            else:
                # Si falta alguna columna no crítica, la dejamos vacía
                if col_db != 'rubro_temp': 
                    df_clean[col_db] = ""
                else:
                    log(f"⚠️ ATENCIÓN: No encuentro la columna exacta '{col_excel}'")

        # Limpiezas de datos
        if 'ean' in df_clean.columns:
            df_clean['ean'] = df_clean['ean'].str.replace(r'\.0$', '', regex=True).str.strip()
        if 'imagen_url' in df_clean.columns:
            df_clean['imagen_url'] = df_clean['imagen_url'].astype(str).str.strip()
        
        # Convertir Rubro a mayúsculas para comparar fácil
        if 'rubro_temp' in df_clean.columns:
            df_clean['rubro_temp'] = df_clean['rubro_temp'].astype(str).str.upper().str.strip()

        # A. Guardar Productos
        # Importante: Fillna para que no falle si hay celdas vacías
        df_final_prod = df_clean[['seccion', 'sap', 'ean', 'nombre', 'stock', 'umb', 'precio', 'imagen_url']].fillna('')
        data_prod = list(df_final_prod.itertuples(index=False, name=None))
        
        cursor.executemany('''INSERT OR REPLACE INTO productos 
            (seccion, sap, ean, nombre, stock, umb, precio, imagen_url) VALUES (?,?,?,?,?,?,?,?)''', data_prod)
        log(f"📦 {len(data_prod)} productos cargados correctamente.")

        # B. Generar Alarmas Automáticas
        hoy = datetime.now()
        alertas_generadas = 0

        if 'rubro_temp' in df_clean.columns:
            for index, row in df_clean.iterrows():
                rubro_producto = str(row['rubro_temp'])
                
                dias_vida_util = 0
                # Buscamos coincidencias (ej: si dice "LECHES LIQUIDAS", coincide con "LECHE")
                for clave, dias in CONFIGURACION_VIDA_UTIL.items():
                    if clave in rubro_producto: 
                        dias_vida_util = dias
                        break
                
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