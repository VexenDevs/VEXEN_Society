# VEXEN Society Bot · v1.9 Dashboard Control + Discord Logs

Este parche conecta el bot oficial de VEXEN Society con las acciones administrativas creadas desde VEXEN Society Dashboard y añade auditoría visual en Discord.

## Qué añade

- Consumidor de `society_control_jobs` dentro del bot oficial.
- Heartbeat `vexen-society-bot-control` en PostgreSQL.
- Reintentos y recuperación de jobs interrumpidos.
- Creación/eliminación de Society usando el `SpaceService` existente.
- Respeto de la selección inicial de canales de una solicitud.
- Sincronización/reparación de plantilla.
- Reenvío de bienvenida.
- Canales personalizados y renombrado.
- Gestión de Staff.
- Configuración global Society.
- Roles autorizados (solo OWNER).
- Configuración/sincronización de Discord Onboarding.
- Canal configurable de logs de auditoría.
- Publicación de eventos importantes de `audit_logs` como embeds de Discord.

## Comandos de logs

```text
/society config canal_logs canal:#logs-society
/society config canal_logs canal:ninguno
/society config probar_logs
```

`canal_logs` acepta un canal de texto. Si se deja sin canal, desactiva el envío de logs. `probar_logs` envía un embed de prueba al canal configurado.

## Instalación

Extrae este ZIP directamente sobre la raíz del repositorio `VEXEN_Society` y conserva el `.env` existente.

No requiere variables nuevas. Usa `DATABASE_URL`, `GUILD_ID`, `OWNER_ID` y `SOCIETY_DB_SCHEMA` que el bot ya utiliza. La migración de `log_channel_id` y del estado del dispatcher es idempotente y se ejecuta al iniciar el bot.

## Seguridad

El Dashboard solo crea trabajos en PostgreSQL. Las operaciones de Discord se ejecutan dentro del bot oficial con `discord.py`, por lo que no se crea un segundo Gateway bot ni se expone el token al navegador.

El sistema de logs nunca debe bloquear la operación principal: si el canal fue eliminado, el bot perdió permisos o Discord responde con un error temporal, el fallo se registra en los logs técnicos y la acción principal permanece independiente.

## v1.9.1

El puente y el sistema de logs usan reintentos con backoff ante fallos transitorios de PostgreSQL. No debería ser necesario reiniciar manualmente el bot después de un timeout temporal. El job de creación también acepta `requested_channels` con los tipos `TXT`, `STAFF-TXT`, `VOICE` y `STAFF-VOICE`.
