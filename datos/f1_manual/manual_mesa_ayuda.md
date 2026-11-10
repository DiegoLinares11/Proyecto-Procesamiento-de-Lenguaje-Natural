<!--
Fuente del manual F1. scripts/construir_f1.py genera un PDF por versión.
Convenciones:
  ## Capítulo N: Título      -> capítulo, empieza en página nueva
  ### N.M Título             -> procedimiento
  !N2                        -> el procedimiento es de uso exclusivo de técnicos N2
  1. Texto                   -> paso numerado (nunca se parte al segmentar)
  ::: 2026-1 ... :::         -> texto que solo aparece en esa versión
Solo caracteres latin-1: usar «comillas» y guion simple.
-->

## Capítulo 1: Uso del manual

### 1.1 Alcance y audiencia

Este manual describe los procedimientos de la mesa de ayuda de TI de Corporación Valcora. Lo usan los agentes de nivel 1 (N1), que atienden el primer contacto, y los técnicos de nivel 2 (N2), que resuelven los casos escalados.

Los procedimientos marcados como «Uso exclusivo: técnicos N2» tienen impacto en la seguridad o en sistemas críticos. Un agente N1 no debe ejecutarlos ni compartir su contenido con el usuario: debe escalar el ticket a N2 con la evidencia recopilada.

Cuando un procedimiento cambia, la versión anterior del manual deja de estar vigente. Ante cualquier duda, aplique siempre la versión más reciente.

### 1.2 Niveles de soporte

El nivel 1 (N1) registra el ticket, confirma la categoría y la prioridad, aplica los procedimientos de este manual y escala cuando el caso lo requiere. N1 puede solicitar acciones sensibles, pero no aprobarlas.

El nivel 2 (N2) realiza diagnósticos avanzados, ejecuta los procedimientos restringidos y aprueba o rechaza las acciones sensibles que solicita N1, como restablecer MFA, cerrar un ticket sin confirmación del usuario o desbloquear cuentas privilegiadas.

### 1.3 Categorías de ticket

Cada ticket se clasifica en una sola categoría principal:

ACCESO: cuentas de red, contraseñas, bloqueos, MFA y permisos sobre carpetas o sistemas.

CORREO: Outlook, buzón de correo, Teams y correos sospechosos.

EQUIPOS: computadoras, impresoras, periféricos y actualizaciones del sistema operativo.

RED: conexión a internet, Wi-Fi, VPN y cableado de la oficina.

APLICACIONES: instalación de software, el ERP SIRA, Microsoft Office y navegadores.

OTRO: solicitudes que no encajan en las categorías anteriores o que están fuera del alcance de la mesa de ayuda.

Si un ticket menciona dos problemas, la categoría principal es la del problema que impide trabajar. El segundo problema se anota en las notas del ticket o se registra como un ticket aparte.

### 1.4 Prioridades y tiempos de atención

La prioridad se asigna según el impacto, no según la insistencia del usuario.

ALTA: detiene el trabajo de una persona sin ninguna alternativa, afecta a varias personas o a un proceso crítico como facturación o nómina, o es un posible incidente de seguridad. Tiempo de primera respuesta: 30 minutos. Tiempo objetivo de resolución: 4 horas.

MEDIA: afecta el trabajo, pero existe una alternativa temporal, por ejemplo usar otro equipo o el correo desde el navegador. Primera respuesta: 2 horas. Resolución: 1 día hábil.

BAJA: consultas, solicitudes que se pueden programar o inconvenientes menores. Primera respuesta: 1 día hábil. Resolución: 3 días hábiles.

### 1.5 Protección de datos personales

Nunca solicite contraseñas, códigos de verificación ni respuestas de seguridad, ni por teléfono ni por escrito.

Si un usuario escribe su contraseña en un ticket, marque el ticket como sensible, oculte el texto con la opción «Ocultar dato» y pida al usuario que cambie la contraseña de inmediato en Valcora ID (procedimiento 2.1).

No copie en las notas del ticket números de DPI, números de tarjeta, teléfonos personales ni direcciones. Para identificar a un colaborador use su número de empleado.

## Capítulo 2: Accesos y cuentas

