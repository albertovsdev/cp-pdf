"""OCR: mismo IR que pdf_text y pdf_chars, para que layout/ no cambie."""

from __future__ import annotations

import inspect
import subprocess
import sys

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

# --- Fase 8d: el OCR nunca ha funcionado en Windows ---------------------
# `ocr.py` lanzaba Tesseract con `text=True` y sin `encoding`, asi que
# Python decodificaba con el default del sistema. En Linux ese default es
# UTF-8 y no se nota; en un Windows en espanol es cp1252, el hilo lector de
# `subprocess` muere con UnicodeDecodeError, `communicate()` devuelve
# `stdout=None` y `_tsv_a_palabras` estalla dos capas mas abajo con
# `AttributeError: 'NoneType' object has no attribute 'splitlines'`. Ese
# AttributeError es el SINTOMA; se interpreto mal dos veces.
#
# La suite corre en WSL, asi que ningun test puede apoyarse en la
# plataforma: estos fuerzan la CONDICION -- bytes UTF-8 que cp1252 no puede
# decodificar, y una salida vacia -- que es lo que la maquina objetivo tenia.

_TSV_ENCABEZADO = ("level\tpage_num\tblock_num\tpar_num\tline_num\t"
                   "word_num\tleft\ttop\twidth\theight\tconf\ttext")
# El caracter es una comilla tipografica derecha, U+201D = E2 80 9D en
# UTF-8. El 0x9D no existe en cp1252: es el byte exacto del error de
# SERVIDORSIST. Tesseract en espanol las produce.
_TSV_CON_COMILLA = (_TSV_ENCABEZADO
                    + "\n5\t1\t1\t1\t1\t1\t100\t200\t50\t20\t96\tPAGO\n"
                    + "5\t1\t1\t1\t1\t2\t160\t200\t90\t20\t95\t”NOMINA”\n")


def test_la_condicion_de_windows_es_real_y_esta_forzada_aqui():
    """La premisa, en codigo: sin esto los dos tests de abajo no prueban nada."""
    crudo = _TSV_CON_COMILLA.encode("utf-8")
    with pytest.raises(UnicodeDecodeError) as exc:
        crudo.decode("cp1252")
    assert "0x9d" in str(exc.value)


def test_tesseract_se_lee_en_utf8_y_no_en_el_default_del_sistema():
    """Se corre un proceso de verdad: es la decodificacion lo que se prueba."""
    crudo = _TSV_CON_COMILLA.encode("utf-8")
    orden = [sys.executable, "-c",
             f"import sys; sys.stdout.buffer.write({crudo!r})"]
    assert ocr._correr_tesseract(orden, 1) == _TSV_CON_COMILLA


def test_las_palabras_sobreviven_a_los_bytes_que_cp1252_no_decodifica():
    palabras = ocr._tsv_a_palabras(_TSV_CON_COMILLA, 1, 300 / 72, 40.0)
    assert [w.text for w in palabras] == ["PAGO", "”NOMINA”"]


def test_una_salida_vacia_da_un_error_con_nombre_propio(monkeypatch):
    """No un AttributeError dos capas mas abajo, que es lo que se leyo mal."""
    def sin_salida(orden, **kwargs):
        return subprocess.CompletedProcess(orden, 0, stdout=None, stderr="")

    monkeypatch.setattr(ocr.subprocess, "run", sin_salida)
    with pytest.raises(ocr.TesseractSinSalida) as exc:
        ocr._correr_tesseract(["tesseract"], 7)
    assert "7" in str(exc.value)


def test_una_salida_en_blanco_tambien(monkeypatch):
    # Tesseract siempre imprime al menos la fila de encabezado del TSV:
    # una salida vacia con codigo 0 es un fallo, no una pagina en blanco.
    def en_blanco(orden, **kwargs):
        return subprocess.CompletedProcess(orden, 0, stdout="", stderr="")

    monkeypatch.setattr(ocr.subprocess, "run", en_blanco)
    with pytest.raises(ocr.TesseractSinSalida):
        ocr._correr_tesseract(["tesseract"], 3)


def test_leer_pagina_no_estalla_con_un_attributeerror(monkeypatch):
    """La traza de SERVIDORSIST, reproducida sin depender de la plataforma."""
    def sin_salida(orden, **kwargs):
        return subprocess.CompletedProcess(orden, 0, stdout=None, stderr="")

    monkeypatch.setattr(ocr, "hay_tesseract", lambda **kwargs: True)
    monkeypatch.setattr(ocr.subprocess, "run", sin_salida)
    with pytest.raises(ocr.TesseractSinSalida):
        ocr.leer_pagina(requires_real_pdf("edocta"), 1)
