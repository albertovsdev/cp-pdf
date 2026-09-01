"""Los cinco comandos del CLI.

Fase 7e. Hasta aqui solo `balanza` y `confirmar` existian, y los otros
cuatro parsers eran alcanzables unicamente por API. La capa web necesita
los cinco, y el CLI es el contrato que va a envolver.

Todos tienen la misma forma: `<comando> <pdf> [-o salida.xlsx]
[--tenant] [--plantillas]`, todos reportan cobertura y todos usan el mismo
codigo de salida (0 cuadra, 1 hay discrepancias, 2 no se pudo procesar).
"""

from __future__ import annotations

import io

import openpyxl
import pytest
from conftest import requires_real_pdf

from contapdf.cli import main

# (comando, fixture, hojas del Excel, algo que el reporte tiene que decir)
_COMANDOS = (
    ("balanza", "balanza", ["Balanza", "Validacion"], "475"),
    ("auxiliar", "auxiliar", ["Auxiliar", "Validacion"], "filas"),
    ("polizas", "poliza", ["Polizas", "Movimientos", "CFDI", "Plana",
                           "Validacion"], "polizas"),
    ("estado-cuenta", "edocta", ["Cuentas", "Movimientos", "Plana",
                                 "Validacion"], "movimientos"),
    ("mayor", "mayor-gume", ["Cuentas", "Meses", "Plana", "Validacion"],
     "cuentas"),
)


# --- Criterio 2 ---------------------------------------------------------
@pytest.mark.parametrize("comando,fixture,hojas,marca", _COMANDOS)
def test_cada_comando_corre_y_escribe_su_excel(comando, fixture, hojas, marca,
                                               tmp_path):
    pdf = requires_real_pdf(fixture)
    destino = tmp_path / f"{comando}.xlsx"
    salida = io.StringIO()

    codigo = main([comando, str(pdf), "-o", str(destino)], salida=salida)

    assert codigo in (0, 1), salida.getvalue()
    assert destino.exists()
    assert openpyxl.load_workbook(destino).sheetnames == hojas
    assert marca in salida.getvalue().lower()


@pytest.mark.parametrize("comando,fixture,hojas,marca", _COMANDOS)
def test_cada_comando_reporta_su_cobertura(comando, fixture, hojas, marca,
                                           tmp_path):
    """Nunca un resultado sin decir contra que se comprobo (PLAN 2)."""
    salida = io.StringIO()
    main([comando, str(requires_real_pdf(fixture))], salida=salida)
    texto = salida.getvalue().lower()
    assert "cobertura" in texto
    assert "reglas" in texto
    assert "0 discrepancias" not in texto
    assert "extraccion" in texto


@pytest.mark.parametrize("comando", [c for c, *_ in _COMANDOS])
def test_cada_comando_avisa_si_el_pdf_no_existe(comando, tmp_path):
    salida = io.StringIO()
    codigo = main([comando, str(tmp_path / "no-existe.pdf")], salida=salida)
    assert codigo == 2
    assert "no existe" in salida.getvalue().lower()


@pytest.mark.parametrize("comando", [c for c, *_ in _COMANDOS])
def test_sin_o_ningun_comando_escribe_excel(comando, tmp_path):
    fixture = next(f for c, f, *_ in _COMANDOS if c == comando)
    salida = io.StringIO()
    main([comando, str(requires_real_pdf(fixture))], salida=salida)
    assert list(tmp_path.iterdir()) == []


def test_los_cinco_aceptan_el_mismo_par_de_banderas(tmp_path):
    """Y solo aprende plantilla el documento cuya aritmetica cuadro.

    Los fixtures de auxiliar y polizas traen discrepancias reales, asi que
    `guardar()` los rechaza: no se aprende un formato que no cuadro (PLAN 2).
    Salen con codigo 1, que es justo lo que ese codigo significa.
    """
    from contapdf.templates.store import AlmacenPlantillas

    codigos = {}
    for comando, fixture, _, _ in _COMANDOS:
        salida = io.StringIO()
        codigos[comando] = main(
            [comando, str(requires_real_pdf(fixture)), "--tenant", "t",
             "--plantillas", str(tmp_path)], salida=salida)
        assert "cobertura" in salida.getvalue().lower(), comando

    aprendidas = {p.tipo for p in AlmacenPlantillas(tmp_path).listar("t")}
    cuadran = {c for c, k in codigos.items() if k == 0}
    assert cuadran == {"balanza", "estado-cuenta", "mayor"}
    assert aprendidas == {"balanza", "estado_cuenta", "mayor"}


def test_el_estado_de_cuenta_queda_pendiente_por_el_separador(tmp_path):
    salida = io.StringIO()
    main(["estado-cuenta", str(requires_real_pdf("edocta")), "--tenant", "t",
          "--plantillas", str(tmp_path)], salida=salida)
    texto = salida.getvalue().lower()
    assert "pendiente de confirmacion" in texto
    assert "separador de continuacion" in texto
    # Se pregunta sin proponer: la geometria no da con que (PLAN 2).
    assert "sin propuesta" in texto


def test_el_estado_de_cuenta_con_varias_cuentas_las_desglosa(tmp_path):
    """No basta el total: hay que ver cuanto le toco a cada cuenta."""
    salida = io.StringIO()
    codigo = main(["estado-cuenta", str(requires_real_pdf("edocta-julio-banorte"))],
                  salida=salida)
    texto = salida.getvalue().lower()
    assert codigo == 0
    assert "283" in texto
    # Un renglon por cuenta, con su nombre y sus movimientos.
    assert "enlace negocios pfae: 283 movimientos" in texto
    assert "inversion enlace negocios pfae: 0 movimientos" in texto


def test_un_reporte_que_no_trae_tabla_de_movimientos_dice_que_es(tmp_path):
    """No 'layout desconocido': la capa web tiene que poder explicarlo."""
    salida = io.StringIO()
    codigo = main(["estado-cuenta", str(requires_real_pdf("edocta-multiva"))],
                  salida=salida)
    texto = salida.getvalue().lower()
    assert codigo == 2
    assert "sin_movimientos" in texto
    assert "movimiento" in texto


def test_el_reporte_dice_que_estrategia_eligio_y_por_que():
    salida = io.StringIO()
    main(["balanza", str(requires_real_pdf("balanza-businesspro"))], salida=salida)
    texto = salida.getvalue().lower()
    assert "pdf_chars" in texto
    # El porque, no solo el que: es lo que permite discutir la eleccion.
    assert "contaminado" in texto or "encimado" in texto or "traslap" in texto
