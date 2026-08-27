#!/usr/bin/env python3
"""
dump_layout.py v2 — Extrae la ESTRUCTURA de un PDF contable sin exponer datos.

Corre 100% local. El PDF original nunca sale de tu maquina.

CAMBIOS v1 -> v2
  1. Deteccion de columnas por BORDE DERECHO (x1) para montos y por borde
     izquierdo (x0) para texto. En v1 todo se agrupaba por x0, lo que hacia
     que cada monto de distinta longitud pareciera una columna distinta.
  2. Pseudonimos con SAL secreta, para que un RFC no se pueda recuperar
     probando RFCs hasta que el hash coincida.
  3. Encabezados multilinea ("Saldo Inicial" arriba / "Deudor" abajo) se
     fusionan por solape horizontal con la columna detectada.
  4. El diagnostico ya no miente: reporta el numero real de columnas.

Uso:
    export CONTAPDF_SALT="una-frase-secreta-tuya-que-no-compartes"
    python scripts/dump_layout.py fixtures/real/balanza.pdf \\
        -o fixtures/layouts --preview
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path


# --- Vocabulario que NUNCA se enmascara ---------------------------------
WHITELIST = {
    "no", "cuenta", "naturaleza", "saldo", "inicial", "final", "deudor",
    "acreedor", "debe", "haber", "folio", "fecha", "tipo", "documento",
    "tercero", "descripcion", "descripción", "referencia", "depositos",
    "depósitos", "retiros", "dia", "día", "concepto", "importe", "moneda",
    "periodo", "período", "pagina", "página", "de", "al", "hasta", "desde",
    "totales", "total", "subtotal", "movimiento", "conciliado", "poliza",
    "póliza", "polizas", "pólizas", "auxiliar", "cuentas", "balanza",
    "comprobacion", "comprobación", "impreso", "estado", "corte",
    "notas", "adicionales", "asociados", "la", "a", "y", "en", "del",
    "impresion", "impresión", "mxn", "usd", "contable", "banco", "sucursal",
    "telefono", "teléfono", "clave", "bancaria", "estandar", "estándar",
    "numero", "número", "informacion", "información", "general", "resumen",
    "comisiones", "detalle", "operaciones", "promedio", "diario", "minimo",
    "mínimo", "requerido", "cheques", "girados", "exentos", "ganancia",
    "anual", "nominal", "real", "tasa", "interes", "interés", "ordinaria",
    "rendimiento", "cobradas", "otras", "iva", "sobre", "libro", "ingreso",
    "egreso", "venta", "compra", "cfdi", "uuid", "rfc",
}

RE_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$", re.I)
RE_UUID = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-?[0-9A-F]{0,12}$", re.I)
RE_CLABE = re.compile(r"^\d{16,20}$")
RE_NUMERIC = re.compile(r"^[\d.,\-$()%/:]+$")
# Cuenta contable: base de EXACTAMENTE 3 digitos, con o sin subcuentas.
# Es deliberadamente estrecho. Con base de 4 digitos entraban fechas
# (2025-05-03) y folios (8140), y ambos se filtraban sin enmascarar.
# Si una empresa usa cuentas de 4 digitos, se enmascaran de mas: se pierde
# legibilidad pero NO se filtra nada. Ese es el lado correcto donde fallar.
RE_CUENTA = re.compile(r"^\d{3}(-\d{1,6})*$")
RE_LETTER = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")

# La sal hace que el pseudonimo no sea reversible por fuerza bruta.
# Guardala fuera del repo. Si la pierdes, los pseudonimos viejos y nuevos
# dejan de coincidir (no es grave: solo regeneras los fixtures).
SALT = os.environ.get("CONTAPDF_SALT", "fiscalizacion")


@dataclass
class Column:
    """Una columna detectada en la tabla."""
    index: int
    align: str        # 'left' | 'right'
    anchor: float     # x0 si es left, x1 si es right
    x_min: float      # extension real observada
    x_max: float
    support: int      # cuantas palabras la sustentan
    header: str = ""  # etiqueta fusionada del encabezado


def _stable_id(text: str, prefix: str, length: int = 6) -> str:
    """Mismo texto -> mismo pseudonimo. Con sal, no reversible."""
    digest = hashlib.sha256((SALT + "|" + text.upper()).encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:length].upper()}"


def mask_token(text: str, mode: str) -> str:
    """Enmascara un token preservando su forma (longitud y separadores)."""
    if mode == "none":
        return text

    stripped = text.strip()
    if not stripped:
        return text

    if mode == "values":
        if stripped.lower().strip(".:,()") in WHITELIST:
            return text
        if RE_CUENTA.match(stripped):   # 100-01 no es PII, es estructural
            return text

    if RE_RFC.match(stripped):
        return _stable_id(stripped, "RFC", 9)
    if RE_UUID.match(stripped):
        return _stable_id(stripped, "UUID-", 12)
    if RE_CLABE.match(stripped):
        return _stable_id(stripped, "CLB", 14)
    if RE_NUMERIC.match(stripped):
        return re.sub(r"\d", "9", text)

    # Texto libre o token mixto (CUENTA:07265001095611, MAR.07761716).
    # CRITICO: hay que enmascarar letras Y digitos. Sustituir solo las
    # letras deja intactos numeros de cuenta, folios y referencias, que es
    # justo lo identificable.
    def _sub(m: re.Match) -> str:
        ch = m.group(0)
        if ch.isdigit():
            return "9"
        return "X" if ch.isupper() else "x"

    return re.sub(r"[0-9]|" + RE_LETTER.pattern, _sub, text)


def cluster_1d(values: list[float], tol: float = 3.0) -> list[list[float]]:
    """Agrupa numeros cercanos entre si (clustering aglomerativo simple).

    Recorre los valores ordenados y corta el grupo cuando el hueco con el
    siguiente supera la tolerancia. Es todo lo que se necesita aqui: las
    columnas de un PDF estan bien separadas entre si.
    """
    if not values:
        return []
    ordered = sorted(values)
    groups: list[list[float]] = [[ordered[0]]]
    for v in ordered[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return groups


RE_FECHA = re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$")


def is_numeric(text: str) -> bool:
    """True solo para MONTOS (alineados a la derecha).

    Los numeros de cuenta (100-01) y las fechas (01-01-2025) tambien son
    "numericos" pero van alineados a la IZQUIERDA. Si se tratan como montos,
    su borde derecho varia con la longitud y su columna nunca se detecta.
    """
    s = text.strip()
    if not s or not any(c.isdigit() for c in s):
        return False
    if RE_CUENTA.match(s) or RE_FECHA.match(s):
        return False
    return bool(RE_NUMERIC.match(s))


def detect_columns(words: list[dict], tol: float = 3.0,
                   min_support: int = 3) -> list[Column]:
    """Detecta columnas separando por tipo de alineacion.

    Clave del asunto: en estos PDFs los montos van alineados a la DERECHA,
    asi que lo que comparten es x1, no x0. Los textos van a la izquierda y
    comparten x0. Agrupar todo por x0 produce decenas de falsas columnas.
    """
    numeric = [w for w in words if is_numeric(w["text"])]
    textual = [w for w in words if not is_numeric(w["text"])]

    cols: list[Column] = []

    for group in cluster_1d([w["x1"] for w in numeric], tol):
        if len(group) < min_support:
            continue
        anchor = sum(group) / len(group)
        members = [w for w in numeric if abs(w["x1"] - anchor) <= tol * 2]
        if not members:
            continue
        cols.append(Column(
            index=0, align="right", anchor=round(anchor, 1),
            x_min=round(min(w["x0"] for w in members), 1),
            x_max=round(max(w["x1"] for w in members), 1),
            support=len(group),
        ))

    for group in cluster_1d([w["x0"] for w in textual], tol):
        if len(group) < min_support:
            continue
        anchor = sum(group) / len(group)
        members = [w for w in textual if abs(w["x0"] - anchor) <= tol * 2]
        if not members:
            continue
        cols.append(Column(
            index=0, align="left", anchor=round(anchor, 1),
            x_min=round(min(w["x0"] for w in members), 1),
            x_max=round(max(w["x1"] for w in members), 1),
            support=len(group),
        ))

    # Las columnas reales tienen una palabra por renglon, asi que su soporte
    # es parecido entre si. Los textos sueltos de encabezado o metadatos (que
    # estan ARRIBA de la tabla) generan columnas con soporte muy bajo.
    # Se descartan comparando contra la mediana, no contra un numero fijo,
    # para que el umbral se adapte a documentos de 5 o de 500 renglones.
    if cols:
        sup = sorted(c.support for c in cols)
        median = sup[len(sup) // 2]
        floor = max(min_support, median * 0.25)
        cols = [c for c in cols if c.support >= floor]

    cols.sort(key=lambda c: c.x_min)
    for i, c in enumerate(cols):
        c.index = i
    return cols


def merge_columns_by_overlap(cols: list[Column]) -> list[Column]:
    """Funde columnas de texto cuyas extensiones se traslapan.

    Pasa cuando una columna de texto ancha (ej. nombre de cuenta) genera
    varios anclajes por indentacion jerarquica. Si se traslapan, es una sola.
    """
    if not cols:
        return []
    merged = [cols[0]]
    for c in cols[1:]:
        prev = merged[-1]
        # Se traslapan horizontalmente -> es una sola columna partida.
        # Pasa cuando parte de los valores se clasifico con otra alineacion
        # (ej. cuentas con formato raro leidas como montos).
        if c.x_min < prev.x_max:
            if c.support > prev.support:
                prev.align = c.align
            prev.x_min = min(prev.x_min, c.x_min)
            prev.x_max = max(prev.x_max, c.x_max)
            prev.support += c.support
        else:
            merged.append(c)
    for i, c in enumerate(merged):
        c.index = i
    return merged


def group_into_lines(words: list[dict], tolerance: float = 2.5) -> list[list[dict]]:
    """Agrupa palabras en renglones por SOLAPAMIENTO vertical.

    Agrupar solo por 'top' falla en tablas con celdas altas: cuando el
    importe esta centrado verticalmente y la etiqueta pegada arriba, ambos
    pertenecen al mismo renglon logico pero sus 'top' difieren varios puntos.

    Criterio: una palabra entra al renglon si su CENTRO vertical cae dentro
    del alto acumulado del renglon (mas la tolerancia). Es mas permisivo que
    comparar 'top' pero no se traga la fila siguiente, porque el centro de
    una fila distinta queda fuera del rango.
    """
    ordered = sorted(words, key=lambda x: (x["top"], x["x0"]))
    lines: list[list[dict]] = []
    spans: list[tuple[float, float]] = []   # (top, bottom) por renglon

    for w in ordered:
        center = (w["top"] + w["bottom"]) / 2
        placed = False
        # Solo se revisan los ultimos renglones: la lista viene ordenada.
        for i in range(len(lines) - 1, max(-1, len(lines) - 4), -1):
            top, bottom = spans[i]
            if top - tolerance <= center <= bottom + tolerance:
                lines[i].append(w)
                spans[i] = (min(top, w["top"]), max(bottom, w["bottom"]))
                placed = True
                break
        if not placed:
            lines.append([w])
            spans.append((w["top"], w["bottom"]))

    return [sorted(ln, key=lambda x: x["x0"]) for ln in lines]


def find_header_lines(lines: list[list[dict]], max_lines: int = 4) -> list[int]:
    """Localiza los renglones de encabezado.

    Heuristica: el encabezado es el bloque de renglones SIN numeros que
    aparece justo antes del primer renglon que si tiene 3 o mas numeros.
    """
    first_data = None
    for i, line in enumerate(lines):
        if sum(1 for w in line if is_numeric(w["text"])) >= 3:
            first_data = i
            break
    if first_data is None:
        return []

    header: list[int] = []
    for i in range(first_data - 1, max(-1, first_data - 1 - max_lines), -1):
        if any(is_numeric(w["text"]) for w in lines[i]):
            break
        if len(lines[i]) < 2:
            break
        header.insert(0, i)
    return header


def assign_headers(lines: list[list[dict]], header_idx: list[int],
                   cols: list[Column]) -> None:
    """Fusiona encabezados multilinea asignando cada palabra a su columna.

    'Saldo Inicial' (arriba) y 'Deudor' (abajo) terminan como una sola
    etiqueta porque ambos caen dentro de la extension horizontal de la
    misma columna. Esto es lo que NO se puede resolver subiendo la
    tolerancia vertical: son dos renglones visuales de verdad.
    """
    parts: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
    for i in header_idx:
        for w in lines[i]:
            center = (w["x0"] + w["x1"]) / 2
            best, best_dist = None, float("inf")
            for c in cols:
                if c.x_min - 6 <= center <= c.x_max + 6:
                    dist = 0.0
                else:
                    dist = min(abs(center - c.x_min), abs(center - c.x_max))
                if dist < best_dist:
                    best, best_dist = c, dist
            if best is not None and best_dist < 40:
                parts[best.index].append((w["top"], w["x0"], w["text"]))

    for c in cols:
        chunk = sorted(parts.get(c.index, []))
        c.header = " ".join(t for _, _, t in chunk)


def audit_leaks(words: list[dict]) -> list[dict]:
    """Busca PII que se haya escapado del enmascarado.

    Regla: tras enmascarar, ningun token deberia contener un digito que no
    sea 9, salvo las cuentas contables (que se conservan a proposito) y los
    pseudonimos con prefijo RFC/UUID/CLB. Cualquier otra cosa con digitos
    reales es una fuga.

    Verificar esto a mano no escala: un solo estado de cuenta trae miles de
    tokens. Que lo revise la maquina.
    """
    leaks: list[dict] = []
    for w in words:
        t = w["text"].strip()
        if not any(c.isdigit() for c in t):
            continue
        if RE_CUENTA.match(t):
            continue
        if t.startswith(("RFC", "UUID-", "CLB")):
            continue
        # Un token bien enmascarado solo puede traer 9 como digito.
        if any(c.isdigit() and c != "9" for c in t):
            leaks.append({"text": t, "page": w.get("page"),
                          "x0": w["x0"], "top": w["top"]})
    return leaks


def parse_pages(spec: str | None, total: int) -> list[int]:
    if not spec:
        return sorted({1, min(2, total), total})
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part and not part.startswith("-"):
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            n = int(part)
            out.add(total + n + 1 if n < 0 else n)
    return sorted(p for p in out if 1 <= p <= total)


def dump(pdf_path: Path, out_dir: Path, mode: str, pages_spec: str | None,
         preview: bool, tolerance: float, col_tol: float,
         min_support: int = 3) -> None:
    try:
        import pdfplumber
    except ImportError:
        sys.exit("Falta pdfplumber. Instala con: pip install pdfplumber")

    if not SALT and mode != "none":
        print("  AVISO: sin CONTAPDF_SALT los pseudonimos son mas debiles.\n"
              "  Corre:  export CONTAPDF_SALT=\"tu-frase-secreta\"", file=sys.stderr)

    out_dir.mkdir(parents=True, exist_ok=True)

    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        targets = parse_pages(pages_spec, total)
        print(f"PDF con {total} paginas. Procesando: {targets}")

        report: dict = {
            "source_pages_total": total,
            "pages_sampled": targets,
            "mask_mode": mode,
            "salted": bool(SALT),
            "pages": [],
        }
        preview_lines: list[str] = []
        all_leaks: list[dict] = []

        for pno in targets:
            page = pdf.pages[pno - 1]
            raw = page.extract_words(extra_attrs=["fontname", "size"])

            words = [{
                "text": mask_token(w["text"], mode),
                "x0": round(w["x0"], 1),
                "x1": round(w["x1"], 1),
                "top": round(w["top"], 1),
                "bottom": round(w["bottom"], 1),
                "size": round(float(w.get("size", 0)), 1),
                "bold": "bold" in str(w.get("fontname", "")).lower(),
            } for w in raw]

            cols = merge_columns_by_overlap(detect_columns(words, col_tol, min_support))
            lines = group_into_lines(words, tolerance)
            header_idx = find_header_lines(lines)
            assign_headers(lines, header_idx, cols)

            for w in words:
                w.setdefault("page", pno)
            leaks = audit_leaks(words)
            all_leaks.extend(leaks)

            page_info = {
                "page": pno,
                "width": round(page.width, 1),
                "height": round(page.height, 1),
                "has_text_layer": len(raw) > 0,
                "ruling_lines": len(page.lines),
                "rects": len(page.rects),
                "columns": [asdict(c) for c in cols],
                "header_line_indexes": header_idx,
                "words": words,
            }
            report["pages"].append(page_info)

            if preview:
                preview_lines.append(
                    f"\n{'=' * 78}\nPAGINA {pno}  "
                    f"({page_info['width']}x{page_info['height']}, "
                    f"lines={page_info['ruling_lines']}, "
                    f"rects={page_info['rects']})\n{'=' * 78}")
                preview_lines.append(f"COLUMNAS DETECTADAS: {len(cols)}")
                for c in cols:
                    preview_lines.append(
                        f"  col {c.index:>2}  {c.align:<5}  "
                        f"x[{c.x_min:>6.1f}..{c.x_max:>6.1f}]  "
                        f"n={c.support:<4}  '{c.header}'")
                preview_lines.append("-" * 78)
                for idx, line in enumerate(lines):
                    tag = "H" if idx in header_idx else " "
                    body = "  ".join(
                        f"[{w['x0']:.0f}-{w['x1']:.0f}]{w['text']}" for w in line)
                    preview_lines.append(f"{tag}{line[0]['top']:>7.1f} | {body}")

    stem = pdf_path.stem
    json_path = out_dir / f"{stem}.layout.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"OK -> {json_path}")

    if preview:
        txt_path = out_dir / f"{stem}.preview.txt"
        txt_path.write_text("\n".join(preview_lines), encoding="utf-8")
        print(f"OK -> {txt_path}")

    if all_leaks:
        leak_path = out_dir / f"{stem}.LEAKS.txt"
        leak_path.write_text(
            "\n".join(f"pag {l['page']:>4}  x={l['x0']:>6.1f}  y={l['top']:>6.1f}  {l['text']}"
                      for l in all_leaks), encoding="utf-8")
        print(f"\n  !! AUDITORIA: {len(all_leaks)} tokens con digitos reales sin enmascarar")
        print(f"  !! Revisa {leak_path} y NO subas este fixture a git todavia.")
        muestra = all_leaks[:5]
        for l in muestra:
            print(f"     pag {l['page']}  '{l['text']}'")
        print()
    else:
        print("\n  AUDITORIA: sin fugas detectadas.\n")

    for p in report["pages"]:
        strategy = ("texto nativo" if p["has_text_layer"]
                    else "SIN capa de texto -> requiere OCR")
        table = ("tabla con bordes" if p["ruling_lines"] > 10
                 else "tabla sin bordes")
        print(f"  pag {p['page']}: {strategy} | {table} | "
              f"{len(p['columns'])} columnas")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("fixtures/layouts"))
    ap.add_argument("--mask", choices=["values", "full", "none"], default="values")
    ap.add_argument("--pages", default=None)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--tolerance", type=float, default=2.5,
                    help="Tolerancia vertical para agrupar renglones")
    ap.add_argument("--col-tol", type=float, default=3.0,
                    help="Tolerancia horizontal para agrupar columnas")
    ap.add_argument("--min-support", type=int, default=3,
                    help="Minimo de palabras para considerar algo una columna")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"No existe: {args.pdf}")

    dump(args.pdf, args.out, args.mask, args.pages, args.preview,
         args.tolerance, args.col_tol, args.min_support)


if __name__ == "__main__":
    main()