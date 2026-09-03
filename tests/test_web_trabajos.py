"""El trabajo corre aparte y la pagina responde de inmediato.

Fase 8a. Medido en aislamiento: `auxiliar-gume.pdf` tarda **3m57s**. Ningun
navegador ni ningun usuario espera cuatro minutos con la pantalla en
blanco, asi que la subida no puede procesar de forma sincrona.

Lo minimo, y nada mas: un hilo por trabajo, un id que se devuelve al
instante, y una pagina que se refresca sola. Sin cola persistente, sin
Redis, sin Celery, sin reintentos. El registro de trabajos es un
diccionario en la capa web -- nunca en el nucleo, que no tiene estado.

La pagina de estado muestra el TIEMPO TRANSCURRIDO y nada mas. No hay
porcentaje ni barra: no existe forma de saber cuanto falta, y fabricar esa
cifra seria inventar un dato.
"""

from __future__ import annotations

import io
import re
import time

import pytest
from conftest import requires_real_pdf

from contapdf.web import crear_app


@pytest.fixture()
def app(tmp_path):
    aplicacion = crear_app(trabajos=tmp_path)
    aplicacion.config.update(TESTING=True)
    return aplicacion


@pytest.fixture()
def cliente(app):
    with app.test_client() as c:
        yield c


def _subir(cliente, fixture, tipo, nombre=None):
    ruta = requires_real_pdf(fixture)
    return cliente.post("/procesar", data={
        "tipo": tipo,
        "pdf": (io.BytesIO(ruta.read_bytes()), nombre or f"{fixture}.pdf"),
    }, content_type="multipart/form-data")


