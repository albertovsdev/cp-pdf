"""La web sobre la cola: worker secuencial, tenants y reinicio.

Fase 8b. El tenant llega por RUTA (`/t/<despacho>/…`), no por login: esta
fase no trae autenticacion. Eso significa que el aislamiento es
organizativo, no de seguridad -- quien conozca el nombre de otro despacho
entra en su area. Lo que si garantiza es que **un id de trabajo no sirve
fuera de su despacho**, que es lo que evita que una URL compartida por
error filtre el documento de otro cliente.
"""

from __future__ import annotations

import io
import re
import time

import pytest
from conftest import requires_real_pdf

from contapdf.web import crear_app
from contapdf.web.cola import (
    CON_DISCREPANCIAS,
    INTERRUMPIDO,
    LISTO,
    NO_RECONOCIDO,
)


@pytest.fixture()
def app(tmp_path):
    aplicacion = crear_app(trabajos=tmp_path)
    aplicacion.config.update(TESTING=True)
    return aplicacion


@pytest.fixture()
def cliente(app):
    with app.test_client() as c:
        yield c


def _subir(cliente, fixture, tipo, tenant="despacho-a"):
    ruta = requires_real_pdf(fixture)
    return cliente.post(f"/t/{tenant}/procesar", data={
        "tipo": tipo,
        "pdf": (io.BytesIO(ruta.read_bytes()), f"{fixture}.pdf"),
    }, content_type="multipart/form-data")


def _esperar(cliente, url, limite=180):
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        respuesta = cliente.get(url)
        if 'http-equiv="refresh"' not in respuesta.get_data(as_text=True):
            return respuesta
        time.sleep(0.2)
    raise AssertionError(f"el trabajo no termino en {limite}s")


# --- Criterio 3: un tenant no alcanza lo de otro ------------------------
def test_un_tenant_no_puede_leer_el_trabajo_de_otro(cliente):
    url = _subir(cliente, "balanza", "balanza", tenant="despacho-a") \
        .headers["Location"]
    identificador = url.rstrip("/").rsplit("/", 1)[-1]

    assert cliente.get(url).status_code == 200
    # El mismo id, colgado de otro despacho: no existe para el.
    ajeno = cliente.get(f"/t/despacho-b/trabajo/{identificador}")
    assert ajeno.status_code == 404


def test_un_tenant_no_puede_descargar_lo_de_otro(cliente):
    url = _subir(cliente, "balanza", "balanza", tenant="despacho-a") \
        .headers["Location"]
    pagina = _esperar(cliente, url).get_data(as_text=True)
    enlace = re.search(r'href="(/t/[^"]*/descargar/[^"]+)"', pagina).group(1)

    # El cruzado va PRIMERO: la descarga es de un solo uso y borra el
    # trabajo, asi que despues el 404 saldria por el motivo equivocado.
    cruzado = enlace.replace("/t/despacho-a/", "/t/despacho-b/")
    assert cliente.get(cruzado).status_code == 404
    assert cliente.get(enlace).status_code == 200


def test_las_plantillas_de_un_despacho_no_son_de_otro(app, cliente):
    """Cada despacho aprende sus formatos por separado (PLAN 0)."""
    _esperar(cliente, _subir(cliente, "balanza", "balanza",
                             tenant="despacho-a").headers["Location"])
    raiz = app.config["CONTAPDF_TRABAJOS"]
    plantillas = list((raiz / "plantillas").rglob("*.json"))
    assert plantillas, "no se aprendio ninguna plantilla"
    assert all("despacho-a" in str(p) for p in plantillas)
    assert not any("despacho-b" in str(p) for p in plantillas)


def test_la_lista_de_un_despacho_solo_trae_lo_suyo(cliente):
    _subir(cliente, "balanza", "balanza", tenant="despacho-a")
    _esperar(cliente, "/t/despacho-a/")
    pagina_b = cliente.get("/t/despacho-b/").get_data(as_text=True)
    assert "balanza.pdf" not in pagina_b


@pytest.mark.parametrize("malo", ["../otro", "con espacio", "a" * 100])
def test_un_despacho_con_nombre_peligroso_se_rechaza(cliente, malo):
    respuesta = cliente.get(f"/t/{malo}/")
    assert respuesta.status_code in (400, 404)
    assert "Traceback" not in respuesta.get_data(as_text=True)


# --- Criterio 2: uno a la vez, con posicion -----------------------------
def test_el_segundo_trabajo_espera_y_ve_su_posicion(cliente):
    primero = _subir(cliente, "balanza-gume", "balanza").headers["Location"]
    segundo = _subir(cliente, "balanza", "balanza").headers["Location"]

    pagina = cliente.get(segundo).get_data(as_text=True)
    assert 'http-equiv="refresh"' in pagina
    plano = pagina.lower()
    assert "cola" in plano or "espera" in plano
    assert "1" in pagina, "no se ve la posicion"

    _esperar(cliente, primero, limite=240)
    assert _esperar(cliente, segundo, limite=240).status_code == 200


def test_solo_un_documento_se_procesa_a_la_vez(app, cliente):
    """PLAN 6: 543 MB de pico en una maquina de 8 GB compartida."""
    from contapdf.web.cola import PROCESANDO

    _subir(cliente, "balanza-gume", "balanza")
    _subir(cliente, "balanza", "balanza")
    _subir(cliente, "balanza-businesspro", "balanza")
    time.sleep(0.6)
    cola = app.extensions["contapdf_cola"]
    en_curso = [t for t in cola.listar("despacho-a") if t.estado == PROCESANDO]
    assert len(en_curso) <= 1, [t.archivo for t in en_curso]


