"""La aplicacion Flask.

Flask y no FastAPI: esta fase sirve HTML, no JSON. El trabajo pesado es
CPU-bound y bloqueante, asi que el async de FastAPI no aportaria nada --
habria que mandarlo a un hilo igualmente -- y traeria uvicorn y una
plantilla de terceros. Flask trae Jinja2 y send_file de serie.

**Por que hay cola.** `auxiliar-gume.pdf` tarda 3m57s medidos, y
SERVIDORSIST se apaga a las 21:00: un trabajo a medias no es una hipotesis.
El estado vive en SQLite (ver `cola.py`), asi que al arrancar un trabajo
interrumpido lo dice en vez de dar un 404.

**Un worker, secuencial** (PLAN 6): la maquina objetivo tiene 8 GB
compartidos con Apache y MySQL y el pico medido del pipeline es 543 MB. Los
demas esperan con su posicion visible.

**El tenant va en la ruta** (`/t/<despacho>/…`), no en un login: esta fase
no trae autenticacion. El aislamiento es organizativo -- separa los
trabajos, las plantillas y las descargas de cada despacho -- pero **no es
una barrera de seguridad**: quien conozca el nombre de otro despacho entra
en su area. Lo que si impide es que un id de trabajo sirva fuera de su
despacho.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
from pathlib import Path

from flask import (
    Flask,
    abort,
    after_this_request,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from contapdf.cli import (
    TIPOS_DE_DOCUMENTO,
    DocumentoNoReconocido,
    procesar_documento,
)
from contapdf.web import vista
from contapdf.web.cola import (
    CON_DISCREPANCIAS,
    EN_COLA,
    ERROR,
    INTERRUMPIDO,
    LISTO,
    NO_RECONOCIDO,
    PROCESANDO,
    Cola,
    TenantInvalido,
    validar_tenant,
)

_LOG = logging.getLogger(__name__)
_FIRMA_PDF = b"%PDF"
# Un documento contable de 968 paginas pesa ~9 MB; 64 deja margen de sobra
# sin permitir que una subida cualquiera llene el disco.
_MAXIMO = 64 * 1024 * 1024
_POR_DEFECTO = "general"


def crear_app(*, trabajos: Path | None = None) -> Flask:
    """La app. `trabajos` es donde viven la base de la cola y los temporales."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = _MAXIMO
    raiz = (Path(trabajos) if trabajos is not None
            else Path(tempfile.gettempdir()) / "contapdf-web")
    raiz.mkdir(parents=True, exist_ok=True)
    app.config["CONTAPDF_TRABAJOS"] = raiz
    # Estado en la app, nunca en un global de modulo: dos apps no se pisan.
    app.extensions["contapdf_cola"] = Cola(raiz / "cola.sqlite3", raiz=raiz)
    app.extensions["contapdf_worker"] = threading.Lock()

    def cola() -> Cola:
        return app.extensions["contapdf_cola"]

    def tenant_de(valor: str) -> str:
        try:
            return validar_tenant(valor)
        except TenantInvalido:
            abort(404)

    @app.before_request
    def _mantenimiento():
        cola().barrer()
        # Re-armar en CADA peticion, no solo al subir: el worker muere al
        # vaciar la cola, y entre su ultimo `tomar_siguiente()` y el momento
        # en que suelta el candado cabe una subida. Sin esto ese trabajo se
        # queda dormido hasta que el barrido lo borre, sin procesarse nunca.
        _arrancar_worker(app)

    @app.get("/")
    def raiz_sin_tenant():
        return redirect(url_for("portada", tenant=_POR_DEFECTO), code=302)

    @app.get("/t/<tenant>/")
    def portada(tenant):
        tenant = tenant_de(tenant)
        return render_template("portada.html", tipos=TIPOS_DE_DOCUMENTO,
                               tenant=tenant, trabajos=cola().listar(tenant))

    @app.post("/t/<tenant>/procesar")
    def procesar(tenant):
        tenant = tenant_de(tenant)
        subido = request.files.get("pdf")
        tipo = (request.form.get("tipo") or "").strip()
        if subido is None or not subido.filename:
            return _error(tenant, "No se recibio ningun archivo.",
                          "Elige un PDF antes de enviar."), 400
        if not any(tipo == n for n, _ in TIPOS_DE_DOCUMENTO):
            return _error(
                tenant,
                f"Tipo de documento no valido: {tipo!r}." if tipo
                else "No se eligio el tipo de documento.",
                "Selecciona uno de la lista."), 400

        trabajo = cola().encolar(tenant=tenant, tipo=tipo,
                                 archivo=subido.filename)
        pdf = trabajo.directorio / "entrada.pdf"
        subido.save(pdf)
        if pdf.read_bytes()[:4] != _FIRMA_PDF:
            cola().marcar_terminado(
                trabajo.identificador, estado=NO_RECONOCIDO, resumen={},
                mensaje=f"{subido.filename!r} no es un PDF.")
            _borrar(trabajo.directorio)
            return _error(
                tenant, f"{subido.filename!r} no es un PDF.",
                "El archivo no empieza con la firma de un PDF. Vuelve a "
                "guardarlo como PDF y subelo otra vez."), 400

        _arrancar_worker(app)
        return redirect(url_for("estado", tenant=tenant,
                                identificador=trabajo.identificador), code=302)

    @app.get("/t/<tenant>/trabajo/<identificador>")
    def estado(tenant, identificador):
        tenant = tenant_de(tenant)
        trabajo = cola().buscar(identificador, tenant=tenant)
        if trabajo is None:
            abort(404)
        if trabajo.estado in (EN_COLA, PROCESANDO):
            return render_template("procesando.html", t=trabajo, tenant=tenant,
                                   posicion=cola().posicion(identificador))
        if trabajo.entrega:
            return render_template("resultado.html", t=trabajo, tenant=tenant,
                                   r=trabajo.resumen)
        # 'interrumpido' NO es un 400: nadie rechazo el documento, ni
        # siquiera se llego a juzgarlo. Los otros dos si conservan el 400
        # que la 8a le puso a un documento que el sistema no acepta.
        codigo = 200 if trabajo.estado == INTERRUMPIDO else 400
        return render_template("interrumpido.html", t=trabajo, tenant=tenant,
                               r=trabajo.resumen), codigo

    @app.get("/t/<tenant>/descargar/<identificador>")
    def descargar(tenant, identificador):
        tenant = tenant_de(tenant)
        trabajo = cola().buscar(identificador, tenant=tenant)
        if (trabajo is None or not trabajo.entrega or trabajo.xlsx is None
                or not trabajo.xlsx.exists()):
            abort(404)

        @after_this_request
        def limpiar(respuesta):
            # De un solo uso: en cuanto el Excel sale hacia el navegador, el
            # documento del cliente deja de existir en el servidor.
            cola().olvidar(identificador, tenant=tenant)
            return respuesta

        return send_file(trabajo.xlsx, as_attachment=True,
                         download_name=trabajo.nombre_xlsx)

    @app.errorhandler(413)
    def demasiado_grande(_):
        # El 413 salta al leer el cuerpo, antes de que haya `view_args`, asi
        # que el despacho se saca de la ruta para no mandar al usuario al
        # area de otro con el enlace de volver.
        return _error(_tenant_de_la_ruta(request.path),
                      "El archivo es demasiado grande.",
                      f"El limite son {_MAXIMO // (1024 * 1024)} MB."), 413

    return app


