import sqlite3
import os
import datetime
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt 
from functools import wraps
from dotenv import load_dotenv 

load_dotenv() 

app = Flask(__name__)
CORS(app)
DATABASE = 'productos.db'

app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'un-secreto-simple')

# --- DB HELPER ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row 
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- DECORADOR DE SEGURIDAD ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']
        if not token:
            return jsonify({'error': 'Token no encontrado'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data
        except:
            return jsonify({'error': 'Token inválido o expirado'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

# ==========================================
# RUTAS DE PRODUCTOS (ACTUALIZADAS)
# ==========================================

@app.route("/api/products/ean/<string:codigo>", methods=["GET"])
@token_required
def get_product_by_ean(current_user, codigo):
    codigo = codigo.strip()
    print(f"🔎 Buscando EAN/SAP: '{codigo}'")
    cur = get_db().cursor()
    
    # Buscamos por EAN o por SAP
    cur.execute("SELECT * FROM productos WHERE ean = ? OR sap = ?", (codigo, codigo))
    row = cur.fetchone()
    
    if row:
        prod = dict(row)
        # Construimos la respuesta con los NUEVOS campos del Excel
        response = {
            "nombre": prod.get("nombre", "Sin Nombre"),
            "ean": prod.get("ean", "N/A"),
            "sap": prod.get("sap", "N/A"),
            "precio": prod.get("precio", "0"),
            "stock": prod.get("stock", "0"),
            "ubicacion": prod.get("seccion", "General"), # Mapeamos 'Sección' a 'Ubicación/Pasillo'
            "umb": prod.get("umb", "UN"),
            "imagen_url": prod.get("imagen_url", ""), # URL de la imagen
            "condicion": prod.get("condicion_alimentaria", "Normal")
        }
        return jsonify(response)
    else:
        return jsonify({"error": "Producto no encontrado"}), 404

@app.route("/api/products/search/<string:query>", methods=["GET"])
@token_required
def search_products(current_user, query):
    texto = query.strip().upper()
    if not texto: return jsonify([])
    
    cur = get_db().cursor()
    
    # Búsqueda inteligente: Por Nombre O por SAP
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
            "imagen_url": prod.get("imagen_url", ""), # Enviamos la imagen al buscador
            "condicion": prod.get("condicion_alimentaria", "Normal")
        })
        
    return jsonify(lista_limpia)

# ==========================================
# NUEVO SISTEMA DE ALERTAS (MANUAL)
# ==========================================

# 1. Guardar un vencimiento (POST)
@app.route("/api/alerts", methods=['POST'])
@token_required
def add_alert(current_user):
    data = request.get_json()
    # Esperamos: { "ean": "...", "nombre": "...", "fecha": "YYYY-MM-DD" }
    
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
            current_user['email']
        ))
        db.commit()
        return jsonify({"mensaje": "Vencimiento registrado exitosamente"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 2. Leer vencimientos (GET)
@app.route("/api/alerts", methods=['GET'])
@token_required
def get_alerts(current_user):
    # Devuelve la lista de productos que vencen pronto (o todos)
    cur = get_db().cursor()
    # Ordenamos por fecha para ver lo más próximo a vencer primero
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
# RUTAS DE USUARIO (REGISTRO/LOGIN) - SIN CAMBIOS
# ==========================================

@app.route('/api/auth/register', methods=['POST'])
def register_user():
    data = request.get_json()
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Faltan datos"}), 400
    # ... (lógica de registro igual que antes) ...
    # Resumida para no hacer el código gigante, usa la que ya tenías o copia del mensaje anterior
    # Solo asegúrate de incluir el insert a la tabla usuarios
    try:
        password_hash = generate_password_hash(data.get('password'))
        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO usuarios (nombre, email, password_hash) VALUES (?, ?, ?)", 
                      (data.get('nombre', 'Usuario'), data.get('email'), password_hash))
        db.commit()
        return jsonify({"mensaje": "Creado"}), 201
    except:
        return jsonify({"error": "Email existe"}), 409

@app.route('/api/auth/login', methods=['POST'])
def login_user():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
    user = cursor.fetchone()

    if user and check_password_hash(user['password_hash'], password):
        token = jwt.encode({
            'id': user['id'],
            'nombre': user['nombre'],
            'email': user['email'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=30)
        }, app.config['SECRET_KEY'], algorithm="HS256")
        
        return jsonify({
            "mensaje": "Login exitoso",
            "token": token,
            "usuario": {"nombre": user['nombre'], "email": user['email']}
        })
    
    return jsonify({"error": "Credenciales inválidas"}), 401

@app.route("/api/users/me", methods=["GET"])
@token_required
def get_user(current_user):
    return jsonify({
        "id": current_user['id'],
        "nombre": current_user['nombre'],
        "email": current_user['email']
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=True)