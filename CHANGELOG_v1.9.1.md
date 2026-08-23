# VEXEN Society Bot · v1.9.1

## Recuperación automática
- Dashboard Control Worker continúa vivo después de timeouts transitorios de PostgreSQL.
- Backoff progresivo de reintento hasta 30 segundos.
- Heartbeat pasa a `degraded` con un error útil y vuelve a `online` al recuperarse.
- El worker de logs Discord también se recupera sin reiniciar el bot.
- Excepciones sin mensaje, como `TimeoutError()`, registran al menos el nombre de la excepción.

## Solicitudes de Society
- Soporte para `requested_channels` en las solicitudes.
- Tipos permitidos: `TXT`, `STAFF-TXT`, `VOICE`, `STAFF-VOICE`.
- Los canales se crean reutilizando `SpaceService.create_custom_channel`.
- Si un canal adicional falla durante el aprovisionamiento, el bot intenta revertir la Society completa para evitar estructuras parciales.
