"""Enrutamiento a OCR por texto en CID.

Fase 7e. Tercera senal de `strategy`, junto a los tokens contaminados y las
palabras traslapadas. Un PDF sin mapa ToUnicode entrega '(cid:123)(cid:45)'
en vez de letras: ni pdf_text ni pdf_chars lo salvan, porque el problema no
es como se lee sino que el archivo no trae la tabla que traduce glifos.

**El OCR cuesta ~21 s por documento**, asi que la decision no puede ser "hay
tokens en CID" sino "el documento es ilegible". Medido sobre los 27
fixtures: HSBC da 98.8% de su muestra en CID y el siguiente da 0.55%. No
hay nada en medio, asi que cualquier umbral entre los dos separa, y el
default 0.50 dice lo que se quiere decir: se releen documentos ilegibles,
no documentos con un sello digital en CID. Esos ultimos ya los cubre el
carril de `reintento.reintentar_cid`, pagina por pagina.
"""

from __future__ import annotations

import io

import pytest
from conftest import requires_real_pdf

from contapdf.extract import ocr
from contapdf.extract.strategy import decidir, extraer, fraccion_cid


def _sin_tesseract():
    return not ocr.hay_tesseract()


# --- Criterio 3: HSBC se enruta solo ------------------------------------
def test_el_documento_ilegible_se_manda_a_ocr():
    decision = decidir(requires_real_pdf("edocta-hsbc"))
    assert decision.estrategia == "ocr"
    assert "cid" in decision.motivo.lower()
    # El motivo trae la cifra medida, no una etiqueta: es lo que permite
    # discutir el umbral sin volver a medir.
    assert decision.senales["fraccion_cid"] > 0.9


def test_la_decision_dice_por_que_en_los_tres_caminos():
    for nombre, esperada in (("edocta-hsbc", "ocr"),
                             ("balanza-businesspro", "pdf_chars"),
                             ("balanza", "pdf_text")):
        decision = decidir(requires_real_pdf(nombre))
        assert decision.estrategia == esperada, nombre
        assert decision.motivo, nombre
        assert set(decision.senales) >= {"fraccion_cid", "tokens_contaminados",
                                         "palabras_traslapadas"}, nombre


# --- Criterio 4: pocos tokens en CID NO se mandan a OCR -----------------
@pytest.mark.parametrize("nombre", ["edocta-inbursa", "edocta-multiva"])
def test_unos_pocos_tokens_en_cid_no_disparan_el_ocr(nombre):
    """Son el sello digital: 0.55% y 0.49% de la muestra.

    Mandarlos a OCR cuesta 21 s para recuperar seis tokens decorativos, y
    ademas degrada el resto del documento, que se lee perfecto.
    """
    decision = decidir(requires_real_pdf(nombre))
    assert decision.estrategia != "ocr"
    assert 0 < decision.senales["fraccion_cid"] < 0.01


def test_el_umbral_es_configurable():
    # Bajarlo hasta el sello digital SI lo manda a OCR: prueba que lo que
    # decide es el umbral y no una lista de documentos.
    ruta = requires_real_pdf("edocta-inbursa")
    assert decidir(ruta).estrategia != "ocr"
    assert decidir(ruta, umbral_cid=0.001).estrategia == "ocr"


def test_la_fraccion_de_cid_se_mide_sobre_las_palabras():
    from contapdf.ir import Word

    def w(texto):
        return Word(text=texto, x0=0, x1=10, top=0, bottom=8, size=8,
                    bold=False, page=1)

    assert fraccion_cid([]) == 0.0
    assert fraccion_cid([w("hola"), w("(cid:12)(cid:9)")]) == 0.5
    assert fraccion_cid([w("hola"), w("mundo")]) == 0.0


@pytest.mark.skipif(_sin_tesseract(), reason="tesseract no esta instalado")
def test_sin_tesseract_no_se_cae_y_lo_declara(monkeypatch):
    monkeypatch.setattr(ocr, "hay_tesseract", lambda **kw: False)
    decision = decidir(requires_real_pdf("edocta-hsbc"))
    assert decision.estrategia != "ocr"
    assert "tesseract" in decision.motivo.lower()


# --- Criterio 3: de punta a punta, sin intervencion manual --------------
@pytest.mark.lento
def test_hsbc_se_procesa_entero_sin_pasarle_nada_a_mano():
    if _sin_tesseract():
        pytest.skip("tesseract no esta instalado")
    from decimal import Decimal

    from contapdf.pipeline import procesar_estado_cuenta

    r = procesar_estado_cuenta(requires_real_pdf("edocta-hsbc"))
    assert r.estrategia == "ocr"
    assert "cid" in r.motivo_estrategia.lower()
    cuenta = r.estado.cuentas[0]
    assert cuenta.saldo_inicial == Decimal("7945.22")
    assert cuenta.saldo_corte == Decimal("5195.60")
    assert sum(m.retiro for m in r.estado.movimientos) == Decimal("2749.62")


@pytest.mark.lento
def test_hsbc_desde_el_cli_reporta_la_estrategia_y_el_motivo(tmp_path):
    if _sin_tesseract():
        pytest.skip("tesseract no esta instalado")
    from contapdf.cli import main

    destino = tmp_path / "hsbc.xlsx"
    salida = io.StringIO()
    codigo = main(["estado-cuenta", str(requires_real_pdf("edocta-hsbc")),
                   "-o", str(destino)], salida=salida)
    texto = salida.getvalue().lower()
    assert codigo == 0
    assert destino.exists()
    assert "ocr" in texto
    assert "cid" in texto


# --- Los documentos que ya funcionaban no cambian -----------------------
@pytest.mark.parametrize("nombre", ["balanza", "auxiliar", "poliza",
                                    "mayor-gume", "edocta"])
def test_la_senal_nueva_no_reenruta_lo_que_ya_funcionaba(nombre):
    decision = decidir(requires_real_pdf(nombre))
    assert decision.estrategia in ("pdf_text", "pdf_chars")
    assert decision.senales["fraccion_cid"] == 0.0


def test_extraer_sigue_devolviendo_par_documento_estrategia():
    """Firma vieja intacta: hay veintitantos llamadores que la desempaquetan."""
    doc, estrategia = extraer(requires_real_pdf("balanza"), page_numbers=[1])
    assert doc.page_count >= 1
    assert estrategia == "pdf_text"
