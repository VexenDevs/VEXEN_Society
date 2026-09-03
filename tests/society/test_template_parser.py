from pathlib import Path

import pytest

from app.society.template_parser import (
    TemplateValidationError,
    parse_template,
    render_category_name,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE = ROOT / "templates" / "society_default.txt"


def test_default_template_is_valid():
    parsed = parse_template(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))
    assert parsed.category_name == "👥 VXS | asociado | comunidad"
    assert parsed.channel_count == 12
    assert parsed.announcement_channel.channel_key == "announcements"
    assert parsed.announcement_channel.name == "📢┃anuncios"
    assert parsed.channels[1].name == "💬┃general"
    assert parsed.channels[2].name == "🛡️┃staff-chat"


def test_category_render_with_bare_variables():
    parsed = parse_template(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))
    assert render_category_name(parsed, "LaWilly", "LosPoPiWa") == (
        "👥 VXS | LaWilly | LosPoPiWa"
    )


def test_legacy_braced_variables_remain_compatible():
    raw = """
[CATEGORY] 👥 { VXS } { asociado } { comunidad }
[ANN] 📢┃anuncios
"""
    parsed = parse_template(raw)
    assert render_category_name(parsed, "LaWilly", "LosPoPiWa") == (
        "👥 { VXS } { LaWilly } { LosPoPiWa }"
    )


def test_variable_decoration_is_chosen_by_template():
    raw = """
[CATEGORY] 👥 [VXS] · {asociado} · 【 comunidad 】
[ANN] 📢┃anuncios
"""
    parsed = parse_template(raw)
    assert render_category_name(parsed, "Denep", "VEXEN Crew") == (
        "👥 [VXS] · {Denep} · 【 VEXEN Crew 】"
    )


def test_category_can_be_static_without_variables():
    raw = """
[CATEGORY] 👥 SOCIETY CENTRAL
[ANN] 📢┃anuncios
"""
    parsed = parse_template(raw)
    assert render_category_name(parsed, "", "") == "👥 SOCIETY CENTRAL"


def test_rejects_duplicate_announcements():
    raw = """
[CATEGORY] 👥 VXS asociado comunidad
[ANN] 📢┃anuncios
[ANN] 📣┃noticias
"""
    with pytest.raises(TemplateValidationError):
        parse_template(raw)


def test_keys_are_stable_by_type_order():
    raw = """
[CATEGORY] 👥 VXS asociado comunidad
[ANN] 📢┃anuncios
[TXT] 💬┃general
[TXT] 🎟️┃soporte
[VOICE] 🔊┃General
"""
    parsed = parse_template(raw)
    assert [item.channel_key for item in parsed.channels] == [
        "announcements",
        "txt_01",
        "txt_02",
        "voice_01",
    ]


def test_custom_discord_emoji_is_removed_only_from_rendered_associate_name():
    parsed = parse_template(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))
    result = render_category_name(
        parsed,
        "<:logo:1538690277991120938> Prueba",
        "LosPoPis",
    )
    assert result == "👥 VXS | Prueba | LosPoPis"
    assert "<:" not in result


def test_animated_custom_discord_emoji_is_removed_from_associate_name():
    parsed = parse_template(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))
    result = render_category_name(
        parsed,
        "<a:logo:1538690277991120938> Prueba",
        "LosPoPis",
    )
    assert result == "👥 VXS | Prueba | LosPoPis"


def test_category_rejects_associate_variable_when_name_is_only_custom_emoji():
    parsed = parse_template(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))
    with pytest.raises(TemplateValidationError):
        render_category_name(
            parsed,
            "<:logo:1538690277991120938>",
            "LosPoPis",
        )


def test_variable_names_are_not_replaced_inside_longer_words():
    raw = """
[CATEGORY] comunidad asociados comunidad2
[ANN] 📢┃anuncios
"""
    parsed = parse_template(raw)
    assert render_category_name(parsed, "Denep", "VEXEN") == (
        "VEXEN asociados comunidad2"
    )
