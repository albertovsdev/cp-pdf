"""El CFDI se cruza con su poliza por CONTENCION, no por igualdad.

Fase 7g, arreglo 3. PLAN 1.2 dice que el `documento` del CFDI trae el mismo
numero que la `descripcion` de la poliza; la regla lo comparaba con `!=`, y
eso convertia en falla toda descripcion que trajera texto alrededor.

Medido en la 7f sobre 1,942 CFDI comparables: 1,025 fallan por igualdad y
162 por contencion. Las 863 de diferencia son falsas alarmas --
`65501589987` SI esta dentro de `FACT. FOLIO: 65501589987`.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import requires_real_pdf

from contapdf.parsers.polizas import CFDI, LibroDiario, Poliza
from contapdf.pipeline import procesar_polizas
from contapdf.validate.rules import CUADRA, FALLA, evaluar_polizas

_CERO = Decimal("0.00")


def _poliza(pid, descripcion):
    return Poliza(poliza_id=pid, tipo="Compra", naturaleza="", fecha="",
                  descripcion=descripcion, folio="", total_debe=_CERO,
                  total_haber=_CERO, completa=True)


def _cfdi(pid, documento):
    return CFDI(poliza_id=pid, fecha="", documento=documento, uuid="u",
                rfc="", tipo="I")


def _regla(libro, nombre="cfdi_cruzado"):
    return next(r for r in evaluar_polizas(libro).reglas if r.regla == nombre)


def test_el_numero_dentro_de_la_descripcion_cruza():
    libro = LibroDiario(
        polizas=(_poliza("P1", "FACT. FOLIO: 65501589987"),),
        movimientos=(), cfdi=(_cfdi("P1", "65501589987"),))
    assert _regla(libro).estado == CUADRA


def test_la_igualdad_exacta_sigue_cruzando():
    libro = LibroDiario(polizas=(_poliza("P1", "18243"),),
                        movimientos=(), cfdi=(_cfdi("P1", "18243"),))
    assert _regla(libro).estado == CUADRA


def test_un_numero_que_no_aparece_sigue_fallando():
    """Contencion no es 'cualquier cosa cuadra'."""
    libro = LibroDiario(polizas=(_poliza("P1", "FACT. FOLIO: 999"),),
                        movimientos=(), cfdi=(_cfdi("P1", "18243"),))
    regla = _regla(libro)
    assert regla.estado == FALLA
    assert len(regla.discrepancias) == 1


def test_sobre_el_documento_real_pasa_de_1025_fallas_a_53():
    """La contencion quito 863 falsas alarmas y la fase 7h otras 109.

    En la 7g quedaban 162 con `evaluados=1942`. La 7h dejo de inventar el
    `documento` de los CFDI sin folio fiscal, asi que 121 salieron del
    numerador -- el denominador NO se movio -- y quedan 53 fallas reales.
    """
    libro = procesar_polizas(requires_real_pdf("poliza")).libro
    regla = _regla(libro)
    assert regla.aplicables == 1942
    assert regla.evaluados == 1821
    assert len(regla.discrepancias) == 53
    assert regla.exactas == 1821 - 53
