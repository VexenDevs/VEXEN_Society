from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

import discord
from discord import app_commands

from app.bot.checks import require_admin

log = logging.getLogger("vexen_society.discord_logs")


_ACTION_LABELS = {
    "SOCIETY_CREATED": "Society creada",
    "SOCIETY_DELETE_REQUESTED": "Eliminación de Society solicitada",
    "SOCIETY_DELETED": "Society eliminada",
    "SOCIETY_DELETE_PARTIAL": "Eliminación parcial de Society",
    "SOCIETY_DELETE_BLOCKED_ONBOARDING": "Eliminación bloqueada por incorporación",
    "TEMPLATE_SYNCED": "Plantilla sincronizada",
    "TEMPLATE_VISUAL_SAVED": "Nueva plantilla activada",
    "CUSTOM_CHANNEL_CREATED": "Canal personalizado creado",
    "CUSTOM_CHANNEL_DELETED": "Canal personalizado eliminado",
    "CATEGORY_RENAMED": "Categoría renombrada",
    "CHANNEL_RENAMED": "Canal renombrado",
    "STAFF_MEMBER_ADDED": "Miembro agregado al Staff",
    "STAFF_MEMBER_REMOVED": "Miembro retirado del Staff",
    "WELCOME_REPUBLISHED": "Bienvenida republicada",
    "SOCIETY_APPLICATION_SUBMITTED": "Nueva solicitud de Society",
    "DASHBOARD_CONFIG_UPDATED": "Configuración actualizada",
    "DASHBOARD_ALLOWED_ROLE_ADDED": "Rol administrativo autorizado",
    "DASHBOARD_ALLOWED_ROLE_REMOVED": "Rol administrativo retirado",
    "DASHBOARD_STAFF_ADDED": "Staff agregado desde Dashboard",
    "DASHBOARD_STAFF_REMOVED": "Staff retirado desde Dashboard",
    "DASHBOARD_WELCOME_REPUBLISHED": "Bienvenida republicada desde Dashboard",
    "DASHBOARD_STAFF_PERMISSIONS_REFRESHED": "Permisos Staff reconciliados",
    "DASHBOARD_ONBOARDING_CONFIGURED": "Incorporación configurada desde Dashboard",
    "DASHBOARD_ONBOARDING_SYNCED": "Incorporación sincronizada desde Dashboard",
    "LOG_CHANNEL_CONFIGURED": "Canal de logs configurado",
    "LOG_CHANNEL_DISABLED": "Canal de logs desactivado",
}

_METADATA_LABELS = {
    "template_version": "Plantilla",
    "created_channels": "Canales creados",
    "channels": "Canales",
    "name": "Nombre",
    "type": "Tipo",
    "onboarding_state": "Incorporación",
    "status": "Estado",
    "key": "Ajuste",
    "value": "Valor",
    "authorized": "Autorizado",
    "added": "Agregado",
    "configured": "Configurado",
    "prompt_title": "Pregunta",
    "updated": "Actualizados",
    "unchanged": "Sin cambios",
    "failed": "Fallos",
}


def _humanize_action(action: str) -> str:
    if action in _ACTION_LABELS:
        return _ACTION_LABELS[action]
    return action.replace("_", " ").strip().title() or "Evento Society"


def _severity(action: str) -> tuple[str, discord.Color]:
    upper = action.upper()
    if any(token in upper for token in ("ERROR", "FAILED", "PARTIAL", "BLOCKED")):
        return "ERROR", discord.Color.red()
    if any(token in upper for token in ("DELETE_REQUESTED", "REMOVED", "DISABLED")):
        return "WARNING", discord.Color.orange()
    if any(token in upper for token in ("ALLOWED_ROLE", "ACCESS", "CONFIG_UPDATED", "LOG_CHANNEL")):
        return "SECURITY", discord.Color.gold()
    return "SUCCESS", discord.Color.green()


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _metadata_lines(value: Any) -> list[str]:
    metadata = _metadata_dict(value)
    lines: list[str] = []
    for key, raw in metadata.items():
        if key.endswith("_id") or key in {
            "deleted",
            "missing",
            "errors",
            "selected_channel_keys",
            "permissions",
            "societies",
        }:
            continue
        if isinstance(raw, (dict, list, tuple)):
            continue
        if raw is None or raw == "":
            continue
        label = _METADATA_LABELS.get(key, key.replace("_", " ").capitalize())
        text = str(raw)
        if len(text) > 180:
            text = text[:177] + "…"
        lines.append(f"**{label}:** {text}")
        if len(lines) >= 6:
            break
    return lines


