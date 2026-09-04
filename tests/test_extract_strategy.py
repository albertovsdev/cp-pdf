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


@pytest.mark.lento          # 4 s
def test_reconoce_los_dos_documentos_que_necesitan_extraccion_por_corridas():
    # Dos firmas distintas: Business Pro pega glifos de corridas distintas
    # en una palabra; el diario general imprime una columna ENCIMA de otra
    # y sus palabras se intercalan al ordenar por x.
    for sucio in ("balanza-businesspro", "diario-general"):
        assert esta_contaminada(requires_real_pdf(sucio)) is True, sucio
    for limpio in ("balanza", "poliza", "auxiliar", "auxiliar-gume", "mayor-gume"):
        assert esta_contaminada(requires_real_pdf(limpio)) is False, limpio


def test_la_sobreimpresion_se_mide_aparte_de_los_glifos_pegados():
    from contapdf.extract import pdf_text
    from contapdf.extract.strategy import palabras_traslapadas

    pagina = next(pdf_text.extract(requires_real_pdf("diario-general"),
                                   page_numbers=[1]).open_pages())
    assert tokens_contaminados(pagina.words) == []      # no hay glifos pegados
    assert palabras_traslapadas(pagina.words) > 100     # si hay sobreimpresion


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


# --- Criterio 1: la repeticion ahogaba el clustering --------------------
@pytest.mark.parametrize(("nombre", "minimo"), [
    ("polizas-manufacturas", 4),
    ("mayor-manufacturas", 4),
])
def test_los_documentos_repetidos_dejan_de_ver_una_sola_columna(nombre, minimo):
    from contapdf.extract.strategy import extraer
    from contapdf.parsers.base import detectar_layout

    doc, _ = extraer(requires_real_pdf(nombre), page_numbers=[1, 2])
    layout = detectar_layout(list(doc.open_pages()))
    assert layout is not None
    assert len(layout.columns) >= minimo


def test_extraer_deduplica_y_lo_reporta():
    from contapdf.extract import pdf_text
    from contapdf.extract.dedup import multiplicador
    from contapdf.extract.strategy import extraer

    crudo = next(pdf_text.extract(requires_real_pdf("auxiliar-manufacturas"),
                                  page_numbers=[1]).open_pages())
    assert multiplicador(crudo.words) == 25

    doc, _ = extraer(requires_real_pdf("auxiliar-manufacturas"), page_numbers=[1])
    limpio = next(doc.open_pages())
    assert multiplicador(limpio.words) == 1
    assert len(limpio.words) < len(crudo.words)


# --- Criterio 2: los documentos sanos no cambian ------------------------
# Los cuatro grandes van marcados uno a uno: la propiedad se comprueba
# igual con los pequenos en cada ciclo, y los grandes antes de entregar.
@pytest.mark.parametrize("nombre", [
    "balanza", "balanza-businesspro", "balanza-gume",
    pytest.param("poliza", marks=pytest.mark.lento),
    pytest.param("diario-general", marks=pytest.mark.lento),
    pytest.param("auxiliar", marks=pytest.mark.lento),
    pytest.param("auxiliar-gume", marks=pytest.mark.lento),
    "mayor-gume", "edocta",
])
def test_deduplicar_no_altera_a_los_que_ya_funcionaban(nombre):
    from contapdf.extract import pdf_chars, pdf_text
    from contapdf.extract.strategy import esta_contaminada, extraer

    crudo_mod = pdf_chars if esta_contaminada(requires_real_pdf(nombre)) else pdf_text
    crudo = next(crudo_mod.extract(requires_real_pdf(nombre),
                                   page_numbers=[2]).open_pages())
    doc, _ = extraer(requires_real_pdf(nombre), page_numbers=[2])
    limpio = next(doc.open_pages())
    assert limpio.words == crudo.words
