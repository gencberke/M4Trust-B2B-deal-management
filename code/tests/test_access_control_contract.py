"""`backend.app.services.access_control` black-box kontrat testleri (Plan 02 sonu freeze).

Berke'nin sahibi olduğu `access_control.py`'nin İÇ implementasyonuna
bağlanılmaz — yalnız public import'lar, `ActorContext` alan seti, `get_current_actor`
varsayılan davranışı (yalnız anonymous/legacy_capability, Plan 02'de session/
membership yok), `require_authenticated_user`/`require_active_membership`
imzaları ve Plan 03'ün ihtiyaç duyacağı `dependency_overrides` uyumluluğu
kilitlenir. Bu dosya `access_control.py`'yi DEĞİŞTİRMEZ.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app.services.access_control import (
    ActorContext,
    get_current_actor,
    require_active_membership,
    require_authenticated_user,
)


def test_actor_context_is_frozen_dataclass_with_expected_fields() -> None:
    assert dataclasses.is_dataclass(ActorContext)
    field_names = {f.name for f in dataclasses.fields(ActorContext)}
    assert field_names == {
        "actor_type",
        "user_id",
        "acting_entity_id",
        "platform_role",
        "transaction_assignment_role",
        "participant_role",
        "request_id",
        "auth_method",
    }

    actor = ActorContext(actor_type="anonymous")
    with pytest.raises(dataclasses.FrozenInstanceError):
        actor.actor_type = "legacy_capability"  # type: ignore[misc]


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(actor: ActorContext = Depends(get_current_actor)):
        return dataclasses.asdict(actor)

    @app.get("/needs-auth")
    def needs_auth(actor: ActorContext = Depends(require_authenticated_user)):
        return dataclasses.asdict(actor)

    @app.get("/needs-membership")
    def needs_membership(actor: ActorContext = Depends(require_active_membership)):
        return dataclasses.asdict(actor)

    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_build_app())


def test_get_current_actor_defaults_to_anonymous_without_capability_token(
    client: TestClient,
) -> None:
    response = client.get("/whoami")
    assert response.status_code == 200
    body = response.json()
    assert body["actor_type"] == "anonymous"
    assert body["auth_method"] == "none"
    assert body["user_id"] is None


@pytest.mark.parametrize("param_name", ["token", "buyer_token", "seller_token", "manager_token"])
def test_get_current_actor_recognizes_legacy_capability_tokens(
    client: TestClient, param_name: str
) -> None:
    response = client.get("/whoami", params={param_name: "some-token-value"})
    assert response.status_code == 200
    body = response.json()
    assert body["actor_type"] == "legacy_capability"
    assert body["auth_method"] == "legacy_capability"


def test_require_authenticated_user_rejects_anonymous_actor(client: TestClient) -> None:
    response = client.get("/needs-auth")
    assert response.status_code == 401


def test_require_active_membership_rejects_actor_without_entity(client: TestClient) -> None:
    # legacy_capability actor'da bugün user_id/acting_entity_id hâlâ None'dır
    # (Plan 02'de session/membership henüz uygulanmaz) -> `require_active_membership`,
    # kendi bağımlı olduğu `require_authenticated_user` katmanında 401 ile düşer.
    response = client.get("/needs-membership", params={"token": "x"})
    assert response.status_code == 401


def test_dependency_overrides_can_stub_get_current_actor_for_future_plan_03_tests() -> None:
    """Plan 03'ün ihtiyaç duyacağı asıl kontrat: `dependency_overrides` üzerinden stub actor."""
    app = _build_app()

    def stub_actor() -> ActorContext:
        return ActorContext(
            actor_type="legacy_capability",
            user_id="user-1",
            acting_entity_id="entity-1",
            auth_method="legacy_capability",
        )

    app.dependency_overrides[get_current_actor] = stub_actor
    try:
        client = TestClient(app)

        whoami = client.get("/whoami")
        assert whoami.status_code == 200
        assert whoami.json()["user_id"] == "user-1"

        # require_authenticated_user/require_active_membership get_current_actor'a
        # Depends ile bağlıdır; override zincir boyunca da etkili olmalı.
        auth = client.get("/needs-auth")
        assert auth.status_code == 200
        assert auth.json()["user_id"] == "user-1"

        membership = client.get("/needs-membership")
        assert membership.status_code == 200
        assert membership.json()["acting_entity_id"] == "entity-1"
    finally:
        app.dependency_overrides.clear()


def test_dependency_override_cleanup_fixture_resets_overrides(
    dependency_override_cleanup,
) -> None:
    """`conftest.py::dependency_override_cleanup` — override'lar test sonunda temizlenir."""
    from backend.app.main import app

    def stub_actor() -> ActorContext:
        return ActorContext(actor_type="anonymous")

    dependency_override_cleanup[get_current_actor] = stub_actor
    assert app.dependency_overrides.get(get_current_actor) is stub_actor
    # Fixture teardown'da temizler; burada yalnız kurulumun etkili olduğunu doğrularız.
