from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import suppress
from typing import Any

import discord

from app.society.welcome import disable_welcome_button, publish_welcome
from database import (
    delete_associate_channel_record,
    get_associate,
    get_associate_space,
    list_associate_channels,
    list_associates,
)

log = logging.getLogger("vexen_society.dashboard_control")


class DashboardControlWorker:
    """Consume trabajos creados por VEXEN Society Dashboard.

    El Dashboard nunca replica las operaciones Discord complejas: únicamente
    crea un job. Este worker vive dentro del bot oficial y ejecuta la misma
    SpaceService que usan los comandos de Society.
    """

    POLL_SECONDS = 2
    MAX_ATTEMPTS = 3

    def __init__(self, bot, settings) -> None:
        self.bot = bot
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def db(self):
        if self.bot.db is None:
            raise RuntimeError("PostgreSQL no está disponible.")
        return self.bot.db

    @property
    def schema(self) -> str:
        return self.settings.society_db_schema

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(
                self._run(), name="vexen-society-dashboard-control"
            )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _ensure_tables(self) -> None:
        s = self.schema
        await self.db.execute(f'''
            CREATE TABLE IF NOT EXISTS "{s}".society_control_jobs (
                job_id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                actor_id BIGINT NOT NULL,
                associate_user_id BIGINT,
                payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                status TEXT NOT NULL DEFAULT 'pending',
                result JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                error_message TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                CHECK (status IN ('pending','processing','completed','error','cancelled'))
            )
        ''')
        await self.db.execute(f'''
            CREATE INDEX IF NOT EXISTS society_control_jobs_status_idx
            ON "{s}".society_control_jobs(guild_id,status,created_at)
        ''')
        await self.db.execute(f'''
            CREATE TABLE IF NOT EXISTS "{s}".society_applications (
                application_id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                discord_username TEXT NOT NULL,
                public_name TEXT NOT NULL,
                community_name TEXT NOT NULL,
                platforms JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                selected_channel_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
                requested_channels JSONB NOT NULL DEFAULT '[]'::jsonb,
                extra_channel_request TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                applicant_message TEXT,
                admin_message TEXT,
                reviewed_by BIGINT,
                control_job_id BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CHECK (status IN ('draft','pending','review','needs_info','approved','creating','active','rejected','cancelled','error'))
            )
        ''')
        await self.db.execute(
            f'ALTER TABLE "{s}".society_applications '
            "ADD COLUMN IF NOT EXISTS requested_channels JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
        # La tabla de heartbeat normalmente la crea el Dashboard. La creamos
        # también aquí para que el puente pueda funcionar de forma autónoma.
        await self.db.execute(f'''
            CREATE TABLE IF NOT EXISTS "{s}".service_heartbeats (
                service_name TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'online',
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CHECK (status IN ('online','degraded','offline','starting'))
            )
        ''')

    async def _heartbeat(self, *, status: str = "online", metadata: dict | None = None) -> None:
        await self.db.execute(
            f'''INSERT INTO "{self.schema}".service_heartbeats(service_name,status,metadata)
                VALUES ('vexen-society-bot-control',$1,$2::jsonb)
                ON CONFLICT (service_name) DO UPDATE SET
                    status=EXCLUDED.status, metadata=EXCLUDED.metadata, heartbeat_at=NOW(),
                    started_at=CASE WHEN EXCLUDED.status='starting' THEN NOW() ELSE "{self.schema}".service_heartbeats.started_at END''',
            status,
            json.dumps(metadata or {}),
        )

    async def _recover_stale_jobs(self) -> None:
        await self.db.execute(
            f'''UPDATE "{self.schema}".society_control_jobs
                SET status=CASE WHEN attempt_count >= $1 THEN 'error' ELSE 'pending' END,
                    error_message=CASE WHEN attempt_count >= $1
                        THEN COALESCE(error_message,'Máximo de intentos alcanzado.')
                        ELSE 'Recuperado después de una ejecución interrumpida.' END,
                    started_at=NULL,
                    finished_at=CASE WHEN attempt_count >= $1 THEN NOW() ELSE finished_at END
                WHERE status='processing'
                  AND started_at < NOW() - INTERVAL '5 minutes' ''',
            self.MAX_ATTEMPTS,
        )

    async def _claim(self):
        async with self.db.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f'''SELECT * FROM "{self.schema}".society_control_jobs
                        WHERE guild_id=$1 AND status='pending'
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1''',
                    self.settings.guild_id,
                )
                if row is None:
                    return None
                await conn.execute(
                    f'''UPDATE "{self.schema}".society_control_jobs
                        SET status='processing',started_at=NOW(),attempt_count=attempt_count+1,
                            error_message=NULL
                        WHERE job_id=$1''',
                    row["job_id"],
                )
                return dict(row)

    async def _finish(self, job_id: int, *, result: dict | None = None) -> None:
        await self.db.execute(
            f'''UPDATE "{self.schema}".society_control_jobs
                SET status='completed',result=$2::jsonb,error_message=NULL,finished_at=NOW()
                WHERE job_id=$1''',
            job_id,
            json.dumps(result or {}),
        )

    async def _fail(self, job: dict, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {str(exc)}"[:1500]
        job_id = int(job["job_id"])
        attempts = int(job.get("attempt_count") or 0) + 1
        retryable = attempts < self.MAX_ATTEMPTS
        await self.db.execute(
            f'''UPDATE "{self.schema}".society_control_jobs
                SET status=$2,error_message=$3,started_at=NULL,
                    finished_at=CASE WHEN $2='error' THEN NOW() ELSE NULL END
                WHERE job_id=$1''',
            job_id,
            "pending" if retryable else "error",
            message,
        )
        application_id = self._payload(job).get("application_id")
        if application_id and not retryable:
            await self.db.execute(
                f'''UPDATE "{self.schema}".society_applications
                    SET status='error',admin_message=$2,updated_at=NOW()
                    WHERE application_id=$1''',
                int(application_id),
                message[:1000],
            )
        log.exception("Job Society #%s falló%s", job_id, " y se reintentará" if retryable else "")

    @staticmethod
    def _payload(job: dict) -> dict[str, Any]:
        value = job.get("payload")
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _requested_channels(payload: dict) -> list[dict[str, str]]:
        raw = payload.get("requested_channels") or []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = []
        if not isinstance(raw, list):
            raise ValueError("La lista de canales adicionales es inválida.")
        if len(raw) > 10:
            raise ValueError("La solicitud excede el máximo de 10 canales adicionales.")
        allowed = {"TXT", "STAFF-TXT", "VOICE", "STAFF-VOICE"}
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("La definición de un canal adicional es inválida.")
            channel_type = str(item.get("type") or "").strip().upper()
            name = str(item.get("name") or "").strip()
            if channel_type not in allowed:
                raise ValueError("Tipo de canal adicional no permitido.")
            if not 1 <= len(name) <= 100:
                raise ValueError("Nombre de canal adicional inválido.")
            key = (channel_type, name.casefold())
            if key in seen:
                continue
            seen.add(key)
            result.append({"type": channel_type, "name": name})
        return result

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        message = str(exc).strip()
        return f"{type(exc).__name__}: {message}" if message else type(exc).__name__

    async def _audit(
        self,
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
            int(self.settings.guild_id),
            action,
            actor_id,
            associate_user_id,
            community_name,
            json.dumps(metadata or {}, ensure_ascii=False),
        )

    async def _guild(self) -> discord.Guild:
        guild_id = int(self.settings.guild_id)
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            raise RuntimeError("El servidor configurado no está disponible para el bot.")
        return guild

    async def _create_society(self, job: dict, guild: discord.Guild) -> dict:
        payload = self._payload(job)
        user_id = int(job["associate_user_id"] or 0)
        actor_id = int(job["actor_id"])
        display_name = str(payload.get("display_name") or "").strip()
        community_name = str(payload.get("community_name") or "").strip()
        requested_channels = self._requested_channels(payload)
        if not user_id or not display_name or not community_name:
            raise ValueError("Faltan usuario, nombre público o comunidad.")

        existing = await get_associate(self.db, self.schema, guild.id, user_id)
        inserted = False
        space_created = False
        if existing is None:
            duplicate = await self.db.fetchval(
                f'''SELECT EXISTS(SELECT 1 FROM "{self.schema}".associates
                    WHERE guild_id=$1 AND lower(community_name)=lower($2))''',
                guild.id,
                community_name,
            )
            if duplicate:
                raise ValueError("Ya existe una Society con ese nombre de comunidad.")
            await self.db.execute(
                f'''INSERT INTO "{self.schema}".associates
                    (guild_id,user_id,display_name,community_name,added_by)
                    VALUES ($1,$2,$3,$4,$5)''',
                guild.id,
                user_id,
                display_name,
                community_name,
                actor_id,
            )
            inserted = True
        else:
            space = await get_associate_space(self.db, self.schema, guild.id, user_id)
            if space is not None and space["status"] == "active":
                raise ValueError("Ese usuario ya tiene una Society activa.")

        try:
            created = await self.bot.space_service.create_space(guild, user_id, actor_id)
            space_created = True
            pruned = await self._apply_initial_channel_selection(guild, user_id, payload)
            custom_channels: list[dict[str, Any]] = []
            for item in requested_channels:
                channel = await self.bot.space_service.create_custom_channel(
                    guild,
                    user_id,
                    actor_id,
                    item["type"],
                    item["name"],
                )
                custom_channels.append(
                    {"channel_id": channel.id, "type": item["type"], "name": channel.name}
                )
        except Exception:
            if space_created:
                # Si falla un canal solicitado después de crear la estructura,
                # revertimos la Society completa para no dejar Discord y DB a medias.
                with suppress(Exception):
                    await self.bot.space_service.delete_space(guild, user_id, actor_id)
            elif inserted:
                with suppress(Exception):
                    await self.db.execute(
                        f'DELETE FROM "{self.schema}".associates WHERE guild_id=$1 AND user_id=$2',
                        guild.id,
                        user_id,
                    )
            raise

        application_id = payload.get("application_id")
        if application_id:
            await self.db.execute(
                f'''UPDATE "{self.schema}".society_applications
                    SET status='active',admin_message=NULL,updated_at=NOW()
                    WHERE application_id=$1''',
                int(application_id),
            )

        return {
            "community_name": community_name,
            "category_id": created["category"].id,
            "channels_created": len(created["channels"]),
            "channels_omitted": pruned,
            "requested_channels_created": custom_channels,
            "welcome_published": bool(created.get("welcome_message")),
            "onboarding_state": created.get("onboarding_state"),
        }

    async def _apply_initial_channel_selection(self, guild: discord.Guild, user_id: int, payload: dict) -> int:
        if "selected_channel_keys" not in payload:
            return 0
        selected = {str(v) for v in payload.get("selected_channel_keys") or []}
        selected.add("announcements")
        # Respeta también cualquier canal marcado como obligatorio en la
        # plantilla activa al momento real de creación.
        template_json = await self.db.fetchval(
            f'SELECT parsed_template FROM "{self.schema}".category_templates WHERE guild_id=$1 AND is_active=TRUE',
            guild.id,
        )
        if isinstance(template_json, str):
            try:
                template_json = json.loads(template_json)
            except json.JSONDecodeError:
                template_json = {}
        if isinstance(template_json, dict):
            for item in template_json.get("channels") or []:
                if isinstance(item, dict) and item.get("required"):
                    selected.add(str(item.get("key") or ""))
        rows = await list_associate_channels(self.db, self.schema, guild.id, user_id)
        removed = 0
        for row in rows:
            if not row["is_template"] or str(row["channel_key"]) in selected:
                continue
            channel = guild.get_channel(int(row["channel_id"]))
            if channel is not None:
                await channel.delete(reason="VEXEN Society: canal no seleccionado en solicitud")
            await delete_associate_channel_record(
                self.db, self.schema, guild.id, int(row["channel_id"])
            )
            removed += 1
        return removed

    async def _resend_welcome(self, job: dict, guild: discord.Guild) -> dict:
        user_id = int(job["associate_user_id"] or 0)
        row = await get_associate(self.db, self.schema, guild.id, user_id)
        space = await get_associate_space(self.db, self.schema, guild.id, user_id)
        if row is None or space is None or space["status"] != "active":
            raise ValueError("La Society no está activa.")
        old_space = space
        message, error = await publish_welcome(
            self.bot,
            self.settings,
            guild,
            user_id,
            row["display_name"],
            row["community_name"],
            space["community_role_id"],
            int(job["actor_id"]),
        )
        if message is None:
            raise RuntimeError(error or "No se pudo publicar la bienvenida.")
        await disable_welcome_button(
            self.bot, self.settings, guild, old_space, row["community_name"]
        )
        await self._audit(
            "DASHBOARD_WELCOME_REPUBLISHED",
            int(job["actor_id"]),
            associate_user_id=user_id,
            community_name=str(row["community_name"]),
            metadata={"channel_id": message.channel.id, "message_id": message.id},
        )
        return {"channel_id": message.channel.id, "message_id": message.id}

    async def _set_config(self, job: dict) -> dict:
        payload = self._payload(job)
        key = str(payload.get("key") or "").strip()
        value = str(payload.get("value") or "").strip()
        columns = {
            "global_announcements_channel_id": "bigint",
            "base_category_id": "bigint",
            "welcome_channel_id": "bigint",
            "log_channel_id": "bigint",
            "welcome_color_hex": "text",
            "welcome_button_style": "text",
            "announcement_button_style": "text",
            "community_button_style": "text",
        }
        if key not in columns:
            raise ValueError("Ajuste no permitido.")
        if columns[key] == "bigint":
            parsed: Any = int(value) if value else None
        else:
            parsed = value
            if key == "welcome_color_hex" and not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                raise ValueError("El color debe usar formato #RRGGBB.")
            if key.endswith("button_style") and value not in {"primary", "secondary", "success", "danger"}:
                raise ValueError("Estilo de botón inválido.")
        # Las columnas están en allowlist; nunca provienen libres del usuario.
        await self.db.execute(
            f'''INSERT INTO "{self.schema}".settings(guild_id,{key},updated_by)
                VALUES ($1,$2,$3)
                ON CONFLICT (guild_id) DO UPDATE SET
                    {key}=EXCLUDED.{key},updated_by=EXCLUDED.updated_by,updated_at=NOW()''',
            int(self.settings.guild_id),
            parsed,
            int(job["actor_id"]),
        )
        await self._audit(
            "DASHBOARD_CONFIG_UPDATED",
            int(job["actor_id"]),
            metadata={"key": key, "value": parsed},
        )
        return {"key": key, "value": parsed}

    async def _access_role(self, job: dict, *, add: bool) -> dict:
        if int(job["actor_id"]) != int(self.settings.owner_id):
            raise PermissionError("Solo OWNER puede modificar los roles administrativos de Society.")
        role_id = int(self._payload(job).get("role_id") or 0)
        if not role_id:
            raise ValueError("ID de rol inválido.")
        guild_id = int(self.settings.guild_id)
        if add:
            await self.db.execute(
                f'''INSERT INTO "{self.schema}".allowed_roles(guild_id,role_id,added_by)
                    VALUES ($1,$2,$3) ON CONFLICT DO NOTHING''',
                guild_id, role_id, int(job["actor_id"]),
            )
        else:
            await self.db.execute(
                f'DELETE FROM "{self.schema}".allowed_roles WHERE guild_id=$1 AND role_id=$2',
                guild_id, role_id,
            )
        await self._audit(
            "DASHBOARD_ALLOWED_ROLE_ADDED" if add else "DASHBOARD_ALLOWED_ROLE_REMOVED",
            int(job["actor_id"]),
            metadata={"role_id": role_id, "authorized": add},
        )
        return {"role_id": role_id, "authorized": add}

    async def _staff(self, job: dict, guild: discord.Guild, *, add: bool) -> dict:
        user_id = int(job["associate_user_id"] or 0)
        member_id = int(self._payload(job).get("member_id") or 0)
        space = await get_associate_space(self.db, self.schema, guild.id, user_id)
        if space is None or space["status"] != "active":
            raise ValueError("La Society no está activa.")
        role = guild.get_role(int(space["staff_role_id"] or 0))
        if role is None:
            raise ValueError("El rol Staff ya no existe.")
        member = guild.get_member(member_id)
        if member is None:
            member = await guild.fetch_member(member_id)
        if add:
            await member.add_roles(role, reason="VEXEN Society Dashboard: agregar Staff")
        else:
            await member.remove_roles(role, reason="VEXEN Society Dashboard: quitar Staff")
        associate = await get_associate(self.db, self.schema, guild.id, user_id)
        await self._audit(
            "DASHBOARD_STAFF_ADDED" if add else "DASHBOARD_STAFF_REMOVED",
            int(job["actor_id"]),
            associate_user_id=user_id,
            community_name=str(associate["community_name"]) if associate else None,
            metadata={"member_id": member.id, "staff_role_id": role.id, "added": add},
        )
        return {"member_id": member.id, "staff_role_id": role.id, "added": add}

    async def _execute(self, job: dict) -> dict:
        guild = await self._guild()
        action = str(job["action"])
        user_id = int(job["associate_user_id"] or 0)
        actor_id = int(job["actor_id"])
        payload = self._payload(job)

        if action == "create_society":
            return await self._create_society(job, guild)
        if action == "delete_society":
            report = await self.bot.space_service.delete_space(guild, user_id, actor_id)
            if not report.complete:
                raise RuntimeError("Eliminación parcial: " + "; ".join(report.errors))
            return {"complete": True, "deleted": report.deleted, "missing": report.missing, "errors": []}
        if action in {"sync_template", "repair_society"}:
            created = await self.bot.space_service.sync_template(guild, user_id, actor_id)
            if action == "repair_society":
                report = await self.bot.space_service.refresh_staff_category_permissions(guild)
                return {"created_channels": created, "permissions": report}
            return {"created_channels": created}
        if action == "sync_all_templates":
            rows = await list_associates(self.db, self.schema, guild.id)
            results: list[dict] = []
            for row in rows:
                if row["status"] != "active":
                    continue
                try:
                    created = await self.bot.space_service.sync_template(
                        guild, int(row["user_id"]), actor_id
                    )
                    results.append({"user_id": int(row["user_id"]), "created": created, "ok": True})
                except Exception as exc:
                    results.append({"user_id": int(row["user_id"]), "ok": False, "error": str(exc)[:300]})
            return {"societies": results}
        if action == "resend_welcome":
            return await self._resend_welcome(job, guild)
        if action == "create_custom_channel":
            channel = await self.bot.space_service.create_custom_channel(
                guild, user_id, actor_id, str(payload.get("channel_type") or "TXT"), str(payload.get("name") or "")
            )
            return {"channel_id": channel.id, "name": channel.name}
        if action == "rename_category":
            await self.bot.space_service.rename_category(guild, user_id, actor_id, str(payload.get("new_name") or ""))
            return {"renamed": True}
        if action == "rename_channel":
            await self.bot.space_service.rename_channel(guild, user_id, actor_id, int(payload.get("channel_id") or 0), str(payload.get("new_name") or ""))
            return {"renamed": True}
        if action == "delete_custom_channel":
            await self.bot.space_service.delete_custom_channel(guild, user_id, actor_id, int(payload.get("channel_id") or 0))
            return {"deleted": True}
        if action == "staff_add":
            return await self._staff(job, guild, add=True)
        if action == "staff_remove":
            return await self._staff(job, guild, add=False)
        if action == "set_config":
            return await self._set_config(job)
        if action == "allowed_role_add":
            return await self._access_role(job, add=True)
        if action == "allowed_role_remove":
            return await self._access_role(job, add=False)
        if action == "refresh_staff_permissions":
            report = await self.bot.space_service.refresh_staff_category_permissions(guild)
            await self._audit(
                "DASHBOARD_STAFF_PERMISSIONS_REFRESHED",
                actor_id,
                metadata=report,
            )
            return report
        if action == "configure_onboarding":
            if self.bot.onboarding_integration is None:
                raise RuntimeError("La integración de incorporación no está disponible.")
            report = await self.bot.onboarding_integration.configure_and_sync(
                guild, str(payload.get("prompt_identifier") or ""), actor_id
            )
            result = {
                "configured": report.configured, "prompt_title": report.prompt_title,
                "added": report.added, "updated": report.updated,
                "unchanged": report.unchanged, "conflicts": report.conflicts,
            }
            await self._audit(
                "DASHBOARD_ONBOARDING_CONFIGURED",
                actor_id,
                metadata=result,
            )
            return result
        if action == "sync_onboarding":
            if self.bot.onboarding_integration is None:
                raise RuntimeError("La integración de incorporación no está disponible.")
            report = await self.bot.onboarding_integration.sync_all(guild, actor_id)
            result = {
                "configured": report.configured, "prompt_title": report.prompt_title,
                "added": report.added, "updated": report.updated,
                "unchanged": report.unchanged, "conflicts": report.conflicts,
            }
            await self._audit(
                "DASHBOARD_ONBOARDING_SYNCED",
                actor_id,
                metadata=result,
            )
            return result
        raise ValueError(f"Acción de Dashboard desconocida: {action}")

    async def _run(self) -> None:
        await self.bot.wait_until_ready()
        initialized = False
        cycles = 0
        backoff = self.POLL_SECONDS
        while not self._stop.is_set():
            try:
                if not initialized:
                    await self._ensure_tables()
                    await self._heartbeat(status="starting")
                    log.info("Puente Dashboard → VEXEN Society Bot iniciado.")
                    initialized = True
                    cycles = 0

                cycles += 1
                if cycles == 1 or cycles % 150 == 0:
                    await self._recover_stale_jobs()
                job = await self._claim()
                if job is None:
                    if cycles % 15 == 0:
                        await self._heartbeat(status="online", metadata={"cycles": cycles})
                    backoff = self.POLL_SECONDS
                    await asyncio.sleep(self.POLL_SECONDS)
                    continue

                try:
                    result = await self._execute(job)
                    await self._finish(int(job["job_id"]), result=result)
                    await self._heartbeat(
                        status="online",
                        metadata={
                            "cycles": cycles,
                            "last_job_id": int(job["job_id"]),
                            "last_action": str(job["action"]),
                        },
                    )
                    log.info("Job Society #%s (%s) completado.", job["job_id"], job["action"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self._fail(job, exc)
                backoff = self.POLL_SECONDS
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error_text = self._error_text(exc)[:500]
                log.exception(
                    "Puente Dashboard → Bot perdió temporalmente acceso a un recurso; "
                    "reintentará en %ss. Error: %s",
                    backoff,
                    error_text,
                )
                with suppress(Exception):
                    await self._heartbeat(
                        status="degraded",
                        metadata={
                            "recoverable_error": error_text,
                            "retry_in_seconds": backoff,
                        },
                    )
                await asyncio.sleep(backoff)
                backoff = min(max(self.POLL_SECONDS, backoff * 2), 30)

