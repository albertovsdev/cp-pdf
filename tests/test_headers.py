"""Etiquetado de columnas a partir de los renglones de encabezado."""

from __future__ import annotations

import pytest
from conftest import layout_page

from contapdf.layout.columns import detect
from contapdf.layout.headers import assign
from contapdf.layout.lines import group
from contapdf.layout.region import find_table_region, lines_within


def _etiquetadas(name: str, page_number: int):
    lines = group(layout_page(name, page_number).words, tol=2.5)
    region = find_table_region(lines)
    columns = detect(lines_within(lines, region))
    return assign(lines, region, columns)


def _headers(name: str, page_number: int) -> list[str]:
    return [c.header for c in _etiquetadas(name, page_number)]


def test_balanza_pagina_1_etiqueta_las_nueve_columnas():
    # Lo que la fase 2 necesita: mapear por nombre, no por indice.
    assert _headers("balanza", 1) == [
        "No. Cuenta",
        "Naturaleza",
        "Cuenta",
        "Saldo Inicial Deudor",
        "Saldo Inicial Acreedor",
        "Debe",
        "Haber",
        "Saldo Final Deudor",
        "Saldo Final Acreedor",
    ]


def test_balanza_pagina_2_da_las_mismas_etiquetas():
    assert _headers("balanza", 2) == _headers("balanza", 1)


def test_encabezado_multilinea_se_fusiona_en_una_etiqueta():
    # 'Saldo Inicial' arriba y 'Deudor' abajo son dos renglones visuales
    # reales: no se arreglan subiendo la tolerancia vertical de lines.group.
    cols = _etiquetadas("balanza", 1)
    assert cols[3].header == "Saldo Inicial Deudor"
    assert cols[3].align == "right"


def test_una_etiqueta_fuera_del_ancho_de_su_columna_se_asigna_a_la_mas_cercana():
    # 'Saldo' (309-325) cae en el hueco: la columna de importes es angosta
    # porque sus valores son cortos. Va a la columna 4, no a la 3.
    assert _etiquetadas("balanza", 1)[4].header == "Saldo Inicial Acreedor"


def test_edocta_pagina_2_no_arrastra_el_titulo_de_seccion():
    # 'DETALLE DE OPERACIONES' es un titulo, no un encabezado de columna.
    assert _headers("edocta", 2) == [
        "Día", "Descripción", "Referencia", "Depósitos", "Retiros", "Saldo",
    ]


def test_edocta_pagina_1_solo_etiqueta_las_columnas_que_existen():
    # En esta pagina no hay movimientos con deposito ni con referencia, asi
    # que esas columnas no se detectan y sus etiquetas se descartan.
    headers = _headers("edocta", 1)
    assert headers[0] == "Día"
    assert headers[1] == "Descripción"
    assert "Depósitos" not in headers
    assert "Referencia" not in headers
    assert headers[-1] == "Saldo"


def test_auxiliar_pagina_1():
    # FOLIO no tiene datos en esta pagina, asi que no hay columna propia y
    # su etiqueta cae en la vecina. Es la lectura honesta del documento.
    assert _headers("auxiliar", 1) == [
        "FOLIO FECHA", "TIPO", "DOCUMENTO", "TERCERO", "DEBE", "HABER", "SALDO",
    ]


def test_poliza_descarta_la_etiqueta_lejana():
    # 'Folio' vive a 99pt de la primera columna: es del encabezado del
    # bloque, no de la tabla de movimientos.
    assert _headers("poliza", 1) == ["Cuenta Contable", "Debe", "Haber"]


def test_no_muta_las_columnas_recibidas():
    lines = group(layout_page("balanza", 1).words, tol=2.5)
    region = find_table_region(lines)
    columns = detect(lines_within(lines, region))
    etiquetadas = assign(lines, region, columns)
    assert all(c.header == "" for c in columns)
    assert etiquetadas is not columns
    assert [c.index for c in etiquetadas] == [c.index for c in columns]


def test_sin_region_devuelve_las_columnas_sin_etiqueta():
    lines = group(layout_page("auxiliar", 398).words, tol=2.5)
    columns = detect(lines)
    assert [c.header for c in assign(lines, None, columns)] == [""] * len(columns)


def test_sin_columnas_no_hay_nada_que_etiquetar():
    lines = group(layout_page("balanza", 1).words, tol=2.5)
    assert assign(lines, find_table_region(lines), []) == []


def test_es_determinista():
    assert _etiquetadas("balanza", 1) == _etiquetadas("balanza", 1)


