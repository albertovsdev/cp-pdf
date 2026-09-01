"""Separacion de tokens que el PDF entrega pegados."""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.extract.tokens import separar_fecha_pegada
from contapdf.ir import Word


def _w(text: str, x0: float = 55.0) -> Word:
    return Word(text=text, x0=x0, x1=x0 + len(text) * 3.0, top=100.0,
                bottom=106.0, size=6.0, bold=False, page=1)


def test_parte_la_fecha_de_la_descripcion():
    salida = separar_fecha_pegada([_w("01-JUL-23DEP.EFECTIVO")])
    assert [w.text for w in salida] == ["01-JUL-23", "DEP.EFECTIVO"]


def test_el_largo_del_anio_sale_de_los_tokens_inequivocos():
    # '03-JUL-23085901' es ambiguo por si solo; '01-JUL-23DEP' no lo es y
    # dice que el anio va de dos digitos.
    salida = separar_fecha_pegada([_w("01-JUL-23DEP"), _w("03-JUL-23085901")])
    assert [w.text for w in salida] == ["01-JUL-23", "DEP", "03-JUL-23", "085901"]


def test_sin_ninguna_fecha_inequivoca_no_adivina():
    assert [w.text for w in separar_fecha_pegada([_w("03-JUL-23085901")])] == \
        ["03-JUL-23085901"]


def test_la_fecha_conserva_su_posicion_y_la_cola_arranca_despues():
    original = _w("01-JUL-23DEP.EFECTIVO")
    fecha, cola = separar_fecha_pegada([original])
    assert fecha.x0 == original.x0
    assert fecha.x1 <= cola.x0
    assert cola.x1 == original.x1
    assert fecha.top == cola.top == original.top


@pytest.mark.parametrize("texto", [
    "01-JUL-23", "DEP.EFECTIVO", "99,999.99", "2025-05-03", "SALDO",
])
def test_no_toca_lo_que_no_viene_pegado(texto):
    assert [w.text for w in separar_fecha_pegada([_w(texto)])] == [texto]


def test_en_el_documento_real_de_banorte():
    from contapdf.extract import pdf_text

    doc = pdf_text.extract(requires_real_pdf("edocta-julio-banorte"),
                           page_numbers=[2])
    page = next(doc.open_pages())
    pegadas = [w for w in page.words
               if len(w.text) > 9 and w.text[:9].count("-") == 2]
    assert len(pegadas) >= 10

    separadas = separar_fecha_pegada(page.words)
    textos = {w.text for w in separadas}
    assert "01-JUL-23" in textos
    assert "DEP.EFECTIVO" in textos
    assert not any(len(t) > 9 and t[:9].count("-") == 2 and t[9:] for t in textos)
