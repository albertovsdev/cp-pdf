"""Huella del formato de un documento.

Identifica el layout sin mirar nada que cambie entre cargas: ni empresa,
ni RFC, ni periodo, ni paginas, ni montos. Solo la forma de la tabla.

Se arma con tres cosas medidas como estables entre paginas del mismo
documento: el CONJUNTO de tokens de encabezado (las etiquetas se reparten
distinto entre columnas segun la pagina, pero el vocabulario no cambia),
cuantas columnas de monto hay, y la forma del numero de cuenta.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from contapdf.parsers.base import Layout, normalizar

_LARGO_VALOR = 16
_RE_CUENTA = re.compile(r"^\d[\d-]{2,}$")


@dataclass(frozen=True)
class Huella:
    """La forma de un documento, reducida a algo comparable."""

    tokens: tuple[str, ...]
    columnas_monto: int
    forma_cuenta: str

    @property
    def valor(self) -> str:
        """Clave estable entre corridas.

        sha256 y no hash(): el hash de Python cambia con cada proceso y la
        plantilla tiene que encontrarse manana.
        """
        crudo = f"{'|'.join(self.tokens)}#{self.columnas_monto}#{self.forma_cuenta}"
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:_LARGO_VALOR]

    def __str__(self) -> str:
        return self.valor


def forma_de_cuenta(cuentas: Sequence[str]) -> str:
    """'sep' si el catalogo usa separadores, 'fijo:N' si son N digitos."""
    candidatas = [c for c in cuentas if _RE_CUENTA.match(c)]
    if not candidatas:
        return "?"
    if any("-" in c for c in candidatas):
        return "sep"
    largos = {len(c) for c in candidatas}
    return f"fijo:{min(largos)}" if len(largos) == 1 else "variable"


def huella_de(layout: Layout | None, cuentas: Sequence[str] = ()) -> Huella | None:
    """Huella del formato, o None si no hay layout del que sacarla."""
    if layout is None or not layout.columns:
        return None
    tokens = {t for c in layout.columns for t in normalizar(c.header).split()}
    return Huella(
        tokens=tuple(sorted(tokens)),
        columnas_monto=len(layout.montos),
        forma_cuenta=forma_de_cuenta(cuentas),
    )
