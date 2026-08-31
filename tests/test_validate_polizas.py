"""Validacion del libro diario: debe contra haber, por poliza."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.polizas import PolizasParser
from contapdf.validate.rules import CUADRA, FALLA, NO_VERIFICABLE, evaluar_polizas


def _libro(nombre: str, paginas: list[int]):
    doc, _ = extraer(requires_real_pdf(nombre), page_numbers=paginas)
    return PolizasParser().parse(doc)


@pytest.fixture(scope="module")
def bloques():
    return _libro("poliza", [1, 2, 3, 4])


@pytest.fixture(scope="module")
def diario():
    return _libro("diario-general", [1, 2, 3])


def _regla(cobertura, nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


# --- Criterio 3 ---------------------------------------------------------
def test_cada_poliza_cuadra_debe_contra_haber(bloques):
    regla = _regla(evaluar_polizas(bloques), "partida_doble")
    assert regla.estado == CUADRA
    assert regla.comprobaciones == 8


def test_el_diario_general_tambien_cuadra(diario):
    regla = _regla(evaluar_polizas(diario), "partida_doble")
    assert regla.estado == CUADRA
    assert regla.comprobaciones == 27


def test_una_poliza_descuadrada_se_reporta_por_su_id(bloques):
    movimientos = list(bloques.movimientos)
    movimientos[0] = dataclasses.replace(movimientos[0],
                                         debe=movimientos[0].debe + Decimal("1.00"))
    roto = dataclasses.replace(bloques, movimientos=tuple(movimientos))

    cobertura = evaluar_polizas(roto)
    assert _regla(cobertura, "partida_doble").estado == FALLA
    assert cobertura.discrepancias[0].fila == bloques.polizas[0].poliza_id


# --- Criterio 2: cobertura con motivo -----------------------------------
def test_los_totales_declarados_se_comprueban(bloques):
    regla = _regla(evaluar_polizas(bloques), "totales")
    assert regla.estado == CUADRA
    assert regla.comprobaciones > 0


def test_sin_totales_declarados_la_regla_lo_dice():
    from contapdf.parsers.polizas import LibroDiario, Poliza

    vacio = LibroDiario(
        polizas=(Poliza(poliza_id="P0001", tipo="", naturaleza="", fecha="",
                        descripcion="", folio="", total_debe=None,
                        total_haber=None),),
        movimientos=(), cfdi=())
    regla = _regla(evaluar_polizas(vacio), "totales")
    assert regla.estado == NO_VERIFICABLE
    assert regla.motivo


def test_sin_polizas_no_se_finge_cobertura():
    from contapdf.parsers.polizas import LibroDiario

    cobertura = evaluar_polizas(LibroDiario(polizas=(), movimientos=(), cfdi=()))
    assert all(r.estado == NO_VERIFICABLE for r in cobertura.reglas)
    assert cobertura.cuadran == 0


def test_no_imprime(bloques, capsys):
    evaluar_polizas(bloques)
    salida = capsys.readouterr()
    assert salida.out == "" and salida.err == ""


# --- Criterio 1: el CFDI se ata por DATO, no por posicion ---------------
def test_el_cfdi_se_verifica_contra_el_dato_de_su_poliza(bloques):
    # Que cada poliza reciba un CFDI no prueba que sea el suyo: ocho
    # cruzados dan el mismo 8/8. Lo que lo prueba es que el numero de
    # documento del CFDI sea el de la poliza.
    regla = _regla(evaluar_polizas(bloques), "cfdi_cruzado")
    assert regla.estado == CUADRA
    assert regla.comprobaciones == 8
    assert regla.exactas == 8


def test_un_cfdi_asignado_a_la_poliza_equivocada_se_detecta(bloques):
    import dataclasses

    cfdis = list(bloques.cfdi)
    # Se intercambian dos: la comprobacion por posicion seguiria dando 8/8.
    cfdis[0], cfdis[1] = (dataclasses.replace(cfdis[0], poliza_id=cfdis[1].poliza_id),
                          dataclasses.replace(cfdis[1], poliza_id=cfdis[0].poliza_id))
    roto = dataclasses.replace(bloques, cfdi=tuple(cfdis))

    cobertura = evaluar_polizas(roto)
    assert _regla(cobertura, "cfdi").estado == CUADRA        # posicion: pasa
    assert _regla(cobertura, "cfdi_cruzado").estado == FALLA  # dato: no
    assert len(_regla(cobertura, "cfdi_cruzado").discrepancias) == 2


def test_sin_cruce_disponible_la_regla_lo_declara(diario):
    # El diario general no trae tabla de CFDI: la regla no se omite, sale
    # no_verificable con su motivo.
    regla = _regla(evaluar_polizas(diario), "cfdi_cruzado")
    assert regla.estado == NO_VERIFICABLE
    assert regla.motivo
