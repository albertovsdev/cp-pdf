"""Validacion aritmetica de la balanza."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from conftest import synthetic_document

from contapdf.parsers.balanza import BalanzaParser
from contapdf.validate.rules import validar_balanza


def _balanza(name: str = "balanza_sintetica"):
    return BalanzaParser().parse(synthetic_document(name))


def test_el_sintetico_cuadrado_no_tiene_discrepancias():
    assert validar_balanza(_balanza()) == []


def test_el_sintetico_descuadrado_reporta_exactamente_esa_fila():
    discrepancias = validar_balanza(_balanza("balanza_descuadrada"))
    assert len(discrepancias) == 1
    d = discrepancias[0]
    assert d.fila == "102-02"
    assert d.regla == "renglon"
    assert d.esperado == Decimal("40749.50")
    assert d.obtenido == Decimal("40849.50")


def test_la_discrepancia_apunta_al_indice_de_la_fila():
    balanza = _balanza("balanza_descuadrada")
    d = validar_balanza(balanza)[0]
    assert balanza.filas[d.indice].cuenta == "102-02"


def test_jerarquia_padre_igual_a_la_suma_de_sus_hijas_directas():
    # El sintetico cuadra: si rompo una hija, el padre deja de cuadrar.
    balanza = _balanza()
    filas = list(balanza.filas)
    i = next(i for i, f in enumerate(filas) if f.cuenta == "101-01")
    filas[i] = dataclasses.replace(filas[i], debe=filas[i].debe + Decimal("10.00"),
                                   saldo_fin_deudor=filas[i].saldo_fin_deudor + Decimal("10.00"))
    roto = dataclasses.replace(balanza, filas=tuple(filas))

    reglas = {(d.fila, d.regla) for d in validar_balanza(roto)}
    assert ("101", "jerarquia_debe") in reglas


def test_la_jerarquia_solo_mira_hijas_directas():
    # 102 tiene a 102-01 y 102-02 como hijas; 102-01-0001 es nieta y no
    # debe contarse dos veces.
    balanza = _balanza()
    assert not [d for d in validar_balanza(balanza) if d.regla.startswith("jerarquia")]


def test_totales_contra_la_suma_de_las_cuentas_de_nivel_1():
    balanza = _balanza()
    filas = list(balanza.filas)
    i = next(i for i, f in enumerate(filas) if f.cuenta == "601")
    filas[i] = dataclasses.replace(filas[i], debe=filas[i].debe + Decimal("5.00"),
                                   saldo_fin_deudor=filas[i].saldo_fin_deudor + Decimal("5.00"))
    roto = dataclasses.replace(balanza, filas=tuple(filas))

    reglas = {(d.fila, d.regla) for d in validar_balanza(roto)}
    assert ("Totales", "totales_debe") in reglas


def test_suma_debe_igual_suma_haber():
    balanza = _balanza()
    filas = list(balanza.filas)
    i = next(i for i, f in enumerate(filas) if f.cuenta == "401")
    filas[i] = dataclasses.replace(filas[i], haber=filas[i].haber + Decimal("1.00"),
                                   saldo_fin_acreedor=filas[i].saldo_fin_acreedor + Decimal("1.00"))
    roto = dataclasses.replace(balanza, filas=tuple(filas))

    reglas = {d.regla for d in validar_balanza(roto)}
    assert "partida_doble" in reglas


def test_tolera_un_centavo():
    balanza = _balanza()
    filas = list(balanza.filas)
    i = next(i for i, f in enumerate(filas) if f.cuenta == "601-02")
    filas[i] = dataclasses.replace(filas[i],
                                   saldo_fin_deudor=filas[i].saldo_fin_deudor + Decimal("0.01"))
    roto = dataclasses.replace(balanza, filas=tuple(filas))
    assert [d for d in validar_balanza(roto) if d.regla == "renglon"] == []

    filas[i] = dataclasses.replace(filas[i],
                                   saldo_fin_deudor=filas[i].saldo_fin_deudor + Decimal("0.02"))
    peor = dataclasses.replace(balanza, filas=tuple(filas))
    assert [d for d in validar_balanza(peor) if d.regla == "renglon"]


def test_no_lanza_excepciones_ni_imprime(capsys):
    validar_balanza(_balanza("balanza_descuadrada"))
    salida = capsys.readouterr()
    assert salida.out == "" and salida.err == ""


def test_es_determinista():
    balanza = _balanza("balanza_descuadrada")
    assert validar_balanza(balanza) == validar_balanza(balanza)