### 2.1 Restablecimiento de contraseña

Aplica cuando el usuario olvidó su contraseña de red o cuando la contraseña expiró. La contraseña expira cada 90 días y el sistema avisa 7 días antes.

::: 2026-1
1. Verifique la identidad del usuario con su número de empleado y la fecha de ingreso registrada en el directorio.
2. En la consola de directorio, seleccione la cuenta y elija «Restablecer contraseña».
3. Genere una contraseña temporal de 12 caracteres y marque la opción «Cambiar en el próximo inicio de sesión».
4. Comunique la contraseña temporal solo por llamada telefónica, nunca por correo ni por chat.
5. Confirme que el usuario pudo iniciar sesión y cierre el ticket.
:::

::: 2026-2
Desde la versión 2026-2, los agentes N1 ya no generan contraseñas temporales. El restablecimiento se hace en el portal de autoservicio Valcora ID (id.valcora.example).

1. Indique al usuario que ingrese a Valcora ID desde cualquier navegador y elija «Olvidé mi contraseña».
2. El portal envía un código de verificación a la aplicación Microsoft Authenticator registrada.
3. El usuario define una contraseña nueva de al menos 14 caracteres que no repita ninguna de las últimas 10.
4. Si el usuario no tiene MFA registrado o perdió su teléfono, no intente restablecer la contraseña manualmente: escale a N2 con categoría ACCESO y prioridad MEDIA, o ALTA si el usuario no puede trabajar.
5. Confirme que el usuario pudo iniciar sesión y cierre el ticket.
:::

### 2.2 Cuenta bloqueada por intentos fallidos

La cuenta se bloquea después de 5 intentos fallidos en 10 minutos.

::: 2026-1
El desbloqueo es automático a los 15 minutos.
:::

::: 2026-2
El desbloqueo es automático a los 30 minutos.
:::

1. Pregunte si el usuario cambió su contraseña recientemente. Un teléfono con el correo configurado o una unidad de red mapeada con la contraseña anterior provocan bloqueos repetidos.
2. Si es el primer bloqueo del día, indique al usuario que espere el desbloqueo automático.
3. Si el bloqueo se repite más de 3 veces en un día, revise el registro de inicios de sesión en la consola de directorio y pida al usuario eliminar la cuenta de correo del teléfono y volver a agregarla con la contraseña nueva.
4. Si los intentos fallidos vienen de una ubicación desconocida, trate el caso como posible incidente de seguridad: prioridad ALTA y escalamiento inmediato a N2.

### 2.3 Registro de MFA en un teléfono nuevo

El uso de MFA con Microsoft Authenticator es obligatorio para todas las cuentas.

1. Si el usuario conserva el teléfono anterior, indíquele que entre a Valcora ID, abra «Información de seguridad», agregue el teléfono nuevo como método, lo verifique y después elimine el anterior.
2. Si el usuario ya no tiene el teléfono anterior, no puede registrar el nuevo por su cuenta. Escale a N2 para el restablecimiento de MFA (procedimiento 2.4).
3. Nunca registre MFA en nombre de otra persona ni acepte que un compañero lo haga por el usuario.

### 2.4 Restablecimiento de MFA

!N2

1. Verifique la identidad del usuario de forma presencial o por videollamada, con el carné corporativo visible.
2. En la consola de identidad, elimine los métodos MFA registrados y active la opción «Exigir registro nuevo».
3. Anote en el ticket el método de verificación usado, sin copiar datos del documento de identidad.
4. Revise los inicios de sesión de los últimos 7 días. Si hay accesos desde ubicaciones desconocidas, abra un incidente de seguridad.

### 2.5 Acceso a carpetas compartidas

1. Pida al usuario la ruta de la carpeta, por ejemplo \\archivos\finanzas\presupuestos, y el tipo de acceso que necesita: lectura o modificación.
2. La solicitud requiere la aprobación por correo del dueño de la carpeta registrado en el catálogo de carpetas compartidas.
3. Con la aprobación adjunta al ticket, agregue al usuario al grupo de seguridad correspondiente: GS-nombre-L para lectura o GS-nombre-M para modificación.
4. El cambio se aplica en un máximo de 60 minutos o al cerrar y volver a abrir sesión.
5. Si no llega la aprobación, deje el ticket «En espera de aprobación». Pasados 5 días hábiles sin respuesta, ciérrelo e informe al usuario.

