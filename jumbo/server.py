import sqlite3
import os
import sys
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt 
from functools import wraps
from dotenv import load_dotenv 

# --- 1. CONFIGURACIÓN DE LOGGING (VITAL PARA DEPURAR) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv() 

# --- 2. CONFIGURACIÓN DE LA APP ---
app = Flask(__name__)
# CORS: Permite peticiones desde cualquier origen (ajustar para producción si es necesario)
CORS(app) 

DATABASE = 'productos.db'
# Clave secreta: Intenta leerla del entorno, si no, usa una por defecto y avisa
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'un-secreto-simple-para-pruebas')
if SECRET_KEY == 'un-secreto-simple-para-pruebas':
    logger.warning("⚠️ Usando clave secreta por defecto. Configura FLASK_SECRET_KEY en producción.")

app.config['SECRET_KEY'] = SECRET_KEY

# --- 3. AUTO-MIGRACIÓN AL INICIAR ---
def run_migration():
    if os.path.exists("migrar_db.py"):
        logger.info("🔄 Ejecutando auto-migración de base de datos...")
        try:
            exit_code = os.system("python migrar_db.py")
            if exit_code == 0:
                logger.info("✅ Migración completada exitosamente.")
            else:
                logger.error(f"❌ La migración falló con código de salida: {exit_code}")
        except Exception as e:
            logger.error(f"❌ Error crítico al intentar migrar: {e}")
    else:
        logger.warning("⚠️ No se encontró 'migrar_db.py'. Saltando migración.")

# Ejecutamos la migración antes de definir rutas
run_migration()

# --- 4. HELPER DE BASE DE DATOS ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        try:
            db = g._database = sqlite3.connect(DATABASE)
            db.row_factory = sqlite3.Row # Permite acceder a columnas por nombre
            # Activar Foreign Keys para integridad (buena práctica)
            db.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as e:
            logger.error(f"❌ Error conectando a la BD: {e}")
            return None
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- 5. DECORADOR DE SEGURIDAD ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # Estandarizamos: Buscamos en 'x-access-token' o 'Authorization'
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']
        
        if not token:
            return jsonify({'error': 'Token no encontrado. Inicia sesión.'}), 401

        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'El token ha expirado. Inicia sesión nuevamente.'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token inválido.'}), 401
        except Exception as e:
            logger.error(f"Error decodificando token: {e}")
            return jsonify({'error': 'Error de autenticación.'}), 401

        return f(current_user, *args, **kwargs)
    return decorated

# --- 6. RUTA DE SALUD (HEALTH CHECK) ---
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "online", "message": "JumboTrack API v10.0 funcionando correctamente"}), 200

# ==========================================
# RUTAS DE PRODUCTOS
# ==========================================

@app.route("/api/products/ean/<string:codigo>", methods=["GET"])
@token_required
def get_product_by_ean(current_user, codigo):
    codigo = codigo.strip()
    logger.info(f"🔎 Usuario {current_user.get('email')} buscó EAN/SAP: '{codigo}'")
    
    db = get_db()
    if not db: return jsonify({"error": "Error de base de datos"}), 500

    cur = db.cursor()
    cur.execute("SELECT * FROM productos WHERE ean = ? OR sap = ?", (codigo, codigo))
    row = cur.fetchone()
    
    if row:
        return jsonify(dict(row)) 
    
    return jsonify({"error": "Producto no encontrado"}), 404

@app.route("/api/products/search/<string:query>", methods=["GET"])
@token_required
def search_products(current_user, query):
    texto = query.strip().upper()
    if not texto: return jsonify([])
    
    db = get_db()
    if not db: return jsonify({"error": "Error de base de datos"}), 500

    cur = db.cursor()
    try:
        # Búsqueda por Nombre O por SAP
        cur.execute("SELECT * FROM productos WHERE UPPER(nombre) LIKE ? OR sap LIKE ? LIMIT 50", (f'%{texto}%', f'%{texto}%'))
        rows = cur.fetchall()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        logger.error(f"Error en búsqueda: {e}")
        return jsonify({"error": "Error al buscar productos"}), 500

# ==========================================
# SISTEMA DE ALERTAS (Lógica 15 Días)
# ==========================================

@app.route("/api/alerts", methods=['POST'])
@token_required
def add_alert(current_user):
    data = request.get_json()
    if not data or not data.get('fecha'):
        return jsonify({"error": "Falta la fecha de vencimiento"}), 400

    ean = data.get('ean', 'S/C')
    nombre = data.get('nombre', 'Producto Manual')
    fecha = data.get('fecha')
    email_usuario = current_user.get('email', 'desconocido')

    try:
        db = get_db()
        db.cursor().execute("""
            INSERT INTO vencimientos (ean, nombre_producto, fecha_vencimiento, usuario_email)
            VALUES (?, ?, ?, ?)
        """, (ean, nombre, fecha, email_usuario))
        db.commit()
        logger.info(f"🔔 Alerta creada por {email_usuario} para {nombre} ({fecha})")
        return jsonify({"mensaje": "Vencimiento registrado exitosamente"}), 201
    except Exception as e:
        logger.error(f"Error guardando alerta: {e}")
        return jsonify({"error": "No se pudo guardar la alerta"}), 500

