"""El MISMO parser de balanza, sobre el documento de otra empresa.

Business Pro cambia vocabulario (CARGOS/CREDITOS), semantica (una sola
columna de saldo con signo) y estructura (columna N con ACUM/DETA).
Sin ramas por formato: lo que el documento no declara, se deriva.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.balanza import BalanzaParser
from contapdf.validate.rules import validar_balanza


@pytest.fixture(scope="module")
def balanza():
    doc, _ = extraer(requires_real_pdf("balanza-businesspro"))
    return BalanzaParser().parse(doc)


@pytest.fixture(scope="module")
def original():
    doc, _ = extraer(requires_real_pdf("balanza"))
    return BalanzaParser().parse(doc)


# --- Criterio 1 ---------------------------------------------------------
def test_extrae_los_225_renglones(balanza):
    assert len(balanza.filas) == 225


def test_lee_la_fila_de_sumas(balanza):
    # 'SUMAS:' no esta alineada a las mismas anclas que los datos.
    assert balanza.totales is not None
    assert balanza.totales.debe == Decimal("52268181.56")
    assert balanza.totales.haber == Decimal("53070598.23")


# --- Criterio 2 ---------------------------------------------------------
def test_cero_discrepancias(balanza):
    assert validar_balanza(balanza) == []


# --- Criterio 3: el mismo parser, sin tocar el documento original -------
def test_la_balanza_original_sigue_igual(original):
    assert len(original.filas) == 475
    assert validar_balanza(original) == []


# --- Criterio 4: naturaleza derivada por aritmetica ---------------------
def test_naturaleza_derivada_coincide_con_las_familias_medidas(balanza):
    acreedoras = {"0400", "0401", "0402", "0410", "0430"}
    determinadas = 0
    for fila in balanza.filas:
        if fila.debe == fila.haber:
            continue  # indeterminada: hereda, no se mide aqui
        determinadas += 1
        familia = fila.cuenta.split("-")[0]
        esperada = "A" if familia in acreedoras else "D"
        assert fila.naturaleza == esperada, f"{fila.cuenta}: {fila.naturaleza}"
    assert determinadas >= 155


def test_la_naturaleza_no_se_deduce_del_prefijo_de_cuenta(balanza):
    # Si alguien cablea '04xx es acreedora', esto no lo detecta; lo que se
    # verifica es que la aritmetica sostiene cada renglon determinado.
    for fila in balanza.filas:
        if fila.debe == fila.haber:
            continue
        ini = fila.saldo_ini_deudor - fila.saldo_ini_acreedor
        fin = fila.saldo_fin_deudor - fila.saldo_fin_acreedor
        assert ini + fila.debe - fila.haber == fin


def test_los_indeterminados_heredan_del_padre(balanza):
    por_cuenta = {f.cuenta: f for f in balanza.filas}
    heredados = [f for f in balanza.filas
                 if f.debe == f.haber and f.cuenta_padre in por_cuenta]
    assert heredados
    for fila in heredados:
        assert fila.naturaleza == por_cuenta[fila.cuenta_padre].naturaleza


# --- Criterio 5: es_acumulativa -----------------------------------------
def test_es_acumulativa_coincide_con_la_columna_N(balanza):
    reparto = Counter(f.es_acumulativa for f in balanza.filas)
    assert reparto[True] == 24
    assert reparto[False] == 201


def test_el_marcador_declarado_le_gana_a_la_jerarquia(balanza):
    # 0500-0001-0421 viene marcada ACUM y el documento no imprime ninguna
    # hija suya: derivarla de la jerarquia la habria puesto en 'detalle'.
    # Es el renglon que justifica preferir el marcador explicito.
    cuentas = {f.cuenta for f in balanza.filas}
    padres = {f.cuenta_padre for f in balanza.filas if f.cuenta_padre} & cuentas
    discrepan = [f.cuenta for f in balanza.filas
                 if f.es_acumulativa != (f.cuenta in padres)]
    assert discrepan == ["0500-0001-0421-0000"]
    assert next(f for f in balanza.filas
                if f.cuenta == "0500-0001-0421-0000").es_acumulativa is True


def test_en_la_balanza_original_se_deriva_de_la_jerarquia(original):
    # Ese documento no declara ACUM/DETA: el marcador se deriva.
    cuentas = {f.cuenta for f in original.filas}
    padres = {f.cuenta_padre for f in original.filas if f.cuenta_padre} & cuentas
    assert sum(1 for f in original.filas if f.es_acumulativa) == len(padres)
    assert any(f.es_acumulativa for f in original.filas)


# --- Jerarquia con segmentos de relleno ---------------------------------
def test_los_segmentos_todo_ceros_son_relleno_no_niveles(balanza):
    por_cuenta = {f.cuenta: f for f in balanza.filas}
    raiz = por_cuenta["0400-0000-0000-0000"]
    hija = por_cuenta["0400-0001-0000-0000"]
    assert (raiz.nivel, raiz.cuenta_padre) == (1, "")
    assert hija.nivel == 2
    assert hija.cuenta_padre == "0400-0000-0000-0000"


def test_el_vocabulario_se_mapeo_por_sinonimos(balanza):
    # CARGOS -> debe, CREDITOS -> haber, SALDO ANTERIOR/ACTUAL -> ini/fin.
    fila = next(f for f in balanza.filas if f.cuenta == "0400-0001-0000-0000")
    assert fila.debe == Decimal("0.00")
    assert fila.haber == Decimal("3680167.75")
    assert fila.saldo_ini_acreedor == Decimal("41608185.15")
    assert fila.saldo_fin_acreedor == Decimal("45288352.90")
    assert fila.naturaleza == "A"
