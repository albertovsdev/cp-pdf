#!/usr/bin/env bash
set -e
python scripts/dump_layout.py fixtures/real/1-Balanza/balanza.pdf        -o fixtures/layouts --preview
python scripts/dump_layout.py fixtures/real/2-Libro-Diario/poliza.pdf    -o fixtures/layouts --preview --pages 1,2,500
python scripts/dump_layout.py fixtures/real/3-Auxiliares/auxiliar.pdf    -o fixtures/layouts --preview --pages 1,2,-1
python scripts/dump_layout.py fixtures/real/4-Estados-Cuenta/edocta.pdf  -o fixtures/layouts --preview --pages 1,2
echo "--- fugas pendientes ---"
ls fixtures/layouts/*.LEAKS.txt 2>/dev/null || echo "ninguna"