"""
pipeline.py: Orquestador maestro del pipeline AgyOcrPipeline.
Integra detección inteligente por página, motores adaptativos (PyMuPDF, Docling, DocTR, Tesseract),
reparación automática de PDFs dañados y limpieza profunda de Markdown.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
import time
import os
import csv
import logging
import datetime as dt
import fitz  # PyMuPDF

from .config import PipelineConfig, PageType
from .detector import PageClassifier
from .cleaner import MarkdownCleaner
from .preprocessors import reparar_pdf_ghostscript
from .engines import (
    DigitalPyMuPDFEngine,
    DoclingEngine,
    DocTREngine,
    TesseractFallbackEngine
)

logger = logging.getLogger("agy_ocr_md")


class AgyOcrPipeline:
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.classifier = PageClassifier(self.config)
        self.cleaner = MarkdownCleaner(
            merge_hyphens=self.config.merge_hyphenated_words,
            clean_headers_footers=self.config.remove_running_headers_footers,
            normalize_tables=self.config.fix_markdown_tables
        )
        
        # Inicializar motores
        self.digital_engine = DigitalPyMuPDFEngine(self.config)
        self.docling_engine = DoclingEngine(self.config)
        self.doctr_engine = DocTREngine(self.config)
        self.tesseract_engine = TesseractFallbackEngine(self.config)

    def process_file(
        self,
        pdf_path: Path,
        output_md_path: Optional[Path] = None,
        force_engine: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Procesa un único archivo PDF y genera su Markdown (.md) estructurado y limpio.
        """
        pdf_path = Path(pdf_path).resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"No existe el archivo: {pdf_path}")

        if output_md_path is None:
            output_md_path = pdf_path.with_suffix('.md')
        else:
            output_md_path = Path(output_md_path).resolve()

        # Comprobar reanudación si ya existe
        if self.config.skip_existing and output_md_path.is_file() and output_md_path.stat().st_size > 0:
            logger.info(f"Omitido (ya procesado): {output_md_path.name}")
            return {
                "pdf": str(pdf_path),
                "output_md": str(output_md_path),
                "estado": "OMITIDO_YA_EXISTE",
                "paginas": 0,
                "duracion_segundos": 0.0
            }

        start_time = time.time()
        working_pdf = pdf_path
        reparado = False

        # Intentar abrir el PDF
        doc = None
        try:
            doc = fitz.open(str(working_pdf))
            num_pages = len(doc)
        except Exception as e_open:
            logger.warning(f"Error al abrir {pdf_path.name} ({e_open}). Intentando reparar con Ghostscript...")
            if self.config.auto_repair_ghostscript:
                rep = reparar_pdf_ghostscript(pdf_path)
                if rep:
                    working_pdf = rep
                    doc = fitz.open(str(working_pdf))
                    num_pages = len(doc)
                    reparado = True
                else:
                    raise RuntimeError(f"El archivo {pdf_path.name} está corrupto y no pudo repararse.")
            else:
                raise e_open

        page_markdowns: List[str] = []
        engine_usage: Dict[str, int] = {}

        try:
            # Si el usuario fuerza Docling y el documento no es manuscrito, podemos pasarlo completo
            if force_engine == "docling" and self.config.enable_docling:
                try:
                    logger.info(f"Ejecutando Docling completo en {pdf_path.name}...")
                    raw_md = self.docling_engine.extract_document(working_pdf)
                    page_markdowns.append(raw_md)
                    engine_usage["DoclingFull"] = num_pages
                except Exception as e_docling:
                    logger.warning(f"Docling falló ({e_docling}). Procediendo con extracción por página...")
                    force_engine = None

            # Procesamiento página por página (Enrutador Híbrido)
            if not page_markdowns:
                for p_idx in range(num_pages):
                    p_num = p_idx + 1
                    
                    if force_engine:
                        selected_type = PageType(force_engine.upper())
                        metrics = {}
                    else:
                        selected_type, metrics = self.classifier.classify_pdf_page(doc, p_idx)

                    # Seleccionar motor según el tipo clasificado
                    page_text = ""
                    engine_used_name = "Digital"

                    if selected_type == PageType.DIGITAL:
                        page_text = self.digital_engine.extract_page(doc, p_idx)
                        engine_used_name = "Digital-PyMuPDF"

                    elif selected_type == PageType.SCANNED_STRUCTURED:
                        # Prioridad Docling para mantener tablas
                        if self.config.enable_docling:
                            try:
                                page_text = self.docling_engine.extract_page(doc, p_idx)
                                engine_used_name = "Docling"
                            except Exception:
                                # Fallback a Tesseract
                                page_text = self.tesseract_engine.extract_page(doc, p_idx)
                                engine_used_name = "Tesseract-Fallback"
                        else:
                            page_text = self.tesseract_engine.extract_page(doc, p_idx)
                            engine_used_name = "Tesseract"

                    elif selected_type == PageType.HANDWRITTEN:
                        # Prioridad DocTR para manuscritos
                        if self.config.enable_doctr:
                            try:
                                page_text = self.doctr_engine.extract_page(doc, p_idx)
                                engine_used_name = "DocTR-Handwritten"
                            except Exception:
                                page_text = self.tesseract_engine.extract_page(doc, p_idx)
                                engine_used_name = "Tesseract-Fallback"
                        else:
                            page_text = self.tesseract_engine.extract_page(doc, p_idx)
                            engine_used_name = "Tesseract"

                    else:
                        page_text = self.tesseract_engine.extract_page(doc, p_idx)
                        engine_used_name = "Tesseract-Fallback"

                    engine_usage[engine_used_name] = engine_usage.get(engine_used_name, 0) + 1

                    # Formato por página
                    header_p = f"## Página {p_num}\n\n" if num_pages > 1 and self.config.include_page_breaks else ""
                    page_markdowns.append(f"{header_p}{page_text}".strip())

        finally:
            if doc:
                doc.close()

        # Combinar cuerpo del Markdown
        separator = "\n\n---\n\n" if self.config.include_page_breaks else "\n\n"
        raw_full_md = separator.join(page_markdowns)

        # Aplicar limpieza de Markdown si está habilitada
        final_body_md = self.cleaner.clean(raw_full_md) if self.config.clean_markdown else raw_full_md

        # Generar metadatos frontmatter YAML
        duration = round(time.time() - start_time, 2)
        table_count = final_body_md.count("\n|")
        char_count = len(final_body_md)

        frontmatter_parts = [
            "---",
            f'pdf_original: "{pdf_path.as_posix()}"',
            f'paginas: {num_pages}',
            f'motores_utilizados: {list(engine_usage.keys())}',
            f'distribucion_paginas: {engine_usage}',
            f'reparado_ghostscript: {reparado}',
            f'tablas_detectadas: {table_count}',
            f'caracteres_extraidos: {char_count}',
            f'fecha_procesamiento: "{dt.datetime.now().isoformat()}"',
            f'duracion_segundos: {duration}',
            "---\n\n"
        ]
        
        frontmatter = "\n".join(frontmatter_parts) if self.config.include_frontmatter else ""
        document_title = f"# {pdf_path.stem}\n\n"
        full_content = frontmatter + document_title + final_body_md + "\n"

        # Guardar en archivo atómicamente
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = output_md_path.with_suffix('.tmp_md')
        try:
            tmp_target.write_text(full_content, encoding="utf-8")
            os.replace(tmp_target, output_md_path)
        except Exception as e_write:
            if tmp_target.exists():
                tmp_target.unlink(missing_ok=True)
            raise e_write

        return {
            "pdf": str(pdf_path),
            "output_md": str(output_md_path),
            "estado": "PROCESADO_REPARADO" if reparado else "PROCESADO",
            "paginas": num_pages,
            "tablas": table_count,
            "caracteres": char_count,
            "motores": engine_usage,
            "duracion_segundos": duration
        }

    def process_directory(
        self,
        input_dir: Path,
        output_dir: Path,
        recursive: bool = True
    ) -> Path:
        """
        Procesa una carpeta de archivos PDF y genera un reporte CSV y Excel detallado.
        """
        input_dir = Path(input_dir).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        pattern = "**/*.pdf" if recursive else "*.pdf"
        pdf_files = sorted(list(input_dir.glob(pattern)))

        logger.info(f"Encontrados {len(pdf_files)} PDFs en {input_dir}")
        report_data = []
        log_csv = output_dir / f"reporte_procesamiento_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"

        for idx, pdf in enumerate(pdf_files, 1):
            rel_path = pdf.relative_to(input_dir)
            target_md = output_dir / rel_path.with_suffix(".md")
            logger.info(f"[{idx}/{len(pdf_files)}] Procesando: {rel_path}")

            try:
                res = self.process_file(pdf, target_md)
                report_data.append(res)
            except Exception as e:
                logger.error(f"Error procesando {pdf.name}: {e}")
                report_data.append({
                    "pdf": str(pdf),
                    "output_md": str(target_md),
                    "estado": "ERROR",
                    "error": str(e),
                    "paginas": 0,
                    "duracion_segundos": 0.0
                })

        # Guardar reporte en CSV
        if report_data:
            keys = report_data[0].keys()
            with open(log_csv, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=keys, delimiter=";")
                writer.writeheader()
                writer.writerows(report_data)

        return log_csv
