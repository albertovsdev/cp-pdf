"""Extraccion a nivel de caracter, por corrida del content stream.

Existe porque en Business Pro la descripcion se encima sobre las columnas
numericas y extract_words pega glifos de corridas distintas.
"""

from __future__ import annotations

import inspect

from conftest import requires_real_pdf

from contapdf.extract import pdf_chars, pdf_text
from contapdf.ir import Page


def _pagina(nombre: str, numero: int) -> Page:
    return next(pdf_chars.extract(requires_real_pdf(nombre),
                                  page_numbers=[numero]).open_pages())


def test_produce_el_mismo_ir_que_pdf_text():
    doc = pdf_chars.extract(requires_real_pdf("balanza-businesspro"))
    assert doc.page_count == 4
    paginas = doc.open_pages()
    assert inspect.isgenerator(paginas)
    page = next(paginas)
    assert isinstance(page, Page)
    assert page.number == 1
    assert all(w.page == 1 for w in page.words)
    paginas.close()


def test_separa_la_descripcion_del_monto_que_se_le_encima():
    # pdf_text entrega 'A4N1,608,185.15': la descripcion 'AN' intercalada
    # con el importe. Por corrida quedan separados.
    palabras = {w.text for w in _pagina("balanza-businesspro", 1).words}
    assert "41,608,185.15" in palabras
    assert not any("A4N" in t for t in palabras)


def test_separa_dos_montos_pegados_por_el_signo_negativo():
    # '1,185.22-227,015.47' son dos importes sin espacio entre ellos.
    palabras = {w.text for w in _pagina("balanza-businesspro", 1).words}
    assert "-227,015.47" in palabras
    assert not any(t.count(".") > 1 for t in palabras if t[0].isdigit())


def test_separa_el_numero_de_cuenta_de_la_descripcion():
    palabras = {w.text for w in _pagina("balanza-businesspro", 1).words}
    assert "0400-0001-0000-0000" in palabras


def test_recupera_el_renglon_que_ninguna_ventana_por_x_alcanza():
    # 0401-0008: su descripcion trae '15%' y los digitos caen dentro de la
    # ventana del saldo anterior, encimados con el propio importe.
    page = _pagina("balanza-businesspro", 1)
    fila = [w for w in page.words if 380 <= w.top <= 392]
    textos = [w.text for w in fila]
    assert "0401-0008-0000-0000" in textos
    assert "74,769.75" in textos
    assert "127,699.42" in textos


def test_no_pierde_palabras_frente_a_pdf_text():
    con_chars = _pagina("balanza-businesspro", 1)
    con_text = next(pdf_text.extract(requires_real_pdf("balanza-businesspro"),
                                     page_numbers=[1]).open_pages())
    assert len(con_chars.words) > len(con_text.words)
    assert con_chars.width == con_text.width
    assert con_chars.ruling_lines == con_text.ruling_lines


def test_es_determinista():
    doc = pdf_chars.extract(requires_real_pdf("balanza-businesspro"), page_numbers=[1])
    assert list(doc.open_pages()) == list(doc.open_pages())


def test_sirve_igual_en_un_documento_sin_texto_encimado():
    # No es un reemplazo de pdf_text, pero no debe romper lo que ya servia.
    page = _pagina("balanza", 1)
    palabras = {w.text for w in page.words}
    assert "100-01" in palabras
    assert any(t.startswith("BALANZA") or t == "BALANZA" for t in palabras)
