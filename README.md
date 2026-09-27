# VEXEN Society Bot v1.11.0

Actualización entregada sobre el handoff del 20-09-2026. Consulta `docs/RELEASE.md` y los documentos de configuración. No se ha desplegado desde esta entrega.

---

## Referencia histórica conservada

# VEXEN Society

Bot privado para administrar espacios de comunidades y creadores dentro de VEXEN.

## Incluye

- PostgreSQL aislado por schema para Society.
- Registro de asociados.
- Creación automática de:
  - rol de comunidad;
  - `INT-Comunidad`;
  - `Staff-Comunidad`;
  - categoría;
  - canales desde plantilla.
- Permisos limitados a la categoría:
  - asociado principal con permisos completos de canal/categoría;
  - Staff Society con permisos locales dentro de esa Society;
  - comunidad con acceso normal.
- Plantillas con validación, vista previa, historial, descarga y sincronización.
- Administración interactiva de canales.
- Eliminación con confirmación escrita exacta.
- Integración con `vexen_verification.role_transfers`.
- Integración incremental con Discord Onboarding.
- Retransmisión de anuncios mediante webhook con nombre/avatar del autor original.
- Bienvenida automática configurable con botón para obtener el rol de comunidad.
- Posicionamiento automático/configurable de categorías Society.
- Jerarquía garantizada: `Staff-Comunidad` > `Comunidad` > `INT-Comunidad`.
- Auditoría y roles administrativos adicionales.

## Plantilla

Las variables de categoría son opcionales y se reconocen por nombre:

```text
VXS
asociado
comunidad
```

La plantilla decide cómo decorarlas:

```text
[CATEGORY] 👥 VXS | asociado | comunidad
[CATEGORY] 👥 [VXS] · { asociado } · 【comunidad】
[CATEGORY] 👥 SOCIETY CENTRAL
```

Ejemplo completo:

```text
[CATEGORY] 👥 VXS | asociado | comunidad

[ANN] 📢┃anuncios
[TXT] 💬┃general
[STAFF-TXT] 🛡️┃staff-chat
[VOICE] 🔊 ┃ General
[STAFF-VOICE] 🔐 ┃ Staff
```

Las plantillas históricas con `{ asociado }` y `{ comunidad }` continúan siendo compatibles.

## Desarrollo local

No reemplaces tu `.env` real si ya lo tienes.

Variables:

```env
DISCORD_TOKEN=
GUILD_ID=
OWNER_ID=
ALLOWED_ROLES=

DATABASE_URL=
SOCIETY_DB_SCHEMA=vexen_society_dev

VEXEN_VERIFICATION_INTEGRATION=postgres
VEXEN_VERIFICATION_SCHEMA=vexen_verification

SYNC_COMMANDS=true
LOG_LEVEL=INFO
```

VEXEN Society y VEXEN CONTROL deben utilizar el mismo PostgreSQL para compartir `vexen_verification.role_transfers`.

## Intents de Discord

Activa en Developer Portal:

- Server Members Intent
- Message Content Intent

## Inicio

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

o:

```powershell
.\start_local.ps1
```

## Comandos

```text
/society help

/society asociado agregar
/society asociado listar
/society asociado info
/society asociado eliminar

/society administrar
/society miembros

/society staff agregar
/society staff quitar
/society staff listar

/society plantilla ver
/society plantilla cargar
/society plantilla descargar
/society plantilla historial

/society acceso rol_agregar
/society acceso rol_quitar
/society acceso listar

/society config anuncios
/society config categoria_base
/society config canal_bienvenida
/society config color_bienvenida
/society config estado
```

## Posición de categorías

Society coloca cada nueva categoría después de la última Society registrada en PostgreSQL, sin depender del texto o la decoración de la plantilla.
Si todavía no existe ninguna, usa la categoría configurada con:

```text
/society config categoria_base
```

Si no hay configuración, intenta usar una categoría llamada `COMUNIDAD`.

## Bienvenida automática

Configura el canal con:

```text
/society config canal_bienvenida canal:#general
```

Al crear una Society se publica un embed de bienvenida con color predeterminado `#57F287` y el botón:

```text
✨ Unirme a esta comunidad
```

El color se puede cambiar sin tocar código:

```text
/society config color_bienvenida color:#57F287
```

También acepta `default` para volver a `#57F287`.

Después de asignar el rol, el usuario recibe de forma privada:

```text
🚪 Ir a la comunidad
```

## Anuncios

Los mensajes publicados en el canal `[ANN]` de una Society se replican al canal global configurado con `/society config anuncios` usando un webhook. El webhook usa el nombre visible y avatar del remitente original, copia adjuntos y conserva el vínculo para sincronizar edición/eliminación. El bot necesita `Administrar webhooks` en ese canal global.

## Eliminación segura

`/society asociado eliminar` no borra inmediatamente.

1. Muestra lo que se eliminará.
2. Exige botón de eliminación.
3. Abre un modal.
4. Debes escribir exactamente el nombre de comunidad.
5. El bot borra por IDs guardados, no buscando por nombres.
6. Si hay errores, conserva el registro con estado `error`.

## VEXEN Verification

Al crear una Society se añade una sola transferencia:

```text
INT-Comunidad → Comunidad
```

Contrato:

```text
vexen_verification.role_transfers
onboarding_role_id → verified_role_id
```

No se reemplazan las transferencias existentes. Al eliminar la Society se retira únicamente su mapping. Society no crea ni modifica tablas de FAQ, tickets, Crew u otros módulos.

## Incorporación de Discord

La pregunta de asociados debe configurarse una vez desde el Dashboard. Después, cada alta añade únicamente su opción vinculada a `INT-Comunidad` y conserva todas las opciones existentes. Si Discord no confirma esa operación, el alta se revierte para no dejar una Society incompleta. Al eliminar una Society se retira únicamente esa opción.

## Botón de comunidad en anuncios globales

Cada anuncio retransmitido conserva el nombre y avatar del autor original. Debajo, VEXEN Society publica:

```text
✨ ¿Quieres formar parte de Comunidad?

[ ✨ Unirme a esta comunidad ]
```

El botón entrega el rol correspondiente y responde de forma privada con acceso al canal principal. Los botones se restauran automáticamente tras reiniciar el bot.
