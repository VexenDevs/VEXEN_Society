from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Any

from app.config.settings import Settings


@dataclass(slots=True)
class VerificationIntegration:
    """Contrato Society → VEXEN Verification.

    Registra exclusivamente una fila por Society en:
    vexen_verification.role_transfers

    onboarding_role_id (INT-*) → verified_role_id (rol de comunidad)
    """

    db: object
    settings: Settings

    @property
    def enabled(self) -> bool:
        return self.settings.verification_integration == "postgres"

    @property
    def schema(self) -> str:
        return self.settings.vexen_verification_schema

    @property
    def relation(self) -> str:
        return f"{self.schema}.role_transfers"

    async def _available(self) -> bool:
        relation = await self.db.fetchval(  # type: ignore[attr-defined]
            "SELECT to_regclass($1)",
            self.relation,
        )
        return relation is not None

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        acquire = getattr(self.db, "acquire", None)
        if callable(acquire):
            async with acquire() as connection:
                yield connection
            return
        yield self.db

    @staticmethod
    @asynccontextmanager
    async def _transaction(connection: Any) -> AsyncIterator[None]:
        transaction = getattr(connection, "transaction", None)
        if callable(transaction):
            async with transaction():
                yield
            return
        yield

    async def health(self) -> tuple[bool, str]:
        if not self.enabled:
            return True, "disabled"
        available = await self._available()
        return available, "postgres" if available else "missing_table"

    async def register_transfer(
        self,
        guild_id: int,
        onboarding_role_id: int,
        verified_role_id: int,
        name: str,
        configured_by: int,
    ) -> None:
        if not self.enabled:
            return
        if int(onboarding_role_id) == int(verified_role_id):
            raise ValueError("El rol INT y el rol definitivo no pueden ser iguales.")
        if not await self._available():
            raise RuntimeError(f"No existe {self.relation}.")

        mapping_name = str(name or "").strip()
        if not mapping_name:
            mapping_name = f"{onboarding_role_id} → {verified_role_id}"
        elif "→" not in mapping_name:
            mapping_name = f"INT-{mapping_name} → {mapping_name}"
        if len(mapping_name) > 200:
            raise ValueError("El nombre administrativo del mapping es demasiado largo.")

        async with self._connection() as connection:
            async with self._transaction(connection):
                conflict = await connection.fetchval(
                    f'''SELECT onboarding_role_id
                        FROM "{self.schema}".role_transfers
                        WHERE guild_id=$1
                          AND verified_role_id=$2
                          AND onboarding_role_id<>$3''',
                    int(guild_id),
                    int(verified_role_id),
                    int(onboarding_role_id),
                )
                if conflict is not None:
                    raise RuntimeError(
                        "El rol oficial de la comunidad ya pertenece a otra transferencia "
                        f"INT (onboarding_role_id={int(conflict)})."
                    )

                await connection.execute(
                    f'''INSERT INTO "{self.schema}".role_transfers
                            (guild_id,onboarding_role_id,verified_role_id,name,configured_by)
                        VALUES ($1,$2,$3,$4,$5)
                        ON CONFLICT (guild_id,onboarding_role_id) DO UPDATE SET
                            verified_role_id=EXCLUDED.verified_role_id,
                            name=EXCLUDED.name,
                            configured_by=EXCLUDED.configured_by,
                            updated_at=NOW()''',
                    int(guild_id),
                    int(onboarding_role_id),
                    int(verified_role_id),
                    mapping_name,
                    int(configured_by),
                )

    async def remove_transfer(
        self,
        guild_id: int,
        onboarding_role_id: int,
    ) -> bool:
        if not self.enabled:
            return True
        if not await self._available():
            raise RuntimeError(f"No existe {self.relation}.")

        result = await self.db.execute(  # type: ignore[attr-defined]
            f'''DELETE FROM "{self.schema}".role_transfers
                WHERE guild_id=$1 AND onboarding_role_id=$2''',
            int(guild_id),
            int(onboarding_role_id),
        )
        return not str(result).endswith(" 0")
