from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.checks import (
    guild_is_authorized,
    is_society_admin,
    require_admin,
)
from app.config.settings import Settings
from app.society.command_surface import simplify_commands
from app.society.button_config import (
    community_button_style_label,
    normalize_community_button_style,
)
from app.society.template_parser import (
    TemplateValidationError,
    parse_template,
    render_category_name,
)
from app.society.templates import (
    active_template_file,
    preview_embed,
    template_from_row,
)
from app.society.welcome import (
    disable_welcome_button,
    publish_welcome,
    refresh_announcement_button_styles,
    refresh_welcome_button_styles,
)
from app.society.welcome_config import normalize_welcome_color
from app.society.views import (
    CreateSpaceView,
    DeleteSocietyView,
    ManageSocietyView,
    TemplateConfirmView,
)
from database import (
    add_allowed_role,
    add_audit_log,
    create_associate,
    get_active_template,
    get_associate,
    get_base_category,
    get_associate_by_community,
    get_associate_space,
    get_global_announcements_channel,
    get_announcement_button_style,
    get_welcome_button_style,
    get_welcome_channel,
    get_welcome_color,
    list_allowed_roles,
    list_associates,
    list_templates,
    remove_allowed_role,
    set_base_category,
    set_global_announcements_channel,
    set_announcement_button_style,
    set_welcome_button_style,
    set_welcome_channel,
    set_welcome_color,
)


