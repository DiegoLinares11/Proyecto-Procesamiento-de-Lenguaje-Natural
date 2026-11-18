from tickets_rag.pii import detectar, enmascarar, luhn_valido


def test_enmascara_correo_y_conserva_el_sentido():
    texto, encontrados = enmascarar("Mi correo es cliente@example.com y no recibo mi pedido.")
    assert texto == "Mi correo es [EMAIL_REDACTED] y no recibo mi pedido."
    assert encontrados == {"EMAIL": 1}


def test_no_enmascara_el_buzon_institucional():
    texto, encontrados = enmascarar("Escriba a mesadeayuda@valcora.example")
    assert "mesadeayuda@valcora.example" in texto
    assert encontrados == {}


def test_telefono_dpi_y_tarjeta():
    texto, encontrados = enmascarar(
        "Llámame al +502 5555-1234, mi DPI es 2456 78901 0101 y la tarjeta 4111 1111 1111 1111."
    )
    assert "[PHONE_REDACTED]" in texto
    assert "[DPI_REDACTED]" in texto
    assert "[CARD_REDACTED]" in texto
    assert encontrados == {"PHONE": 1, "DPI": 1, "CARD": 1}


def test_no_confunde_codigos_de_error_ni_extensiones():
    texto = "Error 0x80070005, extensión 4357, ERP-401 y la IP 169.254.10.2"
    assert enmascarar(texto) == (texto, {})


def test_volcado_de_memoria_no_cuenta_como_tarjeta():
    texto = "rbx=0000000000000000 ffffa884`c0c40000 00000000`00000000"
    assert "CARD" not in enmascarar(texto)[1]


def test_tarjeta_sin_luhn_valido_no_se_enmascara():
    assert not luhn_valido("4111 1111 1111 1112")
    texto, encontrados = enmascarar("Pedido 4111 1111 1111 1112")
    assert "CARD" not in encontrados


def test_spans_originales_no_contienen_valores_ni_se_solapan():
    texto = "Correo cliente@example.com, teléfono 5555-1234 y DPI 2456 78901 0101."
    detecciones = detectar(texto)
    assert [d.tipo for d in detecciones] == ["EMAIL", "PHONE", "DPI"]
    assert [texto[d.inicio:d.fin] for d in detecciones] == ["cliente@example.com", "5555-1234", "2456 78901 0101"]
    assert all(a.fin <= b.inicio for a, b in zip(detecciones, detecciones[1:]))
    assert "cliente@example.com" not in repr(detecciones)
    assert all(0 < d.score <= 1 for d in detecciones)


def test_tarjeta_tiene_prioridad_sobre_telefono_dentro_del_mismo_numero():
    texto = "4111 1111 1111 1111"
    detecciones = detectar(texto)
    assert [(d.tipo, d.inicio, d.fin) for d in detecciones] == [("CARD", 0, len(texto))]
    assert enmascarar(texto) == ("[CARD_REDACTED]", {"CARD": 1})
