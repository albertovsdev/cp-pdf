"""Acotar el analisis a la zona de la tabla.

Sin esto la pagina 1 del estado de cuenta detecta 1 sola columna, porque
el clustering ve metadatos, resumen de comisiones y sello digital.
"""

from __future__ import annotations

from conftest import layout_page

from contapdf.layout.columns import detect
from contapdf.layout.lines import group
from contapdf.layout.region import find_table_region, lines_within


def _lines(name: str, page_number: int):
    return group(layout_page(name, page_number).words, tol=2.5)


def _palabras(lines) -> set[str]:
    return {w.text for ln in lines for w in ln.words}


# --- Criterio de aceptacion: edocta pagina 1 ----------------------------
def test_edocta_pagina_1_completa_solo_detecta_una_columna():
    # El problema que region.py existe para resolver.
    assert len(detect(_lines("edocta", 1))) == 1


def test_edocta_pagina_1_acota_a_la_zona_de_movimientos():
    lines = _lines("edocta", 1)
    region = find_table_region(lines)
    assert region is not None

    dentro = lines_within(lines, region)
    palabras = _palabras(dentro)

    assert "DETALLE" in palabras and "Día" in palabras
    assert "Descripción" in palabras and "Saldo" in palabras
    # Queda fuera el metadato de arriba...
    assert "Sucursal:" not in palabras
    assert "corte" not in palabras
    assert "cuenta" not in palabras
    # ...y el sello digital de abajo.
    assert not any(len(w) > 60 for w in palabras)
    assert region.top > 420.0
    assert region.bottom < 640.0


def test_edocta_pagina_1_en_la_region_si_detecta_columnas():
    lines = _lines("edocta", 1)
    region = find_table_region(lines)
    assert len(detect(lines_within(lines, region))) >= 4


# --- La region no debe degradar las paginas que ya funcionaban ----------
def test_balanza_pagina_1_mantiene_sus_9_columnas_en_la_region():
    lines = _lines("balanza", 1)
    region = find_table_region(lines)
    assert region is not None
    assert len(detect(lines_within(lines, region))) == 9


def test_edocta_pagina_2_abarca_todo_el_detalle():
    lines = _lines("edocta", 2)
    region = find_table_region(lines)
    palabras = _palabras(lines_within(lines, region))
    assert "Día" in palabras                 # encabezado de la tabla
    assert "Referencia" in palabras
    assert "Estándar" not in palabras        # bloque de CLABE, arriba


def test_pagina_sin_tabla_devuelve_none():
    # auxiliar pagina 398: bloque de totales, sin renglones de movimiento.
    assert find_table_region(_lines("auxiliar", 398)) is None


def test_lines_within_sin_region_devuelve_todo():
    lines = _lines("auxiliar", 398)
    assert lines_within(lines, None) == lines


def test_region_es_desempaquetable_como_tupla():
    top, bottom = find_table_region(_lines("balanza", 1))
    assert top < bottom


def test_es_determinista_y_no_muta():
    lines = _lines("edocta", 1)
    antes = [[w.text for w in ln.words] for ln in lines]
    assert find_table_region(lines) == find_table_region(lines)
    assert [[w.text for w in ln.words] for ln in lines] == antes
