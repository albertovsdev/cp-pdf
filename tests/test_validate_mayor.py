"""Validacion del Libro Mayor, incluido el primer cruce entre documentos."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.mayor import MayorParser
from contapdf.pipeline import procesar_balanza
from contapdf.validate.rules import (
    CUADRA,
    FALLA,
    NO_VERIFICABLE,
    evaluar_mayor,
)


@pytest.fixture(scope="module")
def mayor():
    doc, _ = extraer(requires_real_pdf("mayor-gume"))
    return MayorParser().parse(doc)


@pytest.fixture(scope="module")
def balanza():
    return procesar_balanza(requires_real_pdf("balanza-gume")).balanza


def _regla(cobertura, nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


# --- Criterio 3 ---------------------------------------------------------
def test_el_saldo_mensual_cuadra(mayor):
    regla = _regla(evaluar_mayor(mayor), "saldo_mensual")
    assert regla.estado == CUADRA
    assert regla.comprobaciones == 49 * 12


def test_los_acumulados_cuadran(mayor):
    regla = _regla(evaluar_mayor(mayor), "acumulados")
    assert regla.estado == CUADRA
    assert regla.comprobaciones == 49 * 12 * 2


def test_un_saldo_roto_se_reporta(mayor):
    meses = list(mayor.meses)
    meses[5] = dataclasses.replace(meses[5], saldo=meses[5].saldo + Decimal("1"))
    roto = dataclasses.replace(mayor, meses=tuple(meses))
    cobertura = evaluar_mayor(roto)
    assert _regla(cobertura, "saldo_mensual").estado == FALLA
    assert cobertura.discrepancias


# --- Criterio 4: el cruce entre documentos ------------------------------
def test_sin_balanza_el_cruce_es_no_verificable(mayor):
    regla = _regla(evaluar_mayor(mayor), "cruce_balanza")
    assert regla.estado == NO_VERIFICABLE
    assert "no se recibio" in regla.motivo.lower()


def test_con_balanza_el_cruce_reporta_lo_medido(mayor, balanza):
    # 41 de 49 coinciden; las 8 que difieren son de resultados, cierre o
    # impuestos. No hay regla confirmada para decidir si es esperado, asi
    # que el sistema entrega el dato y la pregunta, no finge saber.
    regla = _regla(evaluar_mayor(mayor, balanza=balanza), "cruce_balanza")
    assert regla.estado == NO_VERIFICABLE
    assert regla.comprobaciones == 49
    assert regla.exactas == 41
    for cuenta in ("4100-000-000", "5000-000-000", "3400-000-000"):
        assert cuenta in regla.motivo
    assert "282,868.37" in regla.motivo


def test_el_cruce_no_inventa_una_excepcion_para_resultados(mayor, balanza):
    # Cablear "las de resultados no cuentan" seria dar por buena una
    # convencion que nadie verifico, y taparia un defecto real.
    regla = _regla(evaluar_mayor(mayor, balanza=balanza), "cruce_balanza")
    assert regla.estado != CUADRA
    assert not regla.discrepancias   # tampoco se reporta como falla
