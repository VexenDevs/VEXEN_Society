from __future__ import annotations

import discord

from app.society.spaces import DeleteReport, SocietySpaceError, SpaceService
from database import get_base_category, list_associates


class VexenSpaceService(SpaceService):
    """SpaceService v1.10 con contrato estricto de Verificación/Onboarding."""

    ONBOARDING_SUCCESS_STATES = {"added", "updated", "already"}

    async def create_space(
        self,
        guild: discord.Guild,
        associate_user_id: int,
        actor_id: int,
    ) -> dict:
        result = await super().create_space(guild, associate_user_id, actor_id)
        onboarding_state = str(result.get("onboarding_state") or "")
        onboarding_error = str(result.get("onboarding_error") or "").strip()

        if (
            onboarding_state in self.ONBOARDING_SUCCESS_STATES
            and not onboarding_error
        ):
            return result

        # Desde v1.10 una Society no se considera creada si su rol INT no quedó
        # incluido en la pregunta configurada de Discord Onboarding. Revertimos
        # la estructura y el mapping para no dejar estados parciales.
        try:
            rollback: DeleteReport = await super().delete_space(
                guild,
                associate_user_id,
                actor_id,
            )
        except Exception as exc:
            raise SocietySpaceError(
                "La Society no pudo integrarse en la incorporación y también "
                f"falló el rollback: {type(exc).__name__}: {str(exc)[:300]}"
            ) from exc

        reason = onboarding_error or (
            "La pregunta de incorporación de Society no está configurada."
            if onboarding_state == "not_configured"
            else f"Estado de incorporación no confirmado: {onboarding_state or 'desconocido'}."
        )
        if not rollback.complete:
            reason += " Rollback parcial: " + "; ".join(rollback.errors)

        raise SocietySpaceError(
            "No se creó la Society porque su rol INT no quedó añadido a "
            f"Discord Onboarding. {reason}"
        )

    async def _place_society_category(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
    ) -> None:
        # Ya no dependemos de que la categoría contenga `{ VXS }`. Las
        # plantillas pueden omitir variables o decorarlas libremente, por lo
        # que la fuente estable son los category_id registrados en PostgreSQL.
        rows = await list_associates(
            self.db,
            self.settings.society_db_schema,
            guild.id,
        )
        registered_ids = {
            int(row["category_id"])
            for row in rows
            if row["category_id"]
            and int(row["category_id"]) != int(category.id)
            and str(row["status"] or "") == "active"
        }
        existing_society = [
            current
            for category_id in registered_ids
            if isinstance(
                (current := guild.get_channel(category_id)),
                discord.CategoryChannel,
            )
        ]

        anchor: discord.CategoryChannel | None = None
        if existing_society:
            anchor = max(existing_society, key=lambda item: item.position)
        else:
            configured_id = await get_base_category(
                self.db,
                self.settings.society_db_schema,
                guild.id,
            )
            configured = guild.get_channel(configured_id) if configured_id else None
            if isinstance(configured, discord.CategoryChannel):
                anchor = configured
            else:
                anchor = next(
                    (
                        item
                        for item in guild.categories
                        if item.name.casefold() == "comunidad"
                    ),
                    None,
                )

        if anchor is not None:
            await category.move(
                after=anchor,
                reason="VEXEN Society: posicionar categoría Society",
            )