def _esperar(cliente, url, limite=180):
    """Sigue la pagina de estado hasta que el trabajo termina."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        respuesta = cliente.get(url)
        pagina = respuesta.get_data(as_text=True)
        if "http-equiv=\"refresh\"" not in pagina:
            return respuesta, pagina
        time.sleep(0.25)
    raise AssertionError(f"el trabajo no termino en {limite}s")


# --- Criterio 2: la subida responde de inmediato ------------------------
def test_la_subida_devuelve_un_id_de_trabajo_al_instante(cliente):
    inicio = time.monotonic()
    respuesta = _subir(cliente, "balanza", "balanza")
    transcurrido = time.monotonic() - inicio

    assert respuesta.status_code == 302
    assert re.match(r"^/trabajo/[0-9a-f]{8,}$",
                    respuesta.headers["Location"]), respuesta.headers["Location"]
    # La balanza tarda ~3s en procesarse; la respuesta no puede esperarlo.
    assert transcurrido < 1.5, f"la subida bloqueo {transcurrido:.1f}s"


def test_la_pagina_de_estado_se_refresca_sola_y_da_el_tiempo(app, cliente):
    """Un trabajo en curso: sin descarga todavia, con reloj."""
    from contapdf.web.app import _Trabajo

    registro = app.extensions["contapdf_trabajos"]
    registro["fingido"] = _Trabajo(
        identificador="fingido", tipo="auxiliar", archivo="grande.pdf",
        directorio=app.config["CONTAPDF_TRABAJOS"] / "fingido",
        comenzado=time.monotonic() - 95.0)

    pagina = cliente.get("/trabajo/fingido").get_data(as_text=True)
    assert 'http-equiv="refresh"' in pagina
    assert "1:35" in pagina, "falta el tiempo transcurrido"
    assert "/descargar/" not in pagina
    # Sin porcentaje inventado: se mira el cuerpo visible, no el CSS, que
    # usa 100% para los anchos.
    cuerpo = pagina.split("<main>")[1]
    assert not re.search(r"\d+\s*%", cuerpo), "hay un porcentaje de progreso"


def test_un_trabajo_que_no_existe_da_404(cliente):
    assert cliente.get("/trabajo/noexiste").status_code == 404


# --- El trabajo termina y la misma pagina muestra el resultado ----------
def test_al_terminar_la_misma_pagina_muestra_el_resultado(cliente):
    url = _subir(cliente, "balanza", "balanza").headers["Location"]
    _, pagina = _esperar(cliente, url)
    assert "cobertura" in pagina.lower()
    assert "/descargar/" in pagina
    assert 'http-equiv="refresh"' not in pagina


def test_el_xlsx_se_descarga_al_terminar(cliente):
    url = _subir(cliente, "balanza", "balanza").headers["Location"]
    _, pagina = _esperar(cliente, url)
    enlace = re.search(r'href="(/descargar/[^"]+)"', pagina).group(1)
    descarga = cliente.get(enlace)
    assert descarga.status_code == 200
    assert descarga.data[:2] == b"PK"


def test_un_documento_que_no_se_reconoce_termina_en_error_sin_traza(cliente):
    """El estado de cuenta enviado como balanza, por el camino asincrono."""
    url = _subir(cliente, "edocta", "balanza").headers["Location"]
    respuesta, pagina = _esperar(cliente, url)
    assert "Traceback" not in pagina
    assert "balanza" in pagina.lower()
    assert "/descargar/" not in pagina


# --- Criterio 5 (bis): el barrido de 30 minutos -------------------------
def test_un_trabajo_viejo_se_barre_aunque_nadie_descargue(app, cliente):
    """La red por si nadie descarga: son documentos de clientes."""
    from contapdf.web.app import _Trabajo, _EDAD_MAXIMA

    raiz = app.config["CONTAPDF_TRABAJOS"]
    viejo = raiz / "viejo"
    viejo.mkdir(parents=True)
    (viejo / "entrada.pdf").write_bytes(b"%PDF-1.4 datos del cliente")
    (viejo / "salida.xlsx").write_bytes(b"PK")

    registro = app.extensions["contapdf_trabajos"]
    registro["viejo"] = _Trabajo(
        identificador="viejo", tipo="balanza", archivo="v.pdf",
        directorio=viejo, comenzado=time.monotonic() - (_EDAD_MAXIMA + 60))

    # Cualquier peticion dispara el barrido: sin scheduler ni proceso aparte.
    cliente.get("/")

    assert not viejo.exists(), "el trabajo viejo sigue en disco"
    assert "viejo" not in registro


def test_un_trabajo_reciente_no_se_barre(app, cliente):
    from contapdf.web.app import _Trabajo

    raiz = app.config["CONTAPDF_TRABAJOS"]
    nuevo = raiz / "nuevo"
    nuevo.mkdir(parents=True)
    (nuevo / "entrada.pdf").write_bytes(b"%PDF-1.4")
    registro = app.extensions["contapdf_trabajos"]
    registro["nuevo"] = _Trabajo(
        identificador="nuevo", tipo="balanza", archivo="n.pdf",
        directorio=nuevo, comenzado=time.monotonic() - 60.0)

    cliente.get("/")
    assert nuevo.exists()
    assert "nuevo" in registro


def test_el_barrido_no_estorba_a_un_trabajo_en_curso(app, cliente):
    url = _subir(cliente, "balanza", "balanza").headers["Location"]
    cliente.get("/")            # barrido mientras el trabajo corre
    _, pagina = _esperar(cliente, url)
    assert "/descargar/" in pagina


def test_la_edad_maxima_son_treinta_minutos():
    from contapdf.web.app import _EDAD_MAXIMA

    assert _EDAD_MAXIMA == 30 * 60


# --- El PDF del cliente no se queda en disco ---------------------------
def test_el_pdf_se_borra_en_cuanto_termina_el_procesamiento(app, cliente):
    url = _subir(cliente, "balanza", "balanza").headers["Location"]
    _esperar(cliente, url)
    raiz = app.config["CONTAPDF_TRABAJOS"]
    assert list(raiz.rglob("*.pdf")) == []


def test_al_descargar_no_queda_nada(app, cliente):
    url = _subir(cliente, "balanza", "balanza").headers["Location"]
    _, pagina = _esperar(cliente, url)
    enlace = re.search(r'href="(/descargar/[^"]+)"', pagina).group(1)
    assert cliente.get(enlace).status_code == 200
    raiz = app.config["CONTAPDF_TRABAJOS"]
    assert list(raiz.rglob("*.xlsx")) == []
    assert list(raiz.rglob("*.pdf")) == []


# --- El registro vive en la app, no en un global -----------------------
def test_dos_apps_no_comparten_trabajos(tmp_path):
    una = crear_app(trabajos=tmp_path / "a")
    otra = crear_app(trabajos=tmp_path / "b")
    assert una.extensions["contapdf_trabajos"] is not \
        otra.extensions["contapdf_trabajos"]
