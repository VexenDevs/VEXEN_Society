# Bot v1.11.0 — comandos rápidos

La superficie pública /society queda limitada a 12 acciones. /society estado sustituye a config estado y /society panel enlaza al Dashboard. Help se simplifica. Se retiran del registro slash config, plantilla, acceso y administrar; logs.setup ya no vuelve a registrar comandos complejos.

Los handlers/servicios internos, jobs Dashboard, permisos y confirmación de eliminación permanecen. No cambia el relay genérico, ni verificación, onboarding o tablas. Configurar DASHBOARD_URL y SYNC_COMMANDS=true; la actualización de Discord se produce al reiniciar y sincronizar el Bot, no al instalar archivos.

La prueba real de discord.py debe ejecutarse con VERIFY_PATCH en el entorno local con dependencies instaladas. Esta entrega no conectó el Bot a Discord.
