import sqlite3
import os
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# Imports para JWT (Tokens)
import jwt 
import datetime
from functools import wraps
from dotenv import load_dotenv 

# Cargar variables de entorno (para FLASK_SECRET_KEY)
load_dotenv() 

app = Flask(__name__)
CORS(app)
DATABASE = 'productos.db'

# Configuración de la llave secreta
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'un-secreto-simple-para-pruebas-locales')

# --- CONEXIÓN A LA BASE DE DATOS ---

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        # Esto hace que la DB devuelva diccionarios en lugar de tuplas
        db.row_factory = sqlite3.Row 
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- AUTENTICACIÓN (El "Guardia" de las rutas) ---

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # La app debe enviar el token en la cabecera 'x-access-token'
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']

        if not token:
            return jsonify({'error': 'Token no encontrado'}), 401

        try:
            # Decodificar el token con la llave secreta
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            # Pasamos los datos del usuario (que vienen en el token) a la función de la ruta
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'El token ha expirado'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token inválido'}), 401

        return f(current_user, *args, **kwargs)
    return decorated

# --- RUTAS PÚBLICAS (Registro y Login) ---

@app.route('/api/auth/register', methods=['POST'])
def register_user():
    data = request.get_json()
    if not data or not data.get('nombre') or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Faltan datos (nombre, email, password)"}), 400

    nombre = data.get('nombre')
    email = data.get('email')
    password_hash = generate_password_hash(data.get('password'))

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
            "usuario": {"id": user_id, "nombre": nombre, "email": email}
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

        # Si llegamos aquí, el login es exitoso. Creamos el token.
        token = jwt.encode(
            {
                'id': usuario['id'],
                'nombre': usuario['nombre'],
                'email': usuario['email'],
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7) # Token dura 7 días
            },
            app.config['SECRET_KEY'],
            algorithm="HS256"
        )

        return jsonify({
            "mensaje": "Login exitoso",
            "usuario": {"id": usuario['id'], "nombre": usuario['nombre'], "email": usuario['email']},
            "token": token
        }), 200
    except Exception as e:
        return jsonify({"error": f"Error en el servidor: {str(e)}"}), 500

# --- RUTAS PROTEGIDAS (Requieren Token) ---

@app.route("/api/users/me", methods=["GET"])
@token_required
def get_user(current_user):
    # 'current_user' viene del token que decodificamos
    print(f"👤 Petición de Perfil para: {current_user['email']}")
    
    # --- ¡ESTA ES LA CORRECCIÓN! ---
    # Antes decía "name", ahora dice "nombre", igual que en tu data class de Kotlin.
    return jsonify({
        "id": current_user['id'],
        "nombre": current_user['nombre'],
        "email": current_user['email']
    }), 200

@app.route("/api/alerts", methods=["GET"])
@token_required
def get_alerts(current_user):
    print(f" Petición de Alertas de: {current_user['email']}")
    return jsonify([
        {"id": "a1", "message": "Poco stock", "type": "LOW_STOCK", "timestamp": "2025-11-05T20:00:00Z"}
    ])

@app.route("/api/products/ean/<string:ean>", methods=["GET"])
@token_required
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
            "precio": prod.get("Precio Venta", 0), # Ajusta si el nombre de tu columna es otro
            "stock": prod.get("STOCK \n11-09-2025", 0) # Ajusta si el nombre de tu columna es otro
        }
        print(f" ENVIANDO: {response['nombre']}")
        return jsonify(response)
    else:
        print(" NO ENCONTRADO")
        return jsonify({"error": "Producto no encontrado"}), 404

@app.route("/api/products/search/<string:query>", methods=["GET"])
@token_required
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

# --- INICIADOR ---

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    print(f" Servidor listo en http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)