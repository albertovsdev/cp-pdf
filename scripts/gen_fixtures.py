#!/usr/bin/env python3
"""Genera los fixtures sinteticos de la balanza.

    python scripts/gen_fixtures.py [-o RAIZ]

Escribe fixtures/synthetic/balanza_sintetica.json, su gemelo descuadrado y
fixtures/golden/balanza_sintetica.csv.

Por que sinteticos: los fixtures de fixtures/layouts/ traen los montos
enmascarados como 99,999.99. Su GEOMETRIA es real, pero su ARITMETICA no
significa nada, asi que no sirven para probar el validador. Estos copian
las coordenadas reales de balanza.layout.json y les ponen numeros
inventados que SI cuadran contablemente: partida doble completa, cuentas
padre que suman exacto sus hijas, un saldo acreedor, un monto negativo y
un nombre de cuenta partido en dos renglones.

El gemelo descuadrado altera SOLO el saldo final deudor de una hoja. Es
deliberado: la jerarquia y los totales miran debe/haber, asi que la
discrepancia queda aislada en una fila y se puede afirmar que el validador
reporta exactamente esa.

Es un script de una sola corrida, no forma parte del nucleo. Aun asi no
usa estado global mutable ni lee el entorno: la raiz de salida entra por
parametro.
"""
from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path

D = Decimal
ANCHO = 3.11          # pt por caracter a size 6 (medido en el fixture real)
X_CUENTA, X_NAT, X_NOMBRE = 26.0, 82.7, 128.0
X1 = {"ini_d": 287.0, "ini_a": 343.6, "debe": 400.3,
      "haber": 457.0, "fin_d": 513.6, "fin_a": 570.3}
PITCH, ALTO = 10.5, 6.0

# cuenta, nat, nombre, ini_d, ini_a, debe, haber, fin_d, fin_a
FILAS = [
    ("101",          "D", "Caja",                    "10000.00","0.00","5000.00","1250.25","13749.75","0.00"),
    ("101-01",       "D", "Caja chica",               "4000.00","0.00","2000.00","1250.25","4749.75","0.00"),
    ("101-02",       "D", "Caja general",             "6000.00","0.00","3000.00","0.00","9000.00","0.00"),
    ("102",          "D", "Bancos",                 "250000.00","0.00","150000.00","70500.75","329499.25","0.00"),
    ("102-01",       "D", "Banco del Centro",       "200500.00","0.00","150000.00","61750.25","288749.75","0.00"),
    ("102-01-0001",  "D", "Cuenta de cheques moneda nacional", "200000.00","0.00","150000.00","60000.00","290000.00","0.00"),
    ("102-01-0002",  "D", "Cuenta de inversion",       "500.00","0.00","0.00","1750.25","-1250.25","0.00"),
    ("102-02",       "D", "Banco del Norte",        "49500.00","0.00","0.00","8750.50","40749.50","0.00"),
    ("201",          "A", "Proveedores",             "0.00","60000.00","40000.00","8000.00","0.00","28000.00"),
    ("201-01",       "A", "Proveedores nacionales",  "0.00","45000.00","30000.00","5000.00","0.00","20000.00"),
    ("201-02",       "A", "Proveedores extranjeros", "0.00","15000.00","10000.00","3000.00","0.00","8000.00"),
    ("301",          "A", "Capital social",          "0.00","200000.00","0.00","0.00","0.00","200000.00"),
    ("401",          "A", "Ventas",                  "0.00","0.00","0.00","150000.00","0.00","150000.00"),
    ("601",          "D", "Gastos generales",        "0.00","0.00","34751.00","0.00","34751.00","0.00"),
    ("601-01",       "D", "Servicios",               "0.00","0.00","25500.75","0.00","25500.75","0.00"),
    ("601-02",       "D", "Papeleria",               "0.00","0.00","9250.25","0.00","9250.25","0.00"),
]
CORTE = 8                       # filas en la pagina 1
PARTIDA = "102-01-0001"         # su nombre se parte en dos renglones
TOTALES = ("229751.00", "229751.00")
# (cuenta, indice del campo, valor roto): saldo final deudor +100.00
DESCUADRE = ("102-02", 7, "40849.50")


def fmt(v: str) -> str:
    d = D(v)
    return f"{d:,.2f}"


def w(text, x0, top, size=6.0, bold=True, page=1, x1=None):
    return {"text": text, "x0": round(x0, 1),
            "x1": round(x1 if x1 is not None else x0 + len(text) * ANCHO, 1),
            "top": round(top, 1), "bottom": round(top + (size if size > 6 else ALTO), 1),
            "size": size, "bold": bold, "page": page}


def right(text, x1, top, page):
    return w(text, x1 - len(text) * ANCHO, top, page=page, x1=x1)


def encabezado(words, y0, page):
    y1 = y0 + 6.5
    for txt, x in (("No.", 26.0), ("Cuenta", 37.0), ("Naturaleza", 82.7),
                   ("Cuenta", 128.0)):
        words.append(w(txt, x, y0, page=page))
    for txt, x1 in (("Saldo", 268.0), ("Inicial", 287.0)):
        words.append(right(txt, x1, y0, page))
    for txt, x1 in (("Saldo", 325.0), ("Inicial", 343.6)):
        words.append(right(txt, x1, y0, page))
    words.append(right("Debe", 400.3, y0, page))
    words.append(right("Haber", 457.0, y0, page))
    for txt, x1 in (("Saldo", 498.0), ("Final", 513.6)):
        words.append(right(txt, x1, y0, page))
    for txt, x1 in (("Saldo", 555.0), ("Final", 570.3)):
        words.append(right(txt, x1, y0, page))
    words.append(right("Deudor", 287.0, y1, page))
    words.append(right("Acreedor", 343.6, y1, page))
    words.append(right("Deudor", 513.6, y1, page))
    words.append(right("Acreedor", 570.3, y1, page))
    return y1 + PITCH


