"""Un saldo que el sistema genero no verifica al documento.

Fase 7h, objetivo 1. `auxiliar-gume/saldo_corrido` reportaba «47 965 de
47 987 cuadra», y 26 032 de esas exactas eran saldos que el propio sistema
habia encadenado con `saldo = anterior + debe - haber`. Verificar esa
identidad sobre un saldo producido con esa misma formula es una tautologia:
no puede fallar.

La verificacion real de una seccion recalculada es OTRA: el ancla contra el
subtotal que el documento declara, y es una comprobacion por SECCION, no
una por movimiento. Por eso `evaluar_auxiliar` reporta ahora una regla
aparte.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.parsers.auxiliar import IMPRESO, RECALCULADO, Auxiliar, FilaAuxiliar
from contapdf.pipeline import procesar_auxiliar
from contapdf.validate.rules import (
    CUADRA,
    Cobertura,
    ResultadoRegla,
    evaluar_auxiliar,
)

# Fase 8c: el fichero entero cuesta 16 s porque vuelve a parsear
# auxiliar.pdf. La suite rapida no puede pagarlo en cada ciclo; `pytest -m
# lento` lo corre antes de cada entrega.
pytestmark = pytest.mark.lento

_CERO = Decimal("0.00")


def _fila(cuenta, debe, haber, saldo, *, origen=IMPRESO, subtotal=False):
    return FilaAuxiliar(
        cuenta=cuenta, nombre_cuenta="X", saldo_inicial_cuenta=_CERO,
        folio="", fecha="01/01/2025", tipo_movimiento="", documento="",
        tercero="", concepto="", debe=Decimal(debe), haber=Decimal(haber),
        saldo=None if saldo is None else Decimal(saldo),
        saldo_origen=origen, es_subtotal=subtotal)


def _regla(cobertura, nombre="saldo_corrido"):
    return next(r for r in cobertura.reglas if r.regla == nombre)


# --- El contrato del dataclass -----------------------------------------
def test_las_dos_exactas_suman_el_total():
    regla = ResultadoRegla(regla="x", estado=CUADRA, aplicables=10,
                           evaluados=10, exactas=10, exactas_impresas=4,
                           exactas_recalculadas=6)
    assert regla.exactas_impresas + regla.exactas_recalculadas == regla.exactas


def test_una_particion_que_no_suma_es_ilegal():
    with pytest.raises(ValueError, match="exactas"):
        ResultadoRegla(regla="x", estado=CUADRA, aplicables=10, evaluados=10,
                       exactas=10, exactas_impresas=4, exactas_recalculadas=1)


def test_sin_particion_explicita_todas_cuentan_como_impresas():
    """Aditivo: las reglas que no derivan nada no cambian."""
    regla = ResultadoRegla(regla="x", estado=CUADRA, aplicables=3,
                           evaluados=3, exactas=3)
    assert regla.exactas_impresas == 3
    assert regla.exactas_recalculadas == 0


# --- Criterio 2: el resumen no puede esconder las recalculadas ----------
def test_el_resumen_de_la_regla_separa_las_dos():
    regla = ResultadoRegla(regla="saldo_corrido", estado=CUADRA,
                           aplicables=100, evaluados=100, exactas=100,
                           exactas_impresas=30, exactas_recalculadas=70)
    texto = regla.resumen()
    assert "30" in texto and "70" in texto
    assert "recalculad" in texto.lower()


def test_el_resumen_de_la_cobertura_avisa_de_las_recalculadas():
    cobertura = Cobertura(reglas=(
        ResultadoRegla(regla="saldo_corrido", estado=CUADRA, aplicables=100,
                       evaluados=100, exactas=100, exactas_impresas=30,
                       exactas_recalculadas=70),
    ))
    texto = cobertura.resumen()
    assert "70" in texto
    assert "recalculad" in texto.lower()


def test_sin_recalculadas_el_resumen_no_agrega_ruido():
    cobertura = Cobertura(reglas=(
        ResultadoRegla(regla="saldo_corrido", estado=CUADRA, aplicables=3,
                       evaluados=3, exactas=3),
    ))
    assert "recalculad" not in cobertura.resumen().lower()


# --- La regla parte sus exactas segun el origen del saldo ---------------
def test_la_regla_distingue_el_origen_de_cada_saldo():
    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", "600.00", origen=RECALCULADO),
        _fila("101-01", "250.00", "0.00", "850.00"),
    ))
    regla = _regla(evaluar_auxiliar(aux))
    assert regla.exactas == 3
    assert regla.exactas_recalculadas == 1
    assert regla.exactas_impresas == 2


# --- El ancla es una comprobacion por seccion ---------------------------
def test_la_seccion_recalculada_se_verifica_contra_su_subtotal():
    """Lo unico que de verdad comprueba una seccion recalculada."""
    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
        _fila("101-01", "0.00", "400.00", None, origen=RECALCULADO),
        _fila("101-01", "250.00", "0.00", "850.00"),
        _fila("101-01", "1250.00", "400.00", "850.00", subtotal=True),
    ))
    regla = _regla(evaluar_auxiliar(aux), "ancla_recalculo")
    assert regla.aplicables == 1          # una seccion, no tres movimientos
    assert regla.estado == CUADRA


def test_sin_saldos_recalculados_el_ancla_no_aplica():
    aux = Auxiliar(filas=(
        _fila("101-01", "1000.00", "0.00", "1000.00"),
    ))
    regla = _regla(evaluar_auxiliar(aux), "ancla_recalculo")
    assert regla.aplicables == 0
    assert regla.motivo


# --- Sobre el documento real -------------------------------------------
@pytest.mark.lento
def test_auxiliar_gume_muestra_sus_26032_recalculadas():
    """Criterio 1: un cuadra mayoritariamente derivado no es lo mismo."""
    r = procesar_auxiliar(requires_real_pdf("auxiliar-gume"))
    regla = _regla(r.cobertura)
    assert regla.exactas == 47965
    assert regla.exactas_recalculadas == 26032
    assert regla.exactas_impresas == 47965 - 26032
    # Y la cobertura lo dice en su resumen, no solo en el dataclass.
    assert "26032" in r.cobertura.resumen().replace(",", "")


def test_el_auxiliar_sin_recalculo_no_reporta_recalculadas():
    r = procesar_auxiliar(requires_real_pdf("auxiliar"))
    regla = _regla(r.cobertura)
    assert regla.exactas_recalculadas == 0
    assert regla.exactas_impresas == regla.exactas == 6783
