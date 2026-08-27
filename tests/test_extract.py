"""Extraccion de texto nativo con pdfplumber.

Usa los PDFs reales, que estan gitignored: si no estan, se salta.
"""

from __future__ import annotations

import inspect

from conftest import layout_page, load_layout, requires_real_pdf

from contapdf.extract.pdf_text import extract
from contapdf.ir import Page, Word


def test_extract_devuelve_document_con_el_conteo_de_paginas():
    doc = extract(requires_real_pdf("poliza"))
    assert doc.page_count == load_layout("poliza")["source_pages_total"]
    assert doc.source.endswith("poliza.pdf")


def test_las_paginas_llegan_de_a_una_no_todas_juntas():
    # 968 paginas no caben en memoria en un servidor compartido.
    doc = extract(requires_real_pdf("poliza"))
    paginas = doc.open_pages()
    assert inspect.isgenerator(paginas)
    primera = next(paginas)
    assert isinstance(primera, Page)
    assert primera.number == 1
    paginas.close()


def test_page_numbers_limita_lo_que_se_lee():
    doc = extract(requires_real_pdf("balanza"), page_numbers=[2, 9])
    assert [p.number for p in doc.open_pages()] == [2, 9]


def test_las_palabras_extraidas_coinciden_con_el_fixture():
    doc = extract(requires_real_pdf("balanza"), page_numbers=[1])
    page = next(doc.open_pages())
    esperada = layout_page("balanza", 1)

    assert len(page.words) == len(esperada.words)
    assert round(page.width, 1) == esperada.width
    assert round(page.height, 1) == esperada.height
    assert page.ruling_lines == esperada.ruling_lines

    # El texto esta enmascarado en el fixture; las coordenadas son reales.
    for got, ref in zip(page.words, esperada.words):
        assert (round(got.x0, 1), round(got.x1, 1)) == (ref.x0, ref.x1)
        assert (round(got.top, 1), round(got.bottom, 1)) == (ref.top, ref.bottom)
        assert isinstance(got, Word)
        assert got.page == 1


def test_es_determinista():
    doc = extract(requires_real_pdf("auxiliar"), page_numbers=[1])
    a = list(doc.open_pages())
    b = list(doc.open_pages())
    assert a == b
