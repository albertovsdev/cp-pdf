"""Las reglas de validacion se declaran por formato, no van cableadas."""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf, synthetic_document

from contapdf.extract.strategy import extraer
from contapdf.parsers.balanza import BalanzaParser
from contapdf.validate.rules import ReglasBalanza, validar_balanza


@pytest.fixture(scope="module")
def businesspro():
    doc, _ = extraer(requires_real_pdf("balanza-businesspro"))
    return BalanzaParser().parse(doc)


def test_el_subconjunto_de_totales_es_declarable():
    reglas = ReglasBalanza(subconjunto_totales="no_acumulativas")
    assert reglas.subconjunto_totales == "no_acumulativas"
    assert ReglasBalanza().subconjunto_totales == "nivel_1"


def test_nivel_1_cuadra_en_los_dos_documentos(businesspro):
    sintetica = BalanzaParser().parse(synthetic_document("balanza_sintetica"))
    reglas = ReglasBalanza(subconjunto_totales="nivel_1")
    assert [d for d in validar_balanza(sintetica, reglas=reglas)
            if d.regla.startswith("totales")] == []
    assert [d for d in validar_balanza(businesspro, reglas=reglas)
            if d.regla.startswith("totales")] == []


def test_la_partida_doble_no_aplica_a_un_documento_parcial(businesspro):
    # Business Pro imprime solo la seccion de resultados: sus sumas no
    # cuadran entre si por diseño, y su propia fila SUMAS lo declara.
    assert businesspro.totales.debe != businesspro.totales.haber
    reglas = ReglasBalanza.para(businesspro)
    assert reglas.exige_partida_doble is False
    assert [d for d in validar_balanza(businesspro, reglas=reglas)
            if d.regla == "partida_doble"] == []


def test_la_partida_doble_si_aplica_cuando_el_documento_la_declara():
    sintetica = BalanzaParser().parse(synthetic_document("balanza_sintetica"))
    assert sintetica.totales.debe == sintetica.totales.haber
    assert ReglasBalanza.para(sintetica).exige_partida_doble is True


def test_imponer_la_partida_doble_a_un_documento_parcial_la_reporta(businesspro):
    reglas = ReglasBalanza(exige_partida_doble=True)
    fallas = [d for d in validar_balanza(businesspro, reglas=reglas)
              if d.regla == "partida_doble"]
    assert len(fallas) == 1


def test_la_tolerancia_es_parametro_de_las_reglas():
    assert ReglasBalanza().tolerancia == Decimal("0.01")
    assert ReglasBalanza(tolerancia=Decimal("0.05")).tolerancia == Decimal("0.05")
