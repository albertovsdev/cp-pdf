"""Parser de balanza de comprobacion."""

from __future__ import annotations

from decimal import Decimal

from conftest import counted_document, golden_rows, synthetic_document

from contapdf.parsers.balanza import BalanzaParser, FilaBalanza


def _balanza(name: str = "balanza_sintetica"):
    return BalanzaParser().parse(synthetic_document(name))


def test_salida_igual_al_golden_csv():
    filas = _balanza().filas
    esperadas = golden_rows("balanza_sintetica")
    assert len(filas) == len(esperadas)
    for fila, esperada in zip(filas, esperadas):
        assert fila.cuenta == esperada["cuenta"]
        assert fila.nivel == int(esperada["nivel"])
        assert fila.cuenta_padre == esperada["cuenta_padre"]
        assert fila.naturaleza == esperada["naturaleza"]
        assert fila.nombre == esperada["nombre"]
        assert fila.saldo_ini_deudor == Decimal(esperada["saldo_ini_deudor"])
        assert fila.saldo_ini_acreedor == Decimal(esperada["saldo_ini_acreedor"])
        assert fila.debe == Decimal(esperada["debe"])
        assert fila.haber == Decimal(esperada["haber"])
        assert fila.saldo_fin_deudor == Decimal(esperada["saldo_fin_deudor"])
        assert fila.saldo_fin_acreedor == Decimal(esperada["saldo_fin_acreedor"])


def test_nivel_y_cuenta_padre_se_derivan_del_numero():
    por_cuenta = {f.cuenta: f for f in _balanza().filas}
    assert (por_cuenta["101"].nivel, por_cuenta["101"].cuenta_padre) == (1, "")
    assert (por_cuenta["101-01"].nivel, por_cuenta["101-01"].cuenta_padre) == (2, "101")
    assert por_cuenta["102-01-0001"].nivel == 3
    assert por_cuenta["102-01-0001"].cuenta_padre == "102-01"


def test_el_encabezado_repetido_en_cada_pagina_no_entra_como_dato():
    cuentas = [f.cuenta for f in _balanza().filas]
    assert len(cuentas) == len(set(cuentas))
    assert not any(c.startswith("No.") or "Cuenta" in c for c in cuentas)


def test_el_nombre_partido_en_dos_renglones_se_reune():
    por_cuenta = {f.cuenta: f for f in _balanza().filas}
    assert por_cuenta["102-01-0001"].nombre == "Cuenta de cheques moneda nacional"


def test_lee_las_dos_paginas():
    filas = _balanza().filas
    assert filas[0].cuenta == "101"      # pagina 1
    assert filas[-1].cuenta == "601-02"  # pagina 2


def test_la_fila_totales_no_es_una_fila_de_datos():
    balanza = _balanza()
    assert all(f.cuenta != "Totales" for f in balanza.filas)
    assert balanza.totales.debe == Decimal("229751.00")
    assert balanza.totales.haber == Decimal("229751.00")


def test_conserva_montos_negativos():
    por_cuenta = {f.cuenta: f for f in _balanza().filas}
    assert por_cuenta["102-01-0002"].saldo_fin_deudor == Decimal("-1250.25")


def test_conserva_saldos_acreedores():
    por_cuenta = {f.cuenta: f for f in _balanza().filas}
    assert por_cuenta["201"].saldo_ini_acreedor == Decimal("60000.00")
    assert por_cuenta["201"].naturaleza == "A"


def test_una_sola_pasada_por_documento():
    # PLAN 0: el layout se detecta con las primeras paginas y se aplica en
    # el mismo recorrido. Dos pasadas cuestan dos parseos del PDF.
    doc, pasadas = counted_document("balanza_sintetica")
    BalanzaParser().parse(doc)
    assert pasadas == [1]


def test_es_determinista():
    assert _balanza().filas == _balanza().filas


def test_fila_balanza_es_inmutable():
    assert FilaBalanza.__dataclass_params__.frozen


def test_las_columnas_se_mapean_por_encabezado_no_por_indice():
    # Es la razon de ser de headers.py: un PDF con una columna de mas no
    # debe correr el mapeo. Se simula quitando una columna del layout.
    import dataclasses

    from contapdf.parsers.balanza import LayoutDesconocido
    from contapdf.parsers.base import Layout, detectar_layout

    doc = synthetic_document("balanza_sintetica")
    paginas = list(doc.open_pages())
    layout = detectar_layout(paginas)
    sin_haber = Layout(columns=tuple(c for c in layout.columns if c.header != "Haber"))

    try:
        BalanzaParser().parse(dataclasses.replace(doc), layout=sin_haber)
    except LayoutDesconocido as exc:
        assert "haber" in str(exc).lower()
    else:
        raise AssertionError("no aviso que falta la columna Haber")