class SocietyCog(commands.Cog):
    def __init__(
        self,
        bot,
        settings: Settings,
    ) -> None:
        self.bot = bot
        self.settings = settings
        simplify_commands(self.society)

    society = app_commands.Group(
        name="society",
        description=(
            "Administración de VEXEN Society"
        ),
    )

    asociado = app_commands.Group(
        name="asociado",
        description="Gestiona asociados",
        parent=society,
    )

    plantilla = app_commands.Group(
        name="plantilla",
        description=(
            "Gestiona la plantilla Society"
        ),
        parent=society,
    )

    acceso = app_commands.Group(
        name="acceso",
        description=(
            "Roles administrativos de Society"
        ),
        parent=society,
    )

    config = app_commands.Group(
        name="config",
        description=(
            "Configuración general de Society"
        ),
        parent=society,
    )

    staff = app_commands.Group(
        name="staff",
        description="Gestiona el Staff de una Society",
        parent=society,
    )

    bienvenida = app_commands.Group(
        name="bienvenida",
        description="Gestiona las bienvenidas de Society",
        parent=society,
    )

    async def _admin(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        return await require_admin(
            interaction,
            self.settings,
            self.bot.db,
        )

    def _dashboard_view(self) -> discord.ui.View:
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Abrir VEXEN Society", url=self.settings.dashboard_url))
        return view

    @society.command(name="help", description="Guía de acciones rápidas y enlace al Dashboard")
    async def society_help(self, interaction: discord.Interaction) -> None:
        if not await guild_is_authorized(interaction, self.settings):
            await interaction.response.send_message("❌ Este servidor no está autorizado.", ephemeral=True)
            return
        embed = discord.Embed(title="VEXEN Society • Acciones rápidas", color=discord.Color.blurple(),
            description="La configuración de plantillas, permisos, canales, incorporación y redes se administra desde el Dashboard.")
        embed.add_field(name="Consultas", value="`/society panel` · `/society estado` (Admin) · `/society miembros`", inline=False)
        embed.add_field(name="Asociados · Admin", value="`/society asociado agregar` · `listar` · `info` · `eliminar`\nLa eliminación conserva su confirmación de seguridad.", inline=False)
        embed.add_field(name="Staff y bienvenida", value="`/society staff agregar` · `quitar` · `listar`\n`/society bienvenida reenviar` (Admin). Se conservan los permisos de cada acción.", inline=False)
        embed.set_footer(text="VEXEN • SOCIETY")
        await interaction.response.send_message(embed=embed, view=self._dashboard_view(), ephemeral=True)

    @society.command(name="panel", description="Abre el Dashboard de VEXEN Society")
    async def society_panel(self, interaction: discord.Interaction) -> None:
        if not await guild_is_authorized(interaction, self.settings):
            await interaction.response.send_message("❌ Este servidor no está autorizado.", ephemeral=True)
            return
        embed = discord.Embed(title="VEXEN Society", color=discord.Color.blurple(),
            description="Administra tu Society desde el panel web. Inicia sesión con Discord; el panel comprobará tus permisos.")
        await interaction.response.send_message(embed=embed, view=self._dashboard_view(), ephemeral=True)

    @bienvenida.command(
        name="reenviar",
        description="Republica la bienvenida de una Society existente",
    )
    @app_commands.describe(
        asociado="Asociado cuya bienvenida quieres volver a publicar"
    )
    async def resend_welcome(
        self,
        interaction: discord.Interaction,
        asociado: discord.Member,
    ) -> None:
        if not await self._admin(interaction):
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        row = await get_associate(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            asociado.id,
        )
        if row is None:
            await interaction.followup.send(
                "❌ Ese usuario no está registrado como asociado.",
                ephemeral=True,
            )
            return

        space = await get_associate_space(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            asociado.id,
        )
        if space is None or space["status"] != "active":
            await interaction.followup.send(
                "❌ La Society de ese asociado no está activa.",
                ephemeral=True,
            )
            return

        configured_channel_id = await get_welcome_channel(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )
        if not configured_channel_id:
            await interaction.followup.send(
                "❌ No hay un canal de bienvenida configurado. "
                "Usa `/society config canal_bienvenida`.",
                ephemeral=True,
            )
            return

        community_role_id = space["community_role_id"]
        if (
            not community_role_id
            or interaction.guild.get_role(community_role_id) is None
        ):
            await interaction.followup.send(
                "❌ El rol de comunidad ya no existe.",
                ephemeral=True,
            )
            return

        old_space = space
        message, error = await publish_welcome(
            self.bot,
            self.settings,
            interaction.guild,
            asociado.id,
            row["display_name"],
            row["community_name"],
            community_role_id,
            interaction.user.id,
        )

        if message is None:
            await interaction.followup.send(
                "❌ No se pudo republicar la bienvenida."
                + (f"\n`{error}`" if error else ""),
                ephemeral=True,
            )
            return

        # Solo después de confirmar la nueva publicación desactivamos el
        # botón de la bienvenida anterior. El mensaje viejo se conserva.
        await disable_welcome_button(
            self.bot,
            self.settings,
            interaction.guild,
            old_space,
            row["community_name"],
        )

        await add_audit_log(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            "WELCOME_REPUBLISHED",
            interaction.user.id,
            asociado.id,
            row["community_name"],
            {
                "new_welcome_channel_id": message.channel.id,
                "new_welcome_message_id": message.id,
                "previous_welcome_channel_id": old_space["welcome_channel_id"],
                "previous_welcome_message_id": old_space["welcome_message_id"],
            },
        )

        await interaction.followup.send(
            "✅ Bienvenida republicada correctamente para "
            f"{asociado.mention} en {message.channel.mention}.\n"
            f"[Ir al mensaje]({message.jump_url})",
            ephemeral=True,
        )

    @asociado.command(
        name="agregar",
        description=(
            "Registra y prepara un nuevo asociado"
        ),
    )
    async def add_associate(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        nombre: app_commands.Range[
            str,
            1,
            100,
        ],
        comunidad: app_commands.Range[
            str,
            1,
            80,
        ],
    ) -> None:
        if not await self._admin(interaction):
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        if await get_associate(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            usuario.id,
        ):
            await interaction.followup.send(
                "❌ Ese usuario ya está registrado.",
                ephemeral=True,
            )
            return

        if await get_associate_by_community(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            comunidad,
        ):
            await interaction.followup.send(
                "❌ Ya existe una Society con "
                "ese nombre de comunidad.",
                ephemeral=True,
            )
            return

        template_row = await get_active_template(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )

        if template_row is None:
            await interaction.followup.send(
                "❌ No existe plantilla activa.",
                ephemeral=True,
            )
            return

        parsed = template_from_row(
            template_row
        )

        try:
            final_category = render_category_name(
                parsed,
                nombre,
                comunidad,
            )
        except TemplateValidationError as exc:
            await interaction.followup.send(
                f"❌ {exc}",
                ephemeral=True,
            )
            return

        created = await create_associate(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            usuario.id,
            nombre,
            comunidad,
            interaction.user.id,
        )

        if not created:
            await interaction.followup.send(
                "❌ No se pudo registrar el asociado.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=(
                "🏗️ Nuevo espacio VEXEN Society"
            ),
            description=(
                f"**Asociado:** {usuario.mention}\n"
                f"**Nombre:** {nombre}\n"
                f"**Comunidad:** {comunidad}\n\n"
                "**Roles a crear**\n"
                f"`{comunidad}`\n"
                f"`INT-{comunidad}`\n"
                f"`Staff-{comunidad}`\n\n"
                "**Categoría**\n"
                f"`{final_category}`\n\n"
                f"**Canales:** "
                f"{parsed.channel_count}\n"
                f"**Plantilla:** "
                f"v{template_row['version']}"
            ),
            color=discord.Color.blurple(),
        )

        await interaction.followup.send(
            embed=embed,
            view=CreateSpaceView(
                interaction.user.id,
                self.bot,
                usuario.id,
                rollback_associate_on_error=True,
            ),
            ephemeral=True,
        )

    @asociado.command(
        name="listar",
        description=(
            "Lista los asociados registrados"
        ),
    )
    async def list_associates_cmd(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not await self._admin(interaction):
            return

        rows = await list_associates(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )

        if not rows:
            await interaction.response.send_message(
                "No hay asociados registrados.",
                ephemeral=True,
            )
            return

        lines: list[str] = []

        for row in rows[:40]:
            state = (
                row["status"]
                or "sin espacio"
            )

            lines.append(
                f"• <@{row['user_id']}> — "
                f"**{row['community_name']}** "
                f"— `{state}`"
            )

        await interaction.response.send_message(
            "\n".join(lines)[:1900],
            ephemeral=True,
        )

    @asociado.command(
        name="info",
        description=(
            "Muestra la información de un asociado"
        ),
    )
    async def info_associate(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
    ) -> None:
        if not await self._admin(interaction):
            return

        row = await get_associate(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            usuario.id,
        )

        if row is None:
            await interaction.response.send_message(
                "❌ No está registrado.",
                ephemeral=True,
            )
            return

        space = await get_associate_space(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            usuario.id,
        )

        embed = discord.Embed(
            title="VEXEN Society • Asociado",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Usuario",
            value=usuario.mention,
            inline=True,
        )

        embed.add_field(
            name="Nombre",
            value=row["display_name"],
            inline=True,
        )

        embed.add_field(
            name="Comunidad",
            value=row["community_name"],
            inline=True,
        )

        if space:
            embed.add_field(
                name="Categoría",
                value=(
                    f"<#{space['category_id']}>"
                    if space["category_id"]
                    else "Pendiente"
                ),
                inline=True,
            )

            embed.add_field(
                name="Roles",
                value=(
                    "Comunidad: "
                    f"<@&{space['community_role_id']}>\n"
                    "INT: "
                    f"<@&{space['integration_role_id']}>\n"
                    "Staff: "
                    f"<@&{space['staff_role_id']}>"
                ),
                inline=False,
            )

            embed.add_field(
                name="Estado",
                value=space["status"],
                inline=True,
            )

            embed.add_field(
                name="Plantilla",
                value=(
                    f"v{space['template_version']}"
                ),
                inline=True,
            )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    @asociado.command(
        name="eliminar",
        description=(
            "Elimina una Society con "
            "confirmación escrita"
        ),
    )
    async def delete_associate(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
    ) -> None:
        if not await self._admin(interaction):
            return

        row = await get_associate(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            usuario.id,
        )

        if row is None:
            await interaction.response.send_message(
                "❌ No está registrado.",
                ephemeral=True,
            )
            return

        space = await get_associate_space(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            usuario.id,
        )

        if space is None:
            await interaction.response.send_message(
                "❌ El registro no tiene un "
                "espacio Society asociado.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=(
                "⚠️ Eliminar VEXEN Society"
            ),
            description=(
                f"**Asociado:** {usuario.mention}\n"
                "**Comunidad:** "
                f"**{row['community_name']}**\n\n"
                "Se intentará eliminar:\n"
                "• Categoría "
                f"`<#{space['category_id']}>`\n"
                "• Rol comunidad "
                f"`<@&{space['community_role_id']}>`\n"
                "• Rol INT "
                f"`<@&{space['integration_role_id']}>`\n"
                "• Rol Staff "
                f"`<@&{space['staff_role_id']}>`\n"
                "• Todos los canales de la categoría\n"
                "• Mapping temporal de VEXMOD\n"
                "• Registro Society\n\n"
                "Para confirmar tendrás que escribir "
                f"exactamente **{row['community_name']}**."
            ),
            color=discord.Color.red(),
        )

        await interaction.response.send_message(
            embed=embed,
            view=DeleteSocietyView(
                interaction.user.id,
                self.bot,
                usuario.id,
                row["community_name"],
            ),
            ephemeral=True,
        )

    @society.command(
        name="administrar",
        description=(
            "Abre el panel de administración "
            "de una Society"
        ),
    )
    async def manage(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member | None = None,
    ) -> None:
        admin = await is_society_admin(
            interaction,
            self.settings,
            self.bot.db,
        )

        target_id = (
            usuario.id
            if usuario
            else interaction.user.id
        )

        if (
            usuario is not None
            and usuario.id != interaction.user.id
            and not admin
        ):
            await interaction.response.send_message(
                "❌ Solo puedes administrar "
                "tu propia Society.",
                ephemeral=True,
            )
            return

        row = await get_associate(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            target_id,
        )

        if row is None:
            await interaction.response.send_message(
                "❌ No existe una Society asociada "
                "a ese usuario.",
                ephemeral=True,
            )
            return

        space = await get_associate_space(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            target_id,
        )

        if (
            space is None
            or space["status"] != "active"
        ):
            await interaction.response.send_message(
                "❌ Esa Society no está activa.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"⚙️ **Administrar "
            f"{row['community_name']}**\n"
            "Puedes crear canales, gestionar "
            "canales existentes, renombrar "
            "la categoría o sincronizar "
            "la plantilla activa.",
            view=ManageSocietyView(
                interaction.user.id,
                self.bot,
                target_id,
            ),
            ephemeral=True,
        )

    async def _resolve_target_for_member_action(
        self,
        interaction: discord.Interaction,
        asociado: discord.Member | None,
    ):
        admin = await is_society_admin(
            interaction,
            self.settings,
            self.bot.db,
        )

        target_id = (
            asociado.id
            if asociado is not None
            else interaction.user.id
        )

        if (
            asociado is not None
            and asociado.id != interaction.user.id
            and not admin
        ):
            return None, None, (
                "❌ Solo puedes administrar tu propia Society."
            )

        row = await get_associate(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            target_id,
        )

        if row is None:
            return None, None, (
                "❌ No existe una Society para ese asociado."
            )

        space = await get_associate_space(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            target_id,
        )

        if (
            space is None
            or space["status"] != "active"
        ):
            return None, None, (
                "❌ Esa Society no está activa."
            )

        return row, space, None

    @staff.command(
        name="agregar",
        description="Agrega un miembro al Staff de una Society",
    )
    async def staff_add(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member,
        asociado: discord.Member | None = None,
    ) -> None:
        row, space, error = (
            await self._resolve_target_for_member_action(
                interaction,
                asociado,
            )
        )

        if error:
            await interaction.response.send_message(
                error,
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(
            space["staff_role_id"]
        )

        if role is None:
            await interaction.response.send_message(
                "❌ El rol Staff de esta Society ya no existe.",
                ephemeral=True,
            )
            return

        try:
            await miembro.add_roles(
                role,
                reason=(
                    "VEXEN Society: Staff de "
                    f"{row['community_name']}"
                ),
            )
        except (
            discord.Forbidden,
            discord.HTTPException,
        ) as exc:
            await interaction.response.send_message(
                f"❌ No se pudo asignar el rol: "
                f"`{type(exc).__name__}`",
                ephemeral=True,
            )
            return

        await add_audit_log(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            "STAFF_MEMBER_ADDED",
            interaction.user.id,
            row["user_id"],
            row["community_name"],
            {
                "member_id": miembro.id,
                "staff_role_id": role.id,
            },
        )

        await interaction.response.send_message(
            f"✅ {miembro.mention} agregado a "
            f"{role.mention}.",
            ephemeral=True,
        )

    @staff.command(
        name="quitar",
        description="Quita un miembro del Staff de una Society",
    )
    async def staff_remove(
        self,
        interaction: discord.Interaction,
        miembro: discord.Member,
        asociado: discord.Member | None = None,
    ) -> None:
        row, space, error = (
            await self._resolve_target_for_member_action(
                interaction,
                asociado,
            )
        )

        if error:
            await interaction.response.send_message(
                error,
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(
            space["staff_role_id"]
        )

        if role is None:
            await interaction.response.send_message(
                "❌ El rol Staff de esta Society ya no existe.",
                ephemeral=True,
            )
            return

        try:
            await miembro.remove_roles(
                role,
                reason=(
                    "VEXEN Society: quitar Staff de "
                    f"{row['community_name']}"
                ),
            )
        except (
            discord.Forbidden,
            discord.HTTPException,
        ) as exc:
            await interaction.response.send_message(
                f"❌ No se pudo quitar el rol: "
                f"`{type(exc).__name__}`",
                ephemeral=True,
            )
            return

        await add_audit_log(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            "STAFF_MEMBER_REMOVED",
            interaction.user.id,
            row["user_id"],
            row["community_name"],
            {
                "member_id": miembro.id,
                "staff_role_id": role.id,
            },
        )

        await interaction.response.send_message(
            f"✅ {miembro.mention} retirado de "
            f"{role.mention}.",
            ephemeral=True,
        )

    @staff.command(
        name="listar",
        description="Lista el Staff de una Society",
    )
    async def staff_list(
        self,
        interaction: discord.Interaction,
        asociado: discord.Member | None = None,
    ) -> None:
        row, space, error = (
            await self._resolve_target_for_member_action(
                interaction,
                asociado,
            )
        )

        if error:
            await interaction.response.send_message(
                error,
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(
            space["staff_role_id"]
        )

        if role is None:
            await interaction.response.send_message(
                "❌ El rol Staff ya no existe.",
                ephemeral=True,
            )
            return

        members = role.members

        text = (
            "\n".join(
                f"• {member.mention}"
                for member in members[:40]
            )
            or "No hay miembros Staff."
        )

        await interaction.response.send_message(
            f"**Staff • {row['community_name']}**\n"
            f"{text}",
            ephemeral=True,
        )

    @society.command(
        name="miembros",
        description="Lista miembros de una comunidad Society",
    )
    async def members_list(
        self,
        interaction: discord.Interaction,
        asociado: discord.Member | None = None,
    ) -> None:
        row, space, error = (
            await self._resolve_target_for_member_action(
                interaction,
                asociado,
            )
        )

        if error:
            await interaction.response.send_message(
                error,
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(
            space["community_role_id"]
        )

        if role is None:
            await interaction.response.send_message(
                "❌ El rol de comunidad ya no existe.",
                ephemeral=True,
            )
            return

        members = role.members
        visible = "\n".join(
            f"• {member.mention}"
            for member in members[:35]
        )

        if len(members) > 35:
            visible += (
                f"\n… y {len(members) - 35} más."
            )

        await interaction.response.send_message(
            f"**Miembros • {row['community_name']}**\n"
            f"Total: **{len(members)}**\n\n"
            f"{visible or 'Sin miembros.'}",
            ephemeral=True,
        )

    @plantilla.command(
        name="ver",
        description=(
            "Muestra la plantilla activa"
        ),
    )
    async def template_view(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not await self._admin(interaction):
            return

        row = await get_active_template(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )

        if row is None:
            await interaction.response.send_message(
                "No existe plantilla activa.",
                ephemeral=True,
            )
            return

        parsed = template_from_row(row)

        embed = preview_embed(
            parsed,
            (
                "VEXEN Society • Plantilla "
                f"v{row['version']}"
            ),
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    @plantilla.command(
        name="cargar",
        description=(
            "Valida un TXT y permite activarlo"
        ),
    )
    async def template_upload(
        self,
        interaction: discord.Interaction,
        archivo: discord.Attachment,
        nombre: app_commands.Range[
            str,
            1,
            100,
        ] = "VEXEN Society",
    ) -> None:
        if not await self._admin(interaction):
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        if not archivo.filename.lower().endswith(
            ".txt"
        ):
            await interaction.followup.send(
                "❌ Debes subir un archivo `.txt`.",
                ephemeral=True,
            )
            return

        if archivo.size > 131072:
            await interaction.followup.send(
                "❌ El TXT supera 128 KB.",
                ephemeral=True,
            )
            return

        try:
            raw = (
                await archivo.read()
            ).decode("utf-8-sig")

            parsed = parse_template(
                raw
            )

        except UnicodeDecodeError:
            await interaction.followup.send(
                "❌ El archivo debe estar en UTF-8.",
                ephemeral=True,
            )
            return

        except TemplateValidationError as exc:
            await interaction.followup.send(
                "❌ Plantilla inválida:\n"
                f"`{exc}`",
                ephemeral=True,
            )
            return

        embed = preview_embed(
            parsed,
            (
                "✅ Plantilla válida • "
                "Vista previa"
            ),
        )

        embed.add_field(
            name="Importante",
            value=(
                "Activarla no modifica "
                "automáticamente las Society "
                "ya creadas."
            ),
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            view=TemplateConfirmView(
                interaction.user.id,
                self.bot,
                raw,
                nombre,
            ),
            ephemeral=True,
        )

    @plantilla.command(
        name="descargar",
        description=(
            "Descarga la plantilla activa"
        ),
    )
    async def template_download(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not await self._admin(interaction):
            return

        file, row = await active_template_file(
            self.bot.db,
            self.settings,
            interaction.guild_id,
        )

        await interaction.response.send_message(
            (
                "Plantilla activa: "
                f"**v{row['version']}**"
            ),
            file=file,
            ephemeral=True,
        )

    @plantilla.command(
        name="historial",
        description=(
            "Lista las versiones de plantilla"
        ),
    )
    async def template_history(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not await self._admin(interaction):
            return

        rows = await list_templates(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )

        lines = [
            (
                f"• **v{row['version']}** — "
                f"{row['name']} "
                + (
                    "✅ activa"
                    if row["is_active"]
                    else ""
                )
                + f" — <@{row['uploaded_by']}>"
            )
            for row in rows[:30]
        ]

        await interaction.response.send_message(
            "\n".join(lines)
            or "No hay plantillas.",
            ephemeral=True,
        )

    @acceso.command(
        name="rol_agregar",
        description=(
            "Autoriza un rol para administrar Society"
        ),
    )
    async def access_add(
        self,
        interaction: discord.Interaction,
        rol: discord.Role,
    ) -> None:
        if (
            interaction.user.id
            != self.settings.owner_id
        ):
            await interaction.response.send_message(
                "❌ Solo OWNER puede hacer esto.",
                ephemeral=True,
            )
            return

        changed = await add_allowed_role(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            rol.id,
            interaction.user.id,
        )

        await interaction.response.send_message(
            (
                "✅ Rol autorizado: "
                if changed
                else "ℹ️ Ya estaba autorizado: "
            )
            + rol.mention,
            ephemeral=True,
        )

    @acceso.command(
        name="rol_quitar",
        description=(
            "Quita un rol autorizado"
        ),
    )
    async def access_remove(
        self,
        interaction: discord.Interaction,
        rol: discord.Role,
    ) -> None:
        if (
            interaction.user.id
            != self.settings.owner_id
        ):
            await interaction.response.send_message(
                "❌ Solo OWNER puede hacer esto.",
                ephemeral=True,
            )
            return

        changed = await remove_allowed_role(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            rol.id,
        )

        await interaction.response.send_message(
            (
                "✅ Rol retirado."
                if changed
                else "ℹ️ Ese rol no estaba autorizado."
            ),
            ephemeral=True,
        )

    @acceso.command(
        name="listar",
        description=(
            "Lista roles administrativos"
        ),
    )
    async def access_list(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not await self._admin(interaction):
            return

        ids = await list_allowed_roles(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )

        env_ids = sorted(
            self.settings.allowed_role_ids
        )

        text = (
            "**PostgreSQL**\n"
            + (
                "\n".join(
                    f"• <@&{role_id}>"
                    for role_id in ids
                )
                or "Ninguno"
            )
            + "\n\n"
            "**ALLOWED_ROLES (.env)**\n"
            + (
                "\n".join(
                    f"• <@&{role_id}>"
                    for role_id in env_ids
                )
                or "Ninguno"
            )
        )

        await interaction.response.send_message(
            text,
            ephemeral=True,
        )

    @config.command(
        name="anuncios",
        description=(
            "Configura el canal global "
            "de anuncios Society"
        ),
    )
    async def configure_announcements(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
    ) -> None:
        if not await self._admin(interaction):
            return

        await set_global_announcements_channel(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            canal.id if canal else None,
            interaction.user.id,
        )

        await add_audit_log(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            "GLOBAL_ANNOUNCEMENTS_CHANGED",
            interaction.user.id,
            metadata={
                "channel_id": (
                    canal.id
                    if canal
                    else None
                )
            },
        )

        await interaction.response.send_message(
            (
                f"✅ Canal global: {canal.mention}"
                if canal
                else "✅ Espejo global desactivado."
            ),
            ephemeral=True,
        )

    @config.command(
        name="categoria_base",
        description=(
            "Configura debajo de qué categoría comienzan las Society"
        ),
    )
    async def configure_base_category(
        self,
        interaction: discord.Interaction,
        categoria: discord.CategoryChannel | None = None,
    ) -> None:
        if not await self._admin(interaction):
            return

        await set_base_category(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            categoria.id if categoria else None,
            interaction.user.id,
        )

        await add_audit_log(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            "BASE_CATEGORY_CHANGED",
            interaction.user.id,
            metadata={
                "category_id": categoria.id if categoria else None
            },
        )

        await interaction.response.send_message(
            (
                f"✅ Categoría base configurada: **{categoria.name}**."
                if categoria
                else (
                    "✅ Categoría base desactivada. Society usará "
                    "`COMUNIDAD` como respaldo si existe."
                )
            ),
            ephemeral=True,
        )

    @config.command(
        name="canal_bienvenida",
        description=(
            "Configura dónde publicar las bienvenidas de nuevos asociados"
        ),
    )
    async def configure_welcome_channel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
    ) -> None:
        if not await self._admin(interaction):
            return

        await set_welcome_channel(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            canal.id if canal else None,
            interaction.user.id,
        )

        await add_audit_log(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            "WELCOME_CHANNEL_CHANGED",
            interaction.user.id,
            metadata={
                "channel_id": canal.id if canal else None
            },
        )

        await interaction.response.send_message(
            (
                f"✅ Las bienvenidas Society se publicarán en {canal.mention}."
                if canal
                else "✅ Publicación automática de bienvenidas desactivada."
            ),
            ephemeral=True,
        )

    @config.command(
        name="incorporacion",
        description="Configura la pregunta de Onboarding donde aparecen los asociados",
    )
    @app_commands.describe(
        pregunta=(
            "Selecciona la pregunta existente de Discord. "
            "Las nuevas Society añadirán aquí el nombre del asociado con su rol INT."
        )
    )
    async def configure_onboarding_prompt(
        self,
        interaction: discord.Interaction,
        pregunta: app_commands.Range[str, 1, 120],
    ) -> None:
        if not await self._admin(interaction):
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        if self.bot.onboarding_integration is None:
            await interaction.followup.send(
                "❌ La integración de incorporación no está inicializada.",
                ephemeral=True,
            )
            return

        try:
            report = await self.bot.onboarding_integration.configure_and_sync(
                interaction.guild,
                pregunta,
                interaction.user.id,
            )
        except Exception as exc:
            await interaction.followup.send(
                "❌ No se pudo configurar la incorporación.\n"
                f"`{type(exc).__name__}: {str(exc)[:700]}`",
                ephemeral=True,
            )
            return

        await add_audit_log(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            "ONBOARDING_PROMPT_CONFIGURED",
            interaction.user.id,
            metadata={
                "prompt_title": report.prompt_title,
                "added": report.added,
                "updated": report.updated,
                "unchanged": report.unchanged,
                "conflicts": report.conflicts,
            },
        )

        text = (
            "✅ **Incorporación Society configurada.**\n"
            f"Pregunta: **{report.prompt_title}**\n\n"
            f"Opciones añadidas: `{report.added}`\n"
            f"Opciones actualizadas: `{report.updated}`\n"
            f"Ya correctas: `{report.unchanged}`"
        )
        if report.conflicts:
            text += "\n\n⚠️ **Revisar:**\n" + "\n".join(
                f"• {item}" for item in report.conflicts[:10]
            )

        await interaction.followup.send(
            text[:1900],
            ephemeral=True,
        )

    @configure_onboarding_prompt.autocomplete("pregunta")
    async def onboarding_prompt_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None or self.bot.onboarding_integration is None:
            return []
        try:
            prompts = await self.bot.onboarding_integration.list_prompts(
                interaction.guild
            )
        except Exception:
            return []

        folded = current.strip().casefold()
        matches = [
            prompt
            for prompt in prompts
            if not folded or folded in prompt.title.casefold()
        ]
        return [
            app_commands.Choice(
                name=prompt.title[:100],
                value=str(prompt.id),
            )
            for prompt in matches[:25]
        ]

    @config.command(
        name="color_bienvenida",
        description="Cambia el color HEX del embed de bienvenida",
    )
    async def configure_welcome_color(
        self,
        interaction: discord.Interaction,
        color: app_commands.Range[str, 1, 16],
    ) -> None:
        if not await self._admin(interaction):
            return

        try:
            normalized = normalize_welcome_color(
                color
            )
        except ValueError as exc:
            await interaction.response.send_message(
                f"❌ {exc}",
                ephemeral=True,
            )
            return

        previous = await get_welcome_color(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )

        await set_welcome_color(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            normalized,
            interaction.user.id,
        )

        await add_audit_log(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
            "WELCOME_COLOR_CHANGED",
            interaction.user.id,
            metadata={
                "previous": previous,
                "new": normalized,
            },
        )

        preview = discord.Embed(
            title="✅ Color de bienvenida actualizado",
            description=(
                f"Anterior: `{previous}`\n"
                f"Nuevo: `{normalized}`\n\n"
                "Usa `default` para volver a `#57F287`."
            ),
            color=int(normalized[1:], 16),
        )

        await interaction.response.send_message(
            embed=preview,
            ephemeral=True,
        )

    @config.command(
        name="estilo_boton_bienvenida",
        description="Cambia el estilo/color del botón de la bienvenida",
    )
    @app_commands.describe(
        estilo=(
            "Color Discord: primary = azul; secondary = gris/oscuro; "
            "success = verde; danger = rojo."
        )
    )
    @app_commands.choices(
        estilo=[
            app_commands.Choice(name="primary — Azul", value="primary"),
            app_commands.Choice(name="secondary — Gris / oscuro", value="secondary"),
            app_commands.Choice(name="success — Verde", value="success"),
            app_commands.Choice(name="danger — Rojo", value="danger"),
        ]
    )
    async def configure_welcome_button_style(
        self, interaction: discord.Interaction, estilo: app_commands.Choice[str]
    ) -> None:
        if not await self._admin(interaction):
            return
        normalized = normalize_community_button_style(estilo.value)
        previous = await get_welcome_button_style(
            self.bot.db, self.settings.society_db_schema, interaction.guild_id
        )
        await set_welcome_button_style(
            self.bot.db, self.settings.society_db_schema, interaction.guild_id,
            normalized, interaction.user.id,
        )
        refresh = await refresh_welcome_button_styles(
            self.bot, self.settings, interaction.guild, normalized
        )
        await add_audit_log(
            self.bot.db, self.settings.society_db_schema, interaction.guild_id,
            "WELCOME_BUTTON_STYLE_CHANGED", interaction.user.id,
            metadata={"previous": previous, "new": normalized, **refresh},
        )
        await interaction.response.send_message(
            "✅ Estilo del botón de bienvenida actualizado.\n\n"
            f"Anterior: `{community_button_style_label(previous)}`\n"
            f"Nuevo: `{community_button_style_label(normalized)}`\n\n"
            f"Bienvenidas actualizadas: `{refresh['updated']}`\n"
            f"No actualizadas: `{refresh['failed']}`",
            ephemeral=True,
        )

    @config.command(
        name="estilo_boton_anuncios",
        description="Cambia el estilo/color del botón de los anuncios asociados",
    )
    @app_commands.describe(
        estilo=(
            "Color Discord: primary = azul; secondary = gris/oscuro; "
            "success = verde; danger = rojo."
        )
    )
    @app_commands.choices(
        estilo=[
            app_commands.Choice(name="primary — Azul", value="primary"),
            app_commands.Choice(name="secondary — Gris / oscuro", value="secondary"),
            app_commands.Choice(name="success — Verde", value="success"),
            app_commands.Choice(name="danger — Rojo", value="danger"),
        ]
    )
    async def configure_announcement_button_style(
        self, interaction: discord.Interaction, estilo: app_commands.Choice[str]
    ) -> None:
        if not await self._admin(interaction):
            return
        normalized = normalize_community_button_style(estilo.value)
        previous = await get_announcement_button_style(
            self.bot.db, self.settings.society_db_schema, interaction.guild_id
        )
        await set_announcement_button_style(
            self.bot.db, self.settings.society_db_schema, interaction.guild_id,
            normalized, interaction.user.id,
        )
        refresh = await refresh_announcement_button_styles(
            self.bot, self.settings, interaction.guild, normalized
        )
        await add_audit_log(
            self.bot.db, self.settings.society_db_schema, interaction.guild_id,
            "ANNOUNCEMENT_BUTTON_STYLE_CHANGED", interaction.user.id,
            metadata={"previous": previous, "new": normalized, **refresh},
        )
        await interaction.response.send_message(
            "✅ Estilo del botón de anuncios actualizado.\n\n"
            f"Anterior: `{community_button_style_label(previous)}`\n"
            f"Nuevo: `{community_button_style_label(normalized)}`\n\n"
            f"CTA de anuncios actualizados: `{refresh['updated']}`\n"
            f"No actualizados: `{refresh['failed']}`",
            ephemeral=True,
        )

    @society.command(
        name="estado",
        description=(
            "Muestra el estado técnico de Society"
        ),
    )
    async def config_status(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not await self._admin(interaction):
            return

        # Este comando consulta PostgreSQL, VEXMOD y Discord Onboarding.
        # Onboarding puede tardar más de los 3 segundos que Discord permite
        # para la respuesta inicial, así que reconocemos la interacción primero.
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        target = (
            await get_global_announcements_channel(
                self.bot.db,
                self.settings.society_db_schema,
                interaction.guild_id,
            )
        )

        base_category_id = await get_base_category(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )

        welcome_channel_id = await get_welcome_channel(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )

        welcome_color_hex = await get_welcome_color(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )
        welcome_button_style = await get_welcome_button_style(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )
        announcement_button_style = await get_announcement_button_style(
            self.bot.db,
            self.settings.society_db_schema,
            interaction.guild_id,
        )

        ok, provider = (
            await self.bot.verification_integration.health()
        )
        onboarding_status = (
            await self.bot.onboarding_integration.status(interaction.guild)
            if self.bot.onboarding_integration is not None
            else {
                "configured": False,
                "prompt_title": None,
                "prompt_found": False,
                "managed_options": 0,
                "active_societies": 0,
                "error": "Integración no inicializada",
            }
        )

        if not onboarding_status["configured"]:
            onboarding_text = "No configurada"
        elif onboarding_status["prompt_found"]:
            onboarding_text = (
                "✅ "
                + str(onboarding_status["prompt_title"])
                + f" — {onboarding_status['managed_options']} opciones Society"
            )
        else:
            onboarding_text = (
                "⚠️ "
                + str(onboarding_status["prompt_title"] or "Configurada")
            )
            if onboarding_status.get("error"):
                onboarding_text += " — revisar configuración"

        await interaction.followup.send(
            "**Schema Society:** "
            f"`{self.settings.society_db_schema}`\n"
            "**Integración VEXMOD:** "
            f"`{self.settings.verification_integration}` "
            f"({'✅' if ok else '❌'} {provider})\n"
            "**Schema VEXMOD:** "
            f"`{self.settings.vexmod_roles_schema}`\n"
            "**Incorporación Society:** "
            + onboarding_text
            + "\n**Anuncios globales:** "
            + (
                f"<#{target}>"
                if target
                else "No configurado"
            )
            + "\n**Categoría base Society:** "
            + (
                f"<#{base_category_id}>"
                if base_category_id
                else "Automática (fallback: COMUNIDAD)"
            )
            + "\n**Canal de bienvenida:** "
            + (
                f"<#{welcome_channel_id}>"
                if welcome_channel_id
                else "No configurado"
            )
            + "\n**Color de bienvenida:** "
            + f"`{welcome_color_hex}`"
            + "\n**Botón de bienvenida:** "
            + f"`{community_button_style_label(welcome_button_style)}`"
            + "\n**Botón de anuncios:** "
            + f"`{community_button_style_label(announcement_button_style)}`",
            ephemeral=True,
        )
