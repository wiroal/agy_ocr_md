#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_pipeline.py: Punto de entrada directo para agy_ocr_md.
Permite ejecutar directamente: python run_pipeline.py -i documento.pdf
"""

import sys
from pathlib import Path

# Agregar directorio padre al path si se ejecuta directamente
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agy_ocr_md.cli import main

if __name__ == "__main__":
    main()