### 2.6 Cuentas privilegiadas y cuentas de servicio

!N2

Las cuentas privilegiadas usan el prefijo adm- y las cuentas de servicio usan el prefijo svc-.

1. Solo N2 puede desbloquear o restablecer estas cuentas. Si un agente N1 recibe la solicitud, debe escalarla sin modificar la cuenta.
2. Para restablecer una cuenta svc-, coordine con el dueño de la aplicación una ventana de cambio y actualice la contraseña en la bóveda de secretos en la misma ventana.
3. Registre en el ticket el número de cambio aprobado.

## Capítulo 3: Correo y colaboración

### 3.1 Outlook no abre o se queda en «Procesando»

1. Cierre Outlook por completo desde el Administrador de tareas.
2. Abra Outlook en modo seguro: presione Windows + R, escriba outlook.exe /safe y presione Enter. Si abre, desactive los complementos uno por uno en Archivo, Opciones, Complementos, hasta encontrar el que causa el problema.
3. Si no abre ni en modo seguro, cree un perfil nuevo desde Panel de control, Correo, Mostrar perfiles.
4. Si aparece el error 0x800CCC0E, verifique primero la conexión a internet y la VPN (procedimientos 5.1 y 5.2) antes de crear un perfil nuevo.
5. Si el problema continúa con el perfil nuevo, escale a N2 con capturas del error.

Mientras tanto, el usuario puede leer su correo desde el navegador en correo.valcora.example, por lo que la prioridad suele ser MEDIA.

### 3.2 Buzón lleno

::: 2026-1
La cuota de cada buzón es de 50 GB. Outlook avisa cuando el buzón llega al 90 % de la cuota.
:::

::: 2026-2
Desde la versión 2026-2, la cuota de cada buzón es de 100 GB. Outlook avisa cuando el buzón llega al 90 % de la cuota.
:::

1. Pida al usuario vaciar las carpetas Elementos eliminados y Correo no deseado.
2. Active el archivo en línea: los correos con más de 2 años se mueven automáticamente a la carpeta Archivo y dejan de contar para la cuota.
3. Indique guardar los adjuntos grandes en OneDrive y eliminarlos del correo.
4. N1 no aumenta cuotas. Un aumento excepcional requiere la aprobación de la gerencia del área y lo ejecuta N2.

### 3.3 Correo sospechoso o phishing

Asigne prioridad ALTA si el usuario hizo clic en un enlace o escribió su contraseña. Asigne prioridad MEDIA si solo recibió el correo.

1. Indique al usuario que no abra adjuntos ni enlaces y que no reenvíe el mensaje a nadie.
2. Pida usar el botón «Reportar mensaje» de Outlook, que envía el correo al equipo de seguridad.
3. Si el usuario escribió su contraseña en el enlace, pídale cambiarla de inmediato en Valcora ID (procedimiento 2.1) y escale el ticket a N2 como incidente de seguridad.
4. Nunca pida al usuario reenviar el correo sospechoso a la mesa de ayuda.

### 3.4 Teams sin audio, sin video o sin conexión a reuniones

1. En Teams, revise Configuración, Dispositivos y confirme que están seleccionados el micrófono, la bocina y la cámara correctos.
2. En Windows, revise Configuración, Privacidad y seguridad, y confirme que Teams tiene permiso de usar el micrófono y la cámara.
3. Si el problema sigue, restablezca Teams desde Configuración, Aplicaciones, Microsoft Teams, Opciones avanzadas, Restablecer. El usuario conserva sus chats y equipos.
4. Si Teams solo falla dentro de la oficina, revise la red con el procedimiento 5.1.

### 3.5 Recuperación de correos eliminados

1. Si el correo se eliminó hace menos de 30 días, indique al usuario abrir la carpeta Elementos eliminados y usar la opción «Recuperar elementos eliminados».
2. El usuario puede restaurar el correo a su carpeta original.
3. Si el correo se eliminó hace más de 30 días, ya no aparece en esa opción. Escale a N2 para la recuperación desde el respaldo del buzón (procedimiento 3.6).

