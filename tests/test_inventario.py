"""El inventario de cobertura: una linea por fixture, y ningun conteo solo.

El guion existe para poder decirle al despacho QUE cubre el sistema y que
no. Se testean las partes puras --de un `ResultadoDocumento` a su renglon--
sin abrir un PDF, y el recorrido entero va marcado `lento`.

Lo que estos tests defienden, y que es el argumento del proyecto: la
columna COBERTURA lleva SIEMPRE las dos cifras. Un «95%» sin denominador es
el `5/5` de BBVA otra vez.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from inventario import (  # noqa: E402
    TIPOS,
    FilaInventario,
    FilaRechazo,
    emisor_de,
    estado_de_plantilla,
    fila_de,
    inventariar,
    tabla,
)

from contapdf.cli import ResultadoDocumento  # noqa: E402
from contapdf.validate.rules import (  # noqa: E402
    CUADRA,
    FALLA,
    NO_VERIFICABLE,
    Cobertura,
    ResultadoRegla,
)


def _cobertura():
    return Cobertura(reglas=(
        ResultadoRegla(regla="renglon", estado=CUADRA, aplicables=100,
                       evaluados=90, exactas=90),
        ResultadoRegla(regla="totales", estado=FALLA, aplicables=2,
                       evaluados=2, exactas=1),
        ResultadoRegla(regla="jerarquia", estado=NO_VERIFICABLE, aplicables=8,
                       evaluados=0, motivo="sin jerarquia"),
    ))


def _resultado(datos=None, plantilla=None, reutilizada=False):
    return ResultadoDocumento(
        tipo="balanza", fuente="x.pdf", paginas=9, estrategia="pdf_text",
        motivo_estrategia="texto nativo limpio", cobertura=_cobertura(),
        plantilla=plantilla, reutilizada=reutilizada, resumen=(),
        datos=datos if datos is not None else object())


# --- La columna que no puede mentir ------------------------------------
def test_la_cobertura_lleva_siempre_las_dos_cifras():
    fila = fila_de("balanza", _resultado())
    # 90 + 2 + 0 evaluados de 100 + 2 + 8 aplicables.
    assert fila.cobertura == "92 de 110"
    assert "%" not in fila.cobertura


def test_las_reglas_salen_partidas_en_tres():
    fila = fila_de("balanza", _resultado())
    assert fila.reglas == "1/1/1"
    assert (fila.cuadran, fila.fallan, fila.no_verificables) == (1, 1, 1)


def test_el_codigo_sale_de_la_funcion_del_cli_no_de_una_copia():
    """Si el CLI cambia de criterio, el inventario cambia con el."""
    from contapdf.cli import codigo_de_salida

    resultado = _resultado()
    assert fila_de("balanza", resultado).codigo == codigo_de_salida(
        resultado.cobertura) == 1


# --- El emisor sale del documento, o no sale ---------------------------
def test_el_emisor_de_un_estado_de_cuenta_sale_de_su_meta():
    from contapdf.parsers.estado_cuenta import EstadoCuenta, MetaEstadoCuenta

    estado = EstadoCuenta(meta=MetaEstadoCuenta(banco="AFIRME", rfc="XXX"),
                          cuentas=(), movimientos=())
    assert emisor_de(_resultado(datos=estado)) == "AFIRME"


def test_un_documento_contable_no_trae_emisor_y_se_deja_vacio():
    """Ningun parser contable lee la empresa. No se deduce del fichero."""
    assert emisor_de(_resultado()) == ""


def test_el_emisor_nunca_se_deduce_del_nombre_del_fixture():
    fila = fila_de("balanza-businesspro", _resultado())
    assert fila.emisor == ""
    assert "businesspro" not in fila.emisor.lower()


# --- La plantilla ------------------------------------------------------
def test_sin_plantilla_lo_dice():
    assert estado_de_plantilla(_resultado()) == "no"


def test_una_plantilla_pendiente_no_se_cuenta_como_aprendida():
    from contapdf.templates.store import Plantilla

    plantilla = Plantilla(
        tenant_id="t", huella="h", tipo="balanza", estrategia="pdf_text",
        mapeo={}, forma="", verificado_por="aritmetica",
        orientacion_verificada=True, filas_afectadas=0, esquema=None,
        reglas={}, cobertura={}, pendiente_de_confirmacion=True)
    assert estado_de_plantilla(_resultado(plantilla=plantilla)) == "pendiente"
    aprendida = _resultado(
        plantilla=Plantilla(
            tenant_id="t", huella="h", tipo="balanza", estrategia="pdf_text",
            mapeo={}, forma="", verificado_por="aritmetica",
            orientacion_verificada=True, filas_afectadas=0, esquema=None,
            reglas={}, cobertura={}, pendiente_de_confirmacion=False))
    assert estado_de_plantilla(aprendida) == "aprendida"


# --- Las tablas --------------------------------------------------------
def test_la_tabla_de_texto_alinea_y_no_pierde_columnas():
    texto = tabla(("A", "BB"), [("1", "2"), ("largo", "x")])
    assert texto.splitlines()[0].startswith("A")
    assert "largo" in texto
    assert len(texto.splitlines()) == 4


def test_la_tabla_markdown_sale_pegable_en_el_plan():
    texto = tabla(("A", "B"), [("1", "2")], markdown=True)
    assert texto.splitlines()[0] == "| A | B |"
    assert texto.splitlines()[1] == "|---|---|"
    assert texto.splitlines()[2] == "| 1 | 2 |"


def test_una_barra_en_una_celda_no_rompe_la_tabla_markdown():
    """Los motivos del sistema llevan texto libre."""
    texto = tabla(("A",), [("no|cuadra",)], markdown=True)
    assert r"no\|cuadra" in texto


# --- El recorrido ------------------------------------------------------
def test_un_fixture_que_no_esta_se_declara_no_se_inventa(tmp_path):
    producen, rechazados, ausentes = inventariar(
        ["balanza"], {"balanza": tmp_path / "no-existe.pdf"})
    assert (producen, rechazados) == ([], [])
    assert len(ausentes) == 1
    assert "no esta" in ausentes[0].motivo


def test_los_27_fixtures_tienen_tipo_declarado():
    """Sin esto, un fixture nuevo se cae del inventario en silencio."""
    from conftest import REAL_PDFS

    faltan = sorted(set(REAL_PDFS) - set(TIPOS))
    assert not faltan, f"fixtures sin tipo en TIPOS: {faltan}"
    sobran = sorted(set(TIPOS) - set(REAL_PDFS))
    assert not sobran, f"TIPOS nombra fixtures que no existen: {sobran}"


@pytest.mark.lento          # ~7 min: abre los 27 documentos
def test_el_inventario_entero_corre_y_cuadra():
    """Cifras MEDIDAS en la 8f. Si cambian, el inventario caduco."""
    from conftest import REAL_PDFS

    producen, rechazados, ausentes = inventariar(sorted(REAL_PDFS), REAL_PDFS)
    assert not ausentes, [f.fixture for f in ausentes]
    assert len(producen) + len(rechazados) == 27
    assert len(producen) == 16
    assert len(rechazados) == 11
    # Ninguna fila puede traer un conteo sin su denominador.
    for fila in producen:
        assert fila.aplicables >= fila.evaluados, fila.fixture
        assert " de " in fila.cobertura
        assert fila.codigo in (0, 1)
    # Y ningun rechazo puede salir sin motivo.
    for fila in rechazados:
        assert fila.motivo.strip(), fila.fixture


# --- El recorte del emisor es presentacion, no arreglo ------------------
def test_el_emisor_se_recorta_para_la_tabla_pero_el_dato_se_guarda_entero():
    """`MetaEstadoCuenta.banco` arrastra el domicilio, y en Bajio el titular."""
    from inventario import _celdas_a, emisor_corto

    largo = ("Banco Mercantil del Norte S.A. Institución de Banca Múltiple "
             "Grupo Financiero Banorte, Av. Revolución No. 3000")
    corto = emisor_corto(largo)
    assert len(corto) <= 38
    assert corto.endswith("…")
    assert largo.startswith(corto[:-1].rstrip())

    fila = FilaInventario(
        fixture="x", tipo="estado-cuenta", emisor=largo, paginas=1,
        extraccion="pdf_text", evaluados=1, aplicables=1, cuadran=1, fallan=0,
        no_verificables=0, plantilla="no", codigo=0)
    # La celda va recortada; el campo, entero.
    assert fila.emisor == largo
    assert _celdas_a(fila)[2] == corto


def test_un_emisor_corto_no_se_toca():
    from inventario import emisor_corto

    assert emisor_corto("AFIRME") == "AFIRME"
    assert emisor_corto("  AFIRME   GRUPO  ") == "AFIRME GRUPO"


# --- Fase 8g: el inventario se ESCRIBE, no se copia y pega -------------
# Vivía dentro de PLAN.md §2, que es un documento escrito a mano: un
# artefacto generado ahí dentro se queda obsoleto en la primera fase que
# nadie lo regenere. Ahora el guion escribe INVENTARIO.md, y el PLAN solo
# dice dónde vive y con qué comando se rehace.

def _fila(fixture="balanza", tipo="balanza", emisor="", codigo=0):
    return FilaInventario(
        fixture=fixture, tipo=tipo, emisor=emisor, paginas=9,
        extraccion="pdf_text", evaluados=530, aplicables=534, cuadran=4,
        fallan=0, no_verificables=0, plantilla="aprendida", codigo=codigo)


def test_el_documento_se_lee_solo():
    """Es el fichero que se le enseña al despacho."""
    from inventario import documento

    texto = documento([_fila()], [FilaRechazo("mayor-fd", "mayor", "no cuadra")],
                      [], generado="2026-09-11 10:00", commit="abc1234")
    assert texto.startswith("# Inventario de cobertura")
    # Las dos tablas, con su título y su conteo.
    assert "1 producen Excel" in texto or "producen Excel (1)" in texto
    assert "balanza" in texto and "mayor-fd" in texto
    # Y de cuándo es, que es lo que dice si ha caducado.
    assert "2026-09-11 10:00" in texto
    assert "abc1234" in texto
    # Y cómo se regenera, para que nadie lo edite a mano.
    assert "scripts/inventario.py" in texto


def test_el_documento_explica_la_columna_que_no_puede_mentir():
    from inventario import documento

    texto = documento([_fila()], [], [], generado="x", commit="y")
    assert "evaluados" in texto.lower() and "aplicables" in texto.lower()


def test_los_que_no_se_pudieron_medir_salen_declarados():
    from inventario import documento

    texto = documento([], [], [FilaRechazo("balanza", "balanza", "no está el PDF")],
                      generado="x", commit="y")
    assert "no está el PDF" in texto
    assert "balanza" in texto


def test_escribir_deja_el_fichero_en_disco(tmp_path):
    from inventario import escribir

    destino = tmp_path / "INVENTARIO.md"
    devuelto = escribir(destino, [_fila()], [], [], generado="x", commit="y")
    assert devuelto == destino
    assert destino.exists()
    assert destino.read_text(encoding="utf-8").startswith("# Inventario")


def test_el_plan_ya_no_lleva_las_tablas_del_inventario():
    """Un artefacto generado dentro de un documento a mano caduca solo."""
    plan = (Path(__file__).resolve().parent.parent / "PLAN.md").read_text(
        encoding="utf-8")
    assert "| FIXTURE | TIPO | EMISOR |" not in plan
    assert "INVENTARIO.md" in plan
