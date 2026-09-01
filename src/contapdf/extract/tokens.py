"""Separacion de tokens que el PDF entrega pegados.

Banorte imprime la fecha del movimiento sin separador ni columna propia:
'01-JUL-23DEP.EFECTIVO' es una sola palabra que son dos datos. No hay
hueco horizontal ni corrida distinta que los separe, asi que la unica
señal disponible es la forma del prefijo.

Se parte solo cuando el prefijo ES una fecha completa y queda algo
despues: un token que ya es solo la fecha, o que solo se le parece, sale
intacto.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from contapdf.ir import Word

# dd-MMM-aa seguido de algo que no es separador: '01-JUL-23DEP.EFECTIVO'.
_MES = r"[A-Za-zÁÉÍÓÚÑ]{3}"
_RE_FECHA_SOLA = re.compile(rf"^\d{{1,2}}-{_MES}-(\d{{2}}|\d{{4}})$")
# Cola que empieza con algo que no es digito JUSTO DESPUES de un anio de
# largo posible: ahi el anio no es ambiguo porque los digitos se acaban
# donde empieza la descripcion. La corrida de digitos tiene que medir 2 o 4;
# con '\d+' suelto, '11-JUL-2320230711400140BET...' se leia como un anio de
# dieciseis digitos y contaminaba lo aprendido para toda la pagina.
_RE_INEQUIVOCA = re.compile(rf"^\d{{1,2}}-{_MES}-(\d{{2}}|\d{{4}})\D")


def _ancho_del_anio(words: Sequence[Word]) -> int | None:
    """Cuantos digitos usa el anio, segun lo que el documento deja ver.

    Hace falta porque desde un token pegado a numeros no se puede saber:
    '03-JUL-23085901...' se parte en '03-JUL-23' o en '03-JUL-2308' segun
    el anio sea de dos o de cuatro digitos, y las dos dejan cola.

    Se aprende de los tokens donde SI es inequivoco: una fecha suelta, o
    una pegada a texto ('01-JUL-23DEP.EFECTIVO'). Banorte no imprime ni
    una sola fecha suelta, asi que los pegados a texto son la unica
    fuente. Si el documento no da ninguna, no se parte nada.
    """
    anchos: set[int] = set()
    for word in words:
        sola = _RE_FECHA_SOLA.match(word.text)
        if sola:
            anchos.add(len(sola.group(1)))
            continue
        clara = _RE_INEQUIVOCA.match(word.text)
        if clara:
            anchos.add(len(clara.group(1)))
    return anchos.pop() if len(anchos) == 1 else None


def separar_fecha_pegada(words: Sequence[Word]) -> tuple[Word, ...]:
    """Parte los tokens que traen la fecha pegada a la descripcion.

    El ancho se reparte por numero de caracteres. Es una aproximacion, pero
    solo se usa para asignar columna y las dos partes caen del mismo lado
    de la frontera de todos modos.
    """
    ancho = _ancho_del_anio(words)
    if ancho is None:
        return tuple(words)  # sin fecha suelta no hay de donde aprender
    pegada = re.compile(rf"^(\d{{1,2}}-{_MES}-\d{{{ancho}}})(\S.*)$")

    salida: list[Word] = []
    for word in words:
        encontrado = pegada.match(word.text)
        if encontrado is None:
            salida.append(word)
            continue
        fecha, cola = encontrado.group(1), encontrado.group(2)
        ancho = word.x1 - word.x0
        corte = word.x0 + ancho * len(fecha) / len(word.text)
        salida.append(Word(text=fecha, x0=word.x0, x1=corte, top=word.top,
                           bottom=word.bottom, size=word.size, bold=word.bold,
                           page=word.page, run=word.run))
        salida.append(Word(text=cola, x0=corte, x1=word.x1, top=word.top,
                           bottom=word.bottom, size=word.size, bold=word.bold,
                           page=word.page, run=word.run))
    return tuple(salida)
