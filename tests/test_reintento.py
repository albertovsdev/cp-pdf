"""Reintento por pagina disparado por la aritmetica.

La validacion deja de ser solo control de calidad: cuando el saldo corrido
se rompe sin explicacion, esa pagina se reintenta por otra via.
"""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.extract import ocr
from contapdf.extract.strategy import extraer
from contapdf.parsers.auxiliar import AuxiliarParser
from contapdf.reintento import paginas_a_reintentar, reintentar_ilegibles

sin_tesseract = pytest.mark.skipif(not ocr.hay_tesseract(),
                                   reason="tesseract no instalado")


@pytest.fixture(scope="module")
def gume():
    doc, _ = extraer(requires_real_pdf("auxiliar-gume"), page_numbers=[1, 2, 3, 4])
    return AuxiliarParser().parse(doc)


# --- Criterio 4: las paginas salen de la aritmetica, no de una lista ----
def test_identifica_las_paginas_con_dato_ilegible(gume):
    sospechosas = paginas_a_reintentar(gume)
    assert sospechosas
    assert {s.pagina for s in sospechosas} == {3, 4}
    assert all(s.motivo for s in sospechosas)


def test_un_documento_sano_no_pide_reintento():
    doc, _ = extraer(requires_real_pdf("auxiliar"), page_numbers=[1, 2, 3])
    sano = AuxiliarParser().parse(doc)
    assert paginas_a_reintentar(sano) == []


def test_cada_movimiento_sabe_de_que_pagina_salio(gume):
    # Sin esto el reintento seria por documento, no por pagina.
    assert all(f.pagina > 0 for f in gume.filas)
    assert {f.pagina for f in gume.filas} <= {1, 2, 3, 4}


# --- Criterio 6: degrada limpio sin tesseract ---------------------------
def test_sin_tesseract_lo_declara_y_no_truena(gume):
    reporte = reintentar_ilegibles(requires_real_pdf("auxiliar-gume"), gume,
                                   binario="no-existe-este-binario")
    assert reporte.disponible is False
    assert reporte.recuperados == 0
    assert "tesseract" in reporte.motivo.lower()
    assert reporte.paginas == (3, 4)


# --- Criterio 5: cuanto recupera de verdad ------------------------------
@pytest.mark.lento
@sin_tesseract
def test_mide_cuantos_datos_recupera_el_ocr(gume):
    ilegibles = sum(1 for f in gume.filas if not f.es_subtotal and f.saldo is None)
    assert ilegibles == 74

    reporte = reintentar_ilegibles(requires_real_pdf("auxiliar-gume"), gume)
    assert reporte.disponible is True
    assert reporte.paginas == (3, 4)

    # El numero real: CERO. El OCR si lee algo en 19 de las 74 celdas,
    # pero lo que lee viene truncado en la propia pagina ('1,025,814.4',
    # un decimal). Aceptarlo meteria un numero equivocado.
    assert reporte.recuperados == 0
    assert reporte.truncados == 19
    assert "truncadas" in reporte.motivo
