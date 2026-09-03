from __future__ import annotations

import io
import json
from pathlib import Path

import discord

from app.config.settings import Settings
from app.society.template_parser import (
    ParsedTemplate,
    parse_template,
    parsed_template_from_dict,
)
from database import (
    add_audit_log,
    create_template,
    get_active_template,
    get_next_template_version,
)

DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "templates"
    / "society_default.txt"
)


async def ensure_default_template(db, settings: Settings) -> None:
    if settings.guild_id is None:
        return

    current = await get_active_template(
        db,
        settings.society_db_schema,
        settings.guild_id,
    )
    if current is not None:
        return

    raw = DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8")
    parsed = parse_template(raw)
    await create_template(
        db,
        settings.society_db_schema,
        settings.guild_id,
        "VEXEN Society Default",
        1,
        raw,
        parsed.to_dict(),
        settings.owner_id or 0,
        activate=True,
    )


def template_from_row(row) -> ParsedTemplate:
    data = row["parsed_template"]
    if isinstance(data, str):
        data = json.loads(data)
    return parsed_template_from_dict(dict(data))


def preview_embed(
    parsed: ParsedTemplate,
    title: str = "VEXEN Society • Plantilla",
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=(
            f"**Categoría**\n`{parsed.category_name}`\n\n"
            f"**Canales:** {parsed.channel_count}"
        ),
        color=discord.Color.blurple(),
    )
    lines = [
        f"`{channel.channel_type}` • {channel.name}"
        for channel in parsed.channels
    ]
    embed.add_field(
        name="Estructura",
        value="\n".join(lines)[:1024],
        inline=False,
    )
    embed.set_footer(
        text=(
            "Variables opcionales: VXS, asociado y comunidad. "
            "La plantilla decide su decoración."
        )
    )
    return embed


async def save_uploaded_template(
    db,
    settings: Settings,
    guild_id: int,
    actor_id: int,
    raw: str,
    name: str,
) -> tuple[int, int]:
    parsed = parse_template(raw)
    version = await get_next_template_version(
        db,
        settings.society_db_schema,
        guild_id,
    )
    template_id = await create_template(
        db,
        settings.society_db_schema,
        guild_id,
        name,
        version,
        raw,
        parsed.to_dict(),
        actor_id,
        activate=True,
    )
    await add_audit_log(
        db,
        settings.society_db_schema,
        guild_id,
        "TEMPLATE_ACTIVATED",
        actor_id,
        metadata={
            "template_id": template_id,
            "version": version,
            "name": name,
        },
    )
    return template_id, version


async def active_template_file(
    db,
    settings: Settings,
    guild_id: int,
) -> tuple[discord.File, object]:
    row = await get_active_template(
        db,
        settings.society_db_schema,
        guild_id,
    )
    if row is None:
        raise RuntimeError("No existe plantilla activa.")

    payload = io.BytesIO(row["raw_template"].encode("utf-8"))
    file = discord.File(
        payload,
        filename=f"vexen_society_template_v{row['version']}.txt",
    )
    return file, row
