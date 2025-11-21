import sqlite3
import os
import datetime
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
# --- CORRECCIÓN CLAVE: Importamos PyJWT pero lo usamos como jwt ---
import jwt 
from functools import wraps
from dotenv import load_dotenv 

# Cargar variables de entorno (si existen)
load_dotenv() 

app = Flask(__name__)
CORS(app)
DATABASE = 'productos.db'

# Usar una clave secreta segura (o una por defecto para desarrollo)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'un-secreto-simple-para-pruebas-locales')

# ==========================================
# CONEXIÓN A BASE DE DATOS
# ==========================================

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        # Esto permite acceder a las columnas por nombre (ej: row['nombre'])
        db.row_factory = sqlite3.Row 
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ==========================================
# DECORADOR DE SEGURIDAD (TOKEN REQUIRED)
# ==========================================

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # La app envía el token en este header específico
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']

        if not token:
            return jsonify({'error': 'Token no encontrado'}), 401

        try:
            # Decodificamos el token
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'El token ha expirado'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token inválido'}), 401

        return f(current_user, *args, **kwargs)
    return decorated

# ==========================================
# RUTAS DE PRODUCTOS (BUSCADOR Y ESCÁNER)
# ==========================================

@app.route("/api/products/ean/<string:codigo>", methods=["GET"])
@token_required
def get_product_by_ean(current_user, codigo):
    # Esta ruta busca por EAN (código de barras) o por SAP
    codigo = codigo.strip()
    print(f"🔎 Buscando EAN/SAP: '{codigo}' (Usuario: {current_user['email']})")
    
    cur = get_db().cursor()
    # Buscamos coincidencia exacta en cualquiera de las dos columnas
    cur.execute("SELECT * FROM productos WHERE ean = ? OR sap = ?", (codigo, codigo))
    row = cur.fetchone()
    
    if row:
        prod = dict(row)
        # Construimos la respuesta con TODOS los campos nuevos
        response = {
            "nombre": prod.get("nombre", "Sin Nombre"),
            "ean": prod.get("ean", "N/A"),
            "sap": prod.get("sap", "N/A"),
            "precio": prod.get("precio", "0"),
            "stock": prod.get("stock", "0"),
            "ubicacion": prod.get("seccion", "General"), # Mapeamos 'Sección' a 'Ubicación'
            "umb": prod.get("umb", "UN"),
            "imagen_url": prod.get("imagen_url", ""), # URL de la imagen
            "condicion": prod.get("condicion_alimentaria", "Normal")
        }
        print(f"✅ ENVIANDO: {response['nombre']}")
        return jsonify(response)
    else:
        print("❌ NO ENCONTRADO")
        return jsonify({"error": "Producto no encontrado"}), 404

@app.route("/api/products/search/<string:query>", methods=["GET"])
@token_required
def search_products(current_user, query):
    # Buscador de texto
    texto = query.strip().upper()
    print(f"🔎 Buscando texto: '{texto}'")
    
    if not texto: return jsonify([])
    
    cur = get_db().cursor()
    
    # Búsqueda inteligente: Por Nombre (contiene) O por SAP (contiene)
    cur.execute("""
        SELECT * FROM productos 
        WHERE UPPER(nombre) LIKE ? OR sap LIKE ? 
        LIMIT 50
    """, (f'%{texto}%', f'%{texto}%'))
    
    rows = cur.fetchall()
    lista_limpia = []
    
    for row in rows:
        prod = dict(row)
        lista_limpia.append({
            "nombre": prod.get("nombre", "Sin Nombre"),
            "ean": prod.get("ean", "N/A"),
            "sap": prod.get("sap", "N/A"),
            "precio": prod.get("precio", "0"),
            "stock": prod.get("stock", "0"),
            "ubicacion": prod.get("seccion", "General"),
            "umb": prod.get("umb", "UN"),
            "imagen_url": prod.get("imagen_url", ""),
            "condicion": prod.get("condicion_alimentaria", "Normal")
        })
        
    print(f"✅ Resultados encontrados: {len(lista_limpia)}")
    return jsonify(lista_limpia)

# ==========================================
# RUTAS DE ALERTAS (SISTEMA NUEVO)
# ==========================================

# 1. Guardar un vencimiento (POST)
@app.route("/api/alerts", methods=['POST'])
@token_required
def add_alert(current_user):
    data = request.get_json()
    # Esperamos recibir: { "ean": "...", "nombre": "...", "fecha": "YYYY-MM-DD" }
    
    if not data or not data.get('fecha'):
        return jsonify({"error": "Falta la fecha de vencimiento"}), 400

    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO vencimientos (ean, nombre_producto, fecha_vencimiento, usuario_email)
            VALUES (?, ?, ?, ?)
        """, (
            data.get('ean', 'S/C'), 
            data.get('nombre', 'Producto Manual'), 
            data.get('fecha'), 
            current_user['email'] # Guardamos quién creó la alerta
        ))
        db.commit()
        return jsonify({"mensaje": "Vencimiento registrado exitosamente"}), 201
    except Exception as e:
        return jsonify({"error": f"Error al guardar alerta: {str(e)}"}), 500

# 2. Leer lista de vencimientos (GET)
@app.route("/api/alerts", methods=['GET'])
@token_required
def get_alerts(current_user):
    # Devuelve la lista de productos ordenados por fecha de vencimiento
    cur = get_db().cursor()
    cur.execute("SELECT * FROM vencimientos ORDER BY fecha_vencimiento ASC")
    rows = cur.fetchall()
    
    alertas = []
    for row in rows:
        alertas.append({
            "id": row['id'],
            "ean": row['ean'],
            "nombre": row['nombre_producto'],
            "fecha": row['fecha_vencimiento'],
            "usuario": row['usuario_email']
        })
    return jsonify(alertas)

# ==========================================
# RUTAS DE USUARIO (AUTH)
# ==========================================

@app.route('/api/auth/register', methods=['POST'])
def register_user():
    data = request.get_json()
    
    if not data or not data.get('nombre') or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Faltan datos (nombre, email, password)"}), 400

    nombre = data.get('nombre')
    email = data.get('email')
    password = data.get('password')

    # Hashear la contraseña
    password_hash = generate_password_hash(password)

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO usuarios (nombre, email, password_hash) VALUES (?, ?, ?)",
            (nombre, email, password_hash)
        )
        db.commit()
        user_id = cursor.lastrowid
        
        return jsonify({
            "mensaje": "Usuario registrado exitosamente",
            "usuario": {
                "id": user_id,
                "nombre": nombre,
                "email": email
            }
        }), 201

    except sqlite3.IntegrityError:
        return jsonify({"error": "El email ya está registrado"}), 409
    except Exception as e:
        return jsonify({"error": f"Error en el servidor: {str(e)}"}), 500

@app.route('/api/auth/login', methods=['POST'])
def login_user():
    data = request.get_json()

    if not data or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Faltan datos (email, password)"}), 400

    email = data.get('email')
    password = data.get('password')

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
        usuario_encontrado = cursor.fetchone()

        if usuario_encontrado is None:
            return jsonify({"error": "Credenciales inválidas"}), 401

        usuario = dict(usuario_encontrado)

        if not check_password_hash(usuario['password_hash'], password):
            return jsonify({"error": "Credenciales inválidas"}), 401

        # --- LOGIN EXITOSO: Generar Token ---
        token = jwt.encode(
            {
                'id': usuario['id'],
                'nombre': usuario['nombre'],
                'email': usuario['email'],
                # Token expira en 30 días
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=30) 
            },
            app.config['SECRET_KEY'],
            algorithm="HS256"
        )

        return jsonify({
            "mensaje": "Login exitoso",
            "usuario": {
                "id": usuario['id'],
                "nombre": usuario['nombre'],
                "email": usuario['email']
            },
            "token": token
        }), 200

    except Exception as e:
        return jsonify({"error": f"Error en el servidor: {str(e)}"}), 500

@app.route("/api/users/me", methods=["GET"])
@token_required
def get_user(current_user):
    # Esta ruta devuelve los datos del usuario logueado
    print(f"👤 Petición de Perfil para: {current_user['email']}")
    return jsonify({
        "id": current_user['id'],
        "nombre": current_user['nombre'], # Clave corregida: 'nombre' (no 'name')
        "email": current_user['email']
    }), 200

# --- INICIADOR DEL SERVIDOR ---

if __name__ == "__main__":
    # Render asigna el puerto en la variable de entorno PORT
    port = int(os.environ.get("PORT", 3000))
    print(f"🚀 Servidor listo en http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
    # v5: Actualización final con PyJWT corregido
