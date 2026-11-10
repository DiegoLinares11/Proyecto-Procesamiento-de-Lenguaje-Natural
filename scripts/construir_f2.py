"""Genera F2: artículos de soporte de Microsoft en un solo PDF con páginas.

Uso:
    uv run python scripts/construir_f2.py

Descarga los artículos de MicrosoftDocs/SupportArticles-docs en un commit fijo (licencia
CC BY 4.0), los guarda en datos/f2_microsoft/fuente/ y los convierte a PDF con la misma
estructura que F1: un artículo por capítulo y una sección por cada encabezado de nivel 2.
Si los Markdown ya están descargados, no los vuelve a pedir.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "datos" / "f2_microsoft"
FUENTE = CARPETA / "fuente"
PDF = CARPETA / "f2_microsoft_soporte.pdf"
INDICE = CARPETA / "articulos.json"

REPO = "MicrosoftDocs/SupportArticles-docs"
COMMIT = "aee5deb0299f00851f06ac2db644cb3198728a87"
FECHA_COMMIT = datetime(2026, 11, 10, tzinfo=timezone.utc)
ENCABEZADO = f"Microsoft SupportArticles-docs (CC BY 4.0) · commit {COMMIT[:7]}"

# (categoría del manual, ruta en el repositorio)
ARTICULOS = [
    ("CORREO", "Outlook/classic-outlook-for-windows/performance/outlook-2016-hangs-at-processing.md"),
    ("CORREO", "Outlook/classic-outlook-for-windows/performance/outlook-not-responding-error-or-outlook-freezes.md"),
    ("CORREO", "Outlook/classic-outlook-for-windows/performance/cannot-start-outlook-in-cached-mode-or-create-profile.md"),
    ("CORREO", "Outlook/classic-outlook-for-windows/synchronization/error-0x8004010f-when-sending-or-receiving-emails.md"),
    ("CORREO", "Outlook/classic-outlook-for-windows/connectivity/outlook-send-receive-errors-http-0-http-404-http-500.md"),
    ("CORREO", "Teams/teams-administration/clear-teams-cache.md"),
    ("CORREO", "Teams/meetings/fix-choppy-video.md"),
    ("EQUIPOS", "support/windows-client/installing-updates-features-roles/troubleshoot-windows-update-error-0x80070005.md"),
    ("EQUIPOS", "support/windows-client/installing-updates-features-roles/common-windows-update-errors.md"),
    ("EQUIPOS", "support/windows-client/performance/speed-up-your-computer.md"),
    ("EQUIPOS", "support/windows-client/performance/stop-code-error-troubleshooting.md"),
    ("EQUIPOS", "support/windows-client/performance/windows-based-computer-freeze-troubleshooting.md"),
    ("EQUIPOS", "support/windows-server/printing/printer-not-responding.md"),
    ("RED", "support/windows-client/networking/error-codes-for-dial-up-vpn-connection.md"),
    ("RED", "support/windows-client/networking/l2tp-ipsec-vpn-client-connection-issue.md"),
    ("RED", "support/windows-client/networking/network-connectivity-lost.md"),
    ("RED", "support/windows-client/networking/wireless-network-connectivity-issues-troubleshooting.md"),
    ("APLICACIONES", "support/windows-server/licensing-and-activation/error-0xc004f074-activate-windows.md"),
    ("ACCESO", "support/entra/entra-id/mfa/cannot-use-mfa-signin-lose-phone.md"),
    ("ACCESO", "support/entra/entra-id/mfa/troubleshoot-azure-mfa-issue.md"),
    ("ACCESO", "support/entra/entra-id/mfa/text-voice-call-verification-code-mfa-not-send.md"),
    ("ACCESO", "support/entra/entra-id/mfa/cannot-verify-account-reset-pwd.md"),
    ("ACCESO", "support/entra/entra-id/mfa/user-name-pwd-incorrect.md"),
    ("ACCESO", "support/entra/entra-id/mfa/cant-set-up-mfa-five-devices-registered.md"),
]

LATIN1 = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
    "…": "...", "•": "-", " ": " ", "→": "->", "≤": "<=", "≥": ">=",
    "​": "", "﻿": "", "™": "(TM)", "®": "(R)",
})


def descargar(ruta: str) -> str:
    destino = FUENTE / ruta
    if not destino.exists():
        url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{ruta}"
        with urllib.request.urlopen(url, timeout=30) as r:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(r.read())
    return destino.read_text(encoding="utf-8")


def a_latin1(texto: str) -> str:
    return texto.translate(LATIN1).encode("latin-1", "replace").decode("latin-1")


def limpiar_inline(texto: str) -> str:
    """Quita la sintaxis de Markdown y de Docs que no aporta al texto."""
    texto = html.unescape(re.sub(r"<[^>]+>", "", texto))      # etiquetas y entidades HTML
    texto = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", texto)        # imágenes
    texto = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", texto)    # enlaces: queda el texto
    texto = re.sub(r"(\*\*|__)(.+?)\1", r"\2", texto)         # negrita
    texto = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", texto)  # cursiva
    texto = texto.replace("`", "")
    return a_latin1(re.sub(r"\s+", " ", texto).strip())


def bloques(markdown: str) -> tuple[dict, list[tuple[str, str]]]:
    """Convierte el Markdown de Docs en bloques (tipo, texto)."""
    meta = {}
    if markdown.startswith("---"):
        cabecera, markdown = markdown[3:].split("\n---", 1)
        for linea in cabecera.splitlines():
            if ":" in linea:
                clave, valor = linea.split(":", 1)
                meta[clave.strip()] = valor.strip().strip("'\"")
    salida: list[tuple[str, str]] = []
    en_codigo = False
    for cruda in markdown.splitlines():
        linea = cruda.rstrip()
        if linea.strip().startswith("```"):
            en_codigo = not en_codigo
            continue
        if en_codigo:
            if linea.strip():
                salida.append(("codigo", a_latin1(linea.strip())))
            continue
        limpia = linea.strip()
        if not limpia or limpia.startswith((":::", "[!INCLUDE", "[!div", "<!--")) or re.match(r"^\|?\s*-{3,}", limpia):
            continue
        if m := re.match(r"^#\s+(.+)$", limpia):
            meta.setdefault("titulo_h1", limpiar_inline(m.group(1)))
        elif m := re.match(r"^##\s+(.+)$", limpia):
            salida.append(("seccion", limpiar_inline(m.group(1))))
        elif m := re.match(r"^#{3,6}\s+(.+)$", limpia):
            salida.append(("subtitulo", limpiar_inline(m.group(1))))
        elif m := re.match(r"^(\d+)\.\s+(.+)$", limpia):
            salida.append(("paso", f"{m.group(1)}. {limpiar_inline(m.group(2))}"))
        elif m := re.match(r"^[-*+]\s+(.+)$", limpia):
            salida.append(("vineta", "- " + limpiar_inline(m.group(1))))
        elif limpia.startswith(">"):
            texto = re.sub(r"^>\s*(\[!(\w+)\])?\s*", lambda m: f"{m.group(2).title()}: " if m.group(2) else "", limpia)
            if texto.strip():
                salida.append(("parrafo", limpiar_inline(texto)))
        elif limpia.startswith("|"):
            celdas = [limpiar_inline(c) for c in limpia.strip("|").split("|")]
            salida.append(("parrafo", " | ".join(c for c in celdas if c)))
        else:
            salida.append(("parrafo", limpiar_inline(limpia)))
    return meta, [(t, x) for t, x in salida if x]


class Documento(FPDF):
    def __init__(self) -> None:
        super().__init__(format="Letter")
        self.set_margins(22, 18, 22)
        self.set_auto_page_break(auto=True, margin=22)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "", 8)
        self.set_text_color(110)
        self.cell(0, 5, ENCABEZADO, new_x="LMARGIN", new_y="NEXT")
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

    def texto(self, contenido: str, sangria: float = 0, estilo: str = "", tamano: float = 10, alto: float = 5.2) -> None:
        self.set_font("Courier" if estilo == "codigo" else "Helvetica", "B" if estilo == "B" else "", tamano)
        margen = self.l_margin
        self.set_left_margin(margen + sangria)
        self.set_x(margen + sangria)
        self.multi_cell(0, alto, contenido, new_x="LMARGIN", new_y="NEXT")
        self.set_left_margin(margen)


def main() -> None:
    FUENTE.mkdir(parents=True, exist_ok=True)
    pdf = Documento()
    pdf.set_title("F2 - Artículos de soporte de Microsoft")
    pdf.set_author("Microsoft (CC BY 4.0); compilación del equipo del proyecto")
    pdf.set_lang("en")
    pdf.set_creation_date(FECHA_COMMIT)

    pdf.add_page()
    pdf.set_y(60)
    pdf.set_font("Helvetica", "B", 20)
    pdf.multi_cell(0, 10, "F2: Artículos de soporte de Microsoft", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(
        0, 5.5,
        f"Compilación de {len(ARTICULOS)} artículos de {REPO}, commit {COMMIT}. Contenido de Microsoft "
        "publicado bajo la licencia Creative Commons Attribution 4.0 International (CC BY 4.0). Se "
        "convirtió de Markdown a PDF y se quitaron imágenes y enlaces; el texto no se modificó.",
        align="C", new_x="LMARGIN", new_y="NEXT",
    )

    indice = []
    for numero, (categoria, ruta) in enumerate(ARTICULOS, start=1):
        meta, contenido = bloques(descargar(ruta))
        titulo = limpiar_inline(meta.get("title") or meta.get("titulo_h1") or Path(ruta).stem)
        pdf.add_page()
        pagina = pdf.page_no()
        pdf.set_font("Helvetica", "B", 15)
        pdf.multi_cell(0, 7.5, f"Artículo {numero}: {titulo}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 6.5, f"{numero}.0 Overview", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        seccion = 0
        for tipo, texto in contenido:
            if tipo == "seccion":
                seccion += 1
                if pdf.get_y() > pdf.h - 60:
                    pdf.add_page()
                pdf.ln(3)
                pdf.set_font("Helvetica", "B", 12)
                pdf.multi_cell(0, 6.5, f"{numero}.{seccion} {texto}", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)
            elif tipo == "subtitulo":
                pdf.texto(texto, estilo="B", tamano=10.5)
                pdf.ln(1)
            elif tipo == "paso":
                pdf.texto(texto, sangria=5)
                pdf.ln(0.8)
            elif tipo in ("vineta", "codigo"):
                pdf.texto(texto, sangria=5, estilo="codigo" if tipo == "codigo" else "", tamano=9 if tipo == "codigo" else 10)
                pdf.ln(0.8)
            else:
                pdf.texto(texto)
                pdf.ln(1.8)
        indice.append({
            "articulo": numero,
            "slug": Path(ruta).stem,
            "titulo": titulo,
            "categoria": categoria,
            "ruta": ruta,
            "url": f"https://github.com/{REPO}/blob/{COMMIT}/{ruta}",
            "fecha_articulo": meta.get("ms.date", ""),
            "pagina_inicio": pagina,
            "pagina_fin": pdf.page_no(),
        })

    pdf.output(str(PDF))
    INDICE.write_text(json.dumps({"repositorio": REPO, "commit": COMMIT, "licencia": "CC BY 4.0",
                                  "articulos": indice}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{PDF.relative_to(RAIZ)}: {pdf.page_no()} páginas, {len(indice)} artículos")


if __name__ == "__main__":
    main()
