"""Libro diario: dos variantes, un solo parser, tres tablas relacionadas."""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.polizas import CFDI, LibroDiario, Movimiento, PolizasParser


def _libro(nombre: str, paginas: list[int]) -> LibroDiario:
    doc, _ = extraer(requires_real_pdf(nombre), page_numbers=paginas)
    return PolizasParser().parse(doc)


@pytest.fixture(scope="module")
def bloques():
    return _libro("poliza", [1, 2, 3, 4])


@pytest.fixture(scope="module")
def diario():
    return _libro("diario-general", [1, 2, 3])


# --- Criterio 1: el mismo parser con las dos variantes ------------------
def test_lee_las_polizas_del_documento_de_bloques(bloques):
    assert len(bloques.polizas) == 8
    assert len(bloques.movimientos) == 25


def test_lee_las_polizas_del_diario_general(diario):
    assert len(diario.polizas) == 28
    assert len(diario.movimientos) == 200


def test_marca_incompleta_la_poliza_que_el_rango_de_paginas_corta(diario):
    # El ultimo bloque cierra en la pagina 4, fuera de lo leido. Sus
    # movimientos estan a medias: validarlos reportaria un descuadre falso.
    completas = [p for p in diario.polizas if p.completa]
    assert len(completas) == 27
    assert diario.polizas[-1].completa is False


def test_la_salida_son_tres_tablas_no_una_plana(bloques):
    assert isinstance(bloques.polizas, tuple)
    assert isinstance(bloques.movimientos, tuple)
    assert isinstance(bloques.cfdi, tuple)
    assert {type(m) for m in bloques.movimientos} == {Movimiento}


# --- Datos de la poliza --------------------------------------------------
def test_los_campos_del_encabezado_de_poliza(bloques):
    primera = bloques.polizas[0]
    assert primera.tipo == "Venta"
    assert primera.naturaleza == "Ingreso"
    assert primera.fecha == "01/01/2025"
    assert primera.descripcion == "18243"
    assert primera.total_debe == Decimal("500.00")
    assert primera.total_haber == Decimal("500.00")


def test_los_movimientos_traen_su_cuenta_y_su_nombre(bloques):
    movimientos = [m for m in bloques.movimientos
                   if m.poliza_id == bloques.polizas[0].poliza_id]
    assert len(movimientos) == 3
    assert [m.orden for m in movimientos] == [1, 2, 3]
    assert movimientos[0].cuenta == "401-01"
    assert movimientos[0].nombre_cuenta.startswith("Ventas de combustibles")
    assert movimientos[1].debe == Decimal("500.00")
    assert movimientos[1].haber == Decimal("0.00")


def test_el_diario_general_conserva_la_descripcion_completa(diario):
    # El CONCEPTO se imprime ENCIMA de la cola de la DESCRIPCION: se ve
    # recortada pero el texto esta completo en el PDF.
    movimiento = diario.movimientos[0]
    assert movimiento.cuenta == "0105-0026-0001-0000"
    assert "CLIENTES VEHICULOS NUEVOS" in movimiento.nombre_cuenta
    assert "SERDAN" in movimiento.nombre_cuenta


def test_el_diario_general_lee_sus_totales(diario):
    assert all(p.total_debe is not None for p in diario.polizas if p.completa)
    primera = diario.polizas[0]
    assert primera.total_debe == Decimal("464939.59")
    assert primera.total_haber == Decimal("464939.59")


# --- Criterio 4: los CFDI se asocian a su poliza ------------------------
def test_los_cfdi_van_atados_a_su_poliza(bloques):
    assert len(bloques.cfdi) == 8
    ids = {p.poliza_id for p in bloques.polizas}
    assert all(c.poliza_id in ids for c in bloques.cfdi)
    # Un CFDI por poliza en estas paginas, y cada uno con el suyo.
    assert len({c.poliza_id for c in bloques.cfdi}) == 8


def test_el_uuid_partido_en_dos_renglones_se_reune(bloques):
    primero = bloques.cfdi[0]
    assert primero.uuid == "608A8CEA-2A14-40E2-BAB6-55E3EBDAEF76"
    assert primero.rfc == "FUMN920319F38"
    assert primero.tipo == "Ingreso"
    assert primero.documento == "18243"


def test_el_diario_general_no_trae_cfdi(diario):
    assert diario.cfdi == ()


def test_cada_movimiento_apunta_a_una_poliza_existente(diario):
    ids = {p.poliza_id for p in diario.polizas}
    assert all(m.poliza_id in ids for m in diario.movimientos)


def test_es_determinista(bloques):
    assert bloques.movimientos == _libro("poliza", [1, 2, 3, 4]).movimientos
