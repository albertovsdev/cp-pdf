"""Validacion del estado de cuenta."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.estado_cuenta import EstadoCuentaParser
from contapdf.validate.rules import (
    CUADRA,
    FALLA,
    NO_VERIFICABLE,
    evaluar_estado_cuenta,
)


@pytest.fixture(scope="module")
def edocta():
    doc, _ = extraer(requires_real_pdf("edocta"))
    return EstadoCuentaParser().parse(doc)


def _regla(cobertura, nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


# --- Criterios 3 y 4 -----------------------------------------------------
def test_el_resumen_cuadra_exacto(edocta):
    # 32,411.67 + 118,420.39 - 118,958.74 = 31,873.32
    regla = _regla(evaluar_estado_cuenta(edocta), "resumen")
    assert regla.estado == CUADRA
    assert regla.exactas == 1


def test_el_resumen_cuadra_contra_los_movimientos_leidos(edocta):
    regla = _regla(evaluar_estado_cuenta(edocta), "resumen_movimientos")
    assert regla.estado == CUADRA
    assert sum(m.deposito for m in edocta.movimientos) == edocta.meta.depositos
    assert sum(m.retiro for m in edocta.movimientos) == edocta.meta.retiros


def test_el_saldo_corrido_cuadra(edocta):
    regla = _regla(evaluar_estado_cuenta(edocta), "saldo_corrido")
    assert regla.estado == CUADRA
    assert regla.comprobaciones == 45


def test_un_saldo_roto_se_reporta(edocta):
    movimientos = list(edocta.movimientos)
    movimientos[3] = dataclasses.replace(movimientos[3],
                                         saldo=movimientos[3].saldo + Decimal("10"))
    roto = dataclasses.replace(edocta, movimientos=tuple(movimientos))
    cobertura = evaluar_estado_cuenta(roto)
    assert _regla(cobertura, "saldo_corrido").estado == FALLA
    assert cobertura.discrepancias


def test_sin_resumen_la_regla_lo_declara(edocta):
    meta = dataclasses.replace(edocta.meta, saldo_inicial=None)
    cobertura = evaluar_estado_cuenta(dataclasses.replace(edocta, meta=meta))
    regla = _regla(cobertura, "resumen")
    assert regla.estado == NO_VERIFICABLE
    assert regla.motivo


def test_la_cobertura_se_reporta_entera(edocta):
    cobertura = evaluar_estado_cuenta(edocta)
    assert {r.regla for r in cobertura.reglas} == {
        "resumen", "resumen_movimientos", "saldo_corrido"}
    assert cobertura.fallan == 0
    assert "3 reglas" in cobertura.resumen()
