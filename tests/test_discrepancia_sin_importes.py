"""Fase 8e: la `Discrepancia` declara si compara importes, y nadie lo deduce.

Las 53 discrepancias de `cfdi_cruzado` en `poliza.pdf` traian
`esperado == obtenido == 0` porque la regla cruza IDENTIDADES --que el
numero de documento del CFDI aparezca en la descripcion de su poliza-- y
`esperado`/`obtenido` eran `Decimal` obligatorios: la regla no tenia donde
decir «aqui no hay importe» y rellenaba los dos con cero.

Medido en la 8d y otra vez en la 8e: la web lo resolvia INFIRIENDO
(`numerica = esperado != obtenido`) y el CLI y el Excel escribian los ceros.
O sea que el arreglo de la 8a no llego «a la web y no al Excel»: llego solo
a la web y le faltaban los otros dos.

Medido en la 8e antes de elegir la forma: 17 sitios construyen una
`Discrepancia` --los 17 en `validate/rules.py`, y solo 2 de ellos cruzan
identidades-- y exactamente 3 leen `esperado`/`obtenido`, que son las tres
salidas. Se eligio `Decimal | None` sobre un campo de tipo de comprobacion
porque `None` hace IMPOSIBLE el modo de falla: no queda un cero que alguien
pueda imprimir. Un campo de tipo lo dejaria ahi, evitable pero presente, y
la proxima salida que olvide mirarlo volveria a escribir `0.00`.
"""

from __future__ import annotations

import io
from decimal import Decimal

import openpyxl
import pytest
from conftest import requires_real_pdf

from contapdf import cli
from contapdf.export.excel import exportar_polizas
from contapdf.pipeline import procesar_polizas
from contapdf.validate.rules import Discrepancia
from contapdf.web.vista import _discrepancia


# --- El contrato del dataclass -----------------------------------------
def test_una_regla_que_cruza_identidades_no_inventa_un_importe():
    d = Discrepancia(fila="P00476", indice=-1, regla="cfdi_cruzado",
                     esperado=None, obtenido=None)
    assert d.esperado is None and d.obtenido is None
    assert not d.compara_importes


def test_una_regla_que_compara_importes_lo_dice_por_llevar_las_cifras():
    d = Discrepancia(fila="1190-001-000", indice=3, regla="subtotal_debe",
                     esperado=Decimal("37398127.33"),
                     obtenido=Decimal("37398127.31"))
    assert d.compara_importes


def test_media_comparacion_no_existe():
    """Un lado con cifra y el otro sin ella no es un caso: es un error."""
    with pytest.raises(ValueError, match="esperado|obtenido"):
        Discrepancia(fila="x", indice=-1, regla="r",
                     esperado=Decimal("1.00"), obtenido=None)


# --- Las tres salidas, sobre el mismo caso -----------------------------
@pytest.fixture(scope="module")
def polizas():
    return procesar_polizas(requires_real_pdf("poliza"))


@pytest.mark.lento          # 28 s: 968 paginas
def test_ninguna_de_las_tres_salidas_imprime_un_cero_inventado(polizas, tmp_path):
    """El criterio de la fase, recorrido salida por salida."""
    cobertura = polizas.cobertura
    cruzadas = [d for d in cobertura.discrepancias if d.regla == "cfdi_cruzado"]
    assert len(cruzadas) == 53
    assert all(d.esperado is None and d.obtenido is None for d in cruzadas)
    filas = {d.fila for d in cruzadas}

    # 1) el CLI
    buffer = io.StringIO()
    cli._cola(cobertura, None, buffer, plantilla=None, reutilizada=False)
    lineas = [ln for ln in buffer.getvalue().splitlines()
              if "cfdi_cruzado" in ln and ln.strip().startswith("!")]
    assert len(lineas) == 53
    for linea in lineas:
        assert "0.00" not in linea, linea
        assert "esperado" not in linea, linea

    # 2) el Excel
    destino = tmp_path / "poliza.xlsx"
    exportar_polizas(polizas.libro, cobertura, destino)
    hoja = openpyxl.load_workbook(destino)["Validacion"]
    vistas = 0
    for fila in hoja.iter_rows(min_row=2, values_only=True):
        if fila[1] == "cfdi_cruzado" and fila[0] in filas:
            vistas += 1
            assert fila[2] in (None, ""), fila
            assert fila[3] in (None, ""), fila
    assert vistas == 53

    # 3) la web
    for d in cruzadas:
        pintada = _discrepancia(d)
        assert pintada["esperado"] == "" and pintada["obtenido"] == ""
        assert pintada["numerica"] is False


@pytest.mark.lento          # 188 s: auxiliar-gume
def test_las_reglas_que_si_comparan_importes_siguen_imprimiendo_sus_cifras():
    """El renglon del enunciado de la fase, tal cual, tiene que seguir saliendo."""
    from contapdf.pipeline import procesar_auxiliar

    resultado = procesar_auxiliar(requires_real_pdf("auxiliar-gume"))
    numericas = [d for d in resultado.cobertura.discrepancias
                 if d.compara_importes]
    assert numericas, "auxiliar-gume tiene discrepancias de importe"

    buffer = io.StringIO()
    cli._cola(resultado.cobertura, None, buffer, plantilla=None,
              reutilizada=False)
    texto = buffer.getvalue()
    # La linea de CADA discrepancia de importe sigue llevando sus dos
    # cifras, con el formato de siempre.
    for muestra in numericas:
        linea = next(ln for ln in texto.splitlines()
                     if ln.strip().startswith("!") and muestra.fila in ln
                     and muestra.regla in ln)
        assert "esperado" in linea and "obtenido" in linea, linea
        assert f"{muestra.esperado:,.2f}" in linea, linea
        assert f"{muestra.obtenido:,.2f}" in linea, linea