### 3.6 Recuperación desde el respaldo del buzón

!N2

1. Confirme la fecha aproximada, el remitente y el asunto del correo que se debe recuperar.
2. Los respaldos de buzón se conservan por 1 año. Restaure el correo en una carpeta llamada «Recuperado» dentro del buzón del usuario.
3. La recuperación de correos de otra persona requiere la autorización escrita de Recursos Humanos o del área legal.

## Capítulo 4: Equipos

### 4.1 Equipo lento

1. Revise cuánto tiempo lleva encendido el equipo en el Administrador de tareas, pestaña Rendimiento, «Tiempo activo». Si son más de 7 días, pida reiniciarlo.
2. Si el disco C: tiene menos del 10 % de espacio libre, ejecute el Liberador de espacio en disco.
3. Revise si hay actualizaciones pendientes en el Centro de Software e instálelas.
4. Si el equipo tiene más de 5 años o menos de 8 GB de memoria RAM, sugiera una solicitud de reemplazo (procedimiento 4.4).

La prioridad es BAJA, salvo que la lentitud impida trabajar.

### 4.2 Pantalla azul o el equipo no enciende

1. Si el equipo no enciende, revise el cargador, la regleta y la luz de encendido. En portátiles, desconecte el cargador y mantenga presionado el botón de encendido durante 30 segundos antes de volver a intentar.
2. Si aparece una pantalla azul, anote el código de detención, por ejemplo 0x0000007E (SYSTEM_THREAD_EXCEPTION_NOT_HANDLED) o 0x00000050 (PAGE_FAULT_IN_NONPAGED_AREA).
3. Si la pantalla azul ocurre más de una vez, escale a N2 con el código y la hora. No reinstale controladores sin autorización de N2.
4. Si el usuario no puede trabajar, ofrezca un equipo de préstamo (procedimiento 7.2) y asigne prioridad ALTA.

### 4.3 Impresora con documentos atascados en la cola

1. Revise en el panel de la impresora si falta papel o tóner, o si hay un mensaje de error.
2. Cancele todos los documentos de la cola desde Configuración, Impresoras y escáneres.
3. Si la cola no se vacía, reinicie el servicio «Cola de impresión» desde la herramienta de soporte remoto.
4. Las impresoras de piso se llaman IMP-piso-número, por ejemplo IMP-03-02. Si la impresora no aparece en el equipo, agréguela desde \\impresion\IMP-03-02.

### 4.4 Solicitud de equipo nuevo o reemplazo

1. La solicitud requiere el formulario de equipo aprobado por la jefatura del área.
2. Si el reemplazo es por falla, N2 debe confirmar el diagnóstico antes de aprobarlo.
3. Los equipos en inventario se entregan en un máximo de 10 días hábiles.

La prioridad es BAJA, o MEDIA si es un reemplazo por falla y el usuario no tiene equipo de préstamo.

### 4.5 Error 0x80070005 al instalar actualizaciones

El código 0x80070005 significa «acceso denegado».

1. Confirme que la instalación se hace desde el Centro de Software y no con un instalador descargado de internet.
2. Reinicie el equipo y vuelva a intentar la instalación.
3. Ejecute la tarea «Reparar actualizaciones» desde el Centro de Software.
4. Si el error continúa, escale a N2. No otorgue permisos de administrador local al usuario.

### 4.6 Reinstalación de la imagen corporativa

!N2

1. Respalde el perfil del usuario en OneDrive y confirme que la sincronización terminó.
2. Aplique la imagen corporativa VALCORA-W11-2026 desde el servidor de despliegue.
3. Reinstale las aplicaciones que corresponden al puesto del usuario según el catálogo.
4. Registre en el ticket el número de serie del equipo y la versión de la imagen aplicada.

## Capítulo 5: Red y conectividad

### 5.1 Sin internet en la oficina

