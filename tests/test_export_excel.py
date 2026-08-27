"""Exportacion a Excel."""

from __future__ import annotations

from decimal import Decimal

import openpyxl
from conftest import synthetic_document

from contapdf.export.excel import exportar_balanza
from contapdf.parsers.balanza import BalanzaParser
from contapdf.validate.rules import validar_balanza


def _exportar(tmp_path, name="balanza_sintetica"):
    balanza = BalanzaParser().parse(synthetic_document(name))
    discrepancias = validar_balanza(balanza)
    destino = tmp_path / "salida.xlsx"
    return balanza, discrepancias, exportar_balanza(balanza, discrepancias, destino)


def test_genera_el_archivo_en_la_ruta_pedida(tmp_path):
    _, _, destino = _exportar(tmp_path)
    assert destino == tmp_path / "salida.xlsx"
    assert destino.exists()


def test_la_hoja_se_llama_balanza_y_trae_encabezados(tmp_path):
    _, _, destino = _exportar(tmp_path)
    wb = openpyxl.load_workbook(destino)
    assert wb.sheetnames[0] == "Balanza"
    ws = wb["Balanza"]
    assert [c.value for c in ws[1]] == [
        "cuenta", "nivel", "cuenta_padre", "naturaleza", "nombre",
        "saldo_ini_deudor", "saldo_ini_acreedor", "debe", "haber",
        "saldo_fin_deudor", "saldo_fin_acreedor",
    ]


def test_el_encabezado_queda_congelado(tmp_path):
    _, _, destino = _exportar(tmp_path)
    assert openpyxl.load_workbook(destino)["Balanza"].freeze_panes == "A2"


def test_los_montos_se_reabren_como_numeros_no_como_texto(tmp_path):
    balanza, _, destino = _exportar(tmp_path)
    ws = openpyxl.load_workbook(destino)["Balanza"]
    for fila, row in zip(balanza.filas, ws.iter_rows(min_row=2, max_row=1 + len(balanza.filas))):
        for celda, esperado in zip(row[5:11],
                                   (fila.saldo_ini_deudor, fila.saldo_ini_acreedor,
                                    fila.debe, fila.haber,
                                    fila.saldo_fin_deudor, fila.saldo_fin_acreedor)):
            assert isinstance(celda.value, (int, float)), f"{celda.coordinate} es texto"
            assert abs(Decimal(str(celda.value)) - esperado) < Decimal("0.005")
            assert celda.number_format == "#,##0.00"


def test_conserva_negativos(tmp_path):
    _, _, destino = _exportar(tmp_path)
    ws = openpyxl.load_workbook(destino)["Balanza"]
    negativos = [c.value for row in ws.iter_rows(min_row=2) for c in row
                 if isinstance(c.value, (int, float)) and c.value < 0]
    assert negativos == [-1250.25]


def test_sin_discrepancias_no_hay_hoja_de_validacion(tmp_path):
    _, discrepancias, destino = _exportar(tmp_path)
    assert discrepancias == []
    assert openpyxl.load_workbook(destino).sheetnames == ["Balanza"]


def test_con_discrepancias_agrega_la_hoja_validacion(tmp_path):
    _, discrepancias, destino = _exportar(tmp_path, "balanza_descuadrada")
    assert len(discrepancias) == 1
    wb = openpyxl.load_workbook(destino)
    assert "Validacion" in wb.sheetnames
    ws = wb["Validacion"]
    assert [c.value for c in ws[1]] == ["fila", "regla", "esperado", "obtenido"]
    assert ws.cell(row=2, column=1).value == "102-02"
    assert ws.cell(row=2, column=2).value == "renglon"


def test_marca_la_fila_afectada(tmp_path):
    balanza, _, destino = _exportar(tmp_path, "balanza_descuadrada")
    ws = openpyxl.load_workbook(destino)["Balanza"]
    fila_mala = next(i for i, f in enumerate(balanza.filas) if f.cuenta == "102-02")

    marcada = ws.cell(row=2 + fila_mala, column=1)
    limpia = ws.cell(row=2, column=1)
    assert marcada.fill.fgColor.rgb != limpia.fill.fgColor.rgb


def test_no_imprime(tmp_path, capsys):
    _exportar(tmp_path)
    salida = capsys.readouterr()
    assert salida.out == "" and salida.err == ""
