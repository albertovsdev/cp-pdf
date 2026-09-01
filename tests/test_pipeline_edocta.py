"""El estado de cuenta tambien se aprende como plantilla.

Fase 7d: el eje de la plantilla NO es el banco, es (banco, tipo de
reporte). Los dos Santander son el mismo banco con estructuras
incomparables, y los dos Banorte igual.
"""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.pipeline import procesar_estado_cuenta
from contapdf.templates.store import AlmacenPlantillas

_CON_TABLA = ("edocta", "edocta-abril-santander", "edocta-julio-banorte",
              "edocta-bajio", "edocta-inbursa", "edocta-bbva")


# --- Criterio 5 ---------------------------------------------------------
def test_aprende_la_plantilla_y_declara_lo_no_cubierto(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    r = procesar_estado_cuenta(requires_real_pdf("edocta"), tenant_id="t",
                               almacen=almacen)
    assert r.plantilla is not None
    assert r.plantilla.tipo == "estado_cuenta"
    assert r.plantilla.cobertura["sin_cubrir"]
    assert any("continuacion" in s.lower()
               for s in r.plantilla.cobertura["sin_cubrir"])


def test_la_segunda_carga_reutiliza(tmp_path):
    almacen = AlmacenPlantillas(tmp_path)
    pdf = requires_real_pdf("edocta")
    primera = procesar_estado_cuenta(pdf, tenant_id="t", almacen=almacen)
    segunda = procesar_estado_cuenta(pdf, tenant_id="t", almacen=almacen)
    assert segunda.reutilizada is True
    assert segunda.estado.movimientos == primera.estado.movimientos


def test_sin_almacen_funciona_igual():
    r = procesar_estado_cuenta(requires_real_pdf("edocta"))
    assert r.plantilla is None
    assert len(r.estado.movimientos) == 45
    assert r.cobertura.fallan == 0


# --- Criterio 6: una huella por (banco, tipo de reporte) ----------------
@pytest.fixture(scope="module")
def huellas():
    return {n: procesar_estado_cuenta(requires_real_pdf(n)).huella
            for n in _CON_TABLA}


def test_cada_formato_tiene_su_propia_huella(huellas):
    valores = {n: h.valor for n, h in huellas.items()}
    assert all(valores.values())
    assert len(set(valores.values())) == len(_CON_TABLA), valores


def test_la_huella_sale_del_vocabulario_del_encabezado(huellas):
    # Inbursa dice CARGOS/ABONOS donde AFIRME dice Depositos/Retiros: es lo
    # que separa los formatos sin mirar ni un dato del cliente.
    assert "cargos" in huellas["edocta-inbursa"].tokens
    assert "abonos" in huellas["edocta-inbursa"].tokens
    assert "depositos" in huellas["edocta"].tokens
    assert "retiros" in huellas["edocta"].tokens


def test_la_huella_no_mira_datos_volatiles(huellas):
    for nombre, huella in huellas.items():
        plano = " ".join(huella.tokens).lower()
        for volatil in ("rfc", "2022", "2025", "clabe"):
            assert volatil not in plano, (nombre, huella.tokens)


def test_los_dos_santander_no_comparten_huella():
    """Mismo banco, dos tipos de reporte: no pueden colisionar."""
    abril = procesar_estado_cuenta(requires_real_pdf("edocta-abril-santander"))
    integral = procesar_estado_cuenta(requires_real_pdf("edocta-santander"))
    assert abril.huella.valor != integral.huella.valor


# --- Criterio 5: cobertura completa en cada uno -------------------------
@pytest.mark.parametrize("nombre", _CON_TABLA)
def test_ningun_banco_entrega_con_reglas_en_falla(nombre):
    r = procesar_estado_cuenta(requires_real_pdf(nombre))
    assert r.cobertura.fallan == 0, r.cobertura.resumen()
    assert len(r.cobertura.reglas) == 4
    # Lo que no se pudo comprobar viene con su motivo, nunca en blanco.
    for regla in r.cobertura.reglas:
        if regla.estado == "no_verificable":
            assert regla.motivo, (nombre, regla.regla)


# --- Fase 7e: el separador de continuacion lo confirma un humano ---------
def test_la_plantilla_pregunta_por_el_separador_sin_proponer(tmp_path):
    """La geometria NO distingue los dos modos de envolver (PLAN 2).

    Se midio la varianza de x1 del ultimo token de cada linea llena y el
    discriminador no existe: el documento que SI parte palabras es el que
    peor puntua. Asi que la plantilla pregunta, y no propone nada.
    """
    almacen = AlmacenPlantillas(tmp_path)
    r = procesar_estado_cuenta(requires_real_pdf("edocta"), tenant_id="t",
                               almacen=almacen)
    pendientes = r.plantilla.pendientes()
    separador = next(p for p in pendientes
                     if p["campo"] == "separador de continuacion")
    assert separador["se_propone"] is None
    assert "geometr" in separador["se_apoya_en"].lower()
    assert "descripcion" in separador["consecuencia"].lower()
    assert r.plantilla.pendiente_de_confirmacion is True


def test_el_separador_confirmado_se_aplica_en_la_carga_siguiente(tmp_path):
    """Una vez contestado, el formato ya no vuelve a preguntar."""
    import dataclasses

    almacen = AlmacenPlantillas(tmp_path)
    pdf = requires_real_pdf("edocta")
    primera = procesar_estado_cuenta(pdf, tenant_id="t", almacen=almacen)
    assert primera.plantilla.separador_continuacion == ""

    elegido = dataclasses.replace(primera.plantilla, separador_continuacion=" ",
                                  pendiente_de_confirmacion=False,
                                  confirmada_por="contadora")
    almacen.guardar(elegido)

    segunda = procesar_estado_cuenta(pdf, tenant_id="t", almacen=almacen)
    assert segunda.reutilizada is True
    spei = next(m for m in segunda.estado.movimientos
                if m.dia == "07" and "BANORTE" in m.descripcion)
    # Con separador " " la palabra partida sale separada; es exactamente la
    # decision que el humano tomo, y el sistema la respeta.
    assert "CON CEPTO:FACTURA" in spei.descripcion


def test_sin_plantilla_el_separador_es_el_medido_en_el_primer_formato():
    r = procesar_estado_cuenta(requires_real_pdf("edocta"))
    spei = next(m for m in r.estado.movimientos
                if m.dia == "07" and "BANORTE" in m.descripcion)
    assert "CONCEPTO:FACTURA 1766" in spei.descripcion
