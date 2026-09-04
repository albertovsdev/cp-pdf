"""El signo del saldo corrido se deriva, nunca se cablea.

Fase 7g, arreglo 1. `_saldo_corrido` del auxiliar fijaba la identidad
deudora `saldo + debe - haber`, y con eso le hacia la pregunta equivocada a
las 44 cuentas acreedoras del fixture: 3,585 fallas sobre un documento que
se lee perfecto.

Cuarta aparicion del principio de PLAN 2: «nunca fijar el signo de una
identidad de saldo; derivar la naturaleza por renglon o por cuenta». Las
tres anteriores fueron la balanza Business Pro, la balanza GUME y el libro
mayor.

La naturaleza se decide POR CUENTA y por MAYORIA de los renglones que la
revelan, que es el criterio que ya usa `MayorParser._naturaleza`. Un
renglon con `debe == haber` no revela nada porque las dos identidades lo
cumplen, y por eso no vota.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.parsers.auxiliar import IMPRESO, Auxiliar, FilaAuxiliar
from contapdf.pipeline import procesar_auxiliar
from contapdf.validate.rules import (
    CUADRA,
    FALLA,
    NO_VERIFICABLE,
    evaluar_auxiliar,
)

# Fase 8c: el fichero entero cuesta 38 s porque vuelve a parsear
# auxiliar.pdf dos veces. La suite rapida no puede pagarlo en cada ciclo;
# `pytest -m lento` lo corre antes de cada entrega.
pytestmark = pytest.mark.lento

_CERO = Decimal("0.00")


def _fila(cuenta, debe, haber, saldo, *, inicial=_CERO, subtotal=False):
    return FilaAuxiliar(
        cuenta=cuenta, nombre_cuenta="X", saldo_inicial_cuenta=inicial,
        folio="", fecha="01/01/2025", tipo_movimiento="", documento="",
        tercero="", concepto="", debe=Decimal(debe), haber=Decimal(haber),
        saldo=None if saldo is None else Decimal(saldo),
        saldo_origen=IMPRESO, es_subtotal=subtotal)


def _regla(cobertura, nombre="saldo_corrido"):
    return next(r for r in cobertura.reglas if r.regla == nombre)


# --- Una cuenta acreedora cuadra, sin cablear nada ----------------------
def test_una_cuenta_acreedora_cuadra():
    """saldo = anterior - debe + haber. Es la identidad contraria."""
    aux = Auxiliar(filas=(
        _fila("201-01", "0.00", "339097.31", "339097.31"),
        _fila("201-01", "230000.00", "0.00", "109097.31"),
        _fila("201-01", "0.00", "338668.01", "447765.32"),
    ))
    regla = _regla(evaluar_auxiliar(aux))
    assert regla.estado == CUADRA
    assert regla.exactas == 3


def test_una_cuenta_deudora_sigue_cuadrando():
    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", "600.00"),
        _fila("101-01", "250.00", "0.00", "850.00"),
    ))
    assert _regla(evaluar_auxiliar(aux)).estado == CUADRA


def test_las_dos_naturalezas_en_el_mismo_documento():
    """Cada cuenta con la suya: no hay un signo del documento."""
    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", "600.00"),
        _fila("201-01", "0.00", "5000.00", "5000.00"),
        _fila("201-01", "1500.00", "0.00", "3500.00"),
    ))
    regla = _regla(evaluar_auxiliar(aux))
    assert regla.estado == CUADRA
    assert regla.exactas == 4


# --- Criterio 4: el signo no puede estar cableado -----------------------
def test_el_espejo_de_un_auxiliar_cuadra_igual():
    """Intercambiar debe y haber convierte cada cuenta en su contraria.

    Si el signo estuviera cableado el espejo fallaria entero. Es la prueba
    que no depende de leer el texto del codigo: depende de que la regla
    pregunte, no de que suponga.
    """
    filas = (
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", "600.00"),
        _fila("101-01", "250.00", "0.00", "850.00"),
    )
    derecho = _regla(evaluar_auxiliar(Auxiliar(filas=filas)))
    espejo = _regla(evaluar_auxiliar(Auxiliar(filas=tuple(
        _fila(f.cuenta, f.haber, f.debe, f.saldo) for f in filas))))
    assert derecho.estado == espejo.estado == CUADRA
    assert derecho.exactas == espejo.exactas


def test_un_saldo_roto_sigue_saliendo_aunque_la_naturaleza_se_derive():
    """Derivar por mayoria no puede tapar el renglon que no encadena."""
    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", "600.00"),
        _fila("101-01", "250.00", "0.00", "999.99"),   # deberia dar 850.00
        _fila("101-01", "100.00", "0.00", "1099.99"),
    ))
    regla = _regla(evaluar_auxiliar(aux))
    assert regla.estado == FALLA
    assert len(regla.discrepancias) == 1


# --- Sin evidencia no se inventa una naturaleza -------------------------
def test_una_cuenta_que_no_revela_su_naturaleza_no_se_da_por_buena():
    """Con debe == haber las dos identidades cuadran: no hay que elegir."""
    aux = Auxiliar(filas=(
        _fila("301-01", "500.00", "500.00", "0.00"),
        _fila("301-01", "700.00", "700.00", "0.00"),
    ))
    regla = _regla(evaluar_auxiliar(aux))
    assert regla.estado == NO_VERIFICABLE
    assert regla.motivo
    assert "301-01" in regla.motivo or "naturaleza" in regla.motivo.lower()
    # El universo NO encoge por no poder decidir: 2 casos aplicables, 0 evaluados.
    assert (regla.aplicables, regla.evaluados) == (2, 0)


def test_la_cuenta_indeterminada_no_arrastra_a_las_demas():
    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", "600.00"),
        _fila("301-01", "500.00", "500.00", "0.00"),
    ))
    regla = _regla(evaluar_auxiliar(aux))
    assert regla.estado == CUADRA
    assert regla.aplicables == 3
    assert regla.evaluados == 2          # la indeterminada queda fuera
    assert regla.motivo                  # y se dice cual y por que


# --- Sobre los documentos reales ----------------------------------------
def test_el_auxiliar_real_pasa_de_3585_fallas_a_cero():
    """Medido en la 7f: 3,198 deudoras + 3,585 acreedoras, cero ambiguos."""
    r = procesar_auxiliar(requires_real_pdf("auxiliar"))
    regla = _regla(r.cobertura)
    assert regla.estado == CUADRA
    assert len(regla.discrepancias) == 0
    assert (regla.aplicables, regla.evaluados) == (6783, 6783)
    assert regla.exactas == 6783


def test_el_auxiliar_real_reparte_396_deudoras_y_44_acreedoras():
    from contapdf.validate.rules import naturaleza_por_cuenta

    aux = procesar_auxiliar(requires_real_pdf("auxiliar")).auxiliar
    naturalezas = naturaleza_por_cuenta(aux)
    assert sum(1 for n in naturalezas.values() if n == "D") == 396
    assert sum(1 for n in naturalezas.values() if n == "A") == 44
    assert sum(1 for n in naturalezas.values() if not n) == 0


@pytest.mark.lento
def test_auxiliar_gume_tambien_reparte_sus_dos_naturalezas():
    from contapdf.validate.rules import naturaleza_por_cuenta

    aux = procesar_auxiliar(requires_real_pdf("auxiliar-gume")).auxiliar
    naturalezas = naturaleza_por_cuenta(aux)
    assert sum(1 for n in naturalezas.values() if n == "D") == 99
    assert sum(1 for n in naturalezas.values() if n == "A") == 73
