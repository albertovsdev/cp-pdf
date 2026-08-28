"""Numeros de cuenta: esquema, jerarquia y forma canonica."""

from __future__ import annotations

import pytest

from contapdf.cuentas import (
    EsquemaCuenta,
    canonizar,
    inferir_esquema,
    nivel_y_padre,
)

_GUME = ["111000000000000000001", "111000100000000000002",
         "112000000000000000001", "112000100000000000002",
         "112000100100000000003", "112000100200000000003"]
_CLASICO = ["100", "100-01", "100-01-001", "101", "101-01"]
_PADDED = ["0400-0000-0000-0000", "0400-0001-0000-0000", "0500-0001-0393-0000"]


def test_reconoce_un_catalogo_con_separadores():
    esquema = inferir_esquema(_CLASICO)
    assert esquema.separador == "-"
    assert esquema.marcador is None


def test_reconoce_el_marcador_de_nivel_de_un_catalogo_sin_separadores():
    esquema = inferir_esquema(_GUME)
    assert esquema.separador == ""
    assert esquema.marcador == (18, 21)
    assert esquema.largo == 21


def test_deriva_el_ancho_significativo_de_cada_nivel():
    # Equivalentes a los 6/9/12 documentados: los digitos intermedios son
    # ceros en ese nivel, asi que truncar antes o despues da el mismo padre.
    esquema = inferir_esquema(_GUME)
    assert len(esquema.anchos) == 3
    assert esquema.anchos[0] < esquema.anchos[1] < esquema.anchos[2]


@pytest.mark.parametrize(("cuenta", "nivel", "padre"), [
    ("111000000000000000001", 1, ""),
    ("111000100000000000002", 2, "111000000000000000001"),
    ("112000100100000000003", 3, "112000100000000000002"),
])
def test_nivel_y_padre_con_marcador(cuenta, nivel, padre):
    assert nivel_y_padre(cuenta, inferir_esquema(_GUME)) == (nivel, padre)


@pytest.mark.parametrize(("cuenta", "nivel", "padre"), [
    ("100", 1, ""),
    ("100-01", 2, "100"),
    ("100-01-001", 3, "100-01"),
])
def test_nivel_y_padre_con_separadores(cuenta, nivel, padre):
    assert nivel_y_padre(cuenta, inferir_esquema(_CLASICO)) == (nivel, padre)


def test_los_segmentos_de_relleno_siguen_siendo_relleno():
    esquema = inferir_esquema(_PADDED)
    assert nivel_y_padre("0400-0001-0000-0000", esquema) == (2, "0400-0000-0000-0000")


def test_el_marcador_no_es_redundante_con_los_ceros_finales():
    # 115000101000000000003 es nivel 3 con el sub-subnivel numerado '000':
    # deducir el nivel de los ceros la pondria en nivel 2.
    esquema = inferir_esquema(_GUME + ["115000101000000000003"])
    nivel, _ = nivel_y_padre("115000101000000000003", esquema)
    assert nivel == 3


@pytest.mark.parametrize(("texto", "esperado"), [
    ("1120-001-001", "112000100100000000"),
    ("1120001001", "112000100100000000"),
    ("112000100100000000", "112000100100000000"),
])
def test_canonizar_iguala_renderizados_distintos(texto, esperado):
    assert canonizar(texto) == esperado


def test_canonizar_respeta_el_ancho_pedido():
    assert canonizar("1120-001-001", ancho=10) == "1120001001"
    assert len(canonizar("111", ancho=18)) == 18


def test_esquema_vacio_no_revienta():
    esquema = inferir_esquema([])
    assert isinstance(esquema, EsquemaCuenta)
    assert nivel_y_padre("100-01", esquema) == (2, "100")
