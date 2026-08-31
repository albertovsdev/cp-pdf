"""Auxiliar de cuentas: dos variantes, un solo parser.

Lo que comparten: una seccion declara la cuenta y su saldo inicial, y los
movimientos que siguen la arrastran. Lo que cambia (como se declara la
seccion, el vocabulario, si hay subtotales o continuaciones) lo absorbe el
mapeo, igual que con las tres balanzas.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.auxiliar import AuxiliarParser, FilaAuxiliar


def _auxiliar(nombre: str, paginas: list[int]):
    doc, _ = extraer(requires_real_pdf(nombre), page_numbers=paginas)
    return AuxiliarParser().parse(doc)


@pytest.fixture(scope="module")
def original():
    return _auxiliar("auxiliar", [1, 2, 3, 4, 5, 6])


@pytest.fixture(scope="module")
def gume():
    return _auxiliar("auxiliar-gume", [1, 2, 3, 4])


# --- Criterio 1: el mismo parser con las dos variantes ------------------
def test_lee_los_movimientos_del_auxiliar_original(original):
    movimientos = [f for f in original.filas if not f.es_subtotal]
    assert len(movimientos) == 129


def test_lee_los_movimientos_del_auxiliar_gume(gume):
    movimientos = [f for f in gume.filas if not f.es_subtotal]
    assert len(movimientos) == 250


def test_no_pierde_los_movimientos_cuyo_saldo_no_es_legible(gume):
    # La capa de texto de este PDF pierde caracteres: 74 renglones traen
    # el signo del saldo pero no sus digitos. Emitirlos con el saldo vacio
    # conserva el movimiento; descartarlos perdia el 30% del documento.
    movimientos = [f for f in gume.filas if not f.es_subtotal]
    sin_saldo = [f for f in movimientos if f.saldo is None]
    assert len(sin_saldo) == 74
    assert all(f.debe is not None and f.haber is not None for f in sin_saldo)


def test_arrastra_la_cuenta_de_la_seccion_a_cada_movimiento(original):
    assert original.secciones >= 1
    assert all(f.cuenta for f in original.filas)
    primera = original.filas[0]
    assert primera.cuenta == "101-01"
    assert "Caja" in primera.nombre_cuenta
    assert primera.saldo_inicial_cuenta == Decimal("0.00")


def test_arrastra_la_cuenta_tambien_cuando_la_seccion_es_una_fila(gume):
    # GUME no etiqueta la seccion: la cuenta viene en su propia fila.
    movimientos = [f for f in gume.filas if not f.es_subtotal]
    assert all(f.cuenta for f in movimientos)
    assert {f.cuenta for f in movimientos} >= {"1120-001-003"}
    banorte = next(f for f in movimientos if f.cuenta == "1120-001-003")
    assert banorte.nombre_cuenta.startswith("BANORTE")
    assert banorte.saldo_inicial_cuenta == Decimal("36030.99")


# --- Criterio 3: folio y fecha separados --------------------------------
def test_folio_y_fecha_son_campos_distintos(original):
    campos = {f.name for f in FilaAuxiliar.__dataclass_fields__.values()}
    assert {"folio", "fecha"} <= campos
    movimiento = next(f for f in original.filas if not f.es_subtotal)
    assert movimiento.fecha == "01/01/2025"
    # En este documento la columna FOLIO no trae datos: el campo va vacio,
    # no relleno con la fecha.
    assert movimiento.folio == ""


def test_en_gume_el_numero_de_movimiento_llena_el_folio(gume):
    movimientos = [f for f in gume.filas if not f.es_subtotal]
    con_folio = [f for f in movimientos if f.folio]
    assert len(con_folio) > 100
    assert all(f.fecha.count("/") == 2 for f in movimientos)


# --- Continuaciones ------------------------------------------------------
def test_reune_el_tercero_partido_en_varios_renglones(original):
    primero = next(f for f in original.filas if not f.es_subtotal)
    assert primero.tercero == "NOHEMI FUENTES MARTINEZ"
    assert primero.tipo_movimiento == "Movimiento Conciliado"


def test_los_importes_del_movimiento(original):
    primero = next(f for f in original.filas if not f.es_subtotal)
    assert primero.debe == Decimal("500.00")
    assert primero.haber == Decimal("0.00")
    assert primero.saldo == Decimal("500.00")
    assert primero.documento == "18243"


# --- Criterio 4: subtotales identificados -------------------------------
def test_marca_las_filas_de_subtotal_de_gume(gume):
    subtotales = [f for f in gume.filas if f.es_subtotal]
    assert len(subtotales) >= 6
    assert all(f.debe is not None for f in subtotales)


def test_los_subtotales_no_se_cuentan_como_movimientos(gume):
    movimientos = [f for f in gume.filas if not f.es_subtotal]
    suma = sum(f.debe for f in movimientos)
    assert suma > 0
    assert all(not f.es_subtotal for f in movimientos)


def test_el_auxiliar_original_no_inventa_subtotales(original):
    assert [f for f in original.filas if f.es_subtotal] == []


def test_el_tipo_de_movimiento_de_gume(gume):
    tipos = {f.tipo_movimiento for f in gume.filas if not f.es_subtotal}
    assert tipos <= {"Eg", "Ig"}


def test_es_determinista(original):
    assert original.filas == _auxiliar("auxiliar", [1, 2, 3, 4, 5, 6]).filas


def test_gume_usa_concepto_y_deja_vacios_documento_y_tercero(gume):
    # La fuente imprime referencia y contraparte en una sola columna: se
    # entrega cruda en 'concepto' en vez de inventar la division.
    movimiento = next(f for f in gume.filas if not f.es_subtotal)
    assert movimiento.concepto.startswith("PAGO")
    assert movimiento.documento == ""
    assert movimiento.tercero == ""


def test_el_auxiliar_original_si_separa_documento_y_tercero(original):
    movimiento = next(f for f in original.filas if not f.es_subtotal)
    assert movimiento.documento == "18243"
    assert movimiento.tercero == "NOHEMI FUENTES MARTINEZ"
    assert movimiento.concepto == ""
