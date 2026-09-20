"""
config.py: Definiciones de configuración y tipos para agy_ocr_md.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class PageType(str, Enum):
    DIGITAL = "DIGITAL"                     # Texto nativo seleccionable y bien estructurado
    SCANNED_STRUCTURED = "SCANNED_STRUCTURED" # Escaneo mecanografiado, tablas, formularios (Docling)
    HANDWRITTEN = "HANDWRITTEN"             # Minutas, firmas, notas manuscritas (DocTR)
    FALLBACK = "FALLBACK"                   # Fallback clásico (Tesseract / OCRmyPDF)


@dataclass
class PipelineConfig:
    # Idiomas para OCR (formato tesseract 'spa+eng' o lista docling/easyocr ['es', 'en'])
    language: str = "spa+eng"
    docling_languages: List[str] = field(default_factory=lambda: ["es"])
    
    # Resolución en DPI
    dpi_default: int = 300
    dpi_handwritten: int = 350
    
    # Umbrales para clasificación de páginas
    min_digital_chars_per_page: int = 150   # Caracteres mínimos para considerar texto digital nativo
    min_digital_words_per_page: int = 25    # Palabras mínimas
    max_image_coverage_for_digital: float = 0.85 # Si la imagen ocupa > 85% de la página, puede ser escaneo
    
    # Selección de motores
    enable_docling: bool = True
    enable_doctr: bool = True
    enable_tesseract_fallback: bool = True
    auto_repair_ghostscript: bool = True
    
    # Hardware
    device: str = "auto"                    # 'auto', 'cuda', o 'cpu'
    
    # Limpieza de Markdown
    clean_markdown: bool = True
    merge_hyphenated_words: bool = True     # Unir palabras cortadas por guion ('ejem-' + 'plo')
    remove_running_headers_footers: bool = True # Limpiar encabezados repetitivos
    fix_markdown_tables: bool = True        # Formatear y alinear tablas Markdown
    
    # Formato de salida
    include_frontmatter: bool = True
    include_page_breaks: bool = True
    
    # Control de ejecución y reanudación
    skip_existing: bool = True              # No reprocesar si el Markdown ya existe
    timeout_seconds_per_page: int = 120
    
    def get_device(self) -> str:
        if self.device == "auto":
            try:
                import torch
                return "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                return "cpu"
        return self.device
