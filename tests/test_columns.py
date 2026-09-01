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


@pytest.mark.parametrize("cuenta", [
    "101",                    # base de 3, sin subcuentas
    "101-01",
    "102-01-0001",
    "1110-000-000",           # base de 4, tres segmentos
    "0400-0000-0000-0000",    # base de 4, cuatro segmentos
    "12345-1",
])
def test_una_cuenta_contable_nunca_es_un_monto(cuenta):
    # Si se cuela como monto, se agrupa por x1 en vez de x0 y la deteccion
    # de columnas se degrada EN SILENCIO. La restriccion de base de 3
    # digitos exactos vive en dump_layout.py por privacidad; aqui, que es
    # geometria pura, no hay dato que proteger.
    assert is_amount(cuenta) is False


def test_las_cuentas_de_base_4_no_rompen_la_deteccion_de_columnas():
    from contapdf.ir import Line, Word

    def _w(text, x0, x1, top):
        return Word(text=text, x0=x0, x1=x1, top=top, bottom=top + 6,
                    size=6.0, bold=False, page=1)

    lines = []
    for i in range(6):
        top = 100.0 + i * 10
        lines.append(Line(
            words=[
                _w("0400-0000-0000-0000", 26.0, 90.0, top),
                _w("Xxxxxx", 128.0, 160.0, top),
                _w("9,999.99", 370.0, 400.3, top),
                _w("99.99", 442.0, 457.0, top),
            ],
            top=top, bottom=top + 6, page=1))

    cols = detect(lines)
    cuenta = [c for c in cols if c.x_min < 100]
    assert len(cuenta) == 1
    assert cuenta[0].align == "left"
    assert len(cols) == 4


def test_auxiliar_p398_gana_la_columna_documento():
    # La fase 0 midio 3 columnas aqui. Son 4: el folio de 6 digitos
    # (999999) se contaba como monto y se agrupaba por x1, asi que
    # DOCUMENTO no llegaba a formar columna. Medicion nueva, no meta
    # ajustada: la de la fase 0 estaba degradada por is_amount.
    cols = _columns("auxiliar", 398)
    assert len(cols) == 4


@pytest.mark.parametrize("page_number", [1, 2])
def test_documento_del_auxiliar_es_columna_izquierda(page_number):
    # x0 fijo en 186 y x1 variable segun el largo del folio: alineada a la
    # IZQUIERDA. La fase 0 la reportaba a la derecha con extension
    # x[186..211], que solo cuadraba mientras los folios midieran igual.
    from contapdf.layout.region import find_table_region, lines_within

    page = layout_page("auxiliar", page_number)
    lines = group(page.words, tol=2.5)
    cols = detect(lines_within(lines, find_table_region(lines)))
    documento = [c for c in cols if abs(c.x_min - 186.0) < 1.0]
    assert len(documento) == 1
    assert documento[0].align == "left"
    assert documento[0].x_max > 240.0


# --- Cuentas ambiguas: la posicion decide, no la forma ------------------
def test_is_amount_no_puede_distinguir_una_cuenta_con_puntos_por_su_forma():
    # '101.01' y '999.99' son indistinguibles: la misma pinta exacta.
    assert is_amount("999.99") is True
    assert is_amount("101.01") is True


def test_en_la_columna_de_cuenta_la_forma_ambigua_es_texto():
    assert is_amount("101.01", en_columna_de_cuenta=True) is False
    assert is_amount("101.01.01", en_columna_de_cuenta=True) is False
    assert is_amount("999.99", en_columna_de_cuenta=True) is False


def test_la_columna_de_cuenta_no_convierte_en_texto_a_un_monto_normal():
    # Un importe de verdad trae separador de miles o signo: no es ambiguo.
    assert is_amount("99,999.99", en_columna_de_cuenta=True) is True
    assert is_amount("-1,250.25", en_columna_de_cuenta=True) is True


def test_el_parametro_es_aditivo():
    # Los cinco parsers llaman a is_amount(texto) sin el: no cambia nada.
    for texto in ("99,999.99", "101-01", "01/01/2025", "Xxxxxx", "0.00"):
        assert is_amount(texto) == is_amount(texto, en_columna_de_cuenta=False)


def test_proactivity_deja_de_partir_su_columna_de_cuenta():
    """Las cuentas 101.01.01 se agrupaban por x1 y, al tener largos
    distintos, producian tres columnas falsas donde hay una sola.
    """
    from conftest import requires_real_pdf

    from contapdf.extract.strategy import extraer
    from contapdf.parsers.base import detectar_layout

    doc, _ = extraer(requires_real_pdf("balanza-proactivity"), page_numbers=[1, 2])
    columnas = detectar_layout(list(doc.open_pages())).columns

    izquierda = [c for c in columnas if c.x_min < 100]
    assert len(izquierda) == 1
    assert izquierda[0].align == "left"
    assert len(columnas) < 11