# --- Criterio 1: el reinicio no produce 404 -----------------------------
def test_un_trabajo_interrumpido_lo_dice_en_vez_de_dar_404(tmp_path):
    """Se simula el reinicio: la cola se reabre sobre la misma base."""
    from contapdf.web.cola import Cola

    primera = crear_app(trabajos=tmp_path)
    primera.config.update(TESTING=True)
    cola = primera.extensions["contapdf_cola"]
    trabajo = cola.encolar(tenant="despacho-a", tipo="balanza",
                           archivo="a.pdf")
    cola.marcar_procesando(trabajo.identificador)
    cola.cerrar()

    segunda = crear_app(trabajos=tmp_path)   # como si el servidor arrancara
    segunda.config.update(TESTING=True)
    with segunda.test_client() as c:
        respuesta = c.get(f"/t/despacho-a/trabajo/{trabajo.identificador}")
        assert respuesta.status_code == 200, "un trabajo interrumpido no es un 404"
        plano = respuesta.get_data(as_text=True).lower()
        assert "interrump" in plano
        assert "vuelve a subirlo" in plano
    assert segunda.extensions["contapdf_cola"].buscar(
        trabajo.identificador, tenant="despacho-a").estado == INTERRUMPIDO


def test_un_trabajo_que_nunca_existio_sigue_dando_404(cliente):
    assert cliente.get("/t/despacho-a/trabajo/" + "0" * 32).status_code == 404


# --- Criterio 5: los tres finales se distinguen en la cola --------------
def test_un_documento_que_cuadra_queda_listo(app, cliente):
    url = _subir(cliente, "balanza", "balanza").headers["Location"]
    _esperar(cliente, url)
    identificador = url.rstrip("/").rsplit("/", 1)[-1]
    cola = app.extensions["contapdf_cola"]
    assert cola.buscar(identificador, tenant="despacho-a").estado == LISTO


def test_un_documento_no_reconocido_no_se_confunde_con_un_exito(app, cliente):
    url = _subir(cliente, "edocta-multiva", "estado-cuenta").headers["Location"]
    _esperar(cliente, url)
    identificador = url.rstrip("/").rsplit("/", 1)[-1]
    cola = app.extensions["contapdf_cola"]
    trabajo = cola.buscar(identificador, tenant="despacho-a")
    assert trabajo.estado == NO_RECONOCIDO
    assert trabajo.estado != LISTO
    assert not trabajo.entrega          # no hay Excel que descargar


@pytest.mark.lento
def test_un_documento_con_discrepancias_se_distingue_del_que_cuadra(app, cliente):
    url = _subir(cliente, "poliza", "polizas").headers["Location"]
    pagina = _esperar(cliente, url, limite=300).get_data(as_text=True)
    identificador = url.rstrip("/").rsplit("/", 1)[-1]
    trabajo = app.extensions["contapdf_cola"].buscar(
        identificador, tenant="despacho-a")
    assert trabajo.estado == CON_DISCREPANCIAS
    assert trabajo.entrega              # se descarga igual
    assert "53" in pagina
    assert "no permite verificar" in pagina.lower()


# --- Criterio 4: el barrido sigue valiendo -----------------------------
def test_el_barrido_limpia_los_trabajos_viejos(app, cliente):
    url = _subir(cliente, "balanza", "balanza").headers["Location"]
    _esperar(cliente, url)
    identificador = url.rstrip("/").rsplit("/", 1)[-1]
    cola = app.extensions["contapdf_cola"]
    cola.envejecer(identificador, segundos=31 * 60)

    cliente.get("/t/despacho-a/")        # cualquier peticion barre
    assert cola.buscar(identificador, tenant="despacho-a") is None
    assert cliente.get(url).status_code == 404


# --- El worker no puede dejar un trabajo dormido -----------------------
def test_un_trabajo_encolado_sin_worker_se_atiende_igual(app, cliente):
    """Nadie sube por la ruta, pero la cola tiene trabajo.

    El worker vive mientras haya cola y muere al vaciarla. Entre el ultimo
    `tomar_siguiente()` y el momento en que suelta el candado cabe una
    subida: si nadie lo vuelve a arrancar, ese trabajo se queda en cola
    hasta que el barrido lo borre a la media hora, sin haberse procesado
    nunca y sin que nadie se entere. Cualquier peticion tiene que re-armarlo.
    """
    from contapdf.web.cola import EN_COLA

    cola = app.extensions["contapdf_cola"]
    ruta = requires_real_pdf("balanza")
    trabajo = cola.encolar(tenant="despacho-a", tipo="balanza",
                           archivo="balanza.pdf")
    (trabajo.directorio / "entrada.pdf").write_bytes(ruta.read_bytes())
    assert cola.buscar(trabajo.identificador, tenant="despacho-a").estado == EN_COLA

    cliente.get("/t/despacho-a/")        # una peticion cualquiera
    fin = time.monotonic() + 60
    while time.monotonic() < fin:
        estado = cola.buscar(trabajo.identificador, tenant="despacho-a").estado
        if estado not in (EN_COLA, "procesando"):
            break
        time.sleep(0.2)
    assert estado == LISTO, f"el trabajo se quedo en {estado!r}"
