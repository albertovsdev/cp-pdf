"""Validacion del estado de cuenta.

Desde la fase 7d los checksums son POR CUENTA, no por documento: un estado
con dos cuentas tiene dos resumenes que cuadran por separado. Y se agrega
una regla de cruce: cuando el documento imprime una fila TOTAL, la suma de
los saldos por cuenta tiene con que compararse.
"""

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


@pytest.fixture(scope="module")
def banorte():
    doc, _ = extraer(requires_real_pdf("edocta-julio-banorte"))
    return EstadoCuentaParser().parse(doc)


def _regla(cobertura, nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


def _con_cuenta(estado, **cambios):
    """El estado con su primera cuenta modificada."""
    cuentas = list(estado.cuentas)
    cuentas[0] = dataclasses.replace(cuentas[0], **cambios)
    return dataclasses.replace(estado, cuentas=tuple(cuentas))


# --- Criterios 3 y 4 -----------------------------------------------------
def test_el_resumen_cuadra_exacto(edocta):
    # 32,411.67 + 118,420.39 - 118,958.74 = 31,873.32
    regla = _regla(evaluar_estado_cuenta(edocta), "resumen")
    assert regla.estado == CUADRA
    assert regla.exactas == 1


def test_el_resumen_cuadra_contra_los_movimientos_leidos(edocta):
    regla = _regla(evaluar_estado_cuenta(edocta), "resumen_movimientos")
    assert regla.estado == CUADRA
    cuenta = edocta.cuentas[0]
    assert sum(m.deposito for m in edocta.movimientos) == cuenta.depositos
    assert sum(m.retiro for m in edocta.movimientos) == cuenta.retiros


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
    cobertura = evaluar_estado_cuenta(_con_cuenta(edocta, saldo_inicial=None))
    regla = _regla(cobertura, "resumen")
    assert regla.estado == NO_VERIFICABLE
    assert regla.motivo


def test_la_cobertura_se_reporta_entera(edocta):
    cobertura = evaluar_estado_cuenta(edocta)
    assert {r.regla for r in cobertura.reglas} == {
        "resumen", "resumen_movimientos", "saldo_corrido", "total_declarado"}
    assert cobertura.fallan == 0
    assert "4 reglas" in cobertura.resumen()


# --- Fase 7d: los checksums son por cuenta ------------------------------
def test_el_saldo_corrido_no_encadena_entre_cuentas(banorte):
    """Encadenar la cuenta 2 detras de la 1 daria una falla inventada."""
    regla = _regla(evaluar_estado_cuenta(banorte), "saldo_corrido")
    assert regla.estado == CUADRA


def test_el_resumen_de_banorte_no_es_verificable_y_lo_dice(banorte):
    """Sin depositos ni retiros por cuenta, la regla no puede correr."""
    cobertura = evaluar_estado_cuenta(banorte)
    for nombre in ("resumen", "resumen_movimientos"):
        regla = _regla(cobertura, nombre)
        assert regla.estado == NO_VERIFICABLE
        assert regla.motivo
    assert cobertura.fallan == 0


# --- Fase 7d: la fila TOTAL es un cruce con datos -----------------------
def test_el_total_declarado_cuadra_con_la_suma_por_cuenta(banorte):
    regla = _regla(evaluar_estado_cuenta(banorte), "total_declarado")
    assert regla.estado == CUADRA
    assert regla.comprobaciones == 2
    assert regla.exactas == 2


def test_un_total_que_no_cuadra_se_reporta(banorte):
    meta = dataclasses.replace(banorte.meta,
                               total_saldo_corte=Decimal("999999.99"))
    cobertura = evaluar_estado_cuenta(dataclasses.replace(banorte, meta=meta))
    regla = _regla(cobertura, "total_declarado")
    assert regla.estado == FALLA
    assert cobertura.discrepancias


def test_sin_fila_total_no_se_inventa_el_cruce(edocta):
    regla = _regla(evaluar_estado_cuenta(edocta), "total_declarado")
    assert regla.estado == NO_VERIFICABLE
    assert "total" in regla.motivo.lower()