@app.route("/api/alerts", methods=['GET'])
@token_required
def get_alerts(current_user):
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM vencimientos ORDER BY fecha_vencimiento ASC")
        rows = cur.fetchall()
        
        alertas_procesadas = []
        hoy = datetime.now().date()

        for row in rows:
            try:
                fecha_venc = datetime.strptime(row['fecha_vencimiento'], '%Y-%m-%d').date()
                dias = (fecha_venc - hoy).days
            except ValueError:
                dias = 999 # Fecha inválida, tratar como no urgente
                
            estado = "ok"
            mensaje = f"Faltan {dias} días"
            
            if dias < 0: 
                estado = "vencido"
                mensaje = f"Venció hace {abs(dias)} días"
            elif dias <= 15: 
                estado = "alerta" 
                mensaje = f"¡Vence en {dias} días!"

            alertas_procesadas.append({
                "id": row['id'], 
                "ean": row['ean'], 
                "nombre": row['nombre_producto'],
                "fecha": row['fecha_vencimiento'], 
                "usuario": row['usuario_email'],
                "dias_restantes": dias, 
                "estado": estado, 
                "mensaje_estado": mensaje
            })
        
        return jsonify(alertas_procesadas)
    except Exception as e:
        logger.error(f"Error obteniendo alertas: {e}")
        return jsonify({"error": "Error al obtener alertas"}), 500

# ==========================================
# AUTH (Usuarios)
# ==========================================

@app.route('/api/auth/register', methods=['POST'])
def register_user():
    data = request.get_json()
    
    # Validación básica de entrada
    if not data:
        return jsonify({"error": "No se recibieron datos"}), 400
        
    required_fields = ['nombre', 'email', 'password']
    if not all(field in data for field in required_fields):
        return jsonify({"error": f"Faltan datos requeridos: {required_fields}"}), 400

    try:
        password_hash = generate_password_hash(data['password'])
        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO usuarios (nombre, email, password_hash) VALUES (?, ?, ?)", 
                      (data['nombre'], data['email'], password_hash))
        db.commit()
        logger.info(f"👤 Nuevo usuario registrado: {data['email']}")
        return jsonify({"mensaje": "Usuario creado exitosamente"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "El email ya está registrado"}), 409
    except Exception as e:
        logger.error(f"Error en registro: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500

@app.route('/api/auth/login', methods=['POST'])
def login_user():
    data = request.get_json()
    
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Faltan credenciales"}), 400

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE email = ?", (data['email'],))
        user = cursor.fetchone()

        if user and check_password_hash(user['password_hash'], data['password']):
            token = jwt.encode({
                'id': user['id'],
                'nombre': user['nombre'],
                'email': user['email'],
                'exp': datetime.utcnow() + timedelta(days=30)
            }, app.config['SECRET_KEY'], algorithm="HS256")
            
            logger.info(f"🔑 Login exitoso: {data['email']}")
            return jsonify({
                "mensaje": "Login exitoso",
                "token": token,
                "usuario": {"nombre": user['nombre'], "email": user['email']}
            })
        
        logger.warning(f"Login fallido para: {data['email']}")
        return jsonify({"error": "Credenciales inválidas"}), 401
    except Exception as e:
        logger.error(f"Error en login: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500

@app.route("/api/users/me", methods=["GET"])
@token_required
def get_me(current_user):
    # Intentamos obtener datos frescos de la DB, si falla usamos el token
    try:
        db = get_db()
        user = db.cursor().execute("SELECT * FROM usuarios WHERE email = ?", (current_user['email'],)).fetchone()
        if user:
            return jsonify({
                "id": user['id'], 
                "nombre": user['nombre'], 
                "email": user['email']
            }), 200
    except Exception as e:
        logger.error(f"Error al obtener perfil fresco: {e}")
    
    # Fallback: devolver lo que venía en el token
    return jsonify({
        "id": current_user.get('id'),
        "nombre": current_user.get('nombre'),
        "email": current_user.get('email')
    }), 200

# --- MANEJO DE ERRORES GLOBAL ---
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Ruta no encontrada"}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Error interno del servidor"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    logger.info(f"🚀 Iniciando servidor en puerto {port}...")
    app.run(host="0.0.0.0", port=port)