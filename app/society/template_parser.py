from __future__ import annotations

import re
from dataclasses import dataclass


CATEGORY_TYPE = "CATEGORY"
CHANNEL_TYPES = {"ANN", "TXT", "STAFF-TXT", "VOICE", "STAFF-VOICE"}
ALL_TYPES = {CATEGORY_TYPE, *CHANNEL_TYPES}

# Las variables se identifican por nombre. Los caracteres que las rodeen
# pertenecen a la plantilla y se conservan: asociado, {asociado}, [asociado].
VXS_LITERAL = "VXS"
ASSOCIATE_VARIABLE = "asociado"
COMMUNITY_VARIABLE = "comunidad"

MAX_CATEGORY_LENGTH = 100
MAX_CHANNEL_LENGTH = 100
MAX_TEMPLATE_CHANNELS = 49

_LINE_PATTERN = re.compile(r"^\[([A-Za-z-]+)\]\s+(.+)$")
_VARIABLE_PATTERNS = {
    ASSOCIATE_VARIABLE: re.compile(r"(?<![\w])asociado(?![\w])", re.IGNORECASE),
    COMMUNITY_VARIABLE: re.compile(r"(?<![\w])comunidad(?![\w])", re.IGNORECASE),
}

# Discord custom emoji markup:
# <:nombre:123456789012345678>
# <a:nombre:123456789012345678>
_CUSTOM_EMOJI_PATTERN = re.compile(r"<a?:[A-Za-z0-9_~]+:\d{15,25}>")


class TemplateValidationError(ValueError):
    def __init__(self, message: str, line_number: int | None = None) -> None:
        self.message = message
        self.line_number = line_number
        super().__init__(f"Línea {line_number}: {message}" if line_number else message)


def sanitize_associate_name_for_category(value: str) -> str:
    """Quita markup de emojis personalizados solo del nombre de categoría."""
    cleaned = _CUSTOM_EMOJI_PATTERN.sub("", value)
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        raise TemplateValidationError(
            "El nombre del asociado necesita texto además del emoji para poder "
            "renderizar la variable asociado."
        )
    return cleaned


@dataclass(frozen=True, slots=True)
class ChannelTemplate:
    channel_type: str
    name: str
    channel_key: str
    source_line: int

    def to_dict(self) -> dict:
        return {
            "type": self.channel_type,
            "name": self.name,
            "key": self.channel_key,
            "source_line": self.source_line,
        }


@dataclass(frozen=True, slots=True)
class ParsedTemplate:
    category_name: str
    channels: tuple[ChannelTemplate, ...]

    def to_dict(self) -> dict:
        return {
            "category": self.category_name,
            "channels": [channel.to_dict() for channel in self.channels],
        }

    @property
    def channel_count(self) -> int:
        return len(self.channels)

    @property
    def announcement_channel(self) -> ChannelTemplate:
        for channel in self.channels:
            if channel.channel_type == "ANN":
                return channel
        raise RuntimeError("La plantilla no contiene canal ANN.")


def parsed_template_from_dict(data: dict) -> ParsedTemplate:
    return ParsedTemplate(
        category_name=str(data["category"]),
        channels=tuple(
            ChannelTemplate(
                channel_type=str(item["type"]),
                name=str(item["name"]),
                channel_key=str(item["key"]),
                source_line=int(item.get("source_line", 0)),
            )
            for item in data["channels"]
        ),
    )


def parse_template(raw_template: str) -> ParsedTemplate:
    if not isinstance(raw_template, str) or not raw_template.strip():
        raise TemplateValidationError("La plantilla está vacía.")

    category_name: str | None = None
    channels: list[ChannelTemplate] = []
    used_names: set[str] = set()
    counters: dict[str, int] = {}
    announcement_count = 0

    for line_number, original_line in enumerate(raw_template.splitlines(), start=1):
        line = original_line.strip()
        if not line or line.startswith("#"):
            continue

        match = _LINE_PATTERN.fullmatch(line)
        if not match:
            raise TemplateValidationError(
                "Formato inválido. Se esperaba [TIPO] nombre.",
                line_number,
            )

        item_type = match.group(1).upper()
        item_name = match.group(2).strip()

        if item_type not in ALL_TYPES:
            raise TemplateValidationError(
                f"Tipo desconocido [{item_type}]. Tipos válidos: "
                + ", ".join(sorted(ALL_TYPES)),
                line_number,
            )

        if item_type == CATEGORY_TYPE:
            if category_name is not None:
                raise TemplateValidationError(
                    "Solo puede existir una [CATEGORY].",
                    line_number,
                )
            if not item_name:
                raise TemplateValidationError(
                    "El nombre de categoría no puede estar vacío.",
                    line_number,
                )
            if len(item_name) > MAX_CATEGORY_LENGTH:
                raise TemplateValidationError(
                    f"La categoría supera {MAX_CATEGORY_LENGTH} caracteres.",
                    line_number,
                )
            # No se exige ninguna variable y no se imponen llaves. El texto se
            # conserva tal como fue diseñado por el administrador.
            category_name = item_name
            continue

        if len(channels) >= MAX_TEMPLATE_CHANNELS:
            raise TemplateValidationError(
                f"La plantilla supera {MAX_TEMPLATE_CHANNELS} canales.",
                line_number,
            )
        if len(item_name) > MAX_CHANNEL_LENGTH:
            raise TemplateValidationError(
                f"El canal supera {MAX_CHANNEL_LENGTH} caracteres.",
                line_number,
            )
        if "{" in item_name or "}" in item_name:
            raise TemplateValidationError(
                "Los canales no pueden contener variables entre llaves.",
                line_number,
            )

        normalized = item_name.casefold()
        if normalized in used_names:
            raise TemplateValidationError(
                f"Nombre de canal duplicado: {item_name}",
                line_number,
            )
        used_names.add(normalized)
        counters[item_type] = counters.get(item_type, 0) + 1

        if item_type == "ANN":
            announcement_count += 1
            if announcement_count > 1:
                raise TemplateValidationError(
                    "Solo puede existir un canal [ANN].",
                    line_number,
                )
            channel_key = "announcements"
        else:
            prefix = item_type.casefold().replace("-", "_")
            channel_key = f"{prefix}_{counters[item_type]:02d}"

        channels.append(
            ChannelTemplate(
                item_type,
                item_name,
                channel_key,
                line_number,
            )
        )

    if category_name is None:
        raise TemplateValidationError("Falta la línea [CATEGORY].")
    if not channels:
        raise TemplateValidationError("La plantilla debe contener al menos un canal.")
    if announcement_count != 1:
        raise TemplateValidationError(
            "La plantilla debe contener exactamente un canal [ANN]."
        )

    return ParsedTemplate(category_name, tuple(channels))


def _protect_custom_emojis(value: str) -> tuple[str, list[tuple[str, str]]]:
    protected: list[tuple[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        placeholder = f"@@VEXEN_EMOJI_{len(protected)}@@"
        protected.append((placeholder, match.group(0)))
        return placeholder

    return _CUSTOM_EMOJI_PATTERN.sub(replace, value), protected


def _restore_custom_emojis(value: str, protected: list[tuple[str, str]]) -> str:
    for placeholder, original in protected:
        value = value.replace(placeholder, original)
    return value


def render_category_name(
    parsed_template: ParsedTemplate,
    associate_name: str,
    community_name: str,
) -> str:
    associate_name = str(associate_name or "").strip()
    community_name = str(community_name or "").strip()

    if any(character in associate_name + community_name for character in "{}"):
        raise TemplateValidationError("Los nombres no pueden contener llaves.")

    result, protected = _protect_custom_emojis(parsed_template.category_name)

    associate_pattern = _VARIABLE_PATTERNS[ASSOCIATE_VARIABLE]
    if associate_pattern.search(result):
        if not associate_name:
            raise TemplateValidationError(
                "La plantilla usa asociado, pero no hay un nombre disponible."
            )
        result = associate_pattern.sub(
            sanitize_associate_name_for_category(associate_name),
            result,
        )

    community_pattern = _VARIABLE_PATTERNS[COMMUNITY_VARIABLE]
    if community_pattern.search(result):
        if not community_name:
            raise TemplateValidationError(
                "La plantilla usa comunidad, pero no hay un nombre disponible."
            )
        result = community_pattern.sub(community_name, result)

    result = _restore_custom_emojis(result, protected)

    if len(result) > MAX_CATEGORY_LENGTH:
        raise TemplateValidationError(
            f"El nombre final de la categoría supera {MAX_CATEGORY_LENGTH} caracteres."
        )
    return result
