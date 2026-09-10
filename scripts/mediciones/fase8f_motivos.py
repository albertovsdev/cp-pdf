"""Fase 8f, objetivo 2: todos los `falla` y `no_verificable`, por MOTIVO.

Agrupa por motivo distinto y no por caso: la pregunta no es cuantas reglas
no cuadran, sino cuantas EXPLICACIONES distintas da el sistema. Cada una hay
que ir a comprobarla contra el documento, porque el motivo que imprime el
sistema es una HIPOTESIS -- «ninguna cuenta trae el resumen completo»
significa que el parser no lo encontro, no que el documento no lo tenga.

El unico motivo verificado contra el documento hasta hoy es el de BBVA
(fase 7g). Los demas nunca se comprobaron.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tests"))
sys.path.insert(0, str(RAIZ / "scripts"))

from conftest import REAL_PDFS  # noqa: E402
from inventario import TIPOS  # noqa: E402

from contapdf.cli import DocumentoNoReconocido, procesar_documento  # noqa: E402
from contapdf.validate.rules import CUADRA  # noqa: E402

# Los motivos llevan cifras del documento. Para agrupar «6 de 8 CFDI sin
# numero» con «53 de 1942 CFDI sin numero» hay que quitarlas: son el MISMO
# motivo con distinto tamano.
_NUMERO = re.compile(r"\d[\d,\.]*")
_LISTA = re.compile(r":\s*[^;]+$")


def plantilla_de(motivo: str) -> str:
    plano = _NUMERO.sub("N", motivo)
    return _LISTA.sub(": …", plano).strip()


def main() -> int:
    porfamilia: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    rechazos: dict[str, list[str]] = defaultdict(list)
    total_reglas = no_cuadran = 0

    for nombre in sorted(REAL_PDFS):
        tipo = TIPOS.get(nombre)
        ruta = REAL_PDFS.get(nombre)
        if tipo is None or ruta is None or not ruta.exists():
            continue
        try:
            resultado = procesar_documento(tipo, ruta, tenant_id="motivos")
        except DocumentoNoReconocido as exc:
            rechazos[plantilla_de(str(exc))].append(nombre)
            continue
        for regla in resultado.cobertura.reglas:
            total_reglas += 1
            if regla.estado == CUADRA:
                continue
            no_cuadran += 1
            clave = (regla.estado, plantilla_de(regla.motivo) or "(SIN MOTIVO)")
            porfamilia[clave].append(
                (nombre, regla.regla,
                 f"{regla.evaluados} de {regla.aplicables}"
                 + (f", {len(regla.discrepancias)} con diferencia"
                    if regla.discrepancias else "")))

    print("=" * 78)
    print("MOTIVOS DISTINTOS de las reglas que NO cuadran")
    print("=" * 78)
    print(f"reglas evaluadas en los 27 fixtures: {total_reglas}")
    print(f"de esas, no cuadran: {no_cuadran}")
    print(f"MOTIVOS DISTINTOS: {len(porfamilia)}")
    print()
    for indice, (clave, casos) in enumerate(
            sorted(porfamilia.items(), key=lambda kv: (-len(kv[1]), kv[0])), 1):
        estado, motivo = clave
        print(f"--- M{indice:02d}  [{estado}]  {len(casos)} caso(s) ---")
        print(f"    motivo: {motivo}")
        for documento, regla, cifras in casos:
            print(f"      {documento:24} {regla:22} {cifras}")
        print()

    print("=" * 78)
    print("MOTIVOS DE RECHAZO (los que no producen Excel)")
    print("=" * 78)
    print(f"MOTIVOS DISTINTOS: {len(rechazos)}")
    print()
    for indice, (motivo, docs) in enumerate(
            sorted(rechazos.items(), key=lambda kv: (-len(kv[1]), kv[0])), 1):
        print(f"--- R{indice:02d}  {len(docs)} documento(s) ---")
        print(f"    motivo: {motivo}")
        print(f"      {', '.join(docs)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
