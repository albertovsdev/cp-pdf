"""Recalculo del saldo corrido, solo con ancla verificada.

El defecto 3b (tinta nunca dibujada) no lo arregla ningun OCR. Pero la
aritmetica es cerrada y hay ancla en los dos extremos: el saldo inicial de
la seccion y el subtotal declarado. Recalcular con esas anclas comprobadas
no es inventar dato; hacerlo sin comprobarlas si lo seria.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.auxiliar import (
    IMPRESO,
    RECALCULADO,
    SIN_SALDO,
    AuxiliarParser,
)
from contapdf.recalculo import recalcular_saldos
from contapdf.validate.rules import evaluar_auxiliar


def _aux(paginas):
    doc, _ = extraer(requires_real_pdf("auxiliar-gume"), page_numbers=paginas)
    return AuxiliarParser().parse(doc)


@pytest.fixture(scope="module")
def corto():
    return _aux([1, 2, 3, 4])


def test_lo_impreso_se_marca_como_impreso(corto):
    impresos = [f for f in corto.filas if f.saldo is not None and not f.es_subtotal]
    assert impresos
    assert all(f.saldo_origen == IMPRESO for f in impresos)
    sin = [f for f in corto.filas if f.saldo is None and not f.es_subtotal]
    assert all(f.saldo_origen == SIN_SALDO for f in sin)


def test_sin_ancla_no_recalcula_nada(corto):
    # En estas paginas la seccion con movimientos no llega a su subtotal:
    # sin el, no hay con que comprobar que la cadena esta completa.
    recalculada = recalcular_saldos(corto)
    assert not any(f.saldo_origen == RECALCULADO for f in recalculada.filas)
    assert recalculada.filas == corto.filas


def test_no_recalcula_si_falta_un_debe_o_un_haber(corto):
    filas = list(corto.filas)
    i = next(i for i, f in enumerate(filas) if not f.es_subtotal)
    filas[i] = dataclasses.replace(filas[i], debe=None)
    roto = dataclasses.replace(corto, filas=tuple(filas))
    assert not any(f.saldo_origen == RECALCULADO
                   for f in recalcular_saldos(roto).filas)


def test_nunca_recalcula_en_silencio(corto):
    cobertura = evaluar_auxiliar(recalcular_saldos(corto))
    assert "saldo" in cobertura.resumen_saldos().lower()
    assert set(cobertura.saldos) == {IMPRESO, RECALCULADO, SIN_SALDO}


@pytest.mark.lento
def test_con_ancla_recupera_los_2509_saldos():
    """La seccion completa: 118 paginas, ancla en los dos extremos.

    Medido: 7762 movimientos, 0 debe/haber ilegibles, el subtotal cuadra
    exacto, y de los 5253 saldos impresos los 5253 coinciden con el
    recalculo. Cero discrepancias.
    """
    completo = _aux(list(range(1, 119)))
    antes = [f for f in completo.filas if not f.es_subtotal]
    assert sum(1 for f in antes if f.saldo is None) == 2509

    recalculada = recalcular_saldos(completo)
    despues = [f for f in recalculada.filas if not f.es_subtotal]
    assert sum(1 for f in despues if f.saldo is None) == 0
    assert sum(1 for f in despues if f.saldo_origen == RECALCULADO) == 2509
    assert sum(1 for f in despues if f.saldo_origen == IMPRESO) == 5253

    # El recalculo aterriza donde el documento declara que debe aterrizar.
    subtotal = next(f for f in recalculada.filas
                    if f.es_subtotal and f.cuenta == "1120-001-003")
    assert despues[-1].saldo == subtotal.saldo == Decimal("92100.11")


@pytest.mark.lento
def test_el_recalculo_coincide_con_todo_saldo_impreso():
    recalculada = recalcular_saldos(_aux(list(range(1, 119))))
    cobertura = evaluar_auxiliar(recalculada)
    regla = next(r for r in cobertura.reglas if r.regla == "saldo_corrido")
    assert regla.estado == "cuadra"
    # Los 7762, incluido el primero: la cadena abre en el saldo inicial
    # que declara la seccion, asi que tambien es comprobable.
    assert regla.exactas == 7762
    assert not regla.discrepancias