class SocietyLogService:
    POLL_SECONDS = 3

    def __init__(self, bot, settings) -> None:
        self.bot = bot
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._commands_registered = False

    @property
    def db(self):
        if self.bot.db is None:
            raise RuntimeError("PostgreSQL no está disponible.")
        return self.bot.db

    @property
    def schema(self) -> str:
        return self.settings.society_db_schema

    async def setup(self, society_cog) -> None:
        await self._ensure_schema()
        self.register_commands(society_cog)

    async def _ensure_schema(self) -> None:
        s = self.schema
        await self.db.execute(
            f'ALTER TABLE "{s}".settings ADD COLUMN IF NOT EXISTS log_channel_id BIGINT'
        )
        await self.db.execute(
            f'''CREATE TABLE IF NOT EXISTS "{s}".discord_log_state (
                guild_id BIGINT PRIMARY KEY,
                last_log_id BIGINT NOT NULL DEFAULT 0,
                configured_channel_id BIGINT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )'''
        )
        await self.db.execute(
            f'ALTER TABLE "{s}".discord_log_state ADD COLUMN IF NOT EXISTS configured_channel_id BIGINT'
        )

    def register_commands(self, society_cog) -> None:
        if self._commands_registered:
            return

        async def canal_logs(
            interaction: discord.Interaction,
            canal: discord.TextChannel | None = None,
        ) -> None:
            if not await require_admin(
                interaction,
                self.settings,
                self.bot.db,
            ):
                return
            if interaction.guild is None:
                await interaction.response.send_message(
                    "❌ Este comando solo puede usarse dentro del servidor.",
                    ephemeral=True,
                )
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            await self.configure_channel(
                interaction.guild,
                canal,
                actor_id=interaction.user.id,
            )
            if canal is None:
                await interaction.followup.send(
                    "✅ Canal de logs desactivado.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"✅ Los logs de VEXEN Society se enviarán a {canal.mention}.",
                    ephemeral=True,
                )

        async def probar_logs(interaction: discord.Interaction) -> None:
            if not await require_admin(
                interaction,
                self.settings,
                self.bot.db,
            ):
                return
            if interaction.guild is None:
                await interaction.response.send_message(
                    "❌ Este comando solo puede usarse dentro del servidor.",
                    ephemeral=True,
                )
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            channel = await self._configured_channel(interaction.guild)
            if channel is None:
                await interaction.followup.send(
                    "❌ No hay un canal de logs configurado.",
                    ephemeral=True,
                )
                return
            await channel.send(
                embed=self._system_embed(
                    "Prueba de logs completada",
                    "El canal está configurado y el bot puede publicar correctamente.",
                    interaction.user,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await interaction.followup.send(
                f"✅ Log de prueba enviado a {channel.mention}.",
                ephemeral=True,
            )

        society_cog.config.add_command(
            app_commands.Command(
                name="canal_logs",
                description="Configura o desactiva el canal de logs de VEXEN Society",
                callback=canal_logs,
            )
        )
        society_cog.config.add_command(
            app_commands.Command(
                name="probar_logs",
                description="Envía un log de prueba al canal configurado",
                callback=probar_logs,
            )
        )
        self._commands_registered = True

    async def configure_channel(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel | None,
        *,
        actor_id: int,
    ) -> None:
        await self._ensure_schema()
        channel_id = channel.id if channel is not None else None
        await self.db.execute(
            f'''INSERT INTO "{self.schema}".settings(guild_id,log_channel_id,updated_by)
                VALUES ($1,$2,$3)
                ON CONFLICT (guild_id) DO UPDATE SET
                    log_channel_id=EXCLUDED.log_channel_id,
                    updated_by=EXCLUDED.updated_by,
                    updated_at=NOW()''',
            guild.id,
            channel_id,
            actor_id,
        )
        current_max = int(
            await self.db.fetchval(
                f'SELECT COALESCE(MAX(log_id),0) FROM "{self.schema}".audit_logs WHERE guild_id=$1',
                guild.id,
            )
            or 0
        )
        await self.db.execute(
            f'''INSERT INTO "{self.schema}".discord_log_state
                    (guild_id,last_log_id,configured_channel_id)
                VALUES ($1,$2,$3)
                ON CONFLICT (guild_id) DO UPDATE SET
                    last_log_id=EXCLUDED.last_log_id,
                    configured_channel_id=EXCLUDED.configured_channel_id,
                    updated_at=NOW()''',
            guild.id,
            current_max,
            channel_id,
        )
        action = "LOG_CHANNEL_CONFIGURED" if channel_id else "LOG_CHANNEL_DISABLED"
        await self._insert_audit(
            guild.id,
            action,
            actor_id,
            metadata={"channel_name": channel.name if channel else "Desactivado"},
        )
        newest = int(
            await self.db.fetchval(
                f'SELECT COALESCE(MAX(log_id),0) FROM "{self.schema}".audit_logs WHERE guild_id=$1',
                guild.id,
            )
            or current_max
        )
        await self._set_cursor(guild.id, newest)
        if channel is not None:
            with suppress(discord.Forbidden, discord.HTTPException):
                actor = guild.get_member(actor_id)
                await channel.send(
                    embed=self._system_embed(
                        "Canal de logs configurado",
                        "A partir de ahora las acciones importantes de VEXEN Society aparecerán aquí.",
                        actor,
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )

    async def _insert_audit(
        self,
        guild_id: int,
        action: str,
        actor_id: int,
        *,
        associate_user_id: int | None = None,
        community_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.db.execute(
            f'''INSERT INTO "{self.schema}".audit_logs
                (guild_id,action,actor_id,associate_user_id,community_name,metadata)
                VALUES ($1,$2,$3,$4,$5,$6::jsonb)''',
            guild_id,
            action,
            actor_id,
            associate_user_id,
            community_name,
            json.dumps(metadata or {}, ensure_ascii=False),
        )

    async def _configured_channel_id(self, guild_id: int) -> int | None:
        value = await self.db.fetchval(
            f'SELECT log_channel_id FROM "{self.schema}".settings WHERE guild_id=$1',
            guild_id,
        )
        return int(value) if value else None

    async def _configured_channel(
        self,
        guild: discord.Guild,
    ) -> discord.TextChannel | None:
        channel_id = await self._configured_channel_id(guild.id)
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _sync_external_channel_change(self, guild: discord.Guild) -> int | None:
        configured = await self._configured_channel_id(guild.id)
        state = await self.db.fetchrow(
            f'SELECT last_log_id,configured_channel_id FROM "{self.schema}".discord_log_state WHERE guild_id=$1',
            guild.id,
        )
        previous = int(state["configured_channel_id"]) if state and state["configured_channel_id"] else None
        if state is not None and previous == configured:
            return configured

        current_max = int(
            await self.db.fetchval(
                f'SELECT COALESCE(MAX(log_id),0) FROM "{self.schema}".audit_logs WHERE guild_id=$1',
                guild.id,
            )
            or 0
        )
        await self.db.execute(
            f'''INSERT INTO "{self.schema}".discord_log_state
                    (guild_id,last_log_id,configured_channel_id)
                VALUES ($1,$2,$3)
                ON CONFLICT (guild_id) DO UPDATE SET
                    last_log_id=EXCLUDED.last_log_id,
                    configured_channel_id=EXCLUDED.configured_channel_id,
                    updated_at=NOW()''',
            guild.id,
            current_max,
            configured,
        )
        if configured:
            channel = guild.get_channel(configured)
            if isinstance(channel, discord.TextChannel):
                with suppress(discord.Forbidden, discord.HTTPException):
                    await channel.send(
                        embed=self._system_embed(
                            "Canal de logs actualizado",
                            "La configuración cambió desde el Dashboard y los nuevos eventos se registrarán aquí.",
                            None,
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
        return configured

    async def _state_cursor(self, guild_id: int) -> int:
        value = await self.db.fetchval(
            f'SELECT last_log_id FROM "{self.schema}".discord_log_state WHERE guild_id=$1',
            guild_id,
        )
        return int(value or 0)

    async def _set_cursor(self, guild_id: int, log_id: int) -> None:
        await self.db.execute(
            f'''UPDATE "{self.schema}".discord_log_state
                SET last_log_id=$2,updated_at=NOW()
                WHERE guild_id=$1''',
            guild_id,
            log_id,
        )

    def _system_embed(
        self,
        title: str,
        description: str,
        actor: discord.abc.User | None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"VEXEN SOCIETY • {title}",
            description=description,
            color=discord.Color.blurple(),
        )
        if actor is not None:
            embed.add_field(name="Ejecutado por", value=actor.mention, inline=False)
        embed.set_footer(text="VEXEN • SOCIETY LOGS")
        return embed

    def _audit_embed(self, guild: discord.Guild, row) -> discord.Embed:
        action = str(row["action"] or "EVENT")
        severity, color = _severity(action)
        embed = discord.Embed(
            title=f"VEXEN SOCIETY • {_humanize_action(action)}",
            color=color,
            timestamp=row["created_at"],
        )
        embed.add_field(name="Nivel", value=severity, inline=True)

        actor_id = int(row["actor_id"] or 0)
        if actor_id:
            actor = guild.get_member(actor_id)
            embed.add_field(
                name="Ejecutado por",
                value=actor.mention if actor else f"Usuario <@{actor_id}>",
                inline=True,
            )

        community_name = str(row["community_name"] or "").strip()
        if community_name:
            embed.add_field(name="Society", value=community_name, inline=True)

        associate_id = int(row["associate_user_id"] or 0)
        if associate_id:
            member = guild.get_member(associate_id)
            embed.add_field(
                name="Asociado",
                value=member.mention if member else f"<@{associate_id}>",
                inline=True,
            )

        lines = _metadata_lines(row["metadata"])
        if lines:
            embed.add_field(
                name="Detalles",
                value="\n".join(lines)[:1024],
                inline=False,
            )
        embed.set_footer(text="VEXEN • SOCIETY LOGS")
        return embed

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(
                self._run(),
                name="vexen-society-discord-logs",
            )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        message = str(exc).strip()
        return f"{type(exc).__name__}: {message}" if message else type(exc).__name__

    async def _run(self) -> None:
        await self.bot.wait_until_ready()
        log.info("Sistema de logs Discord de VEXEN Society iniciado.")
        backoff = self.POLL_SECONDS
        while not self._stop.is_set():
            try:
                guild_id = self.settings.guild_id
                if guild_id is None:
                    backoff = self.POLL_SECONDS
                    await asyncio.sleep(self.POLL_SECONDS)
                    continue
                guild = self.bot.get_guild(int(guild_id))
                if guild is None:
                    backoff = self.POLL_SECONDS
                    await asyncio.sleep(self.POLL_SECONDS)
                    continue

                configured = await self._sync_external_channel_change(guild)
                if not configured:
                    backoff = self.POLL_SECONDS
                    await asyncio.sleep(self.POLL_SECONDS)
                    continue
                channel = guild.get_channel(configured)
                if not isinstance(channel, discord.TextChannel):
                    backoff = self.POLL_SECONDS
                    await asyncio.sleep(self.POLL_SECONDS)
                    continue

                cursor = await self._state_cursor(guild.id)
                rows = await self.db.fetch(
                    f'''SELECT log_id,guild_id,action,actor_id,associate_user_id,
                               community_name,metadata,created_at
                        FROM "{self.schema}".audit_logs
                        WHERE guild_id=$1 AND log_id>$2
                        ORDER BY log_id ASC
                        LIMIT 25''',
                    guild.id,
                    cursor,
                )
                for row in rows:
                    try:
                        await channel.send(
                            embed=self._audit_embed(guild, row),
                            allowed_mentions=discord.AllowedMentions(
                                everyone=False,
                                roles=False,
                                users=True,
                                replied_user=False,
                            ),
                        )
                    except discord.NotFound:
                        log.warning("El canal de logs configurado ya no existe.")
                        break
                    except discord.Forbidden:
                        log.warning("Sin permisos para escribir en el canal de logs.")
                        break
                    except discord.HTTPException:
                        log.exception("Discord rechazó temporalmente un log de Society.")
                        break
                    else:
                        await self._set_cursor(guild.id, int(row["log_id"]))

                backoff = self.POLL_SECONDS
                await asyncio.sleep(self.POLL_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error_text = self._error_text(exc)[:500]
                log.exception(
                    "Sistema de logs Discord perdió temporalmente acceso a un recurso; "
                    "reintentará en %ss. Error: %s",
                    backoff,
                    error_text,
                )
                await asyncio.sleep(backoff)
                backoff = min(max(self.POLL_SECONDS, backoff * 2), 30)

