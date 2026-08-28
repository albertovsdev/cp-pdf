"""El vocabulario propone, el checksum dispone (PLAN 2)."""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf, synthetic_document

from contapdf.extract.strategy import extraer
from contapdf.parsers.balanza import (
    BalanzaParser,
    LayoutDesconocido,
    proponer_mapeos,
)
from contapdf.parsers.base import detectar_layout


def _layout(nombre_real: str):
    doc, _ = extraer(requires_real_pdf(nombre_real))
    paginas = []
    for page in doc.open_pages():
        paginas.append(page)
        if len(paginas) == 2:
            break
    return detectar_layout(paginas)


def test_propone_varios_mapeos_ordenados_por_calidad_de_coincidencia():
    propuestas = proponer_mapeos(_layout("balanza"))
    assert len(propuestas) >= 1
    # El primero es el que coincide exacto con los encabezados del PDF.
    campos = set(propuestas[0])
    assert {"debe", "haber", "saldo_ini_deudor", "saldo_fin_acreedor"} <= campos


def test_en_business_pro_propone_la_forma_de_saldo_con_signo():
    propuestas = proponer_mapeos(_layout("balanza-businesspro"))
    assert propuestas
    campos = set(propuestas[0])
    assert {"debe", "haber", "saldo_inicial", "saldo_final"} <= campos
    assert "saldo_ini_deudor" not in campos


def test_un_mapeo_que_no_cuadra_se_rechaza():
    doc, _ = extraer(requires_real_pdf("balanza-businesspro"))
    parser = BalanzaParser()
    paginas = []
    for page in doc.open_pages():
        paginas.append(page)
        if len(paginas) == 2:
            break
    layout = detectar_layout(paginas)
    bueno = proponer_mapeos(layout)[0]
    invertido = dict(bueno)
    invertido["debe"], invertido["haber"] = invertido["haber"], invertido["debe"]

    assert parser.verifica(layout, paginas, bueno) is True
    assert parser.verifica(layout, paginas, invertido) is False


def test_si_ningun_mapeo_cuadra_avisa_y_no_entrega():
    # Un layout cuyas etiquetas no nombran ninguna columna de balanza.
    doc, _ = extraer(requires_real_pdf("mayor-gume"))
    with pytest.raises(LayoutDesconocido):
        BalanzaParser().parse(doc)


def test_el_sintetico_sigue_mapeando_por_nombre():
    balanza = BalanzaParser().parse(synthetic_document("balanza_sintetica"))
    assert len(balanza.filas) == 16
