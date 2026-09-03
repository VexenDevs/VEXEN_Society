# VEXEN Society Bot · v1.10.0

## VEXEN Verification definitivo

- La integración deja de apuntar por defecto al schema legacy `vexmod_temp_roles`.
- Nuevo schema runtime: `vexen_verification`.
- Nueva variable: `VEXEN_VERIFICATION_SCHEMA`.
- Nueva variable: `VEXEN_VERIFICATION_INTEGRATION`.
- El mapping utiliza el contrato real:
  - `onboarding_role_id` = rol `INT-*`;
  - `verified_role_id` = rol oficial/comunidad.
- El alta hace upsert únicamente de la transferencia de la nueva Society y conserva las demás.
- La eliminación borra únicamente la transferencia correspondiente al rol INT eliminado.
- La creación solo se confirma si Discord Onboarding devuelve `added`, `updated` o `already`; de lo contrario se ejecuta rollback.
- El orden de categorías usa los `category_id` registrados en PostgreSQL y ya no depende de que el nombre contenga `{ VXS }`.
- Se valida que un rol oficial no esté asignado a otra transferencia.
- Los nombres antiguos se aceptan temporalmente como fallback para evitar un deploy roto.

## Plantillas

- Variables opcionales y sin llaves obligatorias: `VXS`, `asociado`, `comunidad`.
- La plantilla decide la decoración: `{asociado}`, `[asociado]`, `【asociado】`, etc.
- Las plantillas estáticas sin variables son válidas.
- Las plantillas antiguas con `{ asociado }` y `{ comunidad }` siguen funcionando.

La integración incremental existente de Discord Onboarding se conserva: añade o elimina solamente la opción vinculada al rol INT de la Society y mantiene las demás opciones.
