"""Validacion del auxiliar: saldo corrido y subtotales."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.auxiliar import AuxiliarParser
from contapdf.validate.rules import CUADRA, FALLA, NO_VERIFICABLE, evaluar_auxiliar


def _aux(nombre: str, paginas: list[int]):
    doc, _ = extraer(requires_real_pdf(nombre), page_numbers=paginas)
    return AuxiliarParser().parse(doc)


@pytest.fixture(scope="module")
def original():
    return _aux("auxiliar", [1, 2, 3, 4, 5, 6])


@pytest.fixture(scope="module")
def gume():
    return _aux("auxiliar-gume", [1, 2, 3, 4])


def _regla(cobertura, nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


# --- Criterio 2: cobertura completa en ambas ----------------------------
def test_el_saldo_corrido_cuadra_en_el_auxiliar_original(original):
    regla = _regla(evaluar_auxiliar(original), "saldo_corrido")
    assert regla.estado == CUADRA
    assert regla.comprobaciones == 129


def test_el_saldo_corrido_cuadra_en_gume(gume):
    regla = _regla(evaluar_auxiliar(gume), "saldo_corrido")
    assert regla.estado == CUADRA
    assert regla.exactas == 174


def test_declara_los_saldos_que_no_pudo_encadenar(gume):
    # Cuadrar 174 de 250 no es cuadrar: la cobertura tiene que decir que
    # 74 movimientos quedaron fuera de la cadena.
    regla = _regla(evaluar_auxiliar(gume), "saldo_corrido")
    assert "74 de 250" in regla.motivo
    assert "saldo legible" in regla.motivo


def test_ninguna_regla_queda_silenciosamente_sin_correr(original):
    cobertura = evaluar_auxiliar(original)
    assert cobertura.fallan == 0
    for regla in cobertura.reglas:
        assert regla.estado != NO_VERIFICABLE or regla.motivo


def test_el_resumen_incluye_la_cobertura(gume):
    resumen = evaluar_auxiliar(gume).resumen()
    assert "reglas" in resumen and "cuadran" in resumen


# --- Criterio 4: los subtotales no se doble-cuentan ---------------------
def test_los_subtotales_de_gume_se_identifican_y_no_se_suman(gume):
    subtotales = [f for f in gume.filas if f.es_subtotal]
    movimientos = [f for f in gume.filas if not f.es_subtotal]
    assert len(subtotales) == 6
    assert sum(f.debe for f in subtotales) not in (
        Decimal(0), sum(f.debe for f in movimientos))


def test_sin_una_seccion_completa_los_subtotales_no_se_verifican(gume):
    # Las secciones de este documento abarcan decenas de paginas: en el
    # rango leido ninguna llega a su fila de Total.
    regla = _regla(evaluar_auxiliar(gume), "subtotales")
    assert regla.estado == NO_VERIFICABLE
    assert regla.motivo


def test_sin_subtotales_la_regla_es_no_verificable(original):
    regla = _regla(evaluar_auxiliar(original), "subtotales")
    assert regla.estado == NO_VERIFICABLE
    assert "subtotal" in regla.motivo.lower()


def test_un_saldo_roto_se_reporta(original):
    filas = list(original.filas)
    i = next(i for i, f in enumerate(filas) if not f.es_subtotal)
    filas[i] = dataclasses.replace(filas[i], saldo=filas[i].saldo + Decimal("100.00"))
    roto = dataclasses.replace(original, filas=tuple(filas))

    cobertura = evaluar_auxiliar(roto)
    assert _regla(cobertura, "saldo_corrido").estado == FALLA
    assert cobertura.discrepancias


def test_no_imprime_ni_lanza(gume, capsys):
    evaluar_auxiliar(gume)
    salida = capsys.readouterr()
    assert salida.out == "" and salida.err == ""
