"""El dinero va en Decimal. Nunca en float."""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import synthetic_document

from contapdf.parsers.balanza import BalanzaParser
from contapdf.parsers.base import parse_monto

SRC = Path(__file__).resolve().parent.parent / "src" / "contapdf"
MONEDA = [SRC / "parsers" / "base.py", SRC / "parsers" / "balanza.py",
          SRC / "validate" / "rules.py", SRC / "export" / "excel.py"]


@pytest.mark.parametrize(("texto", "esperado"), [
    ("1,234.56", "1234.56"),
    ("-99,999.99", "-99999.99"),
    ("0.00", "0"),
    ("$999.99", "999.99"),
    ("$ 1,000.00", "1000.00"),
    ("(1,250.25)", "-1250.25"),   # parentesis contables = negativo
    ("", "0"),
    ("   ", "0"),
    ("229,751.00", "229751.00"),
])
def test_parse_monto(texto, esperado):
    obtenido = parse_monto(texto)
    assert obtenido == Decimal(esperado)
    assert isinstance(obtenido, Decimal)


def test_parse_monto_rechaza_lo_que_no_es_monto():
    with pytest.raises(ValueError):
        parse_monto("Totales")


def test_la_suma_de_decimales_es_exacta():
    # Con float, 0.1 + 0.2 != 0.3 y cientos de renglones rompen la
    # validacion por un error que no existe en el documento.
    assert parse_monto("0.10") + parse_monto("0.20") == parse_monto("0.30")
    assert sum((parse_monto("0.01") for _ in range(100)), Decimal(0)) == Decimal("1.00")


def test_ningun_monto_parseado_es_float():
    balanza = BalanzaParser().parse(synthetic_document("balanza_sintetica"))
    montos = [
        m
        for fila in balanza.filas
        for m in (fila.saldo_ini_deudor, fila.saldo_ini_acreedor, fila.debe,
                  fila.haber, fila.saldo_fin_deudor, fila.saldo_fin_acreedor)
    ]
    assert montos
    assert all(isinstance(m, Decimal) for m in montos)
    assert not any(isinstance(m, float) for m in montos)
    assert isinstance(balanza.totales.debe, Decimal)


@pytest.mark.parametrize("path", MONEDA, ids=lambda p: p.name)
def test_los_modulos_de_dinero_no_llaman_a_float(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float", f"{path.name}: convierte dinero a float"
