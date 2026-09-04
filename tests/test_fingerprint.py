"""Huella del formato: identifica un layout sin mirar datos volatiles."""

from __future__ import annotations

import pytest
from conftest import requires_real_pdf

from contapdf.extract.strategy import extraer
from contapdf.parsers.base import detectar_layout, lineas_de_tabla
from contapdf.templates.fingerprint import huella_de

_DOCS = ("balanza", "balanza-businesspro", "balanza-gume")


def _huella(nombre: str, paginas: list[int]):
    doc, _ = extraer(requires_real_pdf(nombre))
    muestra = [p for p in doc.open_pages() if p.number in paginas]
    layout = detectar_layout(muestra)
    cuentas = [w.text for p in muestra for ln in lineas_de_tabla(p)
               for w in ln.words if w.x0 < 100]
    return huella_de(layout, cuentas)


# --- Criterio 1 ---------------------------------------------------------
@pytest.mark.lento          # 5 s
def test_los_tres_fixtures_dan_tres_huellas_distintas():
    valores = {n: _huella(n, [1, 2, 3]).valor for n in _DOCS}
    assert len(set(valores.values())) == 3


@pytest.mark.parametrize("nombre", [
    "balanza", "balanza-businesspro",
    # gume cuesta 5.5 s aqui; la propiedad la cubren los otros dos.
    pytest.param("balanza-gume", marks=pytest.mark.lento)])
def test_paginas_distintas_del_mismo_documento_dan_la_misma_huella(nombre):
    assert _huella(nombre, [1, 2, 3]).valor == _huella(nombre, [2, 3, 4]).valor


def test_la_huella_es_estable_entre_corridas():
    # Nada de hash() de Python: tiene que sobrevivir a reiniciar el proceso.
    primera = _huella("balanza", [1, 2]).valor
    assert primera == _huella("balanza", [1, 2]).valor
    assert len(primera) == 16
    assert primera.isalnum()


def test_la_huella_no_mira_datos_volatiles():
    huella = _huella("balanza-gume", [1, 2, 3])
    plano = " ".join(huella.tokens).lower()
    for volatil in ("rfc", "2022", "2018", "pagina", "empresa"):
        assert volatil not in plano


def test_describe_de_que_esta_hecha():
    huella = _huella("balanza-gume", [1, 2])
    assert huella.columnas_monto == 4
    assert huella.forma_cuenta == "fijo:21"
    assert "debe" in huella.tokens and "haber" in huella.tokens


def test_business_pro_se_reconoce_por_su_vocabulario():
    huella = _huella("balanza-businesspro", [1, 2])
    assert "cargos" in huella.tokens and "creditos" in huella.tokens
    assert huella.columnas_monto == 5
    assert huella.forma_cuenta == "sep"


def test_sin_layout_no_hay_huella():
    assert huella_de(None, []) is None
