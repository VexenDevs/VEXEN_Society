"""Public slash surface only. Internal configuration services remain available to Dashboard."""
from __future__ import annotations

RETIRED_ROOT_COMMANDS = ("config", "plantilla", "acceso", "administrar")
QUICK_COMMAND_PATHS = frozenset({
    "help", "estado", "panel", "miembros",
    "asociado agregar", "asociado listar", "asociado info", "asociado eliminar",
    "staff agregar", "staff quitar", "staff listar", "bienvenida reenviar",
})


def command_paths(group, prefix="") -> set[str]:
    result = set()
    for command in group.commands:
        path = (prefix + " " + command.name).strip()
        if hasattr(command, "commands"):
            result.update(command_paths(command, path))
        else:
            result.add(path)
    return result


def simplify_commands(group) -> None:
    for name in RETIRED_ROOT_COMMANDS:
        group.remove_command(name)
    actual = command_paths(group)
    if actual != QUICK_COMMAND_PATHS:
        raise RuntimeError("La superficie de comandos Society no coincide con los 12 comandos rápidos: "
                           + repr(sorted(actual.symmetric_difference(QUICK_COMMAND_PATHS))))
