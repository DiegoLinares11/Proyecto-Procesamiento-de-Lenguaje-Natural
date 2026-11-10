"""Parámetros de los tickets sintéticos de F3.

La semilla fija todo lo que se evalúa: categoría, escenario, prioridad, fechas, datos personales
ficticios y estilo. El modelo de lenguaje solo redacta el texto con esos parámetros, así que las
etiquetas no dependen de lo que escriba.

La prioridad sale de las reglas del procedimiento 1.4 del manual: seguridad, varias personas
afectadas o sin alternativa es ALTA; con alternativa es MEDIA; consulta o molestia menor es BAJA.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from tickets_rag.pii import luhn_valido

SEMILLA = 2026
TOTAL_TICKETS = 300
TICKETS_PRUEBA = 60
CAMBIO_DE_VERSION = date(2026, 7, 1)  # desde aquí rige la versión 2026-2 del manual

PRIORIDAD_POR_PERFIL = {
    "seguridad": "ALTA",
    "varios": "ALTA",
    "sin_alternativa": "ALTA",
    "con_alternativa": "MEDIA",
    "menor": "BAJA",
}

DESCRIPCION_PERFIL = {
    "seguridad": "Hay señales de un posible incidente de seguridad.",
    "varios": "El problema afecta a varias personas, no solo a quien escribe.",
    "sin_alternativa": "La persona no puede trabajar y no tiene ninguna alternativa.",
    "con_alternativa": "Le afecta el trabajo, pero tiene una alternativa temporal.",
    "menor": "Es una consulta o una molestia menor que puede esperar.",
}

PESO_CATEGORIA = {
    "ACCESO": 0.25,
    "CORREO": 0.18,
    "EQUIPOS": 0.18,
    "RED": 0.15,
    "APLICACIONES": 0.16,
    "OTRO": 0.08,
}


@dataclass(frozen=True)
class Opcion:
    perfil: str
    peso: float
    detalles: tuple[str, ...]


@dataclass(frozen=True)
class Escenario:
    id: str
    categoria: str
    seccion: str  # procedimiento del manual que lo resuelve
    descripcion: str
    opciones: tuple[Opcion, ...]
    escala_a_n2: bool = False


def _o(perfil: str, peso: float, *detalles: str) -> Opcion:
    return Opcion(perfil, peso, detalles)


ESCENARIOS: tuple[Escenario, ...] = (
    # ACCESO
    Escenario("a1", "ACCESO", "2.1", "Olvidó su contraseña de red o le expiró.", (
        _o("sin_alternativa", 0.5, "volvió de vacaciones y no recuerda la contraseña", "la contraseña expiró y no puede entrar a la computadora"),
        _o("con_alternativa", 0.4, "aún tiene sesión abierta en el teléfono, pero no puede entrar a la computadora"),
        _o("menor", 0.1, "pregunta cómo cambiar la contraseña antes de que expire"),
    )),
    Escenario("a2", "ACCESO", "2.2", "Su cuenta se bloquea por intentos fallidos.", (
        _o("sin_alternativa", 0.4, "la cuenta quedó bloqueada y no puede iniciar sesión"),
        _o("con_alternativa", 0.35, "la cuenta se bloquea cada rato desde que cambió la contraseña"),
        _o("seguridad", 0.25, "recibió avisos de intentos de inicio de sesión que no hizo, desde otro país"),
    )),
    Escenario("a3", "ACCESO", "2.3", "Cambió de teléfono y necesita registrar MFA en el nuevo; conserva el anterior.", (
        _o("con_alternativa", 0.5, "todavía tiene el teléfono viejo a la mano"),
        _o("menor", 0.5, "quiere pasar Microsoft Authenticator al teléfono nuevo"),
    )),
    Escenario("a4", "ACCESO", "2.4", "Perdió o le robaron el teléfono con MFA y no puede aprobar el inicio de sesión.", (
        _o("sin_alternativa", 0.7, "perdió el teléfono y no puede aprobar el inicio de sesión"),
        _o("seguridad", 0.3, "le robaron el teléfono con Microsoft Authenticator"),
    ), escala_a_n2=True),
    Escenario("a5", "ACCESO", "2.5", "Necesita acceso a una carpeta compartida.", (
        _o("menor", 0.6, "necesita acceso de lectura a una carpeta de otra área"),
        _o("con_alternativa", 0.4, "un compañero le pasa los archivos por correo mientras tanto"),
    )),
    Escenario("a6", "ACCESO", "6.2", "Necesita permisos dentro del ERP SIRA, por ejemplo para aprobar órdenes de compra.", (
        _o("menor", 0.5, "le asignaron nuevas funciones y necesita un módulo de SIRA"),
        _o("con_alternativa", 0.5, "su jefe aprueba por ahora las órdenes que le tocan"),
    )),
    # CORREO
    Escenario("c1", "CORREO", "3.1", "Outlook no abre o se queda en «Procesando».", (
        _o("con_alternativa", 0.7, "puede ver el correo desde el navegador", "aparece el error 0x800CCC0E al abrir Outlook"),
        _o("sin_alternativa", 0.3, "necesita enviar un reporte urgente y Outlook no responde"),
    )),
    Escenario("c2", "CORREO", "3.2", "Su buzón está lleno y no puede recibir correos.", (
        _o("con_alternativa", 0.5, "le aparece el aviso de buzón casi lleno"),
        _o("menor", 0.5, "pregunta cómo liberar espacio del correo"),
    )),
    Escenario("c3", "CORREO", "3.3", "Recibió un correo sospechoso que parece phishing.", (
        _o("seguridad", 0.6, "hizo clic en el enlace y escribió su contraseña", "abrió el adjunto de un supuesto proveedor"),
        _o("con_alternativa", 0.4, "solo recibió el correo y no hizo clic en nada"),
    )),
    Escenario("c4", "CORREO", "3.4", "Teams no tiene audio o video, o no conecta a reuniones.", (
        _o("con_alternativa", 0.6, "en las reuniones nadie lo escucha"),
        _o("sin_alternativa", 0.2, "tiene que presentar en una reunión con un cliente en una hora"),
        _o("menor", 0.2, "la cámara a veces no enciende en Teams"),
    )),
    Escenario("c5", "CORREO", "3.5", "Borró un correo y quiere recuperarlo.", (
        _o("menor", 0.6, "borró un correo de la semana pasada"),
        _o("con_alternativa", 0.4, "borró un correo con una factura que necesita"),
    )),
    Escenario("c6", "CORREO", "7.1", "Quiere configurar el correo corporativo en su teléfono personal.", (
        _o("menor", 1.0, "quiere ver el correo del trabajo en su celular"),
    )),
    # EQUIPOS
    Escenario("e1", "EQUIPOS", "4.1", "Su computadora está lenta.", (
        _o("menor", 0.6, "la computadora tarda mucho en abrir programas"),
        _o("con_alternativa", 0.3, "la computadora se congela varias veces al día"),
        _o("sin_alternativa", 0.1, "la computadora está tan lenta que no puede trabajar"),
    )),
    Escenario("e2", "EQUIPOS", "4.2", "Le aparece una pantalla azul o el equipo no enciende.", (
        _o("sin_alternativa", 0.6, "la computadora no enciende", "aparece una pantalla azul con el código 0x0000007E"),
        _o("con_alternativa", 0.4, "tuvo una pantalla azul con el código 0x00000050, pero volvió a encender"),
    )),
    Escenario("e3", "EQUIPOS", "4.3", "La impresora tiene documentos atascados en la cola.", (
        _o("con_alternativa", 0.6, "puede imprimir en la impresora de otro piso"),
        _o("varios", 0.4, "nadie del piso puede imprimir en la IMP-03-02"),
    )),
    Escenario("e4", "EQUIPOS", "4.4", "Solicita una computadora nueva o un reemplazo.", (
        _o("menor", 1.0, "ingresó un colaborador nuevo a su equipo", "su computadora ya tiene más de cinco años"),
    )),
    Escenario("e5", "EQUIPOS", "4.5", "Le aparece el error 0x80070005 al instalar actualizaciones.", (
        _o("con_alternativa", 0.5, "las actualizaciones fallan con 0x80070005"),
        _o("menor", 0.5, "Windows dice que hay actualizaciones pendientes que no se instalan"),
    )),
    # RED
    Escenario("r1", "RED", "5.1", "No tiene internet en la oficina.", (
        _o("sin_alternativa", 0.5, "no tiene internet en su escritorio"),
        _o("con_alternativa", 0.3, "el cable no funciona, pero el Wi-Fi sí"),
        _o("varios", 0.2, "nadie del piso tiene internet"),
    )),
    Escenario("r2", "RED", "5.2", "La VPN no conecta cuando trabaja desde casa.", (
        _o("sin_alternativa", 0.6, "trabaja desde casa y la VPN no conecta"),
        _o("con_alternativa", 0.4, "la VPN se desconecta seguido, pero logra entrar a veces"),
    )),
    Escenario("r3", "RED", "5.3", "Necesita acceso a Wi-Fi para visitantes.", (
        _o("menor", 1.0, "mañana llegan visitantes de un proveedor"),
    )),
    # APLICACIONES
    Escenario("p1", "APLICACIONES", "6.1", "Necesita instalar un programa.", (
        _o("menor", 0.7, "necesita instalar un programa para editar PDF"),
        _o("con_alternativa", 0.3, "necesita un programa que no está en el catálogo"),
    )),
    Escenario("p2", "APLICACIONES", "6.2", "Tiene errores en el ERP SIRA.", (
        _o("con_alternativa", 0.5, "SIRA le muestra ERP-401 al entrar"),
        _o("menor", 0.3, "SIRA le dice ERP-503 un domingo en la noche"),
        _o("varios", 0.2, "varias personas de finanzas ven ERP-500 en SIRA"),
    )),
    Escenario("p3", "APLICACIONES", "6.3", "Office muestra un error de activación.", (
        _o("con_alternativa", 0.6, "Word dice que el producto no está activado, error 0xC004F074"),
        _o("menor", 0.4, "Excel muestra un aviso de licencia"),
    )),
    Escenario("p4", "APLICACIONES", "6.4", "Un sitio interno no carga o muestra error de certificado.", (
        _o("con_alternativa", 0.6, "el navegador muestra NET::ERR_CERT_DATE_INVALID"),
        _o("varios", 0.2, "el sitio interno de planillas no le abre a nadie del área"),
        _o("menor", 0.2, "un sitio interno no carga desde su casa"),
    )),
    # OTRO
    Escenario("o1", "OTRO", "7.1", "Pide ayuda con algo fuera del alcance de la mesa de ayuda.", (
        _o("menor", 1.0, "su laptop personal tiene un virus", "el internet de su casa está lento", "quiere instalar un juego en su computadora personal"),
    )),
    Escenario("o2", "OTRO", "7.2", "Quiere reservar o pedir prestado equipo audiovisual.", (
        _o("menor", 1.0, "necesita un proyector para una capacitación", "necesita un kit de videoconferencia para el jueves"),
    )),
    Escenario("o3", "OTRO", "7.3", "Pregunta por el horario o el contacto de la mesa de ayuda.", (
        _o("menor", 1.0, "quiere saber si atienden los sábados"),
    )),
)

NOMBRES = ("Ana", "Luis", "María", "José", "Carla", "Diego", "Sofía", "Juan", "Gabriela", "Pedro", "Lucía", "Marco",
           "Andrea", "Fernando", "Paola", "Ricardo", "Valeria", "Estuardo", "Mónica", "Javier", "Karla", "Roberto")
APELLIDOS = ("López", "Pérez", "García", "Morales", "Castillo", "Hernández", "Ramírez", "Méndez", "Rodríguez",
             "Juárez", "Orellana", "Cifuentes", "Barrios", "Sandoval", "Reyes", "Aguilar", "Quiñónez", "Monterroso")
DEPARTAMENTOS = ("Finanzas", "Ventas", "Recursos Humanos", "Operaciones", "Logística", "Legal", "Compras", "Mercadeo")
TONOS = ("formal", "informal", "molesto", "apurado", "confundido")
LONGITUDES = (("breve", 0.35), ("media", 0.45), ("detallada", 0.20))
CANALES = ("portal", "correo", "teléfono, transcrito por el agente")


@dataclass
class Parametros:
    ticket_id: str
    categoria: str
    escenario: str
    seccion: str
    descripcion: str
    perfil: str
    prioridad: str
    detalle: str
    version_manual: str
    escala_a_n2: bool
    categoria_secundaria: str | None
    descripcion_secundaria: str | None
    solicitante: str
    departamento: str
    canal: str
    tono: str
    longitud: str
    errores_ortograficos: bool
    incluye_nombre: bool
    pii_sembrada: list[dict] = field(default_factory=list)
    fecha_apertura: str = ""
    fecha_cierre: str = ""
    estado: str = ""
    particion: str = ""

    def como_dict(self) -> dict:
        return asdict(self)


def _elegir(rng: random.Random, pares):
    valores, pesos = zip(*pares)
    return rng.choices(valores, weights=pesos, k=1)[0]


def _telefono(rng: random.Random) -> str:
    return f"{rng.choice('345')}{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"


def _dpi(rng: random.Random) -> str:
    return f"{rng.randint(1000, 9999)} {rng.randint(10000, 99999)} {rng.randint(101, 2299):04d}"


def _tarjeta(rng: random.Random) -> str:
    while True:
        numero = "4" + "".join(str(rng.randint(0, 9)) for _ in range(15))
        if luhn_valido(numero):
            return " ".join(numero[i:i + 4] for i in range(0, 16, 4))


def _pii(rng: random.Random, nombre: str, escenario: Escenario, perfil: str) -> list[dict]:
    if rng.random() > 0.35:
        return []
    usuario = nombre.lower().replace(" ", ".")
    usuario = usuario.translate(str.maketrans("áéíóúñ", "aeioun"))
    candidatos = [
        ("EMAIL", f"{usuario}@correo.example"),
        ("EMAIL", f"{usuario}@valcora.example"),
        ("PHONE", _telefono(rng)),
        ("DPI", _dpi(rng)),
    ]
    if escenario.id == "c3" and perfil == "seguridad":  # escribió su tarjeta en el enlace falso
        candidatos.append(("CARD", _tarjeta(rng)))
    elegidos = rng.sample(candidatos, k=rng.choice((1, 1, 2)))
    return [{"tipo": t, "valor": v} for t, v in elegidos]


def _fecha(rng: random.Random, inicio: date, fin: date) -> datetime:
    while True:
        dia = inicio + timedelta(days=rng.randint(0, (fin - inicio).days))
        if dia.weekday() < 5:
            return datetime(dia.year, dia.month, dia.day, rng.randint(7, 18), rng.randint(0, 59))


def generar_parametros(total: int = TOTAL_TICKETS, semilla: int = SEMILLA) -> list[Parametros]:
    rng = random.Random(semilla)
    por_categoria = {c: [e for e in ESCENARIOS if e.categoria == c] for c in PESO_CATEGORIA}
    tickets = []
    for _ in range(total):
        categoria = _elegir(rng, PESO_CATEGORIA.items())
        escenario = rng.choice(por_categoria[categoria])
        opcion = _elegir(rng, [(o, o.peso) for o in escenario.opciones])
        apertura = _fecha(rng, date(2026, 1, 5), date(2026, 10, 30))
        horas = {"ALTA": (1, 6), "MEDIA": (4, 30), "BAJA": (20, 80)}[PRIORIDAD_POR_PERFIL[opcion.perfil]]
        secundario = None
        if rng.random() < 0.12:
            secundario = rng.choice([e for e in ESCENARIOS if e.categoria not in (categoria, "OTRO")])
        nombre = f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}"
        escala = escenario.escala_a_n2 or (opcion.perfil in ("seguridad", "varios") and rng.random() < 0.7)
        tickets.append(Parametros(
            ticket_id="",
            categoria=categoria,
            escenario=escenario.id,
            seccion=escenario.seccion,
            descripcion=escenario.descripcion,
            perfil=opcion.perfil,
            prioridad=PRIORIDAD_POR_PERFIL[opcion.perfil],
            detalle=rng.choice(opcion.detalles),
            version_manual="2026-2" if apertura.date() >= CAMBIO_DE_VERSION else "2026-1",
            escala_a_n2=escala,
            categoria_secundaria=secundario.categoria if secundario else None,
            descripcion_secundaria=secundario.descripcion if secundario else None,
            solicitante=nombre,
            departamento=rng.choice(DEPARTAMENTOS),
            canal=rng.choice(CANALES),
            tono=rng.choice(TONOS),
            longitud=_elegir(rng, LONGITUDES),
            errores_ortograficos=rng.random() < 0.3,
            incluye_nombre=rng.random() < 0.5,
            pii_sembrada=_pii(rng, nombre, escenario, opcion.perfil),
            fecha_apertura=apertura.isoformat(timespec="minutes"),
            fecha_cierre=(apertura + timedelta(hours=rng.randint(*horas))).isoformat(timespec="minutes"),
            estado="Escalado a N2 y resuelto" if escala else _elegir(rng, (("Resuelto", 0.93), ("Resuelto sin confirmación", 0.07))),
        ))
    tickets.sort(key=lambda t: t.fecha_apertura)
    for i, t in enumerate(tickets, start=1):
        t.ticket_id = f"TCK-2026-{i:05d}"
    _particionar(tickets, random.Random(semilla + 1))
    return tickets


def _particionar(tickets: list[Parametros], rng: random.Random) -> None:
    """Reserva TICKETS_PRUEBA tickets fuera del índice, estratificados por categoría."""
    for t in tickets:
        t.particion = "indice"
    por_categoria: dict[str, list[Parametros]] = {}
    for t in tickets:
        por_categoria.setdefault(t.categoria, []).append(t)
    restantes = TICKETS_PRUEBA
    categorias = sorted(por_categoria, key=lambda c: -len(por_categoria[c]))
    for n, c in enumerate(categorias):
        grupo = por_categoria[c]
        cuota = restantes if n == len(categorias) - 1 else round(TICKETS_PRUEBA * len(grupo) / len(tickets))
        for t in rng.sample(grupo, k=min(cuota, len(grupo))):
            t.particion = "prueba"
        restantes -= cuota
