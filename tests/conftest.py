"""Utilidades comunes de los tests.

Las rutas se derivan de __file__, nunca del directorio actual: los tests
deben pasar igual si pytest se invoca desde otro lado.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from contapdf.ir import Document, Page, Word

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
LAYOUTS = FIXTURES / "layouts"
REAL = FIXTURES / "real"
SYNTHETIC = FIXTURES / "synthetic"
GOLDEN = FIXTURES / "golden"

REAL_PDFS = {
    "balanza": REAL / "1-Balanza" / "balanza.pdf",
    "poliza": REAL / "2-Libro-Diario" / "poliza.pdf",
    "auxiliar": REAL / "3-Auxiliares" / "auxiliar.pdf",
    "edocta": REAL / "4-Estados-Cuenta" / "edocta.pdf",
}


def load_layout(name: str) -> dict[str, Any]:
    """Lee un fixture enmascarado de fixtures/layouts."""
    return json.loads((LAYOUTS / f"{name}.layout.json").read_text(encoding="utf-8"))


def layout_page(name: str, number: int) -> Page:
    """Reconstruye una Page del IR a partir del fixture enmascarado.

    Es lo que permite testear layout/ sin abrir un PDF real: el fixture
    conserva coordenadas reales aunque el texto este enmascarado.
    """
    raw = load_layout(name)
    for page in raw["pages"]:
        if page["page"] == number:
            words = tuple(
                Word(
                    text=w["text"],
                    x0=w["x0"],
                    x1=w["x1"],
                    top=w["top"],
                    bottom=w["bottom"],
                    size=w["size"],
                    bold=w["bold"],
                    page=number,
                )
                for w in page["words"]
            )
            return Page(
                number=number,
                width=page["width"],
                height=page["height"],
                words=words,
                ruling_lines=page["ruling_lines"],
            )
    raise AssertionError(f"{name}.layout.json no tiene la pagina {number}")


def layout_columns(name: str, number: int) -> list[dict[str, Any]]:
    """Columnas que reporto la fase 0 para esa pagina (numeros de referencia)."""
    raw = load_layout(name)
    for page in raw["pages"]:
        if page["page"] == number:
            return page["columns"]
    raise AssertionError(f"{name}.layout.json no tiene la pagina {number}")


def texts(words) -> list[str]:
    return [w.text for w in words]


def requires_real_pdf(name: str) -> Path:
    path = REAL_PDFS[name]
    if not path.exists():
        pytest.skip(f"fixture real ausente (gitignored): {path}")
    return path


def _pages_from(raw: dict[str, Any]) -> list[Page]:
    return [
        Page(
            number=page["page"],
            width=page["width"],
            height=page["height"],
            ruling_lines=page["ruling_lines"],
            words=tuple(
                Word(text=w["text"], x0=w["x0"], x1=w["x1"], top=w["top"],
                     bottom=w["bottom"], size=w["size"], bold=w["bold"],
                     page=page["page"])
                for w in page["words"]
            ),
        )
        for page in raw["pages"]
    ]


def synthetic_document(name: str) -> Document:
    """Document armado desde un fixture sintetico, sin abrir ningun PDF."""
    doc, _ = counted_document(name)
    return doc


def counted_document(name: str) -> tuple[Document, list[int]]:
    """Igual que synthetic_document, pero anota cada recorrido de paginas.

    Sirve para verificar PLAN 0: una sola pasada completa por documento.
    """
    raw = json.loads((SYNTHETIC / f"{name}.json").read_text(encoding="utf-8"))
    paginas = _pages_from(raw)
    pasadas: list[int] = []

    def abrir():
        pasadas.append(len(pasadas) + 1)
        yield from paginas

    return Document(source=f"{name}.json", page_count=len(paginas),
                    open_pages=abrir), pasadas


def golden_rows(name: str) -> list[dict[str, str]]:
    import csv
    with (GOLDEN / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))
