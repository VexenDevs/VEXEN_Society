## 9. Comandos rápidos del Bot

```text
/society help
/society estado
/society panel
/society miembros
/society asociado agregar
/society asociado listar
/society asociado info
/society asociado eliminar
/society staff agregar
/society staff quitar
/society staff listar
/society bienvenida reenviar
```

Conservan sus controles de rol/servidor. Eliminar una Society mantiene la confirmación. Estado permanece administrativo. Help/panel solo guían al Dashboard, que autentica de nuevo.

En el entorno del Bot conserva el GUILD_ID y añade/verifica:

```dotenv
DASHBOARD_URL=https://society.vexen.one
SYNC_COMMANDS=true
```

La sincronización ocurre al reiniciar el Bot y modifica el árbol Society de este bot en el servidor configurado. No se borran comandos de otras aplicaciones. Si hay comandos globales históricos de otro registro, este paquete no los elimina indiscriminadamente.

Se retiran del registro público config, plantilla, acceso y administrar, incluidos los comandos de configuración de logs. Los handlers/servicios internos siguen disponibles para los trabajos encolados del Dashboard. En Gestión de Society están ajustes, canales de logs, onboarding, permisos y editor. Se añadió importación TXT/JSON y descarga de versiones; importar exige confirmación y no sincroniza automáticamente Societies existentes. Los roles administrativos siguen siendo responsabilidad de OWNER.

