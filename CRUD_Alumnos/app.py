
import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, abort, jsonify
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from bson import ObjectId

app = Flask(__name__)

# ==========================================
# CONEXION A MONGODB
# ==========================================

mongo_uri = os.environ.get("MONGO_URI")

if not mongo_uri:
    if os.environ.get("RENDER"):
        raise RuntimeError("Configura MONGO_URI en Render.")
    mongo_uri = "mongodb://127.0.0.1:27017/"

cliente = MongoClient(
    mongo_uri,
    serverSelectionTimeoutMS=10000
)

base_datos = cliente["tienda_crud"]
productos = base_datos["productos"]


# ==========================================
# VALIDACION DE PRODUCTOS
# ==========================================

def validar_producto(datos):
    if not isinstance(datos, dict):
        abort(400, description="Los datos deben ser un objeto JSON.")

    nombre = str(datos.get("nombre") or "").strip()
    categoria = str(datos.get("categoria") or "").strip()
    descripcion = str(datos.get("descripcion") or "").strip()
    imagen = str(datos.get("imagen") or "").strip()

    if not nombre or not categoria:
        abort(400, description="Completa nombre y categoria.")

    if len(nombre) > 80 or len(categoria) > 50:
        abort(400, description="Nombre o categoria demasiado largos.")

    if len(descripcion) > 500 or len(imagen) > 1000:
        abort(400, description="Descripcion o imagen demasiado largas.")

    try:
        precio = float(datos.get("precio"))
        stock = int(datos.get("stock"))
    except (ValueError, TypeError, OverflowError):
        abort(400, description="Precio o stock no validos.")

    import math

    if not math.isfinite(precio) or precio < 0:
        abort(400, description="El precio debe ser un numero positivo.")

    if stock < 0:
        abort(400, description="El stock no puede ser negativo.")

    if isinstance(datos.get("stock"), (float, bool)):
        abort(400, description="El stock debe ser un numero entero.")

    return {
        "nombre": nombre,
        "categoria": categoria,
        "precio": round(precio, 2),
        "descripcion": descripcion,
        "stock": stock,
        "imagen": imagen
    }


def leer_formulario():
    return validar_producto(request.form.to_dict())


# ==========================================
# BUSCAR PRODUCTO POR ID
# ==========================================

def buscar_producto(id):
    if not ObjectId.is_valid(id):
        abort(404, description="La clave del producto no es valida.")

    producto = productos.find_one({"_id": ObjectId(id)})

    if producto is None:
        abort(404, description="El producto no existe.")

    return producto


def convertir_producto(producto):
    return {
        "id": str(producto["_id"]),
        "nombre": producto.get("nombre", ""),
        "categoria": producto.get("categoria", ""),
        "precio": producto.get("precio", 0),
        "descripcion": producto.get("descripcion", ""),
        "stock": producto.get("stock", 0),
        "imagen": producto.get("imagen", "")
    }


# ==========================================
# PAGINA PRINCIPAL
# ==========================================

@app.route("/")
def inicio():
    lista_productos = list(productos.find().sort("nombre", 1))

    return render_template(
        "index.html",
        productos=lista_productos
    )


# ==========================================
# REGISTRAR PRODUCTOS
# ==========================================

@app.route("/registrar")
def registrar():
    return render_template("registrar.html")


@app.route("/agregar", methods=["POST"])
def agregar():
    datos = leer_formulario()

    productos.insert_one(datos)

    return redirect(url_for("lista"))


# ==========================================
# LISTAR PRODUCTOS
# ==========================================

@app.route("/lista")
def lista():
    lista_productos = list(productos.find().sort("nombre", 1))

    return render_template(
        "lista.html",
        productos=lista_productos
    )


# ==========================================
# EDITAR PRODUCTOS
# ==========================================

@app.route("/editar/<id>", methods=["GET", "POST"])
def editar(id):
    producto = buscar_producto(id)

    if request.method == "POST":
        datos = leer_formulario()

        productos.update_one(
            {"_id": producto["_id"]},
            {"$set": datos}
        )

        return redirect(url_for("lista"))

    return render_template(
        "editar.html",
        producto=producto
    )


# ==========================================
# ELIMINAR PRODUCTOS
# ==========================================

@app.route("/eliminar/<id>", methods=["POST"])
def eliminar(id):
    producto = buscar_producto(id)

    productos.delete_one({"_id": producto["_id"]})

    return redirect(url_for("lista"))


# ==========================================
# PAGINA DE AYUDA
# ==========================================

@app.route("/ayuda")
def ayuda():
    fecha = datetime.now().strftime("%d/%m/%Y")

    return render_template(
        "ayuda.html",
        fecha=fecha
    )


# ==========================================
# API REST - OBTENER PRODUCTOS
# ==========================================

@app.route("/api/productos", methods=["GET"])
def api_obtener_productos():
    lista_productos = list(productos.find().sort("nombre", 1))

    resultado = [
        convertir_producto(producto)
        for producto in lista_productos
    ]

    return jsonify(resultado), 200


# ==========================================
# API REST - OBTENER UN PRODUCTO
# ==========================================

@app.route("/api/productos/<id>", methods=["GET"])
def api_obtener_producto(id):
    producto = buscar_producto(id)

    return jsonify(convertir_producto(producto)), 200


# ==========================================
# API REST - CREAR PRODUCTO
# ==========================================

@app.route("/api/productos", methods=["POST"])
def api_crear_producto():
    datos = validar_producto(request.get_json(silent=True))

    resultado = productos.insert_one(datos)

    producto = productos.find_one({
        "_id": resultado.inserted_id
    })

    return jsonify({
        "mensaje": "Producto registrado correctamente",
        "producto": convertir_producto(producto)
    }), 201


# ==========================================
# API REST - ACTUALIZAR PRODUCTO
# ==========================================

@app.route("/api/productos/<id>", methods=["PUT"])
def api_actualizar_producto(id):
    producto = buscar_producto(id)

    datos = validar_producto(request.get_json(silent=True))

    productos.update_one(
        {"_id": producto["_id"]},
        {"$set": datos}
    )

    actualizado = productos.find_one({
        "_id": producto["_id"]
    })

    return jsonify({
        "mensaje": "Producto actualizado correctamente",
        "producto": convertir_producto(actualizado)
    }), 200


# ==========================================
# API REST - ELIMINAR PRODUCTO
# ==========================================

@app.route("/api/productos/<id>", methods=["DELETE"])
def api_eliminar_producto(id):
    producto = buscar_producto(id)

    productos.delete_one({"_id": producto["_id"]})

    return jsonify({
        "mensaje": "Producto eliminado correctamente"
    }), 200


# ==========================================
# MANEJO DE ERRORES
# ==========================================

@app.errorhandler(PyMongoError)
def error_mongo(error):
    mensaje = "No fue posible conectar con MongoDB."

    if request.path.startswith("/api/"):
        return jsonify({"error": mensaje}), 503

    return render_template(
        "error.html",
        mensaje=mensaje
    ), 503


@app.errorhandler(400)
@app.errorhandler(404)
def error_peticion(error):
    if request.path.startswith("/api/"):
        return jsonify({
            "error": error.description
        }), error.code

    return render_template(
        "error.html",
        mensaje=error.description
    ), error.code


# ==========================================
# EJECUTAR APLICACION
# ==========================================

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )
