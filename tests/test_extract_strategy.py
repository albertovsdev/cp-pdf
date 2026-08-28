"""Eleccion de estrategia de extraccion.

pdf_text es el default. Se cambia a pdf_chars solo si el documento trae
tokens contaminados: glifos de corridas distintas pegados en una palabra.
"""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import (
    esta_contaminada,
    extraer,
    tokens_contaminados,
)
from contapdf.ir import Word


def _w(text: str) -> Word:
    return Word(text=text, x0=0.0, x1=10.0, top=0.0, bottom=6.0, size=6.0,
                bold=False, page=1)


@pytest.mark.parametrize("texto", [
    "A4N1,608,185.15",      # letras intercaladas con el importe
    "SERDAN-228,200.69",    # descripcion pegada a un importe negativo
    "1,185.22-227,015.47",  # dos importes pegados
])
def test_reconoce_un_token_contaminado(texto):
    assert tokens_contaminados([_w(texto)]) == [_w(texto)]


@pytest.mark.parametrize("texto", [
    "99,999.99", "-1,250.25", "INGRESOS", "0400-0001-0000-0000",
    "99/99/9999", "ACUM", "15%", "$999.99",
])
def test_no_confunde_un_token_sano_con_uno_contaminado(texto):
    assert tokens_contaminados([_w(texto)]) == []


def test_business_pro_esta_contaminado_y_los_demas_no():
    limpios = ["balanza", "auxiliar", "auxiliar-gume", "mayor-gume", "diario-general"]
    assert esta_contaminada(requires_real_pdf("balanza-businesspro")) is True
    for nombre in limpios:
        assert esta_contaminada(requires_real_pdf(nombre)) is False, nombre


def test_extraer_elige_y_reporta_la_estrategia():
    doc, estrategia = extraer(requires_real_pdf("balanza-businesspro"))
    assert estrategia == "pdf_chars"
    assert doc.page_count == 4

    doc, estrategia = extraer(requires_real_pdf("balanza"))
    assert estrategia == "pdf_text"
    assert doc.page_count == 9


def test_la_estrategia_se_puede_imponer():
    # Es lo que la fase 4 guardara en la plantilla: no re-detectar cada vez.
    _, estrategia = extraer(requires_real_pdf("balanza-businesspro"),
                            estrategia="pdf_text")
    assert estrategia == "pdf_text"
