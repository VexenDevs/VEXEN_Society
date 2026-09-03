# Instalación · VEXEN Society Bot v1.10.0

Extrae este ZIP sobre la raíz de `VEXEN_Society` y permite reemplazar archivos.

## Variables de Railway

Configura en el servicio **VEXEN Society Bot**:

```env
VEXEN_VERIFICATION_INTEGRATION=postgres
VEXEN_VERIFICATION_SCHEMA=vexen_verification
```

Conserva también:

```env
DATABASE_URL=
SOCIETY_DB_SCHEMA=vexen_society
GUILD_ID=
```

Después de verificar el despliegue, elimina de Railway los nombres legacy:

```env
VERIFICATION_INTEGRATION
VEXMOD_ROLES_SCHEMA
```

El código los admite como fallback temporal, pero ya no deben ser la configuración principal.

## Contrato de creación

Al crear una Society, el flujo existente del bot:

1. crea `Staff-<Comunidad>`, `<Comunidad>` e `INT-<Comunidad>`;
2. añade o actualiza solo esta fila en `vexen_verification.role_transfers`;
3. añade solo la opción de `INT-<Comunidad>` a la pregunta de Discord Onboarding configurada;
4. conserva las transferencias y opciones existentes.

Para que el paso 3 ocurra, configura una vez la pregunta correcta desde **Dashboard → Gestión de Society → Configuración → Incorporación**. Desde v1.10, si Discord no confirma la opción, la creación se revierte para no dejar una Society incompleta.

Al eliminar una Society se retiran únicamente su opción de Onboarding y su mapping.

## Plantillas

Variables opcionales:

```text
VXS
asociado
comunidad
```

Ejemplos válidos:

```text
[CATEGORY] 👥 VXS | asociado | comunidad
[CATEGORY] 👥 [VXS] · { asociado } · 【comunidad】
[CATEGORY] 👥 SOCIETY CENTRAL
```

## Validación local

```powershell
python -m pip install -r requirements.txt
pytest -q
```
