"""El IR es el contrato entre extraccion y parsers: se testea su forma."""

from __future__ import annotations

import dataclasses

import pytest

from contapdf.ir import ColumnSpec, Document, Line, Page, Word


def _word(**kw) -> Word:
    base = dict(text="x", x0=1.0, x1=2.0, top=3.0, bottom=4.0,
                size=10.0, bold=False, page=1)
    base.update(kw)
    return Word(**base)


def test_word_tiene_los_campos_del_contrato():
    w = _word()
    campos = [f.name for f in dataclasses.fields(w)]
    assert campos == ["text", "x0", "x1", "top", "bottom", "size", "bold", "page"]


def test_word_es_inmutable():
    # Un Word compartido entre paginas/hilos no puede mutarse por accidente.
    with pytest.raises(dataclasses.FrozenInstanceError):
        _word().x0 = 99.0


def test_word_es_hashable_y_comparable_por_valor():
    assert _word() == _word()
    assert len({_word(), _word()}) == 1


def test_line_expone_words_top_bottom_page():
    a = _word(top=10.0, bottom=20.0, x0=5.0)
    b = _word(top=12.0, bottom=22.0, x0=1.0)
    line = Line(words=[a, b], top=10.0, bottom=22.0, page=1)
    assert line.words == [a, b]
    assert (line.top, line.bottom, line.page) == (10.0, 22.0, 1)


def test_column_spec_tiene_header_vacio_por_defecto():
    c = ColumnSpec(index=0, align="right", x_min=10.0, x_max=20.0, support=7)
    assert c.header == ""
    assert c.align in ("left", "right")


def test_page_guarda_palabras_y_geometria():
    p = Page(number=3, width=612.0, height=792.0, words=(_word(page=3),))
    assert p.number == 3
    assert p.words[0].page == 3


def test_document_entrega_paginas_bajo_demanda():
    # Contrato clave: Document NO guarda las paginas, guarda como abrirlas.
    # Es lo que evita cargar 968 paginas en memoria.
    paginas = [Page(number=n, width=1.0, height=1.0, words=()) for n in (1, 2)]
    doc = Document(source="x.pdf", page_count=2, open_pages=lambda: iter(paginas))
    assert [p.number for p in doc.open_pages()] == [1, 2]
    assert [p.number for p in doc.open_pages()] == [1, 2]  # re-iterable
