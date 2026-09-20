"""
cleaner.py: Limpieza, normalización y postprocesamiento avanzado de Markdown.
Transforma salidas de OCR en Markdown limpio, legible y listo para indexación o RAG.
"""

import re
from typing import List, Optional


class MarkdownCleaner:
    def __init__(
        self,
        merge_hyphens: bool = True,
        clean_headers_footers: bool = True,
        normalize_tables: bool = True
    ):
        self.merge_hyphens = merge_hyphens
        self.clean_headers_footers = clean_headers_footers
        self.normalize_tables = normalize_tables

    def clean(self, md_text: str) -> str:
        """Aplica la secuencia completa de limpieza."""
        if not md_text:
            return ""

        text = md_text

        # 1. Normalizar saltos de línea y caracteres de control (form-feed, zero-width)
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        text = text.replace('\x0c', '\n\n')  # Form feed de páginas
        text = text.replace('\u200b', '')    # Zero-width space
        text = text.replace('\ufeff', '')    # BOM

        # 2. Deshacer ligaduras tipográficas habituales que confunden motores de búsqueda
        ligatures = {
            'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
            '’': "'", '“': '"', '”': '"', '—': ' - ', '–': ' - '
        }
        for k, v in ligatures.items():
            text = text.replace(k, v)

        # 3. Unir palabras separadas por guion al final de línea (ej: 'cons-\ntitución' -> 'constitución')
        if self.merge_hyphens:
            text = self._merge_hyphenated_words(text)

        # 4. Limpieza de números de página y encabezados huérfanos
        if self.clean_headers_footers:
            text = self._remove_orphan_page_numbers(text)

        # 5. Normalización y ajuste de tablas Markdown
        if self.normalize_tables:
            text = self._normalize_markdown_tables(text)

        # 6. Colapsar saltos de línea excesivos (máximo 2 saltos consecutivos)
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def _merge_hyphenated_words(self, text: str) -> str:
        """
        Detecta palabras cortadas por guion y salto de línea.
        Ej: 'investiga-\nción' -> 'investigación'.
        Preserva casos de guiones verdaderos como 'político-militar'.
        """
        # Letras del español incluyendo tildes y eñes
        pattern = r'([a-zA-ZáéíóúÁÉÍÓÚñÑ]{2,})-\s*\n\s*([a-zA-ZáéíóúÁÉÍÓÚñÑ]{2,})'
        return re.sub(pattern, r'\1\2', text)

    def _remove_orphan_page_numbers(self, text: str) -> str:
        """
        Elimina patrones típicos de paginación que ensucian el texto:
        - 'Página 14 de 98'
        - 'Pág. 14'
        - '- 14 -'
        - '[14]'
        """
        lines = text.split('\n')
        cleaned_lines = []
        
        # Regex para líneas que son exclusivamente numeración de página
        page_pattern = re.compile(
            r'^\s*(?:p[áa]g(?:ina)?\.?\s*\d+(?:\s*(?:de|/)\s*\d+)?|\d+\s*(?:de|/)\s*\d+|[-–—]\s*\d+\s*[-–—]|\[\d+\]|\d+)\s*$',
            re.IGNORECASE
        )

        for line in lines:
            if page_pattern.match(line):
                continue
            cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def _normalize_markdown_tables(self, text: str) -> str:
        """
        Asegura que las tablas Markdown tengan sintaxis válida:
        - Quita espacios redundantes alrededor de los pipes '|'.
        - Asegura delimitadores en la segunda fila si faltan.
        """
        lines = text.split('\n')
        in_table = False
        table_buffer: List[str] = []
        result: List[str] = []

        def flush_table(buffer: List[str]) -> List[str]:
            if not buffer:
                return []
            if len(buffer) == 1:
                return buffer  # No es una tabla completa

            # Normalizar cada fila
            processed = []
            for row in buffer:
                # Quitar espacios múltiples dentro de celdas
                cells = [c.strip() for c in row.split('|')]
                if len(cells) >= 3:
                    # Restaurar fila bien formateada
                    processed.append('| ' + ' | '.join(cells[1:-1]) + ' |')
                else:
                    processed.append(row)

            # Verificar si existe fila delimitadora |---|---|
            if len(processed) >= 2 and not re.search(r'\|(?:\s*[:-]+[-| :]*)\|', processed[1]):
                num_cols = processed[0].count('|') - 1
                if num_cols > 0:
                    divider = '| ' + ' | '.join(['---'] * num_cols) + ' |'
                    processed.insert(1, divider)

            return processed

        for line in lines:
            trimmed = line.strip()
            if trimmed.startswith('|') and trimmed.endswith('|'):
                in_table = True
                table_buffer.append(trimmed)
            else:
                if in_table:
                    result.extend(flush_table(table_buffer))
                    table_buffer = []
                    in_table = False
                result.append(line)

        if in_table:
            result.extend(flush_table(table_buffer))

        return '\n'.join(result)
