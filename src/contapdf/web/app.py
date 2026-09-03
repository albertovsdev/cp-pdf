"""La aplicacion Flask.

Flask y no FastAPI: esta fase sirve HTML, no JSON, y el pipeline es
sincrono y CPU-bound. El async de FastAPI no aporta nada aqui -- habria que
mandar el trabajo a un threadpool igualmente -- y traeria uvicorn y una
plantilla de terceros para renderizar. Flask trae Jinja2 y send_file de
serie, que es exactamente lo que hace falta.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from flask import (
    Flask,
    abort,
    after_this_request,
    render_template,
    request,
    send_file,
)

from contapdf.cli import (
    TIPOS_DE_DOCUMENTO,
    DocumentoNoReconocido,
    procesar_documento,
)

_LOG = logging.getLogger(__name__)
_FIRMA_PDF = b"%PDF"
# Un documento contable de 968 paginas pesa ~9 MB; 64 deja margen de sobra
# sin permitir que una subida cualquiera llene el disco.
_MAXIMO = 64 * 1024 * 1024


@dataclass(frozen=True)
class _Entrega:
    """Un xlsx listo para descargar, y el directorio que hay que borrar."""

    xlsx: Path
    directorio: Path
    nombre: str


def crear_app(*, trabajos: Path | None = None) -> Flask:
    """La app. `trabajos` es donde viven los temporales de cada subida."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = _MAXIMO
    raiz = Path(trabajos) if trabajos is not None else Path(tempfile.gettempdir())
    raiz.mkdir(parents=True, exist_ok=True)
    # El estado vive en la app, no en un global de modulo: dos apps de test
    # no se pisan y no hay nada que se contamine entre peticiones.
    app.extensions["contapdf_entregas"] = {}

    @app.get("/")
    def portada():
        return render_template("portada.html", tipos=TIPOS_DE_DOCUMENTO)

    @app.post("/procesar")
    def procesar():
        tipo = (request.form.get("tipo") or "").strip()
        subido = request.files.get("pdf")
        if subido is None or not subido.filename:
            return _error("No se recibio ningun archivo.",
                          "Elige un PDF antes de enviar."), 400
        if not tipo:
            return _error("No se eligio el tipo de documento.",
                          "Selecciona uno de la lista."), 400

        directorio = raiz / f"trabajo-{uuid.uuid4().hex}"
        directorio.mkdir(parents=True)
        pdf = directorio / "entrada.pdf"
        subido.save(pdf)

        if pdf.read_bytes()[:4] != _FIRMA_PDF:
            _borrar(directorio)
            return _error(
                f"{subido.filename!r} no es un PDF.",
                "El archivo no empieza con la firma de un PDF. Si lo "
                "exportaste desde otro programa, vuelve a guardarlo como "
                "PDF y subelo otra vez."), 400

        nombre = Path(subido.filename).stem or "documento"
        xlsx = directorio / f"{nombre}.xlsx"
        try:
            resultado = procesar_documento(tipo, pdf, xlsx)
        except DocumentoNoReconocido as exc:
            _borrar(directorio)
            return _error(str(exc), _sugerencia(tipo, exc),
                          detalle=exc.detalle, clave=exc.clave), 400
        except Exception:                       # nunca una traza en pantalla
            _LOG.exception("fallo procesando %s como %s", subido.filename, tipo)
            _borrar(directorio)
            return _error(
                "No se pudo procesar el documento.",
                "Quedo registrado en el log del servidor con el detalle "
                "tecnico."), 500

        ficha = uuid.uuid4().hex
        app.extensions["contapdf_entregas"][ficha] = _Entrega(
            xlsx=xlsx, directorio=directorio, nombre=f"{nombre}.xlsx")
        _borrar(pdf)                            # el PDF del cliente no se queda
        return render_template("resultado.html", r=resultado, ficha=ficha,
                               archivo=subido.filename)

    @app.get("/descargar/<ficha>")
    def descargar(ficha):
        entrega = app.extensions["contapdf_entregas"].pop(ficha, None)
        if entrega is None or not entrega.xlsx.exists():
            abort(404)

        @after_this_request
        def limpiar(respuesta):
            # De un solo uso: al terminar la descarga no queda en disco ni
            # el PDF del cliente ni su Excel.
            _borrar(entrega.directorio)
            return respuesta

        return send_file(entrega.xlsx, as_attachment=True,
                         download_name=entrega.nombre)

    @app.errorhandler(413)
    def demasiado_grande(_):
        return _error("El archivo es demasiado grande.",
                      f"El limite son {_MAXIMO // (1024 * 1024)} MB."), 413

    return app


def _error(mensaje: str, sugerencia: str = "", *, detalle=(), clave: str = ""):
    return render_template("error.html", mensaje=mensaje,
                           sugerencia=sugerencia, detalle=detalle, clave=clave)


def _sugerencia(tipo: str, exc: DocumentoNoReconocido) -> str:
    if exc.clave:
        return ("El documento se leyo bien, pero no es una tabla de "
                "movimientos. Si es otro reporte del banco, no hay nada que "
                "convertir.")
    otros = ", ".join(n for n, _ in TIPOS_DE_DOCUMENTO if n != tipo)
    return (f"Se intento leer como «{tipo}». Si el documento es de otro "
            f"tipo, prueba con: {otros}.")


def _borrar(ruta: Path) -> None:
    import shutil

    shutil.rmtree(ruta, ignore_errors=True) if ruta.is_dir() else ruta.unlink(
        missing_ok=True)