1. Confirme si el problema afecta a una persona o a varias. Si afecta a varias personas del mismo piso, es un incidente de red: asigne prioridad ALTA y escale a N2 de inmediato.
2. Si el equipo usa cable, revise el ícono de red y pruebe con otro puerto.
3. Si usa Wi-Fi, confirme que está en la red corporativa «Valcora-Corp», que usa la cuenta de red. La red «Valcora-Invitados» no da acceso a los sistemas internos.
4. Ejecute el solucionador de problemas de red de Windows y reinicie el adaptador.
5. Si el equipo tiene una dirección IP que empieza con 169.254, no obtuvo dirección de la red. Escale a N2 e indique el número de puerto, que está en la etiqueta de la pared.

### 5.2 VPN no conecta

::: 2026-1
El cliente VPN de la organización es «Valcora Connect».

1. Confirme que el usuario tiene internet sin la VPN.
2. Error 809: la red de la casa bloquea la conexión. Pida al usuario revisar que su router permita conexiones VPN o probar con los datos del teléfono.
3. Error 691: el usuario o la contraseña son incorrectos, o la cuenta está bloqueada (procedimiento 2.2).
4. Si el cliente no está instalado, instálelo desde el Centro de Software con el paquete «Valcora Connect».
5. Si nada funciona, escale a N2 con el código de error y la hora del intento.
:::

::: 2026-2
Desde la versión 2026-2, el cliente VPN de la organización es «Valcora Secure Access». El cliente anterior, Valcora Connect, quedó fuera de servicio el 1 de julio de 2026 y ya no debe instalarse.

1. Confirme que el usuario tiene internet sin la VPN.
2. Si el cliente muestra «Autenticación fallida (código SA-401)», revise que la contraseña no haya expirado (procedimiento 2.1) y que el usuario apruebe la notificación de MFA en Microsoft Authenticator.
3. Si muestra «Sin respuesta del portal (código SA-504)», pida al usuario cambiar de red o reiniciar su router.
4. Si el cliente no está instalado, instálelo desde el Centro de Software con el paquete «Valcora Secure Access».
5. Si nada funciona, escale a N2 con el código de error y la hora del intento.
:::

### 5.3 Wi-Fi para visitantes

1. Los visitantes se conectan a la red «Valcora-Invitados» con un código de acceso que genera recepción o un agente N1 en el portal de visitantes.
2. Cada código dura 8 horas y sirve para un máximo de 2 dispositivos.
3. No entregue códigos de visitante a colaboradores para trabajar con sistemas internos desde dispositivos personales.

### 5.4 Cambios en reglas de firewall

!N2

1. La solicitud debe indicar la aplicación, los puertos, el origen, el destino y la justificación del negocio.
2. Todo cambio requiere la aprobación del comité de cambios y se aplica en la ventana de martes o jueves de 19:00 a 21:00.
3. Nunca abra un puerto hacia cualquier origen de internet (0.0.0.0/0).
4. Documente cada regla con el número de cambio aprobado.

## Capítulo 6: Aplicaciones

### 6.1 Instalación de software

1. El usuario puede instalar por su cuenta cualquier programa del catálogo del Centro de Software.
2. El software que no está en el catálogo requiere una solicitud con justificación, aprobada por la jefatura y por el equipo de seguridad. El tiempo de atención es de 5 días hábiles.
3. No instale software usando la cuenta de administrador de la mesa de ayuda dentro de la sesión del usuario.

### 6.2 SIRA: sesión expirada o error ERP-401

SIRA es el ERP de la organización para finanzas, compras e inventario.

1. El error ERP-401 indica que la sesión expiró tras 20 minutos de inactividad. Pida al usuario volver a iniciar sesión.
2. Si el error ERP-401 aparece justo al entrar, pida borrar las cookies del sitio sira.valcora.example y volver a intentar.
3. El error ERP-503 indica que SIRA está en mantenimiento, que ocurre los domingos de 22:00 a 02:00. Informe al usuario el horario.
4. Si varias personas reportan el error ERP-500 fuera del horario de mantenimiento, asigne prioridad ALTA y escale a N2.
5. Los permisos dentro de SIRA, como módulos o niveles de aprobación, los autoriza el dueño del proceso. Esos tickets van en la categoría ACCESO, no en APLICACIONES.

