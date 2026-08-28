"""Tercera variante de balanza: GUME, 21 digitos sin separadores."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.balanza import BalanzaParser
from contapdf.validate.rules import CUADRA, NO_VERIFICABLE, evaluar_balanza


@pytest.fixture(scope="module")
def balanza():
    doc, _ = extraer(requires_real_pdf("balanza-gume"))
    return BalanzaParser().parse(doc)


def _regla(cobertura, nombre):
    return next(r for r in cobertura.reglas if r.regla == nombre)


# --- Criterio 1: jerarquia por el marcador de nivel ----------------------
def test_extrae_los_734_renglones(balanza):
    assert len(balanza.filas) == 734


def test_el_nivel_sale_del_marcador_declarado(balanza):
    assert all(f.nivel == int(f.cuenta[-3:]) for f in balanza.filas)
    assert dict(Counter(f.nivel for f in balanza.filas)) == {1: 49, 2: 190, 3: 495}


def test_toda_cuenta_hija_encuentra_a_su_padre(balanza):
    cuentas = {f.cuenta for f in balanza.filas}
    huerfanas = [f.cuenta for f in balanza.filas
                 if f.nivel > 1 and f.cuenta_padre not in cuentas]
    assert huerfanas == []


def test_deducir_el_nivel_de_los_ceros_finales_falla_en_54(balanza):
    # Documenta por que el marcador explicito no es redundante: existe el
    # sub-subnivel numerado '000'.
    def nivel_por_ceros(cuenta: str) -> int:
        grupos = [cuenta[i * 3:(i + 1) * 3] for i in range(6)]
        ultimo = max((i for i, g in enumerate(grupos) if g != "000"), default=0)
        return max(1, ultimo)

    fallan = [f.cuenta for f in balanza.filas
              if nivel_por_ceros(f.cuenta) != f.nivel]
    assert len(fallan) == 54
    assert "115000101000000000003" in fallan


# --- Criterio 2: la fila de totales -------------------------------------
def test_detecta_la_fila_de_totales_aunque_la_etiqueta_no_abra_la_celda(balanza):
    # El renglon es: 734 | Cuentas reportadas | Totales: | 0.00 | ...
    assert balanza.totales is not None
    assert balanza.totales.debe == Decimal("234982231.10")
    assert balanza.totales.haber == Decimal("234982231.10")


def test_la_regla_de_totales_corre_de_verdad(balanza):
    regla = _regla(evaluar_balanza(balanza), "totales")
    assert regla.estado == CUADRA
    assert regla.comprobaciones > 0


def test_la_jerarquia_ya_no_es_no_verificable(balanza):
    regla = _regla(evaluar_balanza(balanza), "jerarquia")
    assert regla.estado == CUADRA
    assert regla.comprobaciones > 0


# --- Criterio 3: la orientacion debe/haber ------------------------------
def test_el_mapeo_dice_sobre_que_se_apoya(balanza):
    assert balanza.mapeo is not None
    assert balanza.mapeo.verificado_por == "vocabulario"
    assert balanza.mapeo.orientacion_verificada is False


def test_la_orientacion_no_verificada_reporta_cuantas_filas_cambia(balanza):
    # No es solo no verificable: es consecuente. Son las 45 filas que la
    # aritmetica determina mas las 51 que heredan de ellas; las 638
    # restantes caen al default en los dos sentidos.
    assert balanza.mapeo.filas_afectadas == 96
    determinadas = [f for f in balanza.filas if f.debe != f.haber]
    assert len(determinadas) == 45


def test_en_business_pro_la_orientacion_si_se_verifica():
    doc, _ = extraer(requires_real_pdf("balanza-businesspro"))
    mapeo = BalanzaParser().parse(doc).mapeo
    # Ahi la columna SALDO MES rompe la simetria entre debe y haber.
    assert mapeo.orientacion_verificada is True
    assert mapeo.verificado_por == "aritmetica"


# --- Criterio 4: tolerancia consumida -----------------------------------
def test_los_dos_renglones_340000_cuadran_dentro_de_tolerancia(balanza):
    regla = _regla(evaluar_balanza(balanza), "renglon")
    assert regla.estado == CUADRA
    assert set(regla.con_tolerancia) == {
        "340000000000000000001", "340000200000000000002"}
    assert regla.exactas == 732


def test_la_naturaleza_declara_de_donde_sale(balanza):
    cobertura = evaluar_balanza(balanza)
    assert cobertura.naturalezas == {
        "explicita": 0, "derivada": 45, "heredada": 51, "sin_determinar": 638}


def test_las_638_sin_determinar_van_vacias(balanza):
    # Un 'D' por default es indistinguible de uno fundamentado.
    vacias = [f for f in balanza.filas if f.naturaleza == ""]
    assert len(vacias) == 638
