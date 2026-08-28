"""Cobertura sobre los tres documentos reales, de punta a punta."""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.balanza import BalanzaParser
from contapdf.validate.rules import CUADRA, NO_VERIFICABLE, evaluar_balanza


def _cobertura(nombre: str):
    doc, _ = extraer(requires_real_pdf(nombre))
    balanza = BalanzaParser().parse(doc)
    return balanza, evaluar_balanza(balanza)


@pytest.mark.parametrize(("nombre", "filas"), [
    ("balanza", 475),
    ("balanza-businesspro", 225),
    ("balanza-gume", 734),
])
def test_ningun_documento_reporta_fallas(nombre, filas):
    balanza, cobertura = _cobertura(nombre)
    assert len(balanza.filas) == filas
    assert cobertura.fallan == 0
    assert cobertura.discrepancias == ()


def test_la_balanza_original_cubre_las_cuatro_reglas():
    _, cobertura = _cobertura("balanza")
    assert cobertura.cuadran == 4
    assert cobertura.no_verificables == 0


def test_business_pro_declara_por_que_no_exige_partida_doble():
    _, cobertura = _cobertura("balanza-businesspro")
    partida = next(r for r in cobertura.reglas if r.regla == "partida_doble")
    assert partida.estado == NO_VERIFICABLE
    assert partida.motivo
    assert cobertura.cuadran == 3


def test_gume_ya_corre_las_cuatro_reglas():
    # Antes: jerarquia perdida, totales no detectados, partida doble
    # pasando por doble conteo. La cobertura era casi nula.
    _, cobertura = _cobertura("balanza-gume")
    assert cobertura.cuadran == 4
    assert all(r.estado == CUADRA for r in cobertura.reglas)
