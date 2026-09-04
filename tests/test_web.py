"""La capa web: subir un PDF, procesarlo, descargar el Excel.

Fase 8a. Una interfaz minima sobre el nucleo que YA existe: no agrega
capacidades de extraccion ni de validacion. Un documento a la vez, un solo
usuario, en la maquina de desarrollo.

El procesamiento corre en un hilo aparte (ver `test_web_trabajos.py`);
estos tests siguen la pagina de estado hasta el final para comprobar el
resultado.

Lo que esta fase tiene que dejar claro en pantalla es la diferencia entre
«fallo el procesamiento» y «el documento no permite verificar N casos».
Polizas es el ejemplo: sale con 53 discrepancias que NO son un error de la
herramienta, son su producto -- 53 renglones que el contador tiene que
revisar.
"""

from __future__ import annotations

import io
import re
import time

import pytest
from conftest import requires_real_pdf

from contapdf.web import crear_app

TENANT = "despacho-a"


@pytest.fixture()
def cliente(tmp_path):
    # Cada prueba con su propia raiz: desde la 8b la cola persiste en disco,
    # y una raiz compartida arrastraria trabajos de una corrida a otra.
    app = crear_app(trabajos=tmp_path)
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


def _subir(cliente, nombre_fixture, tipo, nombre_archivo=None):
    """Sube y espera a que el trabajo termine.

    Desde que el procesamiento corre en un hilo, la subida devuelve un 302
    al instante; estos tests quieren la pagina final, asi que siguen la de
    estado hasta que deja de refrescarse.
    """
    ruta = requires_real_pdf(nombre_fixture)
    datos = {
        "tipo": tipo,
        "pdf": (io.BytesIO(ruta.read_bytes()),
                nombre_archivo or f"{nombre_fixture}.pdf"),
    }
    respuesta = cliente.post(f"/t/{TENANT}/procesar", data=datos,
                             content_type="multipart/form-data")
    if respuesta.status_code != 302:
        return respuesta
    return _esperar(cliente, respuesta.headers["Location"])


def _esperar(cliente, url, limite=300):
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        respuesta = cliente.get(url)
        if 'http-equiv="refresh"' not in respuesta.get_data(as_text=True):
            return respuesta
        time.sleep(0.25)
    raise AssertionError(f"el trabajo no termino en {limite}s")


# --- Criterio 1: los cinco tipos, de punta a punta ----------------------
def test_la_portada_ofrece_los_cinco_tipos(cliente):
    texto = cliente.get(f"/t/{TENANT}/").get_data(as_text=True)
    assert cliente.get(f"/t/{TENANT}/").status_code == 200
    for tipo in ("balanza", "auxiliar", "polizas", "estado-cuenta", "mayor"):
        assert tipo in texto, tipo


@pytest.mark.lento
@pytest.mark.parametrize("fixture,tipo", [
    ("balanza", "balanza"),
    ("auxiliar", "auxiliar"),
    ("poliza", "polizas"),
    ("edocta", "estado-cuenta"),
    ("mayor-gume", "mayor"),
])
def test_los_cinco_se_procesan_y_se_descargan(cliente, fixture, tipo):
    respuesta = _subir(cliente, fixture, tipo)
    assert respuesta.status_code == 200
    pagina = respuesta.get_data(as_text=True)
    assert "cobertura" in pagina.lower()

    enlace = _enlace_de_descarga(pagina)
    descarga = cliente.get(enlace)
    assert descarga.status_code == 200
    assert descarga.data[:2] == b"PK"          # un .xlsx es un zip
    assert len(descarga.data) > 4000


def _enlace_de_descarga(pagina):
    import re
    encontrado = re.search(r'href="(/t/[^"]+/descargar/[^"]+)"', pagina)
    assert encontrado, "la pagina de resultado no ofrece descarga"
    return encontrado.group(1)


