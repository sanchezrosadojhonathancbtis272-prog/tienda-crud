# Tienda CRUD · Práctica 05 — cuentas y carrito

Se conserva la base de datos **tienda_crud** y la colección **productos** existentes. Se agregan colecciones **usuarios** y **pedidos** en la misma base de datos. Se mantienen los estilos CSS, Bootstrap y las páginas originales.

## Configuración

- `MONGO_URI`: conexión a MongoDB Atlas o MongoDB local.
- `SECRET_KEY`: clave aleatoria estable (obligatoria en Render).
- `ADMIN_EMAIL`: correo de la única cuenta administradora. Primero regístrala en la tienda. Solo ese correo puede entrar a `/lista`, `/registrar`, `/editar` y eliminar/agregar productos.
- `ADMIN_API_KEY`: clave aleatoria distinta de `SECRET_KEY`, necesaria para operaciones POST/PUT/DELETE de la API REST mediante encabezado `X-Admin-API-Key`. Sin esta variable, la API de escritura permanece bloqueada.

Generar claves con: `python -c "import secrets; print(secrets.token_hex(32))"`.

## API

- `GET /api/productos` y `GET /api/productos/<id>`: públicas.
- `POST /api/productos`, `PUT /api/productos/<id>`, `DELETE /api/productos/<id>`: requieren encabezado `X-Admin-API-Key` con la clave configurada.

## Instalación

`pip install -r requirements.txt` y luego `python app.py`.

**Importante**: la compra es simulada, sin pago ni descuento de stock. No subas claves ni archivos `.env` a GitHub. Verifica permisos con una cuenta de cliente en incógnito antes de publicar. Conserva un respaldo antes de reemplazar archivos.
