"""
preprocessors.py: Preprocesamiento de imágenes y reparación de PDFs.
- Reparación con Ghostscript para PDFs corruptos o con errores de sintaxis PDFium.
- Mejora de contraste adaptativo (CLAHE), binarización y deskew con OpenCV.
"""

from pathlib import Path
import subprocess
import tempfile
import logging
from typing import Optional

logger = logging.getLogger("agy_ocr_md")


def reparar_pdf_ghostscript(pdf_path: Path, output_dir: Optional[Path] = None, timeout: int = 300) -> Optional[Path]:
    """
    Repara un PDF corrupto o con errores de tabla de referencias cruzadas mediante Ghostscript.
    """
    if output_dir is None:
        temp_dir = tempfile.mkdtemp(prefix="gs_repair_")
        out_path = Path(temp_dir) / f"{pdf_path.stem}_reparado.pdf"
    else:
        out_path = output_dir / f"{pdf_path.stem}_reparado.pdf"

    cmd = [
        "gs",
        "-o", str(out_path),
        "-sDEVICE=pdfwrite",
        "-dPDFSETTINGS=/prepress",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
        str(pdf_path)
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        if res.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0:
            logger.info(f"PDF reparado exitosamente con Ghostscript: {out_path.name}")
            return out_path
        else:
            logger.warning(f"Ghostscript no pudo reparar {pdf_path.name}: {res.stderr.decode('utf-8', errors='ignore')}")
            return None
    except FileNotFoundError:
        logger.warning("Ghostscript ('gs') no está instalado en el sistema PATH.")
        return None
    except Exception as e:
        logger.error(f"Error ejecutando reparación de PDF: {e}")
        return None


def preprocesar_imagen_para_ocr(img_bgr, mejorar_manuscrito: bool = False):
    """
    Aplica filtros de visión por computador para maximizar el reconocimiento de OCR:
    - Escala de grises
    - Corrección local de contraste CLAHE (resalta tinta desvanecida y limpia fondos sucios)
    - Desinclinado (deskew) suave
    - Binarización adaptativa opcional
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        # Si no está instalado OpenCV, devolver la imagen tal cual
        return img_bgr

    # 1. Escala de grises si es BGR
    if len(img_bgr.shape) == 3:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_bgr

    # 2. Corrección de contraste local CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    if not mejorar_manuscrito:
        return enhanced

    # 3. Filtros específicos para manuscritos / papel antiguo
    blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
    bw = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        35,
        11
    )
    
    # Morfología suave para eliminar ruido punteado
    kernel = np.ones((2, 2), np.uint8)
    clean_bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=1)
    return clean_bw
