"""
engines.py: Adaptadores para los diferentes motores de extracción y OCR:
1. DigitalPyMuPDFEngine (Extracción nativa ultrarrápida sin pérdida)
2. DoclingEngine (IBM Docling con TableFormer para estructura y tablas complejas)
3. DocTREngine (DocTR con Deep Learning para texto manuscrito y minutas)
4. TesseractFallbackEngine (Fallback seguro mediante pdftoppm + Tesseract)
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List
import logging
import subprocess
import tempfile
import fitz  # PyMuPDF

from .config import PipelineConfig
from .preprocessors import preprocesar_imagen_para_ocr

logger = logging.getLogger("agy_ocr_md")


class BaseEngine(ABC):
    def __init__(self, config: PipelineConfig):
        self.config = config

    @abstractmethod
    def extract_page(self, doc: fitz.Document, page_num: int) -> str:
        """Extrae el texto de una página específica y lo devuelve en Markdown."""
        pass


class DigitalPyMuPDFEngine(BaseEngine):
    """Motor de extracción vectorial nativa mediante PyMuPDF."""
    
    def extract_page(self, doc: fitz.Document, page_num: int) -> str:
        page = doc[page_num]
        
        # Extraer bloques estructurados (x0, y0, x1, y1, texto, block_no, block_type)
        blocks = page.get_text("blocks")
        md_lines = []
        
        for b in blocks:
            # b[6] == 0 indica bloque de texto; 1 indica imagen
            if b[6] == 0:
                text = b[4].strip()
                if not text:
                    continue
                
                # Heurística simple de títulos: línea corta en mayúsculas
                if len(text) < 60 and text.isupper() and not text.endswith('.'):
                    md_lines.append(f"### {text}\n")
                else:
                    md_lines.append(f"{text}\n")
                    
        return "\n".join(md_lines).strip()


class DoclingEngine(BaseEngine):
    """Motor estructurado con IBM Docling (soporte de tablas con TableFormer)."""
    
    def __init__(self, config: PipelineConfig):
        super().__init__(config)
        self._converter = None

    def _get_converter(self):
        if self._converter is None:
            try:
                from docling.document_converter import DocumentConverter, PdfFormatOption
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import (
                    PdfPipelineOptions,
                    TableStructureOptions,
                    TableFormerMode,
                    TesseractCliOcrOptions,
                    AcceleratorOptions,
                    AcceleratorDevice
                )
                from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
                
                po = PdfPipelineOptions()
                po.do_ocr = True
                po.do_table_structure = True
                po.table_structure_options = TableStructureOptions(
                    do_cell_matching=True,
                    mode=TableFormerMode.ACCURATE
                )
                
                # Configurar aceleración (GPU si está disponible)
                device = (
                    AcceleratorDevice.GPU
                    if self.config.get_device() == "cuda"
                    else AcceleratorDevice.CPU
                )
                po.accelerator_options = AcceleratorOptions(device=device)
                
                # Idiomas Tesseract CLI
                po.ocr_options = TesseractCliOcrOptions(
                    lang=[s.strip() for s in self.config.language.split('+')],
                    force_full_page_ocr=False
                )
                
                self._converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(
                            pipeline_options=po,
                            pipeline_cls=StandardPdfPipeline
                        )
                    }
                )
            except Exception as e:
                logger.error(f"No se pudo inicializar Docling: {e}")
                self._converter = False
        return self._converter

    def extract_document(self, pdf_path: Path) -> str:
        """Convierte el documento completo con Docling manteniendo tablas y jerarquías."""
        converter = self._get_converter()
        if not converter:
            raise RuntimeError("Docling no está disponible o no se pudo cargar.")
        
        result = converter.convert(str(pdf_path))
        return result.document.export_to_markdown()

    def extract_page(self, doc: fitz.Document, page_num: int) -> str:
        # Extraer página individual guardándola temporalmente
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp_doc = fitz.open()
            tmp_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            tmp_doc.save(tmp.name)
            tmp_doc.close()
            return self.extract_document(Path(tmp.name))


class DocTREngine(BaseEngine):
    """Motor de OCR con PyTorch y DocTR para manuscritos y minutas."""
    
    def __init__(self, config: PipelineConfig):
        super().__init__(config)
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from doctr.models import ocr_predictor
                import torch
                pretrained = True
                self._model = ocr_predictor(
                    det_arch='db_resnet50',
                    reco_arch='crnn_vgg16_bn',
                    pretrained=pretrained
                )
                if self.config.get_device() == "cuda" and torch.cuda.is_available():
                    self._model = self._model.cuda()
            except Exception as e:
                logger.error(f"No se pudo cargar modelo DocTR: {e}")
                self._model = False
        return self._model

    def extract_page(self, doc: fitz.Document, page_num: int) -> str:
        model = self._get_model()
        if not model:
            raise RuntimeError("DocTR no está disponible en este entorno.")
            
        import numpy as np
        from doctr.io import DocumentFile
        
        # Renderizar la página con alta resolución para manuscrito
        page = doc[page_num]
        zoom = self.config.dpi_handwritten / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        # Convertir a imagen numpy
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        if pix.n == 4:
            import cv2
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 1:
            import cv2
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        # Preprocesar con CLAHE y binarización adaptativa
        img_prep = preprocesar_imagen_para_ocr(img, mejorar_manuscrito=True)
        
        # DocTR espera RGB
        import cv2
        if len(img_prep.shape) == 2:
            img_rgb = cv2.cvtColor(img_prep, cv2.COLOR_GRAY2RGB)
        else:
            img_rgb = cv2.cvtColor(img_prep, cv2.COLOR_BGR2RGB)

        # Inferencia
        doc_input = DocumentFile.from_images([img_rgb])
        result = model(doc_input)
        
        # Reconstruir texto en líneas y párrafos
        lines_output = []
        for block in result.pages[0].blocks:
            for line in block.lines:
                words = [w.value for w in line.words]
                if words:
                    lines_output.append(" ".join(words))
            lines_output.append("")  # Separador de párrafo
            
        return "\n".join(lines_output).strip()


class TesseractFallbackEngine(BaseEngine):
    """Fallback clásico usando pdftoppm y tesseract CLI."""
    
    def extract_page(self, doc: fitz.Document, page_num: int) -> str:
        with tempfile.TemporaryDirectory() as td:
            # Guardar página temporal
            single_pdf = Path(td) / "single.pdf"
            tmp_doc = fitz.open()
            tmp_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            tmp_doc.save(str(single_pdf))
            tmp_doc.close()
            
            img_prefix = Path(td) / "page"
            # Renderizar con pdftoppm
            cmd_ppm = [
                "pdftoppm",
                "-singlefile",
                "-r", str(self.config.dpi_default),
                "-gray",
                "-png",
                str(single_pdf),
                str(img_prefix)
            ]
            res_ppm = subprocess.run(cmd_ppm, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            img_path = img_prefix.with_suffix(".png")
            
            if not img_path.is_file():
                return "[ERROR: No se pudo renderizar la página con pdftoppm]"

            # Ejecutar Tesseract
            cmd_tess = [
                "tesseract",
                str(img_path),
                "stdout",
                "-l", self.config.language,
                "--oem", "1",
                "--psm", "6",
                "-c", "preserve_interword_spaces=1"
            ]
            res_tess = subprocess.run(cmd_tess, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            return res_tess.stdout.strip()
