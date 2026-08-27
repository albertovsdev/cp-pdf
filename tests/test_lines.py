"""Agrupamiento de palabras en renglones logicos."""

from __future__ import annotations

from conftest import layout_page, texts

from contapdf.ir import Word
from contapdf.layout.lines import group


def _w(text: str, x0: float, top: float, alto: float = 10.0) -> Word:
    return Word(text=text, x0=x0, x1=x0 + 10, top=top, bottom=top + alto,
                size=10.0, bold=False, page=1)


def test_agrupa_por_solapamiento_no_por_top():
    # Mismo renglon logico con 'top' distinto: es el caso de las polizas.
    etiqueta = _w("401-01", 134.0, 157.2)
    importe = _w("$9.99", 462.0, 163.0)
    lines = group([etiqueta, importe], tol=2.5)
    assert len(lines) == 1


def test_no_se_traga_el_renglon_siguiente():
    lines = group([_w("a", 10.0, 100.0), _w("b", 10.0, 118.0)], tol=2.5)
    assert len(lines) == 2


def test_line_ordena_palabras_por_x0_y_renglones_por_top():
    derecha = _w("b", 300.0, 100.0)
    izquierda = _w("a", 10.0, 100.0)
    abajo = _w("c", 10.0, 130.0)
    lines = group([abajo, derecha, izquierda], tol=2.5)
    assert [texts(ln.words) for ln in lines] == [["a", "b"], ["c"]]
    assert lines[0].top < lines[1].top


def test_line_toma_top_y_bottom_de_sus_palabras():
    lines = group([_w("a", 10.0, 100.0, alto=10.0),
                   _w("b", 60.0, 103.0, alto=12.0)], tol=2.5)
    assert len(lines) == 1
    assert lines[0].top == 100.0
    assert lines[0].bottom == 115.0
    assert lines[0].page == 1


def test_sin_palabras_no_hay_renglones():
    assert group([], tol=2.5) == []


def test_es_determinista():
    page = layout_page("balanza", 1)
    a = group(page.words, tol=2.5)
    b = group(page.words, tol=2.5)
    assert [texts(ln.words) for ln in a] == [texts(ln.words) for ln in b]


def test_no_muta_la_entrada():
    page = layout_page("balanza", 1)
    antes = list(page.words)
    group(page.words, tol=2.5)
    assert list(page.words) == antes


# --- Criterio de aceptacion 4 -------------------------------------------
def test_poliza_etiqueta_y_sus_dos_importes_en_un_solo_line():
    page = layout_page("poliza", 1)
    lines = group(page.words, tol=2.5)

    con_401 = [ln for ln in lines
               if any(w.text == "401-01" for w in ln.words) and ln.top < 200]
    assert len(con_401) == 1, "la etiqueta 401-01 quedo repartida en varios Line"

    ln = con_401[0]
    importes = [w.text for w in ln.words if w.text.startswith("$")]
    assert importes == ["$9.99", "$999.99"]
    # El renglon completo: etiqueta + descripcion + los dos importes.
    assert texts(ln.words) == [
        "401-01", "Xxxxxx", "de", "xxxxxxxxxxxx", "xxxxxxxx", "a", "la",
        "tasa", "general", "$9.99", "$999.99",
    ]
