"""Clasificador de la línea base: TF-IDF de palabras y de caracteres con regresión logística.

Los n-gramas de caracteres ayudan con los errores de escritura («contrasena», «outlok»).
El texto se enmascara antes de entrenar y de predecir, igual que en el resto del sistema.
"""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline, make_union

from tickets_rag.f3 import SEMILLA
from tickets_rag.pii import enmascarar


def preparar(texto: str) -> str:
    return enmascarar(texto)[0]


def construir() -> Pipeline:
    return make_pipeline(
        make_union(
            TfidfVectorizer(strip_accents="unicode", ngram_range=(1, 2), sublinear_tf=True),
            TfidfVectorizer(analyzer="char_wb", strip_accents="unicode", ngram_range=(3, 5), sublinear_tf=True),
        ),
        LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEMILLA),
    )
