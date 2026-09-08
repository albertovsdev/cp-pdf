"""Las restricciones de PLAN.md seccion 0, verificadas.

Son baratas de sostener ahora y caras de meter despues.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from conftest import layout_page

from contapdf.layout.columns import detect
from contapdf.layout.lines import group
from contapdf.layout.region import find_table_region

SRC = Path(__file__).resolve().parent.parent / "src" / "contapdf"
MODULOS = sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("path", MODULOS, ids=lambda p: p.name)
def test_el_nucleo_no_imprime_ni_lee_el_entorno(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            assert not (isinstance(fn, ast.Name) and fn.id == "print"), (
                f"{path.name}: usa print; para mensajes va logging")
            # os.environ / os.getenv al importar contamina entre empresas.
            if isinstance(fn, ast.Attribute) and fn.attr == "getenv":
                pytest.fail(f"{path.name}: lee el entorno")
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            pytest.fail(f"{path.name}: lee el entorno")


@pytest.mark.parametrize("path", MODULOS, ids=lambda p: p.name)
def test_el_nucleo_no_tiene_estado_global_mutable(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if not isinstance(t, ast.Name):
                continue
            assert t.id.isupper() or t.id.startswith("_"), (
                f"{path.name}: '{t.id}' es estado a nivel de modulo")
            assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set)), (
                f"{path.name}: '{t.id}' es mutable a nivel de modulo")


def test_las_funciones_de_layout_no_escriben_a_stdout(capsys):
    lines = group(layout_page("edocta", 1).words)
    detect(lines)
    find_table_region(lines)
    salida = capsys.readouterr()
    assert salida.out == "" and salida.err == ""


@pytest.mark.parametrize("modulo", [
    "contapdf.ir",
    "contapdf.layout.lines",
    "contapdf.layout.columns",
    "contapdf.layout.region",
])
def test_los_modulos_de_layout_no_dependen_de_pdfplumber(modulo):
    # Los parsers se testean sin abrir un PDF; el IR es la frontera.
    mod = importlib.import_module(modulo)
    assert not hasattr(mod, "pdfplumber")


# --- Fase 8e: la evidencia de una medicion vive donde el PLAN la cita ---
RAIZ = Path(__file__).resolve().parent.parent
MEDICIONES = RAIZ / "scripts" / "mediciones"


def test_los_reportes_de_medicion_viven_en_scripts_mediciones():
    """Un `.txt` de medicion suelto en la raiz se borra sin que nadie lo note.

    El de las 17:41 es el UNICO que documenta el fallo del OCR con Tesseract
    presente en SERVIDORSIST (v5.4.0, revienta a los 7.0 s), o sea la unica
    evidencia reproducible de «el OCR nunca funciono alli». PLAN 2 y 5.1 se
    apoyan en el; si desaparece, esas afirmaciones se quedan sin checksum.
    """
    sueltos = sorted(p.name for p in RAIZ.glob("mediciones-*.txt"))
    assert not sueltos, f"reportes de medicion en la raiz del repo: {sueltos}"
    reportes = sorted(p.name for p in MEDICIONES.glob("mediciones-*.txt"))
    assert "mediciones-ServidorSist-20260904-1741-metodoRAPIDO.txt" in reportes
    assert "mediciones-ServidorSist-20260904-1757.txt" in reportes


def test_la_corrida_con_tesseract_conserva_la_traza_del_fallo():
    """Lo que respalda la afirmacion es el contenido, no el nombre."""
    texto = (MEDICIONES / "mediciones-ServidorSist-20260904-1741-metodoRAPIDO.txt"
             ).read_text(encoding="utf-8", errors="replace")
    assert "tesseract    OK" in texto
    assert "AttributeError: 'NoneType' object has no attribute 'splitlines'" in texto
