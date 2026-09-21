"""
cli.py: Interfaz de línea de comandos para agy_ocr_md.
Permite ejecutar el pipeline sobre un archivo individual o sobre carpetas completas.
"""

import argparse
import sys
import logging
from pathlib import Path

from .config import PipelineConfig
from .pipeline import AgyOcrPipeline


def setup_logger(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=level
    )


def main():
    parser = argparse.ArgumentParser(
        description="agy_ocr_md: Pipeline inteligente para extracción de PDF y OCR a Markdown estructurado (.md)"
    )
    
    parser.add_argument("-i", "--input", required=True, type=Path, help="Ruta al archivo PDF o carpeta de entrada")
    parser.add_argument("-o", "--output", required=False, type=Path, help="Ruta al archivo .md de salida o carpeta de destino")
    
    parser.add_argument("--mode", choices=["hybrid", "docling", "doctr", "digital", "tesseract"], default="hybrid",
                        help="Modo de extracción: hybrid (router inteligente por página), docling, doctr, digital, tesseract")
    
    parser.add_argument("--lang", default="spa+eng", help="Idiomas para OCR (default: spa+eng)")
    parser.add_argument("--dpi", type=int, default=300, help="DPI para rasterizado estándar (default: 300)")
    parser.add_argument("--dpi-handwritten", type=int, default=350, help="DPI para texto manuscrito (default: 350)")
    
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto", help="Acelerador de hardware (default: auto)")
    parser.add_argument("--no-clean", action="store_true", help="Desactiva la limpieza automática de Markdown")
    parser.add_argument("--force-reprocess", action="store_true", help="Reprocesar incluso si el .md ya existe")
    parser.add_argument("-v", "--verbose", action="store_true", help="Modo detallado de depuración")

    args = parser.parse_args()
    setup_logger(args.verbose)

    config = PipelineConfig(
        language=args.lang,
        dpi_default=args.dpi,
        dpi_handwritten=args.dpi_handwritten,
        device=args.device,
        clean_markdown=not args.no_clean,
        skip_existing=not args.force_reprocess
    )

    pipeline = AgyOcrPipeline(config)
    input_path = args.input.resolve()

    if input_path.is_file():
        output_file = args.output or input_path.with_suffix(".md")
        if args.output and args.output.suffix.lower() != ".md":
            output_file = args.output / input_path.with_suffix(".md").name
        output_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"📄 Procesando archivo: {input_path.name}")
        force_engine = None if args.mode == "hybrid" else args.mode
        res = pipeline.process_file(input_path, output_file, force_engine=force_engine)
        print(f"✅ Resultado: {res['estado']} | Páginas: {res['paginas']} | Tablas: {res.get('tablas', 0)} | Duración: {res['duracion_segundos']}s")
        print(f"📁 Markdown generado en: {res['output_md']}")

    elif input_path.is_dir():
        output_dir = args.output or Path(str(input_path) + "_md")
        print(f"📂 Procesando lote en: {input_path}")
        print(f"🎯 Carpeta de salida: {output_dir}")
        log_csv = pipeline.process_directory(input_path, output_dir)
        print(f"✅ Lote finalizado. Reporte CSV en: {log_csv}")
    else:
        print(f"❌ Error: La ruta {input_path} no existe.")
        sys.exit(1)


if __name__ == "__main__":
    main()
