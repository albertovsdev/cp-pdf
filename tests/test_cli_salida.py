"""El destino de `-o` se comprueba antes de trabajar, no al guardar.

Fase 8c. Con un directorio inexistente, el CLI reventaba con una traza de
siete niveles desde `zipfile`, **despues** de haber procesado el documento
entero. Sobre `auxiliar-gume` eso son 24 minutos de trabajo tirados por un
directorio mal escrito.

Y peor que la traza: una excepcion sin capturar sale con **codigo 1**, que
en este CLI significa «hay discrepancias que revisar». Un `-o` mal escrito
era indistinguible, para cualquier guion, de un documento que no cuadra.

Se decidio **avisar y no crear el directorio**:

- Crear lo que no se pidio esconde el error. Un `-o C:\\slaida\\x.xlsx` con
  una letra cambiada crearia un directorio nuevo y el usuario buscaria su
  Excel donde creia haberlo escrito.
- El sistema entero esta construido sobre declarar lo que no puede hacer;
  inventar un directorio es lo contrario.
- El argumento a favor de crearlo —no perder el trabajo ya hecho— se cae
  solo si la comprobacion ocurre ANTES de trabajar, que es lo que se hizo.
"""

from __future__ import annotations

import io

import pytest
from conftest import requires_real_pdf

from contapdf.cli import main


def _correr(argumentos):
    salida = io.StringIO()
    codigo = main(argumentos, salida=salida)
    return codigo, salida.getvalue()


def test_un_directorio_de_salida_que_no_existe_da_un_mensaje(tmp_path):
    pdf = requires_real_pdf("balanza")
    destino = tmp_path / "no" / "existe" / "balanza.xlsx"

    codigo, texto = _correr(["balanza", str(pdf), "-o", str(destino)])

    assert codigo == 2, "un destino imposible no es 'hay discrepancias'"
    assert "Traceback" not in texto
    assert str(destino.parent) in texto, "el mensaje no dice que directorio"
    assert not destino.exists()
    assert not destino.parent.exists(), "no se crea lo que no se pidio"


def test_el_mensaje_dice_que_hacer(tmp_path):
    pdf = requires_real_pdf("balanza")
    destino = tmp_path / "falta" / "balanza.xlsx"

    _, texto = _correr(["balanza", str(pdf), "-o", str(destino)])

    plano = texto.lower()
    assert "no existe" in plano
    assert "crea" in plano or "crear" in plano


def test_se_comprueba_antes_de_leer_el_pdf(tmp_path):
    """Lo que evita tirar 24 minutos de trabajo por un directorio.

    Se manda un fichero que NO es un PDF: si la comprobacion del destino
    ocurriera despues de procesar, el mensaje hablaria del documento. Que
    hable del directorio prueba el orden, sin medir tiempo.
    """
    falso = tmp_path / "esto-no-es-un.pdf"
    falso.write_bytes(b"ni de lejos")
    destino = tmp_path / "no" / "existe" / "x.xlsx"

    codigo, texto = _correr(["balanza", str(falso), "-o", str(destino)])

    assert codigo == 2
    assert str(destino.parent) in texto, (
        "el mensaje habla del PDF: la comprobacion del destino llego tarde")


@pytest.mark.parametrize("comando,fixture", [
    ("balanza", "balanza"), ("estado-cuenta", "edocta"),
    ("mayor", "mayor-gume"),
])
def test_los_comandos_comprueban_igual(tmp_path, comando, fixture):
    """No solo balanza: el `-o` es el mismo argumento en los cinco."""
    pdf = requires_real_pdf(fixture)
    destino = tmp_path / "falta" / "x.xlsx"

    codigo, texto = _correr([comando, str(pdf), "-o", str(destino)])

    assert codigo == 2
    assert "Traceback" not in texto


def test_un_destino_que_es_un_directorio_tambien_avisa(tmp_path):
    pdf = requires_real_pdf("balanza")
    destino = tmp_path / "soy-un-directorio"
    destino.mkdir()

    codigo, texto = _correr(["balanza", str(pdf), "-o", str(destino)])

    assert codigo == 2
    assert "Traceback" not in texto


def test_un_directorio_que_si_existe_sigue_funcionando(tmp_path):
    """La red no puede estorbar al caso normal."""
    pdf = requires_real_pdf("balanza")
    destino = tmp_path / "balanza.xlsx"

    codigo, _ = _correr(["balanza", str(pdf), "-o", str(destino)])

    assert codigo == 0
    assert destino.is_file()


def test_sin_o_no_se_comprueba_nada(tmp_path):
    """Sin `-o` no hay destino que validar: solo se reporta."""
    codigo, texto = _correr(["balanza", str(requires_real_pdf("balanza"))])

    assert codigo == 0
    assert "cobertura" in texto.lower()
