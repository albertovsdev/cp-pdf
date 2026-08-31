"""Estado de cuenta bancario.

La pagina 1 es puro metadato y la tabla real empieza en DETALLE DE
OPERACIONES: sin find_table_region no hay de donde leer. Un movimiento
SPEI ocupa nueve renglones visuales; el criterio de fila nueva es que el
renglon traiga dia en la primera columna.

Los tests NO afirman sobre numero de cuenta, CLABE ni RFC: el PDF real
esta gitignored justamente porque trae datos del cliente.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.estado_cuenta import EstadoCuentaParser


@pytest.fixture(scope="module")
def edocta():
    doc, _ = extraer(requires_real_pdf("edocta"))
    return EstadoCuentaParser().parse(doc)


# --- Criterio 1: metadata ------------------------------------------------
def test_lee_el_banco_de_debajo_del_sello_digital(edocta):
    # El nombre del banco se imprime encima del domicilio: sin separar las
    # corridas salen entrelazados.
    assert edocta.meta.banco.startswith("BANCA AFIRME")
    assert "JUÁREZ" not in edocta.meta.banco


def test_lee_la_cuenta_y_la_clabe_sin_exponerlas(edocta):
    assert edocta.meta.num_cuenta.isdigit()
    assert len(edocta.meta.num_cuenta) >= 10
    assert edocta.meta.clabe.isdigit()
    assert len(edocta.meta.clabe) == 18
    assert edocta.meta.rfc


def test_lee_el_periodo(edocta):
    assert edocta.meta.periodo_ini == "01 ABR 2025"
    assert edocta.meta.periodo_fin == "30 ABR 2025"


def test_lee_los_saldos_del_resumen(edocta):
    meta = edocta.meta
    assert meta.saldo_inicial == Decimal("32411.67")
    assert meta.depositos == Decimal("118420.39")
    assert meta.retiros == Decimal("118958.74")
    assert meta.saldo_corte == Decimal("31873.32")


# --- Criterio 2: movimientos multilinea ---------------------------------
def test_cuenta_los_movimientos(edocta):
    assert len(edocta.movimientos) == 45


def test_reune_un_spei_de_nueve_renglones(edocta):
    # Verificado a mano contra el PDF: el envio del dia 07 a 072-BANORTE.
    spei = next(m for m in edocta.movimientos
                if m.dia == "07" and "BANORTE" in m.descripcion)
    assert spei.retiro == Decimal("10254.69")
    assert spei.deposito == Decimal("0.00")
    assert spei.saldo == Decimal("22470.84")
    # Las ocho lineas de continuacion quedaron dentro de la descripcion.
    assert "CUENTA:" in spei.descripcion
    assert "DESTINATARIO:" in spei.descripcion
    assert "CVE RASTREO:" in spei.descripcion
    assert "CONCEPTO:FACTURA 1766" in spei.descripcion


def test_hay_varios_movimientos_multilinea(edocta):
    multilinea = [m for m in edocta.movimientos if len(m.descripcion) > 120]
    assert len(multilinea) >= 8
    assert all(m.dia.isdigit() for m in edocta.movimientos)


def test_un_movimiento_trae_deposito_o_retiro_no_los_dos(edocta):
    for m in edocta.movimientos:
        assert not (m.deposito > 0 and m.retiro > 0)
    assert any(m.deposito > 0 for m in edocta.movimientos)
    assert any(m.retiro > 0 for m in edocta.movimientos)


def test_la_fecha_se_deriva_del_periodo_declarado(edocta):
    # El documento imprime solo el dia; el mes y el anio salen del periodo,
    # que el propio documento declara.
    primero = edocta.movimientos[0]
    assert primero.fecha == f"{primero.dia}/04/2025"


def test_es_determinista(edocta):
    doc, _ = extraer(requires_real_pdf("edocta"))
    assert EstadoCuentaParser().parse(doc).movimientos == edocta.movimientos
