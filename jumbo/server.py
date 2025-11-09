import sqlite3
import os
from flask import Flask, jsonify, request, g
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
DATABASE = 'productos.db'

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

@app.route("/api/users/me", methods=["GET"])
def get_user():
    print("👤 Petición de Perfil")
    return jsonify({"id": "123", "name": "Aaron Segura", "email": "aaron.testing@jumbotrack.cl"})

@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    print(" Petición de Alertas")
    return jsonify([{"id": "a1", "message": "Poco stock", "type": "LOW_STOCK", "timestamp": "2025-11-05T20:00:00Z"}])

# --- RUTA ESCÁNER (JSON SIMPLIFICADO) ---
@app.route("/api/products/ean/<string:ean>", methods=["GET"])
def get_product_by_ean(ean):
    ean_buscado = ean.strip()
    print(f" [SQL] Buscando EAN: '{ean_buscado}'")
    cur = get_db().cursor()
    cur.execute("SELECT * FROM productos WHERE ean_limpio = ?", (ean_buscado,))
    row = cur.fetchone()
    if row:
        prod = dict(row)
        # Enviamos JSON limpio
        response = {
            "nombre": prod.get("producto_limpio", "Sin Nombre"),
            "ean": prod.get("ean_limpio", "N/A"),
            "precio": prod.get("Precio Venta", 0),
            "stock": prod.get("STOCK \n11-09-2025", 0) # Usamos el nombre exacto raro de tu DB aquí
        }
        print(f" ENVIANDO: {response['nombre']}")
        return jsonify(response)
    else:
        print(" NO ENCONTRADO")
        return jsonify({"error": "Producto no encontrado"}), 404

# --- RUTA BUSCADOR (JSON SIMPLIFICADO) ---
@app.route("/api/products/search/<string:query>", methods=["GET"])
def search_products(query):
    texto = query.strip().upper()
    print(f" [SQL] Buscando: '{texto}'")
    if not texto: return jsonify([])
    
    cur = get_db().cursor()
    cur.execute("SELECT * FROM productos WHERE UPPER(producto_limpio) LIKE ? LIMIT 50", (f'%{texto}%',))
    rows = cur.fetchall()
    print(f" Resultados: {len(rows)}")

    lista_limpia = []
    for row in rows:
        prod = dict(row)
        # Creamos un diccionario limpio para cada producto
        lista_limpia.append({
            "nombre": prod.get("producto_limpio", "Sin Nombre"),
            "ean": prod.get("ean_limpio", "N/A"),
            "precio": prod.get("Precio Venta", 0),
            "stock": prod.get("STOCK \n11-09-2025", 0)
        })
        
    return jsonify(lista_limpia)

if __name__ == "__main__":
    print(f" Servidor listo en http://0.0.0.0:3000")
    app.run(host="0.0.0.0", port=3000, debug=True)