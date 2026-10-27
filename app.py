
import os
from datetime import datetime, timezone
from functools import wraps
import secrets
import re

from flask import Flask, render_template, request, redirect, url_for, abort, jsonify, session, flash
from pymongo import MongoClient
from pymongo.errors import PyMongoError, DuplicateKeyError
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or (secrets.token_hex(32) if not os.environ.get("RENDER") else "")
if not app.secret_key:
    raise RuntimeError("Configura SECRET_KEY en Render.")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")))

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
usuarios = base_datos["usuarios"]
pedidos = base_datos["pedidos"]


def usuario_admin():
    correo_admin = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    if not correo_admin or not session.get("usuario_id") or not ObjectId.is_valid(session["usuario_id"]):
        return False
    usuario = usuarios.find_one({"_id": ObjectId(session["usuario_id"])}, {"correo": 1})
    return bool(usuario and usuario.get("correo", "").lower() == correo_admin)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("usuario_id"):
            flash("Inicia sesión para administrar productos.", "warning")
            return redirect(url_for("login"))
        if not usuario_admin():
            abort(403, description="Acceso exclusivo del administrador.")
        return fn(*args, **kwargs)
    return wrapper


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("usuario_id"):
            flash("Inicia sesión para finalizar la compra.", "warning")
            return redirect(url_for("login"))
        if not ObjectId.is_valid(session["usuario_id"]) or not usuarios.find_one({"_id": ObjectId(session["usuario_id"])}):
            session.clear()
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def api_write_required():
    # Las operaciones GET son públicas. Para escribir desde Postman se requiere clave privada.
    expected = os.environ.get("ADMIN_API_KEY", "")
    provided = request.headers.get("X-Admin-API-Key", "")
    if not expected or not secrets.compare_digest(provided, expected):
        abort(403, description="API de escritura exclusiva del administrador. Configura ADMIN_API_KEY.")


@app.before_request
def verificar_csrf():
    if request.method == "POST" and not request.path.startswith("/api/"):
        token = session.get("csrf_token", "")
        provided = request.form.get("_csrf", "")
        if not token or not secrets.compare_digest(token, provided):
            abort(400, description="Formulario caducado. Actualiza la página.")


@app.context_processor
def datos_usuario():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(24)
    carrito = session.get("carrito", {})
    return {"csrf_token": session["csrf_token"], "usuario_actual": session.get("usuario_nombre"),
            "es_admin": usuario_admin(), "carrito_cantidad": sum(carrito.values())}


@app.route("/crear-cuenta", methods=["GET", "POST"])
def crear_cuenta():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        correo = request.form.get("correo", "").strip().lower()
        clave = request.form.get("clave", "")
        if not 2 <= len(nombre) <= 80 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", correo) or not 8 <= len(clave) <= 128:
            flash("Revisa tus datos. La contraseña requiere al menos 8 caracteres.", "danger")
        else:
            try:
                usuarios.create_index("correo", unique=True)
                result = usuarios.insert_one({"nombre": nombre, "correo": correo, "clave_hash": generate_password_hash(clave), "creado": datetime.now(timezone.utc)})
                carrito = session.get("carrito", {})
                session.clear()
                session.update(usuario_id=str(result.inserted_id), usuario_nombre=nombre, carrito=carrito)
                flash("¡Cuenta creada correctamente!", "success")
                return redirect(url_for("carrito"))
            except DuplicateKeyError:
                flash("Ese correo ya está registrado.", "danger")
    return render_template("crear_cuenta.html")


@app.route("/iniciar-sesion", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("correo", "").strip().lower()
        usuario = usuarios.find_one({"correo": correo})
        if usuario and check_password_hash(usuario["clave_hash"], request.form.get("clave", "")):
            carrito = session.get("carrito", {})
            session.clear()
            session.update(usuario_id=str(usuario["_id"]), usuario_nombre=usuario["nombre"], carrito=carrito)
            flash("¡Bienvenido a la tienda!", "success")
            return redirect(url_for("inicio"))
        flash("Correo o contraseña incorrectos.", "danger")
    return render_template("login.html")


@app.route("/cerrar-sesion", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("inicio"))


@app.route("/carrito")
def carrito():
    elementos = []
    total = 0
    for id, cantidad in session.get("carrito", {}).items():
        if not ObjectId.is_valid(id) or not isinstance(cantidad, int) or cantidad < 1:
            continue
        producto = productos.find_one({"_id": ObjectId(id)})
        if producto:
            subtotal = round(float(producto["precio"]) * cantidad, 2)
            elementos.append({"producto": producto, "cantidad": cantidad, "subtotal": subtotal})
            total += subtotal
    return render_template("carrito.html", elementos=elementos, total=round(total, 2))


@app.route("/carrito/agregar/<id>", methods=["POST"])
def carrito_agregar(id):
    producto = buscar_producto(id)
    cart = dict(session.get("carrito", {}))
    actual = int(cart.get(id, 0))
    if actual >= min(int(producto.get("stock", 0)), 100):
        flash("No hay más unidades disponibles.", "warning")
    else:
        cart[id] = actual + 1
        session["carrito"] = cart
        flash("Producto agregado al carrito.", "success")
    return redirect(url_for("carrito"))


@app.route("/carrito/quitar/<id>", methods=["POST"])
def carrito_quitar(id):
    cart = dict(session.get("carrito", {}))
    cart.pop(id, None)
    session["carrito"] = cart
    return redirect(url_for("carrito"))


@app.route("/comprar", methods=["POST"])
@login_required
def comprar():
    cart = session.get("carrito", {})
    if not cart:
        flash("Tu carrito está vacío.", "warning")
        return redirect(url_for("carrito"))
    items = []
    for id, cantidad in cart.items():
        if not ObjectId.is_valid(id) or not isinstance(cantidad, int) or not 1 <= cantidad <= 100:
            abort(400, description="Carrito inválido.")
        producto = productos.find_one({"_id": ObjectId(id)})
        if not producto or int(producto.get("stock", 0)) < cantidad:
            flash("Algún producto ya no tiene existencias suficientes.", "warning")
            return redirect(url_for("carrito"))
        items.append({"id": id, "nombre": producto["nombre"], "precio": float(producto["precio"]), "cantidad": cantidad})
    total = round(sum(i["precio"] * i["cantidad"] for i in items), 2)
    # Compra de demostración: no se cobra ni se descuenta inventario.
    pedidos.insert_one({"usuario_id": ObjectId(session["usuario_id"]), "items": items,
                        "total": total, "fecha": datetime.now(timezone.utc), "estado": "Simulada"})
    session["carrito"] = {}
    flash("¡Compra simulada guardada! No se realizó ningún cobro.", "success")
    return redirect(url_for("mis_compras"))


@app.route("/mis-compras")
@login_required
def mis_compras():
    lista_pedidos = list(pedidos.find({"usuario_id": ObjectId(session["usuario_id"])}).sort("fecha", -1))
    return render_template("mis_compras.html", pedidos=lista_pedidos)



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
@admin_required
def registrar():
    return render_template("registrar.html")


@app.route("/agregar", methods=["POST"])
@admin_required
def agregar():
    datos = leer_formulario()

    productos.insert_one(datos)

    return redirect(url_for("lista"))


# ==========================================
# LISTAR PRODUCTOS
# ==========================================

@app.route("/lista")
@admin_required
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
@admin_required
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
@admin_required
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
    api_write_required()
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
    api_write_required()
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
    api_write_required()
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
@app.errorhandler(403)
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
