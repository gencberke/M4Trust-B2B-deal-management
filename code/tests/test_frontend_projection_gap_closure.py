"""Regression coverage for the narrow frontend contract gap closure."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.db import get_db
from backend.app.repositories import payment_resolutions as resolutions_repo
from backend.app.repositories import participants as participants_repo
from backend.app.services import ratifications as ratifications_service
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext, get_current_actor

from test_ratifications import _actor as ratification_actor
from test_ratifications import _setup_open_package, make_db
from test_rule_revision_endpoints import _PAYLOAD, _actor, _make_db


def _router_app(conn, router, actor: ActorContext | None = None) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(router)

    def _get_db():
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    app.dependency_overrides[get_db] = _get_db
    if actor is not None:
        app.dependency_overrides[get_current_actor] = lambda: actor
    return app


def test_account_tracking_policy_is_session_scoped_idempotent_and_ae_bound(tmp_path) -> None:
    conn, _parent_id = _make_db(tmp_path)
    try:
        from backend.app.routers import transactions
        from backend.app.services.tracking_policy import create_draft_policy

        conn.execute(
            "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
            "created_at, updated_at) VALUES ('u-owner', 'owner@example.com', 'unused', "
            "'Owner', 'User', 'now', 'now')"
        )
        create_draft_policy(conn, "tx-4f")
        app = _router_app(conn, transactions.router, _actor())
        client = TestClient(app)

        read = client.get("/api/transactions/tx-4f/tracking-policy")
        assert read.status_code == 200
        assert read.json()["tracking_policy"]["status"] == "draft"
        assert read.json()["ready_for_policy"] is True
        assert "source_quote" not in json.dumps(read.json())

        update = client.put(
            "/api/transactions/tx-4f/tracking-policy",
            json={"physical_delivery_confirmed": True, "tracking_mode": "off"},
        )
        assert update.status_code == 200
        assert update.json()["updated"] is True
        replay = client.put(
            "/api/transactions/tx-4f/tracking-policy",
            json={"physical_delivery_confirmed": True, "tracking_mode": "off"},
        )
        assert replay.status_code == 200
        assert replay.json()["updated"] is False

        locked = client.post("/api/transactions/tx-4f/tracking-policy/lock", json={})
        assert locked.status_code == 200
        assert locked.json()["locked"] is True
        lock_replay = client.post("/api/transactions/tx-4f/tracking-policy/lock")
        assert lock_replay.status_code == 200
        assert lock_replay.json()["locked"] is False

        forbidden = TestClient(
            _router_app(
                conn,
                transactions.router,
                _actor(user_id="u-other", entity_id="entity-other"),
            )
        ).get("/api/transactions/tx-4f/tracking-policy")
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "TRACKING_POLICY_FORBIDDEN"
    finally:
        conn.close()


def test_account_tracking_policy_mutation_requires_real_session_csrf(tmp_path, monkeypatch) -> None:
    from reviews_fixtures import create_real_session, create_real_user
    from backend.app.routers import transactions
    from backend.app.services.tracking_policy import create_draft_policy

    conn, _parent_id = _make_db(tmp_path)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "4f.db"))
    create_draft_policy(conn, "tx-4f")
    user_id = create_real_user(conn, email_normalized="owner-policy@example.com", user_id="u-session")
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "created_by_user_id, created_at, updated_at) VALUES "
        "('entity-owner', 'company', 'Owner Co', 'VKN', 'cipher', 'hmac', '0000', ?, 'now', 'now')",
        (user_id,),
    )
    conn.execute(
        "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
        "VALUES ('membership-owner', ?, 'entity-owner', 'owner', 'active', 'now')",
        (user_id,),
    )
    conn.execute(
        "UPDATE transaction_assignments SET user_id = ? WHERE transaction_id = ? "
        "AND role = 'manager' AND legal_entity_id = 'entity-owner'",
        (user_id, "tx-4f"),
    )
    conn.commit()
    session = create_real_session(conn, user_id=user_id)
    conn.commit()
    try:
        app = _router_app(conn, transactions.router)
        client = TestClient(app)
        client.cookies.set("m4t_session", session.raw_token)
        missing_csrf = client.put(
            "/api/transactions/tx-4f/tracking-policy",
            json={"physical_delivery_confirmed": True, "tracking_mode": "off"},
        )
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["code"] == "CSRF_TOKEN_INVALID"
        accepted = client.put(
            "/api/transactions/tx-4f/tracking-policy",
            headers={
                "X-CSRF-Token": session.raw_csrf_token,
                "X-Acting-Entity-ID": "entity-owner",
            },
            json={"physical_delivery_confirmed": True, "tracking_mode": "off"},
        )
        assert accepted.status_code == 200, accepted.text
    finally:
        conn.close()


def test_rule_set_history_and_revision_preserve_omitted_parent_quotes(tmp_path) -> None:
    conn, parent_id = _make_db(tmp_path)
    try:
        from backend.app.routers import rule_sets

        app = _router_app(conn, rule_sets.router, _actor())
        client = TestClient(app)
        history = client.get("/api/transactions/tx-4f/rule-sets")
        assert history.status_code == 200
        assert history.json()["current_version_id"] == parent_id
        assert len(history.json()["versions"]) == 1
        assert "source_quote" not in json.dumps(history.json())

        payload = json.loads(json.dumps(_PAYLOAD))
        payload["contract_id"] = "without-quote"
        payload["payment_rules"][0].pop("source_quote")
        revision = client.post(
            f"/api/transactions/tx-4f/rule-sets/{parent_id}/revisions",
            json=payload,
        )
        assert revision.status_code == 200, revision.text
        new_id = revision.json()["id"]
        stored = conn.execute(
            "SELECT rules_json FROM rule_set_versions WHERE id = ?", (new_id,)
        ).fetchone()
        assert json.loads(stored["rules_json"])["payment_rules"][0]["source_quote"] == _PAYLOAD[
            "payment_rules"
        ][0]["source_quote"]
        assert conn.execute(
            "SELECT rules_json FROM rule_set_versions WHERE id = ?", (parent_id,)
        ).fetchone()["rules_json"] == json.dumps(_PAYLOAD, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    finally:
        conn.close()


def test_account_evidence_bundle_omits_source_quotes(tmp_path) -> None:
    conn, _parent_id = _make_db(tmp_path)
    try:
        from backend.app.services.evidence import build_bundle

        bundle = build_bundle(conn, "tx-4f")
        assert "source_quote" not in json.dumps(bundle)
    finally:
        conn.close()


def test_ratification_progress_and_milestone_projection_include_real_ids(tmp_path) -> None:
    conn = make_db(tmp_path / "projection.db")
    tx_id = "tx-projection"
    package_id = _setup_open_package(conn, tx_id)
    buyer = ratification_actor("u-buyer", "entity-buyer")
    seller = ratification_actor("u-seller", "entity-seller")
    try:
        from backend.app.routers import fulfillment, ratifications

        first_app = _router_app(conn, ratifications.router, buyer)
        first = TestClient(first_app).post(
            f"/api/ratification-packages/{package_id}/ratifications", json={}
        )
        assert first.status_code == 200, first.text
        current = TestClient(first_app).get(
            f"/api/transactions/{tx_id}/ratification-packages/current"
        )
        assert current.status_code == 200
        assert current.json()["ratifications"]["buyer"] == {
            "ratified": True,
            "approved_at": current.json()["ratifications"]["buyer"]["approved_at"],
        }
        assert current.json()["ratifications"]["seller"]["ratified"] is False

        second = TestClient(_router_app(conn, ratifications.router, seller)).post(
            f"/api/ratification-packages/{package_id}/ratifications", json={}
        )
        assert second.status_code == 200, second.text
        complete = TestClient(first_app).get(
            f"/api/transactions/{tx_id}/ratification-packages/current"
        )
        assert complete.json()["ratifications"]["buyer"]["ratified"] is True
        assert complete.json()["ratifications"]["seller"]["ratified"] is True

        from backend.app.repositories import release_instructions as release_instructions_repo

        unit_row = conn.execute(
            "SELECT fu.id, fu.amount_minor, fu.currency, pp.id AS provider_payment_id "
            "FROM funding_units fu JOIN provider_payments pp ON pp.funding_unit_id = fu.id "
            "WHERE fu.transaction_id = ? ORDER BY fu.sequence LIMIT 1",
            (tx_id,),
        ).fetchone()
        instruction = release_instructions_repo.insert(
            conn,
            funding_unit_id=unit_row["id"],
            provider_payment_id=unit_row["provider_payment_id"],
            idempotency_key="projection-release-instruction",
            amount_minor=unit_row["amount_minor"],
            currency=unit_row["currency"],
            provider="mock",
        )
        conn.commit()
        projected = TestClient(_router_app(conn, fulfillment.router, buyer)).get(
            f"/api/transactions/{tx_id}/milestones"
        )
        assert projected.status_code == 200, projected.text
        milestone = projected.json()["milestones"][0]
        unit = milestone["funding_units"][0]
        assert milestone["id"]
        assert unit["id"]
        assert unit["milestone_id"] == milestone["id"]
        assert unit["sequence"] == 1
        assert unit["amount_minor"] > 0
        assert unit["release_instruction_id"] == instruction["id"]

        intruder = TestClient(
            _router_app(conn, fulfillment.router, _actor("u-intruder", "entity-x"))
        ).get(f"/api/transactions/{tx_id}/milestones")
        assert intruder.status_code == 403
    finally:
        conn.close()


def test_payment_resolution_list_detail_is_assignment_scoped_and_includes_approvals(tmp_path) -> None:
    conn = make_db(tmp_path / "resolution-projection.db")
    tx_id = "tx-resolution-projection"
    package_id = _setup_open_package(conn, tx_id)
    ratifications_service.create_ratification(
        conn,
        package_id=package_id,
        actor_context=ratification_actor("u-buyer", "entity-buyer"),
        auth_method="session",
    )
    ratifications_service.create_ratification(
        conn,
        package_id=package_id,
        actor_context=ratification_actor("u-seller", "entity-seller"),
        auth_method="session",
    )
    try:
        from backend.app.routers import payment_ops

        unit = conn.execute(
            "SELECT id FROM funding_units WHERE transaction_id = ? LIMIT 1", (tx_id,)
        ).fetchone()
        case = review_service.open_case(
            conn,
            transaction_id=tx_id,
            phase="payment",
            source_type="payment",
            source_id=unit["id"],
            reason_code="PAYMENT_UNDO_REQUESTED",
            title="undo",
            description="undo",
            severity="blocking",
            actor_context=ratification_actor("u-buyer", "entity-buyer"),
        )
        resolution = resolutions_repo.insert(
            conn,
            transaction_id=tx_id,
            funding_unit_id=unit["id"],
            review_case_id=case.id,
            operation_type="undo_approval",
            idempotency_key="resolution-projection-key",
            requested_by_user_id="u-buyer",
            requested_by_entity_id="entity-buyer",
        )
        resolutions_repo.insert_approval(
            conn,
            resolution_id=resolution["id"],
            participant_role="buyer",
            user_id="u-buyer",
            acting_entity_id="entity-buyer",
        )
        conn.commit()

        app = _router_app(conn, payment_ops.router, ratification_actor("u-buyer", "entity-buyer"))
        client = TestClient(app)
        listing = client.get(f"/api/transactions/{tx_id}/payment-resolutions")
        assert listing.status_code == 200
        assert listing.json()["resolutions"][0]["id"] == resolution["id"]
        assert listing.json()["resolutions"][0]["approvals"][0]["participant_role"] == "buyer"
        detail = client.get(
            f"/api/transactions/{tx_id}/payment-resolutions/{resolution['id']}"
        )
        assert detail.status_code == 200
        assert detail.json()["review_case_id"] == case.id

        cross = client.get(
            f"/api/transactions/another-transaction/payment-resolutions/{resolution['id']}"
        )
        assert cross.status_code == 404
        assert "resolution-projection-key" not in cross.text
    finally:
        conn.close()
