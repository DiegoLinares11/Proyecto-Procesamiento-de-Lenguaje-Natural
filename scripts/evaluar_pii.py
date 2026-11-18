"""Evalúa sólo PII local con el holdout congelado, conservando cada corrida.

Uso: uv run python scripts/evaluar_pii.py
No ejecuta un LLM, no llama una API y no lee claves ni una base de datos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from importlib.metadata import distribution
from pathlib import Path

from tickets_rag.evaluacion_pii import (
    META_RECALL,
    SHA256_BANCO,
    VERSION_BANCO,
    cargar_banco,
    evaluar_caso,
    resumir,
    sha256_archivo,
)

RAIZ = Path(__file__).resolve().parents[1]
BANCO = RAIZ / "evaluacion" / "pii_sembrada.jsonl"
SALIDA = RAIZ / "resultados" / "seguridad" / "pii"
MODELO_PERSONAS = "es_core_news_md"
VERSION_MODELO_PERSONAS = "3.8.0"
MODELOS_ESPERADOS = {"es": ("es_core_news_md", "3.8.0"), "en": ("en_core_web_md", "3.8.0")}


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(ruta: Path, contenido: dict) -> None:
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _metadata_modelos(modelos: dict) -> dict:
    """Lee metadatos instalados sin importar/cargar spaCy ni analizar textos.

    Los hashes de METADATA, meta.json y config.cfg permiten identificar el paquete
    y su configuración. No pretenden ser hashes de todos sus pesos binarios.
    """
    resultado = {}
    for idioma, esperado in MODELOS_ESPERADOS.items():
        nombre, version_esperada = esperado
        declarado = modelos.get(idioma, {})
        if declarado.get("nombre") != nombre or declarado.get("version") != version_esperada:
            raise RuntimeError("Los modelos declarados no coinciden con las versiones fijadas")
        paquete = distribution(nombre)
        if paquete.version != version_esperada:
            raise RuntimeError("El modelo instalado no coincide con la versión declarada")
        metadata = paquete.read_text("METADATA")
        if not metadata:
            raise RuntimeError("Faltan metadatos del paquete del modelo")
        hashes = {"METADATA": hashlib.sha256(metadata.encode("utf-8")).hexdigest()}
        metadatos_modelo = 0
        for archivo in paquete.files or ():
            if archivo.name in ("meta.json", "config.cfg") and archivo.parts[0] == nombre:
                hashes[str(archivo)] = sha256_archivo(Path(paquete.locate_file(archivo)))
                metadatos_modelo += archivo.name == "meta.json"
        if not metadatos_modelo:
            raise RuntimeError("Falta meta.json del modelo instalado")
        resultado[idioma] = {"distribucion": nombre, "version_instalada": paquete.version, "archivos_sha256": hashes}
    return resultado


def _reporte(resumen: dict) -> str:
    def numero(valor):
        return f"{valor:.4f}" if valor is not None else "no medido"

    m = resumen["estricto"]
    lineas = [
        "# Evaluación local de PII sembrada", "",
        "Muestra sintética de IA para seguridad; no sustituye los 20 tickets manuales.", "",
        f"SHA-256 del banco: `{SHA256_BANCO}`.", "",
        f"Textos: {resumen['textos_evaluados']}. Entidades: {resumen['entidades_referencia']}.",
        f"TP/FP/FN exactos: {m['tp']}/{m['fp']}/{m['fn']}.",
        f"Precisión: {numero(m['precision'])}; recall: {numero(m['recall'])}; F1: {numero(m['f1'])}.",
        f"Recall de redacción efectiva: {numero(resumen['redaccion']['recall_efectivo'])}.",
        f"Meta ≥ {META_RECALL}: {'cumplida' if resumen['cumple_meta'] else 'no cumplida'}.", "",
        "| Tipo | TP | FP | FN | Precisión | Recall | F1 | Recall efectivo |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tipo, metrica in resumen["por_tipo"].items():
        lineas.append(
            f"| {tipo} | {metrica['tp']} | {metrica['fp']} | {metrica['fn']} | "
            f"{numero(metrica['precision'])} | {numero(metrica['recall'])} | "
            f"{numero(metrica['f1'])} | {numero(metrica['recall_efectivo'])} |"
        )
    negativos = resumen["negativos"]
    lineas.extend([
        "", f"Fragmentos técnicos afectados: {negativos['fragmentos_afectados']}/{negativos['fragmentos']}.",
        f"Detecciones sobre esos negativos: {negativos['detecciones_sobre_negativos']}.",
        f"Textos con redacción no íntegra: {resumen['redaccion']['textos_no_integros']}.", "",
        "Los falsos positivos/negativos se conservan por ID, tipo y offsets en casos.jsonl.",
        "Las métricas exigen coincidencia exacta 1:1 y corresponden a la configuración y hashes del manifiesto.",
        "Se conservan las corridas anteriores; repetir este banco con una configuración distinta no constituye un nuevo holdout ciego.",
        "El tamaño y origen sintético del banco limitan la generalización de estos resultados.", "",
    ])
    return "\n".join(lineas)


def ejecutar(banco: Path, salida: Path, *, detector=None, enmascarador=None, informador=None) -> tuple[int, Path]:
    """Permite fakes offline; la ejecución normal importa el detector local perezosamente."""
    carpeta = salida / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + SHA256_BANCO[:8])
    carpeta.mkdir(parents=True, exist_ok=False)
    manifiesto = {
        "version_formato": 2,
        "inicio_utc": _ahora(),
        "estado": "iniciado",
        "procedencia": "evaluacion_actual_local_sin_llm",
        "interpretacion": "comprobacion_versionada_no_holdout_ciego_nuevo",
        "banco": {"archivo": banco.name, "version": VERSION_BANCO, "sha256_esperado": SHA256_BANCO},
        "meta_recall": META_RECALL,
        "entorno": {"python": platform.python_version()},
        "codigo_sha256": {},
        "dependencias_sha256": {},
        "metadata_modelos": None,
        "detector": None,
        "textos_completos": 0,
        "metricas": None,
    }
    resultados = []
    etapa = "banco"
    codigo = 2
    try:
        manifiesto["banco"]["sha256_observado"] = sha256_archivo(banco)
        casos = cargar_banco(banco)
        manifiesto["banco"]["textos"] = len(casos)
        for relativa in ("src/tickets_rag/pii.py", "src/tickets_rag/evaluacion_pii.py", "scripts/evaluar_pii.py"):
            ruta = RAIZ / relativa
            manifiesto["codigo_sha256"][relativa] = sha256_archivo(ruta)
        for relativa in ("pyproject.toml", "uv.lock"):
            manifiesto["dependencias_sha256"][relativa] = sha256_archivo(RAIZ / relativa)
        etapa = "salud_detector"
        if detector is None or enmascarador is None or informador is None:
            from tickets_rag.pii import detectar, enmascarar, informacion_detector

            detector = detector or detectar
            enmascarador = enmascarador or enmascarar
            informador = informador or informacion_detector
        informacion = informador()
        claves = (
            "local", "ner_disponible", "modelo_personas", "version_modelo_personas",
            "spacy", "presidio_analyzer", "score_personas", "tipos",
            "idioma", "modelos", "componentes_activos", "configuracion", "filtro_personas",
        )
        manifiesto["detector"] = {k: informacion.get(k) for k in claves}
        if (
            informacion.get("local") is not True or informacion.get("ner_disponible") is not True
            or informacion.get("modelo_personas") != MODELO_PERSONAS
            or informacion.get("version_modelo_personas") != VERSION_MODELO_PERSONAS
            or not informacion.get("spacy") or not informacion.get("presidio_analyzer")
            or not isinstance(informacion.get("modelos"), dict)
            or informacion.get("idioma") != "es"
            or not informacion.get("componentes_activos") or not informacion.get("configuracion")
            or not informacion.get("filtro_personas")
        ):
            raise RuntimeError("Detector local o modelo no disponible en la versión fijada")
        manifiesto["metadata_modelos"] = _metadata_modelos(informacion["modelos"])
        etapa = "evaluacion"
        for caso in casos:
            detecciones = detector(caso["texto"])
            texto_redactado, conteos = enmascarador(caso["texto"])
            resultados.append(evaluar_caso(caso, detecciones, texto_redactado, conteos))
            manifiesto["textos_completos"] = len(resultados)
        resumen = resumir(resultados)
        completo = len(resultados) == 30
        manifiesto["estado"] = "completo" if completo else "fallido"
        manifiesto["metricas"] = "resumen.json" if completo else None
        _json(carpeta / "resumen.json", resumen)
        (carpeta / "reporte.md").write_text(_reporte(resumen), encoding="utf-8")
        codigo = 0 if completo and resumen["cumple_meta"] else 1
    except Exception as exc:
        manifiesto["estado"] = "fallido"
        manifiesto["error"] = {"etapa": etapa, "tipo": type(exc).__name__}
        # Los mensajes de excepciones pueden contener texto: nunca serializarlos.
        codigo = 3 if etapa == "banco" else 2
    finally:
        manifiesto["fin_utc"] = _ahora()
        manifiesto["codigo_salida"] = codigo
        (carpeta / "casos.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in resultados), encoding="utf-8"
        )
        _json(carpeta / "manifiesto.json", manifiesto)
    return codigo, carpeta


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__)
    argumentos.add_argument("--banco", type=Path, default=BANCO)
    argumentos.add_argument("--salida", type=Path, default=SALIDA)
    argumentos.add_argument("--solo-validar", action="store_true", help="verifica hash/anotaciones sin cargar NER ni crear resultados")
    args = argumentos.parse_args()
    if args.solo_validar:
        try:
            casos = cargar_banco(args.banco)
        except (OSError, ValueError):
            print("Banco inválido: no coincide con la versión congelada o sus anotaciones.")
            return 3
        print(f"Banco congelado válido: {len(casos)} textos; SHA-256 {SHA256_BANCO}.")
        return 0
    codigo, carpeta = ejecutar(args.banco, args.salida)
    print(f"Evidencia local: {carpeta}")
    if codigo == 0:
        print("Evaluación completa; recall estricto y efectivo cumplen la meta.")
    elif codigo == 1:
        print("Evaluación completa; la meta o la integridad de redacción no se cumple.")
    else:
        print("Evaluación fallida/incompleta: consulte el manifiesto; no hay métricas completas.")
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