# --- Criterio 2: la cobertura de la pagina es la del CLI ----------------
@pytest.mark.lento          # 3 s
def test_la_cobertura_de_la_pagina_es_la_misma_que_la_del_cli(cliente):
    """Mismo documento, mismas cifras. Si divergen, hay logica duplicada."""
    from contapdf.cli import procesar_documento

    respuesta = _subir(cliente, "balanza", "balanza")
    pagina = respuesta.get_data(as_text=True)

    resultado = procesar_documento("balanza", requires_real_pdf("balanza"))
    for regla in resultado.cobertura.reglas:
        assert regla.regla in pagina
        assert f"{regla.evaluados} de {regla.aplicables}" in pagina, regla.regla
        assert str(regla.exactas) in pagina


def test_la_pagina_parte_las_exactas_impresas_de_las_recalculadas(cliente):
    """Lo que la fase 7h hizo visible no puede perderse en la interfaz."""
    respuesta = _subir(cliente, "balanza", "balanza")
    pagina = respuesta.get_data(as_text=True).lower()
    assert "impres" in pagina
    assert "recalculad" in pagina


def test_la_pagina_dice_que_estrategia_uso_y_por_que(cliente):
    respuesta = _subir(cliente, "balanza-businesspro", "balanza")
    pagina = respuesta.get_data(as_text=True)
    assert "pdf_chars" in pagina
    assert "contaminado" in pagina or "encimado" in pagina


def test_la_pagina_dice_si_aprendio_plantilla(cliente):
    respuesta = _subir(cliente, "balanza", "balanza")
    assert "plantilla" in respuesta.get_data(as_text=True).lower()


# --- Criterio 3: un documento con fallas se entrega igual ---------------
@pytest.mark.lento
def test_polizas_se_descarga_con_sus_fallas_visibles(cliente):
    respuesta = _subir(cliente, "poliza", "polizas")
    assert respuesta.status_code == 200
    pagina = respuesta.get_data(as_text=True)

    # Se descarga igual: la validacion en rojo no bloquea la entrega.
    assert cliente.get(_enlace_de_descarga(pagina)).status_code == 200
    assert "53" in pagina
    # Y se distingue de un fallo de la herramienta.
    plano = pagina.lower()
    assert "no permite verificar" in plano or "revisar" in plano
    assert "error" not in plano.split("cobertura")[0].lower()


@pytest.mark.lento
def test_un_documento_con_fallas_no_aprende_plantilla(cliente, tmp_path):
    from contapdf.cli import procesar_documento

    resultado = procesar_documento("polizas", requires_real_pdf("poliza"))
    assert resultado.cobertura.fallan > 0
    assert resultado.plantilla is None


# --- Criterio 4: los errores del usuario dan un mensaje util ------------
def test_un_archivo_que_no_es_pdf_da_un_mensaje(cliente):
    datos = {"tipo": "balanza",
             "pdf": (io.BytesIO(b"esto no es un pdf"), "notas.txt")}
    respuesta = cliente.post(f"/t/{TENANT}/procesar", data=datos,
                             content_type="multipart/form-data")
    pagina = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 400
    assert "pdf" in pagina.lower()
    assert "Traceback" not in pagina


def test_un_pdf_que_no_es_del_tipo_elegido_da_un_mensaje(cliente):
    """Un estado de cuenta enviado como balanza."""
    respuesta = _subir(cliente, "edocta", "balanza")
    pagina = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 400
    assert "Traceback" not in pagina
    assert "balanza" in pagina.lower()


def test_un_estado_de_cuenta_sin_tabla_explica_que_es(cliente):
    """El ReporteNoEsperado de la 7d tiene que llegar a la pantalla."""
    respuesta = _subir(cliente, "edocta-multiva", "estado-cuenta")
    pagina = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 400
    assert "movimiento" in pagina.lower()
    assert "Traceback" not in pagina


