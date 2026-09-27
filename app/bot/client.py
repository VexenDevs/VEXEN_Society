from __future__ import annotations

import logging

import asyncpg
import discord
from discord.ext import commands

from app.bot.control_jobs import DashboardControlWorker
from app.config.settings import Settings
from app.integrations.onboarding import OnboardingIntegration
from app.integrations.verification import VerificationIntegration
from app.society.announcements import (
    AnnouncementsCog,
    restore_announcement_role_views,
)
from app.society.associates import SocietyCog
from app.society.command_surface import simplify_commands
from app.society.logs import SocietyLogService
from app.society.space_service_v110 import VexenSpaceService
from app.society.templates import ensure_default_template
from app.society.welcome import restore_persistent_role_views
from database import create_pool

log = logging.getLogger("vexen_society.bot")


class VexenSocietyBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        intents.presences = False

        super().__init__(
            command_prefix="!",
            intents=intents,
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=True,
                replied_user=False,
            ),
        )

        self.settings = settings
        self.db: asyncpg.Pool | None = None
        self.space_service = VexenSpaceService(self, settings)
        self.verification_integration: VerificationIntegration | None = None
        self.onboarding_integration: OnboardingIntegration | None = None
        self.control_worker = DashboardControlWorker(self, settings)
        self.society_log_service = SocietyLogService(self, settings)
        self._staff_permissions_reconciled = False

    async def setup_hook(self) -> None:
        self.db = await create_pool(
            self.settings.database_url,
            self.settings.society_db_schema,
        )

        self.verification_integration = VerificationIntegration(
            self.db,
            self.settings,
        )
        self.onboarding_integration = OnboardingIntegration(
            self.db,
            self.settings,
        )

        await ensure_default_template(self.db, self.settings)

        restored_views = await restore_persistent_role_views(
            self,
            self.settings,
        )
        log.info("%d botones persistentes de comunidad restaurados.", restored_views)

        restored_announcement_views = await restore_announcement_role_views(
            self,
            self.settings,
        )
        log.info(
            "%d botones persistentes de anuncios restaurados.",
            restored_announcement_views,
        )

        society_cog = SocietyCog(self, self.settings)
        await self.society_log_service.setup(society_cog)
        # Logs retain their service, but never re-expose configuration slash commands.
        simplify_commands(society_cog.society)
        await self.add_cog(society_cog)
        await self.add_cog(AnnouncementsCog(self, self.settings))
        self.society_log_service.start()

        # El worker espera internamente a on_ready. Al ejecutarse dentro del
        # bot oficial, toda operación de Dashboard usa discord.py y SpaceService.
        self.control_worker.start()

        if not self.settings.sync_commands:
            log.info("SYNC_COMMANDS desactivado.")
            return
        if self.settings.guild_id is None:
            log.warning("GUILD_ID no configurado; no se sincronizarán comandos.")
            return

        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info(
            "%d comandos sincronizados en guild %d.",
            len(synced),
            self.settings.guild_id,
        )

    async def on_ready(self) -> None:
        if self.user is None:
            return
        log.info("VEXEN Society conectado como %s (%s)", self.user, self.user.id)

        if self.settings.guild_id is not None:
            for guild in list(self.guilds):
                if guild.id == self.settings.guild_id:
                    if not self._staff_permissions_reconciled:
                        try:
                            report = await self.space_service.refresh_staff_category_permissions(guild)
                            self._staff_permissions_reconciled = True
                            log.info(
                                "Permisos Staff Society sincronizados: %d categorías, %d canales Staff, %d faltantes, %d fallos.",
                                report["categories_updated"],
                                report["staff_channels_updated"],
                                report["missing"],
                                report["failed"],
                            )
                        except Exception:
                            log.exception("No se pudieron sincronizar los permisos Staff Society.")
                    continue

                log.warning("Abandonando guild no autorizado: %s (%s)", guild.name, guild.id)
                try:
                    await guild.leave()
                except discord.HTTPException:
                    pass

    async def on_guild_join(self, guild: discord.Guild) -> None:
        if self.settings.guild_id is None or guild.id != self.settings.guild_id:
            try:
                await guild.leave()
            except discord.HTTPException:
                pass

    async def close(self) -> None:
        await self.society_log_service.stop()
        await self.control_worker.stop()
        if self.db is not None:
            await self.db.close()
            self.db = None
        await super().close()