### 6.3 Office: error de activación 0xC004F074

1. Para validar la licencia, el equipo debe conectarse a la red corporativa o a la VPN al menos una vez cada 30 días.
2. Pida al usuario conectar la VPN, abrir Word y elegir Cuenta, «Actualizar licencia».
3. Si el error continúa, pida cerrar la sesión de Office y volver a entrar con la cuenta corporativa.
4. Si el error sigue apareciendo con el equipo conectado a la red corporativa, escale a N2.

### 6.4 Sitio interno no carga o muestra error de certificado

1. Si aparece el error NET::ERR_CERT_DATE_INVALID, revise la fecha y la hora del equipo y corrija la zona horaria a la de Guatemala.
2. Los sitios internos que terminan en valcora.example solo funcionan dentro de la red corporativa o con la VPN.
3. Pruebe en otro navegador autorizado, Edge o Chrome, y en una ventana privada.
4. Si el certificado está vencido para todos los usuarios, escale a N2 como incidente, con prioridad ALTA si el sitio es un sistema crítico.

### 6.5 Acceso a la base de datos de producción de SIRA

!N2

1. El acceso es solo de lectura, temporal, por un máximo de 8 horas, y requiere un ticket de cambio aprobado.
2. Use la cuenta personal con prefijo adm-. Nunca use la cuenta de servicio de la aplicación.
3. Registre en el ticket las consultas ejecutadas.

## Capítulo 7: Otras solicitudes

### 7.1 Solicitudes fuera de alcance

La mesa de ayuda no atiende computadoras personales, internet residencial, teléfonos personales ni software de uso personal. Estos tickets van en la categoría OTRO con prioridad BAJA: responda con la plantilla «Fuera de alcance» y cierre el ticket.

La única excepción es configurar el correo corporativo en un teléfono personal con la aplicación Outlook, que se atiende como un ticket de la categoría CORREO.

### 7.2 Préstamo de equipo

1. Los portátiles de préstamo se entregan por un máximo de 5 días hábiles.
2. Los proyectores y kits de videoconferencia se reservan con al menos 24 horas de anticipación.
3. El usuario firma una hoja de responsabilidad al recibir el equipo y al devolverlo.

### 7.3 Horario y contacto de la mesa de ayuda

La mesa de ayuda atiende de lunes a viernes de 7:00 a 19:00 y los sábados de 8:00 a 12:00, en la extensión 4357 o en el correo mesadeayuda@valcora.example. Fuera de ese horario solo se atienden incidentes de prioridad ALTA en el teléfono de guardia.

## Capítulo 8: Escalamiento y cierre

### 8.1 Cuándo y cómo escalar a N2

Escale el ticket a N2 cuando el procedimiento está marcado como «Uso exclusivo: técnicos N2», cuando el problema sigue después de aplicar todos los pasos, cuando es un posible incidente de seguridad, cuando afecta a varias personas o cuando se necesita una acción sensible.

Al escalar, incluya un resumen del problema, los pasos ya realizados, la evidencia (códigos de error, capturas y horas) y la prioridad. No incluya datos personales del usuario.

### 8.2 Acciones que requieren aprobación de N2

Un agente N1 puede solicitar estas acciones, pero solo N2 puede aprobarlas: restablecer MFA, desbloquear o restablecer cuentas privilegiadas o de servicio, aumentar la cuota de un buzón, cerrar un ticket sin confirmación del usuario y recuperar correos desde el respaldo del buzón.

Toda aprobación queda registrada en el ticket con el nombre del técnico N2 y la hora.

### 8.3 Cierre de tickets

1. Antes de cerrar, confirme con el usuario que el problema quedó resuelto.
::: 2026-1
2. Si el usuario no responde en 3 días hábiles después de dos recordatorios, cierre el ticket como «Resuelto sin confirmación».
:::
::: 2026-2
2. Si el usuario no responde en 5 días hábiles después de dos recordatorios, cierre el ticket como «Resuelto sin confirmación».
:::
3. Registre la solución aplicada y la categoría final del ticket.
4. Si el mismo problema vuelve a aparecer dentro de 7 días, reabra el mismo ticket en lugar de crear uno nuevo.
