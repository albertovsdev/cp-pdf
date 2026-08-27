"""Deteccion de columnas.

Los numeros de este archivo son las mediciones de la fase 0 (PLAN.md
seccion 2), no metas ajustables.
"""

from __future__ import annotations

import pytest
from conftest import layout_page

from contapdf.layout.columns import detect, is_amount
from contapdf.layout.lines import group


def _columns(name: str, page_number: int):
    page = layout_page(name, page_number)
    return detect(group(page.words, tol=2.5))


# --- Criterios de aceptacion 1, 2 y 3 -----------------------------------
@pytest.mark.parametrize(
    ("name", "page_number", "esperadas"),
    [
        ("balanza", 1, 9),
        ("balanza", 2, 9),
        ("edocta", 2, 5),
        ("auxiliar", 1, 6),
    ],
)
def test_numero_de_columnas_de_la_fase_0(name, page_number, esperadas):
    assert len(_columns(name, page_number)) == esperadas


def test_los_indices_son_consecutivos_y_de_izquierda_a_derecha():
    cols = _columns("balanza", 1)
    assert [c.index for c in cols] == list(range(len(cols)))
    assert [c.x_min for c in cols] == sorted(c.x_min for c in cols)


def test_los_montos_se_agrupan_por_x1():
    # 'Debe' en la balanza: los importes varian de largo, asi que comparten
    # borde derecho (~400) pero no borde izquierdo.
    cols = _columns("balanza", 1)
    debe = [c for c in cols if abs(c.x_max - 400.3) < 1.0]
    assert len(debe) == 1
    assert debe[0].align == "right"
    assert debe[0].x_max - debe[0].x_min > 20  # x0 disperso: por x0 no agrupa


def test_las_columnas_de_texto_se_agrupan_por_x0():
    cols = _columns("balanza", 1)
    cuenta = [c for c in cols if abs(c.x_min - 128.0) < 1.0]
    assert len(cuenta) == 1
    assert cuenta[0].align == "left"


def test_el_soporte_cuenta_las_palabras_que_sustentan_la_columna():
    cols = _columns("balanza", 1)
    assert all(c.support >= 3 for c in cols)
    assert max(c.support for c in cols) > 40  # ~51 renglones de datos


def test_min_support_es_parametro_no_estado_global():
    assert len(detect(group(layout_page("balanza", 1).words), min_support=200)) == 0


def test_es_determinista():
    assert _columns("auxiliar", 1) == _columns("auxiliar", 1)


def test_sin_renglones_no_hay_columnas():
    assert detect([]) == []


@pytest.mark.parametrize(
    ("texto", "es_monto"),
    [
        ("99,999.99", True),
        ("$9.99", True),
        ("-99,999.99", True),
        ("101-01", False),      # cuenta contable: va a la izquierda
        ("102-01-003", False),
        ("99/99/9999", False),  # fecha: va a la izquierda
        ("99-99-9999", False),
        ("Xxxxxx", False),
        ("$", False),           # simbolo suelto, sin digitos
        ("", False),
    ],
)
def test_is_amount_distingue_montos_de_cuentas_y_fechas(texto, es_monto):
    assert is_amount(texto) is es_monto
