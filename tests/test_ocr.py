"""OCR: mismo IR que pdf_text y pdf_chars, para que layout/ no cambie."""

from __future__ import annotations

import inspect

import pytest
from conftest import requires_real_pdf

from contapdf.extract import ocr
from contapdf.ir import Page, Word
from contapdf.layout.lines import group

sin_tesseract = pytest.mark.skipif(not ocr.hay_tesseract(),
                                   reason="tesseract no instalado")


def test_hay_tesseract_no_truena_si_falta():
    # Nunca lanza: responde si esta o no, para que quien llame decida.
    assert isinstance(ocr.hay_tesseract(), bool)
    assert ocr.hay_tesseract(binario="no-existe-este-binario") is False


def test_sin_tesseract_avisa_en_vez_de_reventar():
    with pytest.raises(ocr.TesseractAusente) as exc:
        ocr.extract(requires_real_pdf("auxiliar-gume"),
                    binario="no-existe-este-binario")
    assert "tesseract" in str(exc.value).lower()


@sin_tesseract
def test_produce_el_mismo_ir_que_los_otros_extractores():
    doc = ocr.extract(requires_real_pdf("poliza"), page_numbers=[1])
    assert doc.page_count == 968
    paginas = doc.open_pages()
    assert inspect.isgenerator(paginas)
    page = next(paginas)
    assert isinstance(page, Page)
    assert page.number == 1
    assert all(isinstance(w, Word) for w in page.words)
    assert all(w.page == 1 and w.run == 0 for w in page.words)
    paginas.close()


@sin_tesseract
def test_las_coordenadas_vienen_en_puntos_no_en_pixeles():
    # El IR habla en puntos de PDF: si el OCR devolviera pixeles, layout/
    # detectaria columnas en otro sistema de coordenadas.
    page = next(ocr.extract(requires_real_pdf("poliza"),
                            page_numbers=[1], dpi=300).open_pages())
    assert 500 < page.width < 700
    assert all(0 <= w.x0 <= page.width + 1 for w in page.words)
    assert all(0 <= w.top <= page.height + 1 for w in page.words)


@sin_tesseract
def test_un_parser_existente_lo_consume_sin_cambios():
    # Criterio 3: layout/ y parsers/ no saben de donde vino el texto.
    page = next(ocr.extract(requires_real_pdf("poliza"),
                            page_numbers=[1]).open_pages())
    lineas = group(page.words)
    assert len(lineas) > 10
    texto = " ".join(w.text for ln in lineas for w in ln.words)
    assert "Totales" in texto or "TOTALES" in texto.upper()


@sin_tesseract
def test_descarta_lo_que_el_ocr_no_leyo_con_confianza():
    page = next(ocr.extract(requires_real_pdf("poliza"), page_numbers=[1],
                            confianza_minima=95.0).open_pages())
    exigente = len(page.words)
    page = next(ocr.extract(requires_real_pdf("poliza"), page_numbers=[1],
                            confianza_minima=0.0).open_pages())
    assert exigente <= len(page.words)


@sin_tesseract
def test_es_determinista():
    doc = ocr.extract(requires_real_pdf("poliza"), page_numbers=[1])
    assert list(doc.open_pages()) == list(doc.open_pages())