@pytest.mark.parametrize("name,page_number", [
    ("balanza", 1), ("balanza", 2), ("edocta", 1), ("edocta", 2),
    ("auxiliar", 1), ("auxiliar", 2), ("poliza", 1),
])
def test_toda_columna_conserva_su_geometria(name, page_number):
    lines = group(layout_page(name, page_number).words, tol=2.5)
    region = find_table_region(lines)
    columns = detect(lines_within(lines, region))
    for antes, despues in zip(columns, assign(lines, region, columns)):
        assert (despues.index, despues.align) == (antes.index, antes.align)
        assert (despues.x_min, despues.x_max) == (antes.x_min, antes.x_max)
        assert despues.support == antes.support


# --- Encabezados agrupados ----------------------------------------------
def _layout_de(nombre: str, pagina: int):
    from contapdf.layout.columns import detect
    from contapdf.layout.region import find_table_region, lines_within

    page = layout_page(nombre, pagina)
    lines = group(page.words, tol=2.5)
    region = find_table_region(lines)
    return assign(lines, region, detect(lines_within(lines, region)))


def test_una_etiqueta_que_abarca_dos_columnas_las_prefija():
    # 'Acumulados' se imprime sobre 'Cargos' y 'Abonos', que ya existen
    # como etiquetas de las columnas de movimiento. Sin el prefijo, las
    # cuatro columnas se llaman igual de a dos.
    from conftest import requires_real_pdf

    from contapdf.extract.strategy import extraer
    from contapdf.parsers.base import detectar_layout

    doc, _ = extraer(requires_real_pdf("mayor-gume"), page_numbers=[1, 2])
    layout = detectar_layout(list(doc.open_pages()))
    headers = [c.header for c in layout.columns]
    assert headers[1] == "Cargos" and headers[2] == "Abonos"
    assert headers[4] == "Acumulados Cargos"
    assert headers[5] == "Acumulados Abonos"
    assert len(set(headers)) == len(headers)


# --- Criterio 8 ----------------------------------------------------------
def test_el_agrupado_tambien_funciona_en_otra_balanza():
    """La regla es general, no una excepcion para 'Acumulados'.

    balanza-fd agrupa Deudor/Acreedor bajo SaldoAnterior y bajo
    SaldoActual (enmascarados en el fixture). Lo que se verifica aqui es
    que el prefijo se aplique y que sean grupos DISTINTOS; que ese
    documento tenga seis subetiquetas sobre cuatro columnas detectadas es
    un problema de deteccion suyo, de la fase que le toque.
    """
    cols = _layout_de("balanza-fd", 1)
    prefijados = [c.header for c in cols if "Deudor" in c.header]
    assert len(prefijados) == 2

    grupos = {h.split(" Deudor")[0] for h in prefijados}
    assert len(grupos) == 2               # SaldoAnterior y SaldoActual
    assert all(g and not g.startswith("Deudor") for g in grupos)
    # Y las subetiquetas nunca quedan sin su grupo.
    assert all("Acreedor" not in h or h.index("Acreedor") > 0
               for h in prefijados)


def test_el_encabezado_de_dos_renglones_de_siempre_no_cambia():
    # La balanza original parte 'Saldo Inicial' / 'Deudor' en dos
    # renglones sin que ninguno abarque dos columnas: sigue igual.
    assert _headers("balanza", 1) == [
        "No. Cuenta", "Naturaleza", "Cuenta", "Saldo Inicial Deudor",
        "Saldo Inicial Acreedor", "Debe", "Haber", "Saldo Final Deudor",
        "Saldo Final Acreedor",
    ]


def test_balanza_fd_pone_las_seis_subetiquetas_en_seis_columnas():
    """Criterio 5. Lo que lo impedia no era el agrupado sino la repeticion.

    La pagina 3 imprime su encabezado DOS veces; con los tokens repetidos
    las dos subcolumnas de saldo se fundian en una.
    """
    from conftest import requires_real_pdf

    from contapdf.extract.strategy import extraer
    from contapdf.parsers.base import detectar_layout

    doc, _ = extraer(requires_real_pdf("balanza-fd"), page_numbers=[1, 2, 3])
    headers = [c.header for c in detectar_layout(list(doc.open_pages())).columns]

    assert "SaldosIniciales Deudor" in headers
    assert "SaldosIniciales Acreedor" in headers
    assert "Cargos" in headers and "Abonos" in headers
    assert "SaldosActuales Deudor" in headers
    assert "SaldosActuales Acreedor" in headers
    assert len(headers) == len(set(headers))
