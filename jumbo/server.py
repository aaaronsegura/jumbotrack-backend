import sqlite3
import os
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# --- NUEVOS IMPORTS ---
import jwt # Para crear/decodificar tokens
import datetime # Para la expiración del token
from functools import wraps # Para crear el "decorador" de rutas protegidas
from dotenv import load_dotenv # Para leer el .env local (si lo usas)

load_dotenv() # Carga variables de .env si existen (para pruebas locales)

app = Flask(__name__)
CORS(app)
DATABASE = 'productos.db'

# --- NUEVA CONFIGURACIÓN DE LLAVE SECRETA ---
# Lee la llave secreta de las variables de entorno de Render
# Si no la encuentra (ej. en tu PC), usa una clave simple por defecto
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'un-secreto-simple-para-pruebas')

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

# --- NUEVO: DECORADOR DE TOKEN REQUERIDO ---
# Esta es la función "guardia" que protegerá nuestras rutas
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # La app debe enviar el token en un "header" llamado 'x-access-token'
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']

        if not token:
            return jsonify({'error': 'Token no encontrado'}), 401

        try:
            # Intenta decodificar el token usando nuestra Llave Secreta
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            # Pasamos los datos del usuario a la ruta
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'El token ha expirado'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token inválido'}), 401

        return f(current_user, *args, **kwargs)
    return decorated

# --- RUTA DE PERFIL (AHORA PROTEGIDA) ---
@app.route("/api/users/me", methods=["GET"])
@token_required # <-- ¡Añadimos el "guardia" aquí!
def get_user(current_user):
    # 'current_user' es el diccionario que viene del token (ver @token_required)
    print(f"👤 Petición de Perfil para: {current_user['email']}")
    
    # Ya no devolvemos datos fijos, sino los datos del usuario del token
    return jsonify({
        "id": current_user['id'],
        "name": current_user['nombre'],
        "email": current_user['email']
    })

@app.route("/api/alerts", methods=["GET"])
@token_required # <-- Protegemos también esta ruta
def get_alerts(current_user):
    print(f" Petición de Alertas de: {current_user['email']}")
    return jsonify([{"id": "a1", "message": "Poco stock", "type": "LOW_STOCK", "timestamp": "2025-11-05T20:00:00Z"}])

# --- RUTA ESCÁNER (AHORA PROTEGIDA) ---
@app.route("/api/products/ean/<string:ean>", methods=["GET"])
@token_required # <-- Protegemos también esta ruta
def get_product_by_ean(current_user, ean):
    ean_buscado = ean.strip()
    print(f" [SQL] Buscando EAN: '{ean_buscado}' (Usuario: {current_user['email']})")
    cur = get_db().cursor()
    cur.execute("SELECT * FROM productos WHERE ean_limpio = ?", (ean_buscado,))
    row = cur.fetchone()
    if row:
        prod = dict(row)
        response = {
            "nombre": prod.get("producto_limpio", "Sin Nombre"),
            "ean": prod.get("ean_limpio", "N/A"),
            "precio": prod.get("Precio Venta", 0),
            "stock": prod.get("STOCK \n11-09-2025", 0) 
        }
        print(f" ENVIANDO: {response['nombre']}")
        return jsonify(response)
    else:
        print(" NO ENCONTRADO")
        return jsonify({"error": "Producto no encontrado"}), 404

# --- RUTA BUSCADOR (AHORA PROTEGIDA) ---
@app.route("/api/products/search/<string:query>", methods=["GET"])
@token_required # <-- Protegemos también esta ruta
def search_products(current_user, query):
    texto = query.strip().upper()
    print(f" [SQL] Buscando: '{texto}' (Usuario: {current_user['email']})")
    if not texto: return jsonify([])
    
    cur = get_db().cursor()
    cur.execute("SELECT * FROM productos WHERE UPPER(producto_limpio) LIKE ? LIMIT 50", (f'%{texto}%',))
    rows = cur.fetchall()
    print(f" Resultados: {len(rows)}")

    lista_limpia = []
    for row in rows:
        prod = dict(row)
        lista_limpia.append({
            "nombre": prod.get("producto_limpio", "Sin Nombre"),
            "ean": prod.get("ean_limpio", "N/A"),
            "precio": prod.get("Precio Venta", 0),
            "stock": prod.get("STOCK \n11-09-2025", 0)
        })
        
    return jsonify(lista_limpia)

# --- RUTA DE REGISTRO (Pública) ---
@app.route('/api/auth/register', methods=['POST'])
def register_user():
    data = request.get_json()
    if not data or not data.get('nombre') or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Faltan datos (nombre, email, password)"}), 400
    
    nombre = data.get('nombre')
    email = data.get('email')
    password = data.get('password')
    password_hash = generate_password_hash(password)

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO usuarios (nombre, email, password_hash) VALUES (?, ?, ?)", (nombre, email, password_hash))
        db.commit()
        user_id = cursor.lastrowid
        return jsonify({"mensaje": "Usuario registrado exitosamente", "usuario": {"id": user_id, "nombre": nombre, "email": email}}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "El email ya está registrado"}), 409
    except Exception as e:
        return jsonify({"error": f"Error en el servidor: {str(e)}"}), 500

# --- RUTA DE LOGIN (Pública) (ACTUALIZADA) ---
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

        # --- ¡ÉXITO! AQUÍ CREAMOS EL TOKEN ---
        token = jwt.encode(
            {
                # "Payload" del token:
                'id': usuario['id'],
                'nombre': usuario['nombre'],
                'email': usuario['email'],
                # "exp" (Expiración): 7 días desde ahora
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7) 
            },
            app.config['SECRET_KEY'], # Nuestra llave secreta
            algorithm="HS256" # Algoritmo de firmado
        )

        return jsonify({
            "mensaje": "Login exitoso",
            "usuario": {
                "id": usuario['id'],
                "nombre": usuario['nombre'],
                "email": usuario['email']
            },
            "token": token # <-- ¡Enviamos el token a la app!
        }), 200

    except Exception as e:
        return jsonify({"error": f"Error en el servidor: {str(e)}"}), 500

if __name__ == "__main__":
    print(f" Servidor listo en http://0.0.0.0:3000")
    app.run(host="0.0.0.0", port=3000, debug=True)
