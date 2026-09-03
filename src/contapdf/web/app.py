"""La aplicacion Flask.

Flask y no FastAPI: esta fase sirve HTML, no JSON. El trabajo pesado es
CPU-bound y bloqueante, asi que el async de FastAPI no aportaria nada --
habria que mandarlo a un hilo igualmente -- y traeria uvicorn y una
plantilla de terceros. Flask trae Jinja2 y send_file de serie.

**Por que el trabajo corre aparte.** Medido en aislamiento:
`auxiliar-gume.pdf` (886 paginas, 57 024 renglones) tarda **3m57s**. Ningun
navegador ni ningun usuario espera cuatro minutos con la pantalla en
blanco, asi que la subida devuelve un id al instante y el procesamiento se
va a un hilo.

Lo minimo y nada mas: un hilo por trabajo y un diccionario en memoria. Sin
cola persistente, sin Redis, sin Celery, sin reintentos, sin mas de un
trabajo en paralelo por diseno. Eso es 8b.

El diccionario de trabajos vive en `app.extensions`, no en un global de
modulo: dos apps no se pisan y no hay nada que se contamine entre
peticiones.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
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

_LOG = logging.getLogger(__name__)
_FIRMA_PDF = b"%PDF"
# Un documento contable de 968 paginas pesa ~9 MB; 64 deja margen de sobra
# sin permitir que una subida cualquiera llene el disco.
_MAXIMO = 64 * 1024 * 1024
# Media hora y se borra, descargue alguien o no. Son documentos contables de
# clientes de un despacho, y esto acabara en un servidor que tambien sirve
# produccion y que nadie reinicia en semanas: dejar PDFs ahi por si acaso no
# es una opcion. El barrido corre al servir cualquier peticion, sin
# scheduler ni proceso aparte.
_EDAD_MAXIMA = 30 * 60


@dataclass
class _Trabajo:
    """Un documento en proceso. Mutable: el hilo lo va actualizando.

    `estado` solo toma valores que la capa web puede OBSERVAR de verdad:
    'procesando', 'listo' y 'error'. No hay 'parseando' ni 'validando'
    porque `procesar_documento()` es una sola llamada opaca y afirmar una
    etapa que no se mide seria inventar un dato.
    """

    identificador: str
    tipo: str
    archivo: str
    directorio: Path
    comenzado: float
    estado: str = "procesando"
    resultado: object | None = None
    error: dict = field(default_factory=dict)
    xlsx: Path | None = None
    nombre_xlsx: str = ""

    @property
    def transcurrido(self) -> float:
        return time.monotonic() - self.comenzado

    @property
    def reloj(self) -> str:
        segundos = int(self.transcurrido)
        return f"{segundos // 60}:{segundos % 60:02d}"


def crear_app(*, trabajos: Path | None = None) -> Flask:
    """La app. `trabajos` es donde viven los temporales de cada subida."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = _MAXIMO
    raiz = (Path(trabajos) if trabajos is not None
            else Path(tempfile.gettempdir()) / "contapdf-web")
    raiz.mkdir(parents=True, exist_ok=True)
    app.config["CONTAPDF_TRABAJOS"] = raiz
    app.extensions["contapdf_trabajos"] = {}
    app.extensions["contapdf_candado"] = threading.Lock()

    def registro() -> dict:
        return app.extensions["contapdf_trabajos"]

    def barrer() -> None:
        """Borra lo que lleve mas de media hora, lo haya descargado o no."""
        with app.extensions["contapdf_candado"]:
            viejos = [i for i, t in registro().items()
                      if t.transcurrido > _EDAD_MAXIMA]
            for identificador in viejos:
                trabajo = registro().pop(identificador)
                _borrar(trabajo.directorio)
        if viejos:
            _LOG.info("barridos %s trabajo(s) de mas de %s min",
                      len(viejos), _EDAD_MAXIMA // 60)
        # Tambien los directorios sueltos: si el proceso se reinicio, el
        # registro se perdio pero los archivos del cliente no.
        for directorio in raiz.glob("trabajo-*"):
            try:
                edad = time.time() - directorio.stat().st_mtime
            except OSError:
                continue
            if edad > _EDAD_MAXIMA and directorio.name[8:] not in registro():
                _borrar(directorio)

    @app.before_request
    def _limpiar():
        barrer()

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
        if not any(tipo == n for n, _ in TIPOS_DE_DOCUMENTO):
            return _error(
                f"Tipo de documento no valido: {tipo!r}." if tipo
                else "No se eligio el tipo de documento.",
                "Selecciona uno de la lista."), 400

        identificador = uuid.uuid4().hex
        directorio = raiz / f"trabajo-{identificador}"
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
        trabajo = _Trabajo(identificador=identificador, tipo=tipo,
                           archivo=subido.filename, directorio=directorio,
                           comenzado=time.monotonic(),
                           xlsx=directorio / f"{nombre}.xlsx",
                           nombre_xlsx=f"{nombre}.xlsx")
        registro()[identificador] = trabajo

        hilo = threading.Thread(target=_correr, args=(trabajo, pdf),
                                name=f"contapdf-{identificador[:8]}",
                                daemon=True)
        hilo.start()
        # De inmediato: el usuario no espera cuatro minutos en blanco.
        return redirect(url_for("estado", identificador=identificador), code=302)

    @app.get("/trabajo/<identificador>")
    def estado(identificador):
        trabajo = registro().get(identificador)
        if trabajo is None:
            abort(404)
        if trabajo.estado == "procesando":
            return render_template("procesando.html", t=trabajo)
        if trabajo.estado == "error":
            return _error(trabajo.error["mensaje"],
                          trabajo.error.get("sugerencia", ""),
                          detalle=trabajo.error.get("detalle", ()),
                          clave=trabajo.error.get("clave", "")), 400
        return render_template("resultado.html", r=trabajo.resultado,
                               ficha=identificador, archivo=trabajo.archivo,
                               reloj=trabajo.reloj)

    @app.get("/descargar/<identificador>")
    def descargar(identificador):
        trabajo = registro().get(identificador)
        if (trabajo is None or trabajo.estado != "listo"
                or trabajo.xlsx is None or not trabajo.xlsx.exists()):
            abort(404)

        @after_this_request
        def limpiar(respuesta):
            # Al descargar no queda nada: ni el Excel ni su directorio.
            with app.extensions["contapdf_candado"]:
                registro().pop(identificador, None)
            _borrar(trabajo.directorio)
            return respuesta

        return send_file(trabajo.xlsx, as_attachment=True,
                         download_name=trabajo.nombre_xlsx)

    @app.errorhandler(413)
    def demasiado_grande(_):
        return _error("El archivo es demasiado grande.",
                      f"El limite son {_MAXIMO // (1024 * 1024)} MB."), 413

    return app


def _correr(trabajo: _Trabajo, pdf: Path) -> None:
    """El trabajo, en su hilo. No lanza: todo error acaba en el estado."""
    try:
        trabajo.resultado = procesar_documento(trabajo.tipo, pdf, trabajo.xlsx)
        trabajo.estado = "listo"
    except DocumentoNoReconocido as exc:
        trabajo.error = {"mensaje": str(exc),
                         "sugerencia": _sugerencia(trabajo.tipo, exc),
                         "detalle": exc.detalle, "clave": exc.clave}
        trabajo.estado = "error"
    except Exception:                       # nunca una traza en pantalla
        _LOG.exception("fallo procesando %s como %s",
                       trabajo.archivo, trabajo.tipo)
        trabajo.error = {
            "mensaje": "No se pudo procesar el documento.",
            "sugerencia": ("Quedo registrado en el log del servidor con el "
                           "detalle tecnico.")}
        trabajo.estado = "error"
    finally:
        # El PDF del cliente no se queda ni un minuto de mas: en cuanto el
        # nucleo termino de leerlo, fuera. El Excel sigue hasta la descarga
        # o hasta que lo barra el temporizador.
        _borrar(pdf)


def _error(mensaje: str, sugerencia: str = "", *, detalle=(), clave: str = ""):
    return render_template("error.html", mensaje=mensaje,
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
