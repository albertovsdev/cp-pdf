"""Un formato desconocido se resuelve una vez y queda aprendido."""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.pipeline import procesar_balanza
from contapdf.templates.store import AlmacenPlantillas


# --- Criterio 2: primera carga ------------------------------------------
def test_primera_carga_de_gume_crea_la_plantilla(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    r = procesar_balanza(requires_real_pdf("balanza-gume"),
                         tenant_id="despacho-a", almacen=almacen)

    assert r.reutilizada is False
    assert r.plantilla is not None
    assert almacen.buscar("despacho-a", r.plantilla.huella) == r.plantilla


def test_gume_queda_pendiente_de_confirmacion_por_la_orientacion(tmp_path):
    r = procesar_balanza(requires_real_pdf("balanza-gume"),
                         tenant_id="despacho-a", almacen=AlmacenPlantillas(tmp_path))
    assert r.plantilla.pendiente_de_confirmacion is True
    assert r.plantilla.verificado_por == "vocabulario"
    assert r.plantilla.orientacion_verificada is False
    assert r.plantilla.filas_afectadas == 96


def test_lo_que_hay_que_confirmar_es_serializable(tmp_path):
    # La UI llega en la fase 8: aqui solo tiene que salir como datos.
    r = procesar_balanza(requires_real_pdf("balanza-gume"),
                         tenant_id="despacho-a", almacen=AlmacenPlantillas(tmp_path))
    pendiente = r.plantilla.que_confirmar()
    assert pendiente["campo"] == "orientacion debe/haber"
    assert pendiente["se_apoya_en"] == "vocabulario"
    assert "96" in str(pendiente["consecuencia"])


def test_la_balanza_original_no_queda_pendiente(tmp_path):
    r = procesar_balanza(requires_real_pdf("balanza"),
                         tenant_id="despacho-a", almacen=AlmacenPlantillas(tmp_path))
    assert r.plantilla.pendiente_de_confirmacion is False
    assert r.plantilla.verificado_por == "aritmetica"
    assert r.plantilla.que_confirmar() is None


# --- Criterio 3: segunda carga ------------------------------------------
def test_segunda_carga_reutiliza_la_plantilla(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    pdf = requires_real_pdf("balanza-gume")
    primera = procesar_balanza(pdf, tenant_id="despacho-a", almacen=almacen)
    segunda = procesar_balanza(pdf, tenant_id="despacho-a", almacen=almacen)

    assert segunda.reutilizada is True
    assert segunda.plantilla.huella == primera.plantilla.huella
    assert [f.cuenta for f in segunda.balanza.filas] == \
           [f.cuenta for f in primera.balanza.filas]
    assert segunda.balanza.mapeo.campos == primera.balanza.mapeo.campos
    assert segunda.cobertura.resumen() == primera.cobertura.resumen()


def test_la_segunda_carga_no_vuelve_a_proponer_mapeos(tmp_path, monkeypatch):
    almacen = AlmacenPlantillas(tmp_path)
    pdf = requires_real_pdf("balanza-gume")
    procesar_balanza(pdf, tenant_id="despacho-a", almacen=almacen)

    import contapdf.parsers.balanza as modulo

    def prohibido(*a, **k):
        raise AssertionError("volvio a proponer mapeos con la plantilla guardada")

    monkeypatch.setattr(modulo, "proponer_mapeos", prohibido)
    r = procesar_balanza(pdf, tenant_id="despacho-a", almacen=almacen)
    assert r.reutilizada is True
    assert len(r.balanza.filas) == 734


def test_la_plantilla_de_un_tenant_no_sirve_para_otro(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    pdf = requires_real_pdf("balanza-gume")
    procesar_balanza(pdf, tenant_id="despacho-a", almacen=almacen)
    r = procesar_balanza(pdf, tenant_id="despacho-b", almacen=almacen)
    assert r.reutilizada is False


def test_sin_almacen_todo_sigue_funcionando(tmp_path):
    r = procesar_balanza(requires_real_pdf("balanza"))
    assert r.plantilla is None
    assert len(r.balanza.filas) == 475


# --- Criterio 7 ---------------------------------------------------------
@pytest.mark.parametrize(("nombre", "filas"), [
    ("balanza", 475), ("balanza-businesspro", 225), ("balanza-gume", 734)])
def test_los_tres_documentos_siguen_igual(tmp_path, nombre, filas):
    almacen = AlmacenPlantillas(tmp_path)
    r = procesar_balanza(requires_real_pdf(nombre), tenant_id="t", almacen=almacen)
    assert len(r.balanza.filas) == filas
    assert r.cobertura.fallan == 0


def test_la_plantilla_guarda_todo_lo_que_varia_por_formato(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    r = procesar_balanza(requires_real_pdf("balanza-businesspro"),
                         tenant_id="t", almacen=almacen)
    p = r.plantilla
    assert p.estrategia == "pdf_chars"
    assert p.forma == "saldo_con_signo"
    assert p.mapeo["debe"] != p.mapeo["haber"]
    assert p.esquema["separador"] == "-"
    assert p.reglas["exige_partida_doble"] is False   # no la declara
    assert p.cobertura["no_verificables"] == 1
