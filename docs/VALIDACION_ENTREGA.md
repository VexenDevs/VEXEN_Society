# Informe de validación de la entrega

## Base y alcance

Dashboard: handoff VEXEN_SOCIETY_DASHBOARD_HANDOFF_20260920_014108 + archivos del Bloque Social 1.
Bot: handoff VEXEN_SOCIETY_BOT_HANDOFF_20260920_014150.

Se trabajó exclusivamente sobre copias en el entorno de construcción. No se editó el repositorio del usuario, ni PostgreSQL, Discord, GitHub o Railway.

## Resultados ejecutados

| Validación | Resultado |
|---|---|
| Suite Dashboard (original + nuevos contratos, OAuth, estado, UI y seguridad) | 195 PASS, 0 fallos, 0 omitidas |
| Suite Bot | 63 PASS, 0 fallos, 1 omitida |
| Motor de instalación/rollback de ambos parches | 22 comprobaciones PASS |
| Hashes de payload y archivos base | Verificados en las pruebas del motor |
| Sintaxis Python y compilación de plantillas Jinja | Verificadas sin iniciar los servicios |

Las suites se ejecutaron en copias temporales, sin copiar `.env` y con sockets de salida bloqueados. Los dobles HTTP y de PostgreSQL no se presentan como integraciones reales.

El motor de parches se probó con aplicación normal, CRLF/LF, archivo modificado, dependencia base modificada, payload corrupto, colisión de archivo nuevo, fallo de escritura con reversión automática, reaplicación idempotente, verificación aislada, conflicto de rollback y restauración de los bytes originales. Se comprobó que el `.env` de prueba permanece intacto. Son pruebas del motor Python usado por los lanzadores, no ejecuciones de PowerShell en Windows.

## Pendiente de comprobar en el entorno real

1. Este entorno no tiene asyncpg ni discord.py. Los tests offline del Dashboard no necesitan importar asyncpg hasta abrir una conexión. En el Bot se omite explícitamente la prueba de instanciación del Cog real si falta discord.py/asyncpg. VERIFY_PATCH exige ambas dependencias y ejecuta la carga real del Cog en el entorno del usuario, sin iniciar sesión en Discord.
2. No hay un servidor PostgreSQL de prueba conectado aquí; el DDL, bloqueos, claves y SQL deben probarse al arrancar contra una copia de la base antes de producción.
3. No se ejecutaron los lanzadores PowerShell aquí: este entorno no tiene pwsh. Se suministran como wrappers simples del motor que sí se probó.
4. No se autorizaron cuentas reales Meta/X, ni se comprobaron scopes aprobados, facturación, objetos reales de Facebook, callbacks externos o entregas/relay de Discord. Se necesita el setup de CONFIGURACION.md.
5. No se realizó una revisión visual con navegador real; se renderizó la página completa de ocho tarjetas mediante Jinja/TestClient y se probaron rutas/CSRF. Se debe revisar visualmente al arrancar local.

## Condiciones de seguridad preservadas

Sin tokens en cookies OAuth; estado de un solo uso ligado a actor/servidor/Society/sesión. Credenciales cifradas. Selección de Facebook Page desde la autorización recibida, no un ID arbitrario. Firma del webhook sobre cuerpo original; se confirma el contenido mediante API. Acceso entre Societies rechazado. X exige perfil explícitamente público. Reintentos, cursores y datos de diagnóstico no muestran tokens o cuerpos de error desconocidos.

La retirada de comandos solo cambia el registro público. Verificación, onboarding, relay y confirmaciones destructivas conservan sus servicios originales. La configuración compleja se realiza desde Dashboard; los roles administrativos continúan restringidos a OWNER.

## No confundir

PASS offline no significa despliegue ni aprobación OAuth. «Preparado para conectar» significa presencia/formato de configuración, no cuenta autorizada. Los eventos de prueba no demuestran detección real. La deduplicación de detección no garantiza exactamente-una-vez en la frontera de envío a Discord ante una caída crítica.