def fila(words, f, y, page, partir=False):
    cuenta, nat, nombre, *montos = f
    words.append(w(cuenta, X_CUENTA, y, page=page))
    words.append(w(nat, X_NAT, y, page=page))
    trozos = nombre.split()
    if partir:
        cabeza, cola = trozos[:3], trozos[3:]
    else:
        cabeza, cola = trozos, []
    x = X_NOMBRE
    for t in cabeza:
        palabra = w(t, x, y, page=page)
        words.append(palabra)
        x = palabra["x1"] + 1.7
    for clave, valor in zip(("ini_d", "ini_a", "debe", "haber", "fin_d", "fin_a"), montos):
        words.append(right(fmt(valor), X1[clave], y, page))
    if cola:
        x = X_NOMBRE
        for t in cola:
            palabra = w(t, x, y + 6.5, page=page)
            words.append(palabra)
            x = palabra["x1"] + 1.7
        return y + 6.5 + PITCH
    return y + PITCH


def construir(filas, descuadre=None):
    paginas = []
    for page, bloque in ((1, filas[:CORTE]), (2, filas[CORTE:])):
        words = []
        if page == 1:
            for txt, x, y, s in (("EMPRESA", 20.0, 47.9, 12.0),
                                 ("DEMO", 102.8, 47.9, 12.0),
                                 ("SA DE CV", 130.3, 47.9, 12.0),
                                 ("BALANZA DE COMPROBACION", 414.0, 47.9, 12.0),
                                 ("DEM010101ABC", 20.0, 64.2, 8.0),
                                 ("Fecha de impresion: 31/01/2026", 451.0, 64.2, 8.0),
                                 ("Tipo Moneda", 28.0, 111.6, 8.0),
                                 ("Periodo", 311.0, 111.6, 8.0),
                                 ("MXN", 28.0, 124.1, 8.0),
                                 ("01-01-2026 - 31-01-2026", 311.0, 124.1, 8.0)):
                for i, t in enumerate(txt.split()):
                    words.append(w(t, x + i * 30, y, size=s, page=1))
            y = encabezado(words, 172.8, 1)
        else:
            y = encabezado(words, 39.8, 2)
        for f in bloque:
            if descuadre and f[0] == descuadre[0]:
                f = f[:descuadre[1]] + (descuadre[2],) + f[descuadre[1] + 1:]
            y = fila(words, f, y, page, partir=(f[0] == PARTIDA))
        if page == 2:
            words.append(w("Totales", X_NOMBRE, y, page=2))
            words.append(right(fmt(TOTALES[0]), X1["debe"], y, 2))
            words.append(right(fmt(TOTALES[1]), X1["haber"], y, 2))
            for i, t in enumerate(("Pagina", "2", "de", "2")):
                words.append(w(t, 273.0 + i * 12, 805.4, size=8.0, page=2))
        paginas.append({"page": page, "width": 595.3, "height": 841.9,
                        "has_text_layer": True, "ruling_lines": 10, "rects": 0,
                        "words": words})
    return {"source_pages_total": 2, "pages_sampled": [1, 2],
            "mask_mode": "synthetic", "salted": False, "pages": paginas}


def escribir(raiz: Path) -> list[Path]:
    sinteticos = raiz / "synthetic"
    golden = raiz / "golden"
    sinteticos.mkdir(parents=True, exist_ok=True)
    golden.mkdir(parents=True, exist_ok=True)

    cuadrada = sinteticos / "balanza_sintetica.json"
    cuadrada.write_text(json.dumps(construir(FILAS), ensure_ascii=False, indent=1),
                        encoding="utf-8")

    descuadrada = sinteticos / "balanza_descuadrada.json"
    descuadrada.write_text(
        json.dumps(construir(FILAS, descuadre=DESCUADRE), ensure_ascii=False, indent=1),
        encoding="utf-8")

    csv_path = golden / "balanza_sintetica.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        escritor = csv.writer(fh)
        escritor.writerow(["cuenta", "nivel", "cuenta_padre", "naturaleza", "nombre",
                           "saldo_ini_deudor", "saldo_ini_acreedor", "debe", "haber",
                           "saldo_fin_deudor", "saldo_fin_acreedor"])
        for cuenta, nat, nombre, *montos in FILAS:
            partes = cuenta.split("-")
            escritor.writerow([cuenta, len(partes),
                               "-".join(partes[:-1]) if len(partes) > 1 else "",
                               nat, nombre] + [f"{D(m):.2f}" for m in montos])
    return [cuadrada, descuadrada, csv_path]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, default=Path("fixtures"),
                    help="raiz de fixtures (default: fixtures)")
    args = ap.parse_args()
    for path in escribir(args.out):
        print(f"OK -> {path}")


if __name__ == "__main__":
    main()
