from __future__ import annotations

import pytest

from api.services.auth_service import list_principals


class _FakeResult:
    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[object]:
        return []


class _FakeDB:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):  # type: ignore[no-untyped-def]
        self.statement = statement
        return _FakeResult()


@pytest.mark.asyncio
async def test_principal_search_matches_display_name_and_username() -> None:
    db = _FakeDB()

    await list_principals(db, provider="auth0", search="test1")

    assert db.statement is not None
    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "auth_principals.provider = 'auth0'" in compiled
    assert "auth_principals.username" in compiled
    assert "auth_principals.display_name" in compiled
