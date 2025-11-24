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

# 1. CONFIGURACIÓN DE LOGS
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("JumboTrack")

load_dotenv() 

# 2. AUTO-MIGRACIÓN AL ARRANQUE
if os.path.exists("migrar_db.py"):
    logger.info("🔄 Ejecutando script de migración...")
    os.system("python migrar_db.py")

app = Flask(__name__)
CORS(app)
DATABASE = 'productos.db'
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'clave-secreta-dev')

# --- CONEXIÓN DB ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        try:
            db = g._database = sqlite3.connect(DATABASE)
            db.row_factory = sqlite3.Row 
        except Exception as e:
            logger.error(f"❌ Error conectando a DB: {e}")
            return None
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- SEGURIDAD ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']
        if not token:
            return jsonify({'error': 'Falta el token de acceso'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'El token ha expirado, inicia sesión de nuevo'}), 401
        except:
            return jsonify({'error': 'Token inválido'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

# --- RUTAS DE AUTENTICACIÓN (REGISTRO Y LOGIN) ---

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No se recibieron datos JSON"}), 400
        
    email = data.get('email')
    password = data.get('password')
    nombre = data.get('nombre', 'Usuario')

    if not email or not password:
        return jsonify({"error": "Faltan email o contraseña"}), 400

    try:
        pw_hash = generate_password_hash(password)
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute("INSERT INTO usuarios (nombre, email, password_hash) VALUES (?, ?, ?)", 
                      (nombre, email, pw_hash))
        db.commit()
        
        logger.info(f"✅ Usuario registrado: {email}")
        return jsonify({"mensaje": "Usuario creado exitosamente"}), 201

    except sqlite3.IntegrityError:
        logger.warning(f"⚠️ Intento de registro duplicado: {email}")
        return jsonify({"error": "El correo electrónico ya está registrado"}), 409
    except Exception as e:
        logger.error(f"❌ Error CRÍTICO en registro: {e}")
        return jsonify({"error": f"Error del servidor: {str(e)}"}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    try:
        db = get_db()
        user = db.cursor().execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
        
        if user and check_password_hash(user['password_hash'], password):
            token = jwt.encode({
                'id': user['id'],
                'nombre': user['nombre'],
                'email': user['email'],
                'exp': datetime.utcnow() + timedelta(days=30)
            }, app.config['SECRET_KEY'], algorithm="HS256")
            
            return jsonify({
                "mensaje": "Login exitoso", 
                "token": token, 
                "usuario": {
                    "id": user['id'], 
                    "nombre": user['nombre'], 
                    "email": user['email']
                }
            })
            
        return jsonify({"error": "Credenciales inválidas"}), 401
    except Exception as e:
        logger.error(f"Error en login: {e}")
        return jsonify({"error": "Error interno en login"}), 500

@app.route("/api/users/me", methods=["GET"])
@token_required
def me(current_user):
    return jsonify({
        "id": current_user.get('id'), 
        "nombre": current_user.get('nombre'), 
        "email": current_user.get('email')
    }), 200

# --- RUTAS DE PRODUCTOS ---

@app.route("/api/products/search/<string:query>", methods=["GET"])
@token_required
def search(current_user, query):
    texto = query.strip().upper()
    if not texto: return jsonify([])
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM productos WHERE UPPER(nombre) LIKE ? OR sap LIKE ? LIMIT 50", (f'%{texto}%', f'%{texto}%'))
        rows = cur.fetchall()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        logger.error(f"Error en búsqueda: {e}")
        return jsonify([])

@app.route("/api/products/ean/<string:codigo>", methods=["GET"])
@token_required
def ean(current_user, codigo):
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM productos WHERE ean = ? OR sap = ?", (codigo.strip(), codigo.strip()))
        row = cur.fetchone()
        if row: return jsonify(dict(row))
        return jsonify({"error": "No encontrado"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- RUTAS DE ALERTAS (15 DÍAS) ---

@app.route("/api/alerts", methods=['GET'])
@token_required
def get_alerts(current_user):
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM vencimientos ORDER BY fecha_vencimiento ASC")
        rows = cur.fetchall()
        
        alertas = []
        hoy = datetime.now().date()
        
        for row in rows:
            try:
                fecha_venc = datetime.strptime(row['fecha_vencimiento'], '%Y-%m-%d').date()
                dias = (fecha_venc - hoy).days
            except:
                dias = 999
            
            estado = "ok"
            mensaje = f"Faltan {dias} días"
            if dias < 0: 
                estado = "vencido"
                mensaje = f"Venció hace {abs(dias)} días"
            elif dias <= 15: 
                estado = "alerta"
                mensaje = f"¡Vence en {dias} días!"

            alertas.append({
                "id": row['id'], "ean": row['ean'], "nombre": row['nombre_producto'],
                "fecha": row['fecha_vencimiento'], "usuario": row['usuario_email'],
                "dias_restantes": dias, "estado": estado, "mensaje_estado": mensaje
            })
        return jsonify(alertas)
    except Exception as e:
        logger.error(f"Error alertas: {e}")
        return jsonify({"error": str(e)}), 500

# --- LÓGICA MEJORADA DE ALERTAS (ACTUALIZAR EN VEZ DE DUPLICAR) ---
@app.route("/api/alerts", methods=['POST'])
@token_required
def add_alert(current_user):
    data = request.get_json()
    
    fecha = data.get('fecha')
    ean = data.get('ean')
    nombre = data.get('nombre', 'Manual')
    
    if not fecha: 
        return jsonify({"error": "Falta fecha"}), 400

    try:
        db = get_db()
        cur = db.cursor()
        
        # 1. ¿Ya existe una alerta para este EAN?
        cur.execute("SELECT id FROM vencimientos WHERE ean = ?", (ean,))
        existing_alert = cur.fetchone()
        
        if existing_alert and ean != "S/C" and ean != "":
            # A. ACTUALIZAR (UPSERT)
            cur.execute('''
                UPDATE vencimientos 
                SET fecha_vencimiento = ?, nombre_producto = ?, usuario_email = ?
                WHERE id = ?
            ''', (fecha, nombre, current_user['email'], existing_alert['id']))
            mensaje_final = "Alerta actualizada correctamente"
            code = 200
        else:
            # B. CREAR NUEVA
            cur.execute('''
                INSERT INTO vencimientos (ean, nombre_producto, fecha_vencimiento, usuario_email) 
                VALUES (?, ?, ?, ?)
            ''', (ean, nombre, fecha, current_user['email']))
            mensaje_final = "Alerta creada exitosamente"
            code = 201

        db.commit()
        return jsonify({"mensaje": mensaje_final}), code
        
    except Exception as e:
        logger.error(f"Error guardando alerta: {e}")
        return jsonify({"error": str(e)}), 500

# --- INICIO ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    logger.info(f"🚀 Servidor V13 (Con Upsert) iniciando en puerto {port}")
    app.run(host="0.0.0.0", port=port)
