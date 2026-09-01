"""Libro Mayor: cuenta + 12 meses, en dos tablas relacionadas.

Las secciones se parten entre paginas: la pagina 2 arranca con 'Inicial'
sin numero de cuenta porque quedo en el ultimo renglon de la anterior.
Ningun otro documento del sistema tiene eso.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.mayor import MayorParser


@pytest.fixture(scope="module")
def mayor():
    doc, _ = extraer(requires_real_pdf("mayor-gume"))
    return MayorParser().parse(doc)


# --- Criterio 1: secciones partidas entre paginas -----------------------
def test_lee_todas_las_cuentas(mayor):
    assert len(mayor.cuentas) == 49
    assert all(c.cuenta and c.nombre_cuenta for c in mayor.cuentas)


def test_cada_cuenta_trae_sus_doce_meses(mayor):
    por_cuenta: dict[str, int] = {}
    for m in mayor.meses:
        por_cuenta[m.cuenta] = por_cuenta.get(m.cuenta, 0) + 1
    assert set(por_cuenta.values()) == {12}
    assert len(por_cuenta) == 49


def test_ninguna_fila_queda_huerfana(mayor):
    # El invariante que justifica las dos tablas: todo mes apunta a una
    # cuenta que existe. Es la leccion del CFDI aplicada aqui.
    cuentas = {c.cuenta for c in mayor.cuentas}
    assert all(m.cuenta in cuentas for m in mayor.meses)


def test_arrastra_la_cuenta_a_traves_del_salto_de_pagina(mayor):
    # 1150-000-000 CLIENTES abre en el ultimo renglon de la pagina 1 y sus
    # meses estan en la pagina 2.
    clientes = next(c for c in mayor.cuentas if c.cuenta == "1150-000-000")
    assert clientes.nombre_cuenta == "CLIENTES"
    assert clientes.saldo_inicial == Decimal("263498.86")
    meses = [m for m in mayor.meses if m.cuenta == "1150-000-000"]
    assert len(meses) == 12
    assert {m.pagina for m in meses} == {2}


def test_los_meses_van_en_orden(mayor):
    meses = [m for m in mayor.meses if m.cuenta == "1120-000-000"]
    assert [m.orden for m in meses] == list(range(1, 13))
    assert meses[0].periodo == "ENERO"
    assert meses[-1].periodo == "DICIEMBRE"


def test_los_importes_de_un_mes_verificado_a_mano(mayor):
    enero = next(m for m in mayor.meses
                 if m.cuenta == "1120-000-000" and m.orden == 1)
    assert enero.cargos == Decimal("28304459.40")
    assert enero.abonos == Decimal("28339930.18")
    assert enero.saldo == Decimal("65833.97")
    assert enero.acum_cargos == Decimal("28304459.40")
    assert enero.acum_abonos == Decimal("28339930.18")


def test_la_cuenta_resume_lo_que_el_documento_ya_declara(mayor):
    bancos = next(c for c in mayor.cuentas if c.cuenta == "1120-000-000")
    assert bancos.saldo_inicial == Decimal("101304.75")
    diciembre = next(m for m in mayor.meses
                     if m.cuenta == "1120-000-000" and m.orden == 12)
    assert bancos.saldo_final == diciembre.saldo
    assert bancos.total_cargos == diciembre.acum_cargos
    assert bancos.total_abonos == diciembre.acum_abonos


def test_es_determinista(mayor):
    doc, _ = extraer(requires_real_pdf("mayor-gume"))
    assert MayorParser().parse(doc).meses == mayor.meses
