"""El inventario de cobertura: que documentos cubre el sistema, y cuales no.

Una linea por fixture, para poder pedirle al despacho documentos concretos
de los formatos que faltan. **Caduca cada fase**: se vuelve a correr y se
vuelve a pegar en PLAN 2.

    .venv/bin/python scripts/inventario.py             escribe INVENTARIO.md
    .venv/bin/python scripts/inventario.py --stdout    lo imprime

ESCRIBE `INVENTARIO.md`, no imprime para copiar y pegar: un artefacto
generado viviendo dentro de un documento escrito a mano se queda obsoleto en
la primera fase que nadie lo regenere, y eso es lo que le paso mientras vivio
en PLAN 2.

Necesita los PDFs reales de `fixtures/real/`, que estan en `.gitignore` por
llevar datos de clientes. Los que falten salen declarados, no inventados.

NO deduce el emisor del nombre del fichero: sale del documento o va vacio.
Hoy solo los estados de cuenta lo traen (`MetaEstadoCuenta.banco`); ningun
parser contable lee de quien es el documento, y eso es en si un hallazgo
del inventario.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tests"))

from contapdf.cli import (  # noqa: E402
    DocumentoNoReconocido,
    ResultadoDocumento,
    codigo_de_salida,
    procesar_documento,
)

# El tipo que se le pide al sistema. Va explicito y no por heuristica: es lo
# que teclearia el operador, y una tabla se lee y se corrige.
TIPOS = {
    "balanza": "balanza", "balanza-businesspro": "balanza",
    "balanza-gume": "balanza", "balanza-fd": "balanza",
    "balanza-manufacturas": "balanza", "balanza-proactivity": "balanza",
    "poliza": "polizas", "diario-general": "polizas",
    "polizas-manufacturas": "polizas",
    "auxiliar": "auxiliar", "auxiliar-gume": "auxiliar",
    "auxiliar-manufacturas": "auxiliar",
    "mayor-gume": "mayor", "mayor-proactivity": "mayor",
    "mayor-manufacturas": "mayor", "mayor-fd": "mayor",
    "edocta": "estado-cuenta", "edocta-inbursa": "estado-cuenta",
    "edocta-multiva": "estado-cuenta", "edocta-santander": "estado-cuenta",
    "edocta-julio-banorte": "estado-cuenta",
    "edocta-abril-santander": "estado-cuenta",
    "edocta-bajio": "estado-cuenta", "edocta-bbva": "estado-cuenta",
    "edocta-hsbc": "estado-cuenta", "edocta-monex": "estado-cuenta",
    "edocta-scotiabank": "estado-cuenta",
}


@dataclass(frozen=True)
class FilaInventario:
    """Tabla A: un documento que produce Excel."""

    fixture: str
    tipo: str
    emisor: str
    paginas: int
    extraccion: str
    evaluados: int
    aplicables: int
    cuadran: int
    fallan: int
    no_verificables: int
    plantilla: str
    codigo: int

    @property
    def cobertura(self) -> str:
        """SIEMPRE las dos cifras. Un porcentaje solo es el `5/5` de BBVA."""
        return f"{self.evaluados} de {self.aplicables}"

    @property
    def reglas(self) -> str:
        return f"{self.cuadran}/{self.fallan}/{self.no_verificables}"


@dataclass(frozen=True)
class FilaRechazo:
    """Tabla B: un documento que el sistema no acepta, y por que."""

    fixture: str
    tipo_esperado: str
    motivo: str


_ANCHO_EMISOR = 38


def emisor_de(resultado: ResultadoDocumento) -> str:
    """De quien es el documento, SEGUN EL DOCUMENTO, sin recortar.

    Vacio cuando el sistema no lo lee, que hoy es en los cuatro tipos
    contables: ningun parser extrae la empresa. Deducirlo del nombre del
    fichero seria inventar un dato que el sistema no tiene.
    """
    meta = getattr(resultado.datos, "meta", None)
    return getattr(meta, "banco", "") if meta is not None else ""


def emisor_corto(emisor: str, ancho: int = _ANCHO_EMISOR) -> str:
    """Lo mismo, recortado para que quepa en la tabla.

    El recorte es de PRESENTACION y no arregla el dato: `MetaEstadoCuenta.
    banco` arrastra el domicilio del banco, y en Bajio arrastra ademas el
    TITULAR de la cuenta. La fila entera se guarda sin recortar; el que
    quiera el valor crudo lo tiene en `FilaInventario.emisor`.
    """
    limpio = " ".join(emisor.split())
    if len(limpio) <= ancho:
        return limpio
    return limpio[:ancho - 1].rstrip() + "…"


def estado_de_plantilla(resultado: ResultadoDocumento) -> str:
    if resultado.plantilla is None:
        return "no"
    if resultado.plantilla.pendiente_de_confirmacion:
        return "pendiente"
    return "reutilizada" if resultado.reutilizada else "aprendida"


def fila_de(fixture: str, resultado: ResultadoDocumento) -> FilaInventario:
    """De un `ResultadoDocumento` a su renglon. Puro: no abre nada."""
    cobertura = resultado.cobertura
    return FilaInventario(
        fixture=fixture, tipo=resultado.tipo, emisor=emisor_de(resultado),
        paginas=resultado.paginas, extraccion=resultado.estrategia,
        evaluados=cobertura.evaluados, aplicables=cobertura.aplicables,
        cuadran=cobertura.cuadran, fallan=cobertura.fallan,
        no_verificables=cobertura.no_verificables,
        plantilla=estado_de_plantilla(resultado),
        codigo=codigo_de_salida(cobertura))


_COLUMNAS_A = ("FIXTURE", "TIPO", "EMISOR", "PAG", "EXTRACCION", "COBERTURA",
               "REGLAS", "PLANTILLA", "COD")
_COLUMNAS_B = ("FIXTURE", "TIPO ESPERADO", "MOTIVO DEL RECHAZO")


def _celdas_a(fila: FilaInventario) -> tuple[str, ...]:
    return (fila.fixture, fila.tipo, emisor_corto(fila.emisor) or "—",
            str(fila.paginas), fila.extraccion, fila.cobertura, fila.reglas,
            fila.plantilla, str(fila.codigo))


def _celdas_b(fila: FilaRechazo) -> tuple[str, ...]:
    return (fila.fixture, fila.tipo_esperado, fila.motivo)


def tabla(columnas: Sequence[str], filas: Sequence[tuple[str, ...]], *,
          markdown: bool = False) -> str:
    """Las dos tablas se arman igual; solo cambia el adorno."""
    if markdown:
        cuerpo = ["| " + " | ".join(columnas) + " |",
                  "|" + "|".join("---" for _ in columnas) + "|"]
        cuerpo += ["| " + " | ".join(c.replace("|", "\\|") for c in f) + " |"
                   for f in filas]
        return "\n".join(cuerpo)
    anchos = [max(len(columnas[i]), *(len(f[i]) for f in filas)) if filas
              else len(columnas[i]) for i in range(len(columnas))]
    lineas = ["  ".join(c.ljust(a) for c, a in zip(columnas, anchos)).rstrip(),
              "  ".join("-" * a for a in anchos)]
    lineas += ["  ".join(c.ljust(a) for c, a in zip(f, anchos)).rstrip()
               for f in filas]
    return "\n".join(lineas)


def inventariar(nombres: Iterable[str], rutas: dict[str, Path], *,
                plantillas: Path | None = None
                ) -> tuple[list[FilaInventario], list[FilaRechazo],
                           list[FilaRechazo]]:
    """Recorre los fixtures. Devuelve (tabla A, tabla B, los que no estan).

    `plantillas` es un directorio de almacen. Sin el, la columna PLANTILLA
    sale «no» en todos y no dice nada: `procesar_documento` solo aprende un
    formato si recibe donde guardarlo. Con el, la columna responde a la
    pregunta que importa para el inventario -- si el sistema APRENDE ese
    formato o lo vuelve a detectar cada vez.
    """
    producen: list[FilaInventario] = []
    rechazados: list[FilaRechazo] = []
    ausentes: list[FilaRechazo] = []
    for nombre in nombres:
        tipo = TIPOS.get(nombre)
        ruta = rutas.get(nombre)
        if tipo is None:
            ausentes.append(FilaRechazo(nombre, "?", "no esta en TIPOS"))
            continue
        if ruta is None or not ruta.exists():
            ausentes.append(FilaRechazo(
                nombre, tipo, "el PDF no esta (fixtures/real/ va en .gitignore)"))
            continue
        try:
            resultado = procesar_documento(tipo, ruta, plantillas=plantillas,
                                           tenant_id="inventario")
        except DocumentoNoReconocido as exc:
            rechazados.append(FilaRechazo(nombre, tipo, str(exc)))
            continue
        producen.append(fila_de(nombre, resultado))
    producen.sort(key=lambda f: (f.tipo, f.fixture))
    rechazados.sort(key=lambda f: (f.tipo_esperado, f.fixture))
    return producen, rechazados, ausentes


def _commit() -> str:
    """El commit con el que se generó. Sin él no se sabe si caducó."""
    try:
        hecho = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                               cwd=RAIZ, capture_output=True, text=True,
                               timeout=10)
    except OSError:
        return "(sin git)"
    return hecho.stdout.strip() or "(sin git)"


def documento(producen: Sequence[FilaInventario],
              rechazados: Sequence[FilaRechazo],
              ausentes: Sequence[FilaRechazo], *,
              generado: str, commit: str) -> str:
    """El texto entero de INVENTARIO.md.

    Se le enseña al despacho, así que se lee solo: qué cubrimos, qué no, de
    cuándo es y cómo se rehace.
    """
    partes = [
        "# Inventario de cobertura",
        "",
        "Qué documentos cubre el sistema hoy, uno por línea. **Es un fichero",
        "generado**: no se edita a mano, se regenera.",
        "",
        f"    generado : {generado}",
        f"    commit   : {commit}",
        f"    fixtures : {len(producen) + len(rechazados) + len(ausentes)}",
        "",
        "```",
        ".venv/bin/python scripts/inventario.py",
        "```",
        "",
        "**Caduca en cuanto una fase cambia lo que un documento produce.** Si la",
        "fecha de arriba es vieja, esto no dice lo que el sistema hace hoy: hay",
        "que volver a correr el guion.",
        "",
        "`COBERTURA` son los casos **evaluados** de los **aplicables** que el",
        "documento entero contiene, y van siempre las dos cifras: un porcentaje",
        "sin denominador es la misma mentira que un «0 discrepancias».",
        "`REGLAS` es cuadran/fallan/no_verificables. `COD` es el código de salida",
        "del CLI: 0 cuadra, 1 hay discrepancias que revisar, 2 no se pudo",
        "procesar. `EMISOR` sale **del documento**, nunca del nombre del fichero;",
        "va vacío cuando el sistema no lo lee.",
        "",
        "---",
        "",
        f"## Producen Excel ({len(producen)})",
        "",
        tabla(_COLUMNAS_A, [_celdas_a(f) for f in producen], markdown=True),
        "",
        f"## No producen Excel ({len(rechazados)})",
        "",
        "El motivo es el que imprime el sistema. **Es una hipótesis del parser,",
        "no un hallazgo sobre el documento**: dice que no encontró el dato, no",
        "que el documento no lo tenga.",
        "",
        tabla(_COLUMNAS_B, [_celdas_b(f) for f in rechazados], markdown=True),
    ]
    if ausentes:
        partes += [
            "",
            f"## No se pudieron medir ({len(ausentes)})",
            "",
            tabla(_COLUMNAS_B, [_celdas_b(f) for f in ausentes], markdown=True),
        ]
    return "\n".join(partes) + "\n"


def escribir(destino: Path, producen: Sequence[FilaInventario],
             rechazados: Sequence[FilaRechazo],
             ausentes: Sequence[FilaRechazo], *,
             generado: str, commit: str) -> Path:
    destino.write_text(documento(producen, rechazados, ausentes,
                                 generado=generado, commit=commit),
                       encoding="utf-8")
    return destino


def main(argv: Sequence[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("-o", "--salida", type=Path,
                            default=RAIZ / "INVENTARIO.md",
                            help="dónde escribirlo (por defecto INVENTARIO.md)")
    analizador.add_argument("--stdout", action="store_true",
                            help="imprimirlo en vez de escribirlo")
    analizador.add_argument("fixtures", nargs="*",
                            help="por defecto, los 27")
    opciones = analizador.parse_args(argv)

    from conftest import REAL_PDFS  # noqa: PLC0415 -- solo con los reales

    nombres = opciones.fixtures or sorted(REAL_PDFS)
    with tempfile.TemporaryDirectory(prefix="inventario-") as almacen:
        producen, rechazados, ausentes = inventariar(
            nombres, REAL_PDFS, plantillas=Path(almacen))

    texto = documento(producen, rechazados, ausentes,
                      generado=datetime.now().strftime("%Y-%m-%d %H:%M"),
                      commit=_commit())
    if opciones.stdout:
        print(texto, end="")
        return 0
    opciones.salida.write_text(texto, encoding="utf-8")
    print(f"escrito {opciones.salida}: {len(producen)} producen Excel, "
          f"{len(rechazados)} no"
          + (f", {len(ausentes)} sin medir" if ausentes else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
