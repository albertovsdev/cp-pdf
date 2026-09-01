"""Deduplicacion de tokens repetidos.

Hay documentos que dibujan el mismo contenido varias veces. La repeticion
ahoga el clustering: polizas-manufacturas y mayor-manufacturas detectan
UNA sola columna.

El criterio es coordenada casi identica Y contenido identico DENTRO del
mismo renglon. Deduplicar de mas borraria valores legitimamente repetidos:
dos renglones con 0.00 en la misma columna son dos datos, no uno.
"""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.extract import pdf_text
from contapdf.extract.dedup import deduplicar, multiplicador
from contapdf.ir import Word


def _w(text: str, x0: float, top: float) -> Word:
    return Word(text=text, x0=x0, x1=x0 + 10, top=top, bottom=top + 6,
                size=6.0, bold=False, page=1)


def test_quita_la_repeticion_en_la_misma_coordenada():
    palabras = [_w("CONTPAQ", 28.3, 28.6)] * 5
    assert len(deduplicar(palabras)) == 1


def test_tolera_el_desplazamiento_minimo_del_falso_negrita():
    # Santander repite con 0.03pt de corrimiento para simular negritas.
    palabras = [_w(":", 400.02, 93.6), _w(":", 400.05, 93.6)]
    assert len(deduplicar(palabras)) == 1


def test_no_toca_el_mismo_valor_en_renglones_distintos():
    # Dos renglones con 0.00 en la misma columna son dos datos.
    palabras = [_w("0.00", 198.0, 144.2), _w("0.00", 198.0, 157.7)]
    assert len(deduplicar(palabras)) == 2


def test_no_toca_el_mismo_valor_en_columnas_distintas():
    palabras = [_w("0.00", 198.0, 144.2), _w("0.00", 280.0, 144.2)]
    assert len(deduplicar(palabras)) == 2


def test_conserva_el_orden_y_la_primera_aparicion():
    palabras = [_w("A", 10.0, 5.0), _w("B", 30.0, 5.0), _w("A", 10.0, 5.0)]
    assert [w.text for w in deduplicar(palabras)] == ["A", "B"]


def test_mide_el_multiplicador():
    assert multiplicador([_w("X", 1.0, 1.0)] * 25) == 25
    assert multiplicador([_w("X", 1.0, 1.0), _w("Y", 20.0, 1.0)]) == 1
    assert multiplicador([]) == 1


@pytest.mark.parametrize(("nombre", "esperado"), [
    ("balanza-manufacturas", 5),
    ("polizas-manufacturas", 5),
    ("auxiliar-manufacturas", 25),
    ("mayor-manufacturas", 5),
])
def test_mide_la_repeticion_de_los_documentos_que_la_traen(nombre, esperado):
    page = next(pdf_text.extract(requires_real_pdf(nombre),
                                 page_numbers=[1]).open_pages())
    assert multiplicador(page.words) == esperado


@pytest.mark.parametrize("nombre", [
    "balanza", "balanza-businesspro", "balanza-gume", "poliza",
    "diario-general", "auxiliar", "auxiliar-gume", "mayor-gume",
])
def test_los_documentos_sin_repeticion_no_cambian(nombre):
    page = next(pdf_text.extract(requires_real_pdf(nombre),
                                 page_numbers=[1]).open_pages())
    assert multiplicador(page.words) == 1
    assert deduplicar(page.words) == tuple(page.words)
