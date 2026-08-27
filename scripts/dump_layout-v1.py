#!/usr/bin/env python3
"""
dump_layout.py — Extrae la ESTRUCTURA de un PDF contable sin exponer los datos.

Corre 100% local. El PDF original nunca sale de tu maquina; lo unico que
produces es un JSON (y un preview de texto) con coordenadas y contenido
enmascarado, que si puedes compartir con Claude Code o con quien sea.

Uso tipico:
    python scripts/dump_layout.py real.pdf -o out/balanza --pages 1,2,-1
    python scripts/dump_layout.py real.pdf -o out/edocta --mask values --preview

Modos de enmascarado (--mask):
    values  (default) Enmascara todo MENOS los encabezados detectados y las
                      palabras de la whitelist. Es el que quieres el 99% del tiempo.
    full              Enmascara absolutamente todo. Para el primer vistazo.
    none              Sin enmascarar. SOLO para PDFs que ya son sinteticos.

Reglas de enmascarado (preservan la FORMA, que es lo que necesita el parser):
    - Numeros/montos:  15,764,776.89  ->  99,999,999.99
    - Texto:           NOHEMI FUENTES ->  XXXXXX XXXXXXX
    - RFC/UUID/CLABE:  se reemplazan por un pseudonimo estable (mismo input,
                       mismo output) para poder probar cruces entre documentos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("Falta pdfplumber. Instala con: pip install pdfplumber")


# --- Palabras que NUNCA se enmascaran -----------------------------------
# Son vocabulario contable/estructural: no son PII y son exactamente lo que
# el parser necesita ver para reconocer encabezados y secciones.
WHITELIST = {
    # encabezados de tabla
    "no", "cuenta", "naturaleza", "saldo", "inicial", "final", "deudor",
    "acreedor", "debe", "haber", "folio", "fecha", "tipo", "documento",
    "tercero", "descripcion", "descripción", "referencia", "depositos",
    "depósitos", "retiros", "dia", "día", "concepto", "importe", "moneda",
    "periodo", "período", "pagina", "página", "de", "al", "hasta", "desde",
    "totales", "total", "subtotal", "movimiento", "conciliado", "poliza",
    "póliza", "polizas", "pólizas", "auxiliar", "cuentas", "balanza",
    "comprobacion", "comprobación", "impreso", "estado", "corte", "abr",
    "notas", "adicionales", "asociados", "la", "a", "y", "en", "del",
    "impresion", "impresión", "mxn", "usd",
    # etiquetas de estado de cuenta
    "banco", "sucursal", "telefono", "teléfono", "clave", "bancaria",
    "estandar", "estándar", "numero", "número", "informacion", "información",
    "general", "resumen", "comisiones", "detalle", "operaciones", "promedio",
    "diario", "minimo", "mínimo", "requerido", "cheques", "girados", "exentos",
    "ganancia", "anual", "nominal", "real", "tasa", "interes", "interés",
    "ordinaria", "rendimiento", "cobradas", "otras", "iva", "sobre", "libro",
}

# Patrones que merecen pseudonimo estable en lugar de mascara ciega,
# porque el parser necesita poder cruzarlos entre documentos.
RE_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$", re.I)
RE_UUID = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-?[0-9A-F]{0,12}$", re.I)
RE_CLABE = re.compile(r"^\d{16,20}$")
RE_NUMERIC = re.compile(r"^[\d.,\-$()%/:]+$")
RE_CUENTA = re.compile(r"^\d{3}(-\d{2,3})*$")  # 100-01, 105-01-081 -> se conserva
RE_LETTER = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")


def _stable_id(text: str, prefix: str, length: int = 6) -> str:
    """Mismo texto -> mismo pseudonimo, sin guardar diccionario en disco."""
    digest = hashlib.sha256(text.upper().encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:length].upper()}"


def mask_token(text: str, mode: str, header_tops: set[float] | None = None,
               top: float | None = None) -> str:
    """Enmascara un token preservando su forma."""
    if mode == "none":
        return text

    stripped = text.strip()
    if not stripped:
        return text

    # Encabezados y vocabulario contable se conservan siempre en modo 'values'.
    if mode == "values":
        if stripped.lower().strip(".:,()") in WHITELIST:
            return text
        # Los numeros de cuenta contable NO son PII y son estructurales.
        if RE_CUENTA.match(stripped):
            return text

    # Identificadores que necesitan ser rastreables entre documentos.
    if RE_RFC.match(stripped):
        return _stable_id(stripped, "RFC", 9)[:13]
    if RE_UUID.match(stripped):
        return _stable_id(stripped, "UUID-", 12)
    if RE_CLABE.match(stripped):
        return _stable_id(stripped, "CLB", 14)

    # Montos y fechas: preservar separadores, sustituir digitos.
    if RE_NUMERIC.match(stripped):
        return re.sub(r"\d", "9", text)

    # Texto libre: preservar longitud de cada palabra y mayusculas/minusculas.
    def _sub(m: re.Match) -> str:
        ch = m.group(0)
        return "X" if ch.isupper() else "x"

    return RE_LETTER.sub(_sub, text)


def parse_pages(spec: str | None, total: int) -> list[int]:
    """'1,2,-1' -> [1, 2, total]. '1-3' -> [1,2,3]. None -> primeras 2 + ultima."""
    if not spec:
        pages = {1, min(2, total), total}
        return sorted(pages)
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


def group_into_lines(words: list[dict], tolerance: float = 2.5) -> list[list[dict]]:
    """Agrupa palabras en renglones visuales por su coordenada 'top'.

    Es el mismo agrupamiento que va a usar el parser en produccion, asi que
    verlo aqui te dice de una si la tolerancia default te sirve o no.
    """
    buckets: dict[float, list[dict]] = defaultdict(list)
    for w in sorted(words, key=lambda x: (x["top"], x["x0"])):
        key = next((k for k in buckets if abs(k - w["top"]) <= tolerance), None)
        buckets[key if key is not None else round(w["top"], 1)].append(w)
    return [sorted(v, key=lambda x: x["x0"]) for _, v in sorted(buckets.items())]


def column_histogram(words: list[dict], bin_size: float = 3.0) -> list[dict]:
    """Cuenta cuantas palabras arrancan en cada posicion X.

    Los picos de este histograma SON las columnas. Si aqui no se ven picos
    claros, tu PDF no tiene columnas alineadas y vas a necesitar otra
    estrategia (bordes de tabla o OCR con layout).
    """
    hist: dict[float, int] = defaultdict(int)
    for w in words:
        hist[round(w["x0"] / bin_size) * bin_size] += 1
    peaks = [{"x": x, "count": c} for x, c in sorted(hist.items()) if c >= 3]
    return sorted(peaks, key=lambda d: -d["count"])[:25]


def dump(pdf_path: Path, out_dir: Path, mode: str, pages_spec: str | None,
         preview: bool, tolerance: float) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        targets = parse_pages(pages_spec, total)
        print(f"PDF con {total} paginas. Procesando: {targets}")

        report: dict = {
            "source_pages_total": total,
            "pages_sampled": targets,
            "mask_mode": mode,
            "pages": [],
        }
        preview_lines: list[str] = []

        for pno in targets:
            page = pdf.pages[pno - 1]
            raw = page.extract_words(extra_attrs=["fontname", "size"])

            words = []
            for w in raw:
                words.append({
                    "text": mask_token(w["text"], mode),
                    "x0": round(w["x0"], 1),
                    "x1": round(w["x1"], 1),
                    "top": round(w["top"], 1),
                    "size": round(float(w.get("size", 0)), 1),
                    "bold": "bold" in str(w.get("fontname", "")).lower(),
                })

            page_info = {
                "page": pno,
                "width": round(page.width, 1),
                "height": round(page.height, 1),
                # Estas 3 metricas te dicen que estrategia de extraccion aplica:
                "has_text_layer": len(raw) > 0,
                "ruling_lines": len(page.lines),
                "rects": len(page.rects),
                "column_peaks": column_histogram(raw),
                "words": words,
            }
            report["pages"].append(page_info)

            if preview:
                preview_lines.append(f"\n{'=' * 78}\nPAGINA {pno}  "
                                     f"({page_info['width']}x{page_info['height']}, "
                                     f"lines={page_info['ruling_lines']}, "
                                     f"rects={page_info['rects']})\n{'=' * 78}")
                for line in group_into_lines(words, tolerance):
                    prefix = f"{line[0]['top']:>7.1f} |"
                    body = "  ".join(f"[{w['x0']:.0f}]{w['text']}" for w in line)
                    preview_lines.append(f"{prefix} {body}")

    stem = pdf_path.stem
    json_path = out_dir / f"{stem}.layout.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"OK -> {json_path}")

    if preview:
        txt_path = out_dir / f"{stem}.preview.txt"
        txt_path.write_text("\n".join(preview_lines), encoding="utf-8")
        print(f"OK -> {txt_path}")

    # Diagnostico inmediato, para no tener que abrir el JSON.
    for p in report["pages"]:
        strategy = ("texto nativo" if p["has_text_layer"]
                    else "SIN capa de texto -> requiere OCR")
        table = ("tabla con bordes (camelot lattice)" if p["ruling_lines"] > 10
                 else "tabla sin bordes (clustering por X)")
        print(f"  pag {p['page']}: {strategy} | {table} | "
              f"{len(p['column_peaks'])} columnas candidatas")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path, help="PDF de entrada (no se modifica)")
    ap.add_argument("-o", "--out", type=Path, default=Path("fixtures/layouts"),
                    help="Directorio de salida")
    ap.add_argument("--mask", choices=["values", "full", "none"], default="values",
                    help="Nivel de enmascarado (default: values)")
    ap.add_argument("--pages", default=None,
                    help="Paginas: '1,2,-1' o '1-3'. Default: primeras 2 y ultima")
    ap.add_argument("--preview", action="store_true",
                    help="Genera tambien un .preview.txt legible")
    ap.add_argument("--tolerance", type=float, default=2.5,
                    help="Tolerancia vertical para agrupar renglones")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"No existe: {args.pdf}")

    dump(args.pdf, args.out, args.mask, args.pages, args.preview, args.tolerance)


if __name__ == "__main__":
    main()
