"""
agy_ocr_md: Pipeline inteligente para extracción de texto y OCR a Markdown estructurado (.md).
Soporta texto digital nativo, escaneado mecanografiado, tablas complejas y manuscrito.
"""

from .pipeline import AgyOcrPipeline
from .config import PipelineConfig, PageType
from .detector import PageClassifier
from .cleaner import MarkdownCleaner

__version__ = "1.0.0"
__all__ = ["AgyOcrPipeline", "PipelineConfig", "PageType", "PageClassifier", "MarkdownCleaner"]