def _tenant_de_la_ruta(ruta: str) -> str:
    partes = ruta.strip("/").split("/")
    if len(partes) >= 2 and partes[0] == "t":
        try:
            return validar_tenant(partes[1])
        except TenantInvalido:
            pass
    return _POR_DEFECTO


def _arrancar_worker(app: Flask) -> None:
    """Un solo worker vivo; si ya hay uno, esta atendiendo la cola."""
    if not app.extensions["contapdf_worker"].acquire(blocking=False):
        return
    threading.Thread(target=_atender, args=(app,),
                     name="contapdf-worker", daemon=True).start()


def _atender(app: Flask) -> None:
    """El worker: un trabajo a la vez hasta vaciar la cola.

    Suelta el candado al vaciarla, para no dejar un hilo vivo sin nada que
    hacer. Antes de irse comprueba una vez mas: entre el `tomar_siguiente()`
    que devolvio None y el `release` cabe una subida, y ese trabajo se
    quedaria dormido.
    """
    cola: Cola = app.extensions["contapdf_cola"]
    candado = app.extensions["contapdf_worker"]
    while True:
        try:
            while True:
                trabajo = cola.tomar_siguiente()
                if trabajo is None:
                    break
                _procesar_uno(app, cola, trabajo)
        finally:
            candado.release()
        if not cola.hay_pendientes():
            return
        if not candado.acquire(blocking=False):
            return          # otro worker ya arranco: el trabajo es suyo


def _procesar_uno(app: Flask, cola: Cola, trabajo) -> None:
    pdf = trabajo.directorio / "entrada.pdf"
    nombre = Path(trabajo.archivo).stem or "documento"
    xlsx = trabajo.directorio / f"{nombre}.xlsx"
    plantillas = app.config["CONTAPDF_TRABAJOS"] / "plantillas"
    try:
        resultado = procesar_documento(trabajo.tipo, pdf, xlsx,
                                       tenant_id=trabajo.tenant,
                                       plantillas=plantillas)
        cola.marcar_terminado(
            trabajo.identificador,
            estado=CON_DISCREPANCIAS if resultado.cobertura.fallan else LISTO,
            resumen=vista.como_diccionario(resultado),
            xlsx=xlsx, nombre_xlsx=f"{nombre}.xlsx")
    except DocumentoNoReconocido as exc:
        cola.marcar_terminado(
            trabajo.identificador, estado=NO_RECONOCIDO,
            resumen={"sugerencia": _sugerencia(trabajo.tipo, exc),
                     "detalle": list(exc.detalle), "clave": exc.clave},
            mensaje=str(exc))
    except Exception:                       # nunca una traza en pantalla
        _LOG.exception("fallo procesando %s como %s",
                       trabajo.archivo, trabajo.tipo)
        cola.marcar_terminado(
            trabajo.identificador, estado=ERROR, resumen={},
            mensaje="No se pudo procesar el documento. Quedo registrado en "
                    "el log del servidor con el detalle tecnico.")
    finally:
        # El PDF del cliente no se queda ni un minuto de mas.
        _borrar(pdf)


def _error(tenant: str, mensaje: str, sugerencia: str = "", *, detalle=(),
           clave: str = ""):
    return render_template("error.html", mensaje=mensaje, tenant=tenant,
                           sugerencia=sugerencia, detalle=detalle, clave=clave)


def _sugerencia(tipo: str, exc: DocumentoNoReconocido) -> str:
    if exc.clave:
        return ("El documento se leyo bien, pero no trae una tabla de "
                "movimientos. Si es otro reporte del banco, no hay nada que "
                "convertir.")
    otros = ", ".join(n for n, _ in TIPOS_DE_DOCUMENTO if n != tipo)
    return (f"Se intento leer como «{tipo}». Si el documento es de otro "
            f"tipo, prueba con: {otros}.")


def _borrar(ruta: Path) -> None:
    if ruta.is_dir():
        shutil.rmtree(ruta, ignore_errors=True)
    else:
        ruta.unlink(missing_ok=True)
