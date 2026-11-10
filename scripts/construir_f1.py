"""Genera los PDFs de F1, uno por versión, a partir de la fuente en Markdown.

Uso:
    uv run python scripts/construir_f1.py

La salida es determinista: misma fuente, mismos bytes y mismo hash SHA-256.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

RAIZ = Path(__file__).resolve().parents[1]
FUENTE = RAIZ / "datos" / "f1_manual" / "manual_mesa_ayuda.md"
CARPETA_SALIDA = RAIZ / "datos" / "f1_manual"

ORGANIZACION = "Corporación Valcora"
TITULO = "Manual de Mesa de Ayuda de TI"
VERSIONES = {
    "2026-1": {"fecha": "enero de 2026", "creacion": datetime(2026, 1, 15, tzinfo=timezone.utc)},
    "2026-2": {"fecha": "julio de 2026", "creacion": datetime(2026, 7, 1, tzinfo=timezone.utc)},
}
ETIQUETA_N2 = "Uso exclusivo: técnicos N2"

RE_CAPITULO = re.compile(r"^## (Capítulo \d+: .+)$")
RE_PROCEDIMIENTO = re.compile(r"^### (\d+\.\d+ .+)$")
RE_PASO = re.compile(r"^\d+\. .+$")
RE_BLOQUE_VERSION = re.compile(r"^:::\s*(\S+)$")


def lineas_de_version(fuente: str, version: str) -> list[str]:
    """Quita comentarios y deja solo el texto común y el de la versión pedida."""
    fuente = re.sub(r"<!--.*?-->", "", fuente, flags=re.S)
    lineas: list[str] = []
    activo = True
    for linea in fuente.splitlines():
        limpia = linea.strip()
        if limpia == ":::":
            activo = True
            continue
        bloque = RE_BLOQUE_VERSION.match(limpia)
        if bloque:
            if bloque.group(1) not in VERSIONES:
                raise ValueError(f"Versión desconocida en un bloque: {bloque.group(1)}")
            activo = bloque.group(1) == version
            continue
        if activo:
            lineas.append(limpia)
    return lineas


def bloques(lineas: list[str]) -> list[tuple[str, str]]:
    """Convierte las líneas en bloques (tipo, texto) para dibujarlos."""
    salida = []
    for linea in lineas:
        if not linea:
            continue
        if m := RE_CAPITULO.match(linea):
            salida.append(("capitulo", m.group(1)))
        elif m := RE_PROCEDIMIENTO.match(linea):
            salida.append(("procedimiento", m.group(1)))
        elif linea == "!N2":
            salida.append(("n2", ETIQUETA_N2))
        elif RE_PASO.match(linea):
            salida.append(("paso", linea))
        else:
            salida.append(("parrafo", linea))
    for _, texto in salida:
        texto.encode("latin-1")  # las fuentes base del PDF solo cubren latin-1
    return salida


class Manual(FPDF):
    def __init__(self, version: str) -> None:
        super().__init__(format="Letter")
        self.version = version
        self.set_margins(22, 18, 22)
        self.set_auto_page_break(auto=True, margin=22)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "", 8)
        self.set_text_color(110)
        self.cell(0, 5, f"{ORGANIZACION} · {TITULO} · Versión {self.version}", new_x="LMARGIN", new_y="NEXT")
        self.ln(6)
        self.set_text_color(0)

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(110)
        self.cell(0, 5, f"Página {self.page_no()}", align="C")
        self.set_text_color(0)

    def portada(self, fecha: str) -> None:
        self.add_page()
        self.set_y(80)
        self.set_font("Helvetica", "B", 24)
        self.multi_cell(0, 11, TITULO, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(6)
        self.set_font("Helvetica", "", 14)
        self.multi_cell(0, 8, ORGANIZACION, align="C", new_x="LMARGIN", new_y="NEXT")
        self.multi_cell(0, 8, f"Versión {self.version} · {fecha}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_y(-60)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(90)
        self.multi_cell(
            0, 5,
            "Documento ficticio elaborado con fines académicos para el curso CC3103 Procesamiento de "
            "Lenguaje Natural, Universidad del Valle de Guatemala. La organización, los sistemas, los "
            "nombres y los dominios .example no son reales.",
            align="C",
        )
        self.set_text_color(0)

    def dibujar(self, contenido: list[tuple[str, str]]) -> None:
        for tipo, texto in contenido:
            if tipo == "capitulo":
                self.add_page()
                self.set_font("Helvetica", "B", 16)
                self.multi_cell(0, 8, texto, new_x="LMARGIN", new_y="NEXT")
                self.ln(2)
            elif tipo == "procedimiento":
                if self.get_y() > self.h - 60:  # evita un título solo al final de la página
                    self.add_page()
                self.ln(3)
                self.set_font("Helvetica", "B", 12)
                self.multi_cell(0, 6.5, texto, new_x="LMARGIN", new_y="NEXT")
                self.ln(1)
            elif tipo == "n2":
                self.set_font("Helvetica", "BI", 9)
                self.set_fill_color(253, 236, 234)
                self.set_text_color(150, 30, 30)
                self.cell(self.get_string_width(texto) + 6, 6, texto, fill=True, new_x="LMARGIN", new_y="NEXT")
                self.set_text_color(0)
                self.ln(2)
            elif tipo == "paso":
                self.set_font("Helvetica", "", 10.5)
                margen = self.l_margin
                self.set_left_margin(margen + 5)
                self.set_x(margen + 5)
                self.multi_cell(0, 5.5, texto, new_x="LMARGIN", new_y="NEXT")
                self.set_left_margin(margen)
                self.ln(1)
            else:
                self.set_font("Helvetica", "", 10.5)
                self.multi_cell(0, 5.5, texto, new_x="LMARGIN", new_y="NEXT")
                self.ln(2)


def construir(version: str) -> Path:
    datos = VERSIONES[version]
    contenido = bloques(lineas_de_version(FUENTE.read_text(encoding="utf-8"), version))
    pdf = Manual(version)
    pdf.set_title(f"{TITULO} - Versión {version}")
    pdf.set_author(f"{ORGANIZACION} (organización ficticia)")
    pdf.set_subject("F1 - Proyecto final CC3103")
    pdf.set_lang("es")
    pdf.set_creation_date(datos["creacion"])
    pdf.portada(datos["fecha"])
    pdf.dibujar(contenido)
    salida = CARPETA_SALIDA / f"manual_mesa_ayuda_v{version}.pdf"
    pdf.output(str(salida))
    return salida


def main() -> None:
    for version in VERSIONES:
        ruta = construir(version)
        print(f"{ruta.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
