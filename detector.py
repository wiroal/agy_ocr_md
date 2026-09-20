"""
detector.py: Clasificador y router inteligente de páginas PDF.
Analiza la estructura de cada página para decidir el motor óptimo:
- DIGITAL (PyMuPDF directo)
- SCANNED_STRUCTURED (Docling / TableFormer)
- HANDWRITTEN (DocTR / OpenCV)
- FALLBACK (Tesseract)
"""

from typing import Tuple, Dict, Any, List
from pathlib import Path
import re
from .config import PipelineConfig, PageType


class PageClassifier:
    def __init__(self, config: PipelineConfig):
        self.config = config

    def classify_pdf_page(self, doc, page_num: int) -> Tuple[PageType, Dict[str, Any]]:
        """
        Analiza una página abierta con PyMuPDF (fitz) y determina su PageType.
        Devuelve (PageType, metrics_dict).
        """
        page = doc[page_num]
        rect = page.rect
        page_area = max(rect.width * rect.height, 1.0)
        
        # 1. Extracción de texto vectorial y métricas
        raw_text = page.get_text("text") or ""
        char_count = len(raw_text.strip())
        words = re.findall(r'\b\w+\b', raw_text)
        word_count = len(words)
        
        # 2. Análisis de imágenes incrustadas
        images = page.get_images(full=True)
        image_count = len(images)
        
        # Calcular cobertura visual de imágenes
        covered_area = 0.0
        for img_info in images:
            xref = img_info[0]
            for img_rect in page.get_image_rects(xref):
                covered_area += (img_rect.width * img_rect.height)
        
        image_coverage_ratio = min(covered_area / page_area, 1.0)
        
        # 3. Comprobar fuentes tipográficas
        fonts = page.get_fonts()
        font_count = len(fonts)
        
        metrics = {
            "page_num": page_num + 1,
            "char_count": char_count,
            "word_count": word_count,
            "image_count": image_count,
            "image_coverage_ratio": round(image_coverage_ratio, 3),
            "font_count": font_count,
        }

        # --- Reglas de Decisión ---

        # Regla 1: Texto Digital Nativo
        # Si tiene suficiente cantidad de palabras/caracteres y la imagen no es un escaneo de página completa
        if (char_count >= self.config.min_digital_chars_per_page and 
            word_count >= self.config.min_digital_words_per_page and 
            image_coverage_ratio < self.config.max_image_coverage_for_digital):
            return PageType.DIGITAL, metrics

        # Regla 2: Escaneo con posible contenido manuscrito
        # Si casi no hay texto digital y hay imagen completa, verificar si es minuta/manuscrito
        # Heurística: si contiene palabras clave en metadatos o si la cobertura es alta
        if image_coverage_ratio >= 0.70 and char_count < 50:
            # Si el usuario habilitó DocTR y se detectan indicios de manuscrito
            # o si el nombre del archivo contiene indicios como 'minuta', 'cuaderno', 'mano'
            doc_name = Path(doc.name).stem.lower() if hasattr(doc, 'name') else ""
            if any(k in doc_name for k in ['manuscrit', 'minuta', 'bitacora', 'cuaderno', 'libros_cgfm']):
                return PageType.HANDWRITTEN, metrics
            
            # Por defecto en escaneos institucionales de calidad estructurada:
            return PageType.SCANNED_STRUCTURED, metrics

        # Regla 3: Si tiene algo de texto pero parece un escaneo con OCR defectuoso o parcial
        if image_coverage_ratio >= 0.50:
            return PageType.SCANNED_STRUCTURED, metrics

        # Si no hay certeza pero hay texto mínimo
        if char_count > 0:
            return PageType.DIGITAL, metrics

        # En caso de página en blanco o no identificada
        return PageType.SCANNED_STRUCTURED, metrics

    def classify_whole_document(self, pdf_path: Path) -> List[Tuple[PageType, Dict[str, Any]]]:
        """
        Clasifica todas las páginas de un archivo PDF.
        """
        import fitz
        results = []
        with fitz.open(str(pdf_path)) as doc:
            for p in range(len(doc)):
                p_type, metrics = self.classify_pdf_page(doc, p)
                results.append((p_type, metrics))
        return results