def test_sin_archivo_da_un_mensaje(cliente):
    respuesta = cliente.post(f"/t/{TENANT}/procesar", data={"tipo": "balanza"},
                             content_type="multipart/form-data")
    assert respuesta.status_code == 400
    assert "Traceback" not in respuesta.get_data(as_text=True)


def test_un_tipo_desconocido_da_un_mensaje(cliente):
    datos = {"tipo": "inventado",
             "pdf": (io.BytesIO(b"%PDF-1.4"), "x.pdf")}
    respuesta = cliente.post(f"/t/{TENANT}/procesar", data=datos,
                             content_type="multipart/form-data")
    assert respuesta.status_code == 400
    assert "Traceback" not in respuesta.get_data(as_text=True)


# --- Criterio 5: la web habla con el nucleo por la superficie del CLI ---
def test_la_web_no_importa_el_nucleo_por_dentro():
    """Parsers, reglas y exportadores se alcanzan por la misma puerta que
    usa el CLI. Si la web los importa directo, la logica se duplica."""
    import ast
    import pathlib

    import contapdf.web as paquete

    raiz = pathlib.Path(paquete.__file__).parent
    prohibidos = ("contapdf.parsers", "contapdf.validate", "contapdf.export",
                  "contapdf.pipeline", "contapdf.extract", "contapdf.templates",
                  "contapdf.recalculo", "contapdf.reintento", "contapdf.layout")
    for archivo in raiz.rglob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            modulos = []
            if isinstance(nodo, ast.Import):
                modulos = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                modulos = [nodo.module]
            for modulo in modulos:
                assert not any(modulo.startswith(p) for p in prohibidos), (
                    f"{archivo.name} importa {modulo}: la web tiene que "
                    "hablar con el nucleo por la superficie del CLI")


def test_la_web_no_imprime():
    import ast
    import pathlib

    import contapdf.web as paquete

    for archivo in pathlib.Path(paquete.__file__).parent.rglob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and getattr(nodo.func, "id", "") == "print":
                raise AssertionError(f"{archivo.name} imprime a stdout")


# --- Criterio 5 (bis): nada se queda en disco --------------------------
def test_el_pdf_subido_y_el_xlsx_se_borran(tmp_path):
    app = crear_app(trabajos=tmp_path)
    app.config.update(TESTING=True)
    with app.test_client() as c:
        pagina = _subir(c, "balanza", "balanza").get_data(as_text=True)
        enlace = _enlace_de_descarga(pagina)
        assert c.get(enlace).status_code == 200
        # La descarga es de un solo uso: despues no queda nada en disco.
        assert c.get(enlace).status_code == 404
    assert list(tmp_path.rglob("*.pdf")) == []
    assert list(tmp_path.rglob("*.xlsx")) == []


@pytest.mark.lento          # 3 s
def test_la_pagina_muestra_el_resumen_de_cobertura_entero(cliente):
    """Incluido el aviso de circularidad cuando el documento lo tenga.

    Se compara la cadena completa que produce `Cobertura.resumen()`: si la
    plantilla la recortara, el «OJO: N comprobaciones cayeron sobre saldos
    recalculados» se perderia justo en los documentos donde importa.
    """
    from contapdf.cli import procesar_documento

    pagina = _subir(cliente, "balanza", "balanza").get_data(as_text=True)
    resultado = procesar_documento("balanza", requires_real_pdf("balanza"))
    assert resultado.cobertura.resumen() in pagina


def test_una_discrepancia_sin_importes_no_finge_cifras(cliente):
    """`cfdi_cruzado` cruza identidades, no montos: sus dos cifras son 0."""
    respuesta = _subir(cliente, "edocta", "estado-cuenta")
    assert respuesta.status_code == 200
    # El documento cuadra, asi que no hay tabla de revision; lo que se
    # comprueba es que la plantilla no imprime un 0.00 inventado.
    assert "0.00   obtenido" not in respuesta.get_data(as_text=True)
