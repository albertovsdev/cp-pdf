"""Tres estados por regla y cobertura visible."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from conftest import synthetic_document

from contapdf.parsers.balanza import Balanza, BalanzaParser
from contapdf.validate.rules import (
    CUADRA,
    FALLA,
    NO_VERIFICABLE,
    ReglasBalanza,
    evaluar_balanza,
    validar_balanza,
)


def _balanza(name="balanza_sintetica"):
    return BalanzaParser().parse(synthetic_document(name))


def _regla(cobertura, nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


def test_el_sintetico_cuadra_en_las_cuatro_reglas():
    cobertura = evaluar_balanza(_balanza())
    assert {r.regla for r in cobertura.reglas} == {
        "renglon", "jerarquia", "totales", "partida_doble"}
    assert all(r.estado == CUADRA for r in cobertura.reglas)
    assert cobertura.cuadran == 4
    assert cobertura.fallan == 0
    assert cobertura.no_verificables == 0


def test_el_resumen_nunca_es_solo_cero_discrepancias():
    resumen = evaluar_balanza(_balanza()).resumen()
    assert "4 reglas" in resumen
    assert "cuadran" in resumen


def test_una_regla_que_falla_se_marca_falla():
    cobertura = evaluar_balanza(_balanza("balanza_descuadrada"))
    assert _regla(cobertura, "renglon").estado == FALLA
    assert cobertura.fallan == 1
    assert len(cobertura.discrepancias) == 1


def test_sin_fila_de_totales_la_regla_es_no_verificable():
    balanza = dataclasses.replace(_balanza(), totales=None)
    regla = _regla(evaluar_balanza(balanza), "totales")
    assert regla.estado == NO_VERIFICABLE
    assert "totales" in regla.motivo.lower()


def test_sin_jerarquia_la_regla_es_no_verificable():
    plana = tuple(dataclasses.replace(f, nivel=1, cuenta_padre="")
                  for f in _balanza().filas)
    regla = _regla(evaluar_balanza(dataclasses.replace(_balanza(), filas=plana)),
                   "jerarquia")
    assert regla.estado == NO_VERIFICABLE
    assert "nivel 1" in regla.motivo


def test_sin_renglones_la_regla_es_no_verificable():
    vacia = Balanza(filas=(), totales=None)
    assert _regla(evaluar_balanza(vacia), "renglon").estado == NO_VERIFICABLE


def test_distingue_cuadre_exacto_de_cuadre_dentro_de_tolerancia():
    balanza = _balanza()
    filas = list(balanza.filas)
    i = next(i for i, f in enumerate(filas) if f.cuenta == "601-02")
    filas[i] = dataclasses.replace(
        filas[i], saldo_fin_deudor=filas[i].saldo_fin_deudor + Decimal("0.01"))
    rozando = dataclasses.replace(balanza, filas=tuple(filas))

    regla = _regla(evaluar_balanza(rozando), "renglon")
    assert regla.estado == CUADRA
    assert regla.con_tolerancia == ("601-02",)
    assert regla.exactas == len(filas) - 1


def test_la_partida_doble_que_no_aplica_es_no_verificable():
    balanza = _balanza()
    reglas = ReglasBalanza(exige_partida_doble=False)
    regla = _regla(evaluar_balanza(balanza, reglas=reglas), "partida_doble")
    assert regla.estado == NO_VERIFICABLE
    assert regla.motivo


def test_validar_balanza_sigue_devolviendo_solo_discrepancias():
    # La API vieja no cambia: la cobertura se pide aparte.
    assert validar_balanza(_balanza()) == []
    assert len(validar_balanza(_balanza("balanza_descuadrada"))) == 1


def test_es_determinista():
    assert evaluar_balanza(_balanza()) == evaluar_balanza(_balanza())


# --- Criterio 6: procedencia de la naturaleza ---------------------------
def test_la_cobertura_reporta_las_cuatro_procedencias_de_naturaleza():
    cobertura = evaluar_balanza(_balanza())
    assert set(cobertura.naturalezas) == {
        "explicita", "derivada", "heredada", "sin_determinar"}
    # El sintetico trae columna de Naturaleza: todas explicitas.
    assert cobertura.naturalezas["explicita"] == 16
    assert "16 explicitas" in cobertura.resumen_naturaleza()


def test_la_naturaleza_sin_determinar_queda_vacia():
    from contapdf.parsers.balanza import SIN_DETERMINAR

    balanza = _balanza()
    for fila in balanza.filas:
        if fila.naturaleza_origen == SIN_DETERMINAR:
            assert fila.naturaleza == ""
        else:
            assert fila.naturaleza in ("D", "A")
