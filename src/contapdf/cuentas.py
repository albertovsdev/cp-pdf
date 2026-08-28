"""Numeros de cuenta contable: esquema, jerarquia y forma canonica.

Cada reporte imprime el mismo catalogo a su manera. La misma cuenta es
`1120-001-001` en el libro mayor y `112000100100000000003` en la balanza:
los cortes de segmento no coinciden pero la cadena de digitos si. De ahi
salen las dos cosas de este modulo: deducir la jerarquia con el esquema del
formato, y reducir cualquier renderizado a una clave comparable.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

_RE_NO_DIGITO = re.compile(r"\D")
ANCHO_CANONICO = 18
_MAX_NIVELES = 9


@dataclass(frozen=True)
class EsquemaCuenta:
    """Como se lee el numero de cuenta de un formato.

    'separador' vacio significa que el catalogo no usa separadores y la
    jerarquia se lee del marcador. 'anchos' son los digitos significativos
    de cada nivel; 'marcador' es el rango (inicio, fin) donde el documento
    declara el nivel.
    """

    separador: str = "-"
    anchos: tuple[int, ...] = ()
    marcador: tuple[int, int] | None = None
    largo: int = 0


def _sufijo_es_marcador(cuentas: Sequence[str], ancho: int = 3) -> bool:
    """True si los ultimos digitos declaran el nivel.

    Son pocos valores, empiezan en 1 y no dejan huecos. Con cientos de
    cuentas eso no pasa por casualidad.
    """
    sufijos = {c[-ancho:] for c in cuentas}
    if not 2 <= len(sufijos) <= _MAX_NIVELES:
        return False
    try:
        valores = sorted(int(s) for s in sufijos)
    except ValueError:
        return False
    return valores == list(range(1, len(valores) + 1))


def _anchos_por_nivel(cuentas: Sequence[str], marcador: tuple[int, int]
                      ) -> tuple[int, ...]:
    """Cuantos digitos usa cada nivel, medidos sobre las cuentas mismas.

    El ancho de un nivel es la ultima posicion con un digito distinto de
    cero en alguna de sus cuentas. Da lo mismo que contar grupos: los
    digitos intermedios son ceros en ese nivel, asi que truncar antes o
    despues reconstruye el mismo padre.
    """
    inicio, _ = marcador
    por_nivel: dict[int, int] = {}
    for cuenta in cuentas:
        nivel = int(cuenta[marcador[0]:marcador[1]])
        cuerpo = cuenta[:inicio]
        ultimo = max((i for i, d in enumerate(cuerpo) if d != "0"), default=0)
        por_nivel[nivel] = max(por_nivel.get(nivel, 1), ultimo + 1)

    anchos: list[int] = []
    for nivel in range(1, max(por_nivel, default=0) + 1):
        ancho = por_nivel.get(nivel, 0)
        if anchos:
            ancho = max(ancho, anchos[-1] + 1)  # el ancho crece con el nivel
        anchos.append(ancho)
    return tuple(anchos)


def inferir_esquema(cuentas: Sequence[str]) -> EsquemaCuenta:
    """Deduce el esquema de un catalogo a partir de las cuentas observadas."""
    cuentas = [c for c in cuentas if c]
    if not cuentas:
        return EsquemaCuenta()
    if any("-" in c for c in cuentas):
        return EsquemaCuenta(separador="-")

    largos = {len(c) for c in cuentas}
    if len(largos) != 1 or not all(c.isdigit() for c in cuentas):
        return EsquemaCuenta(separador="")

    largo = largos.pop()
    if largo <= 3 or not _sufijo_es_marcador(cuentas):
        return EsquemaCuenta(separador="", largo=largo)

    marcador = (largo - 3, largo)
    return EsquemaCuenta(separador="", anchos=_anchos_por_nivel(cuentas, marcador),
                         marcador=marcador, largo=largo)


def _significativos(cuenta: str) -> tuple[list[str], int]:
    """Segmentos y cuantos son significativos, para catalogos con separador.

    Hay catalogos que rellenan a lo ancho: 0400-0001-0000-0000 es de nivel
    2, no de nivel 4. Los segmentos finales todo-ceros son relleno.
    """
    partes = cuenta.split("-")
    fin = len(partes)
    while fin > 1 and set(partes[fin - 1]) == {"0"}:
        fin -= 1
    return partes, fin


def nivel_y_padre(cuenta: str, esquema: EsquemaCuenta | None = None
                  ) -> tuple[int, str]:
    """Nivel jerarquico de la cuenta y el numero de su cuenta padre."""
    esquema = esquema or EsquemaCuenta()

    if esquema.marcador is not None:
        inicio, fin = esquema.marcador
        nivel = int(cuenta[inicio:fin])
        if nivel <= 1 or nivel > len(esquema.anchos):
            return max(nivel, 1), ""
        ancho = esquema.anchos[nivel - 2]
        cuerpo = cuenta[:inicio][:ancho].ljust(inicio, "0")
        return nivel, f"{cuerpo}{nivel - 1:0{fin - inicio}d}"

    partes, fin = _significativos(cuenta)
    if fin <= 1:
        return 1, ""
    cabeza = partes[:fin - 1]
    if fin == len(partes):
        return fin, "-".join(cabeza)  # sin relleno: el padre es el prefijo
    relleno = ["0" * len(p) for p in partes[fin - 1:]]
    return fin, "-".join(cabeza + relleno)


def canonizar(texto: str, *, ancho: int = ANCHO_CANONICO) -> str:
    """Clave comparable entre reportes: solo digitos, rellenada a la derecha.

    Verificado sobre el catalogo GUME: cruzan 49/49 las cuentas del libro
    mayor y 7/7 las del auxiliar contra las 734 de la balanza, y las 734
    canonicas siguen siendo distintas.
    """
    digitos = _RE_NO_DIGITO.sub("", texto)
    return digitos[:ancho].ljust(ancho, "0")


def canonizar_cuenta(cuenta: str, esquema: EsquemaCuenta | None = None, *,
                     ancho: int = ANCHO_CANONICO) -> str:
    """Como canonizar, pero quitando antes el marcador de nivel.

    Si no se quita, las cuentas de un formato con marcador no alinean con
    las del mismo catalogo impreso por otro reporte.
    """
    esquema = esquema or EsquemaCuenta()
    if esquema.marcador is not None:
        inicio, fin = esquema.marcador
        cuenta = cuenta[:inicio] + cuenta[fin:]
    return canonizar(cuenta, ancho=ancho)
