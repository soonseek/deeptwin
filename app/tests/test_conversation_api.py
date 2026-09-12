from hashlib import sha256
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.conversation_routes import install_conversation_routes
from app.api.session import LocalSessionAuthority
from app.domain.refs import EntityRef, ObjectRef
from app.server import LocalBoundary, create_app
from app.services.conversation import Conversation, TrustedConversationActor
from app.storage import Store

HOST = "127.0.0.1:4193"
ORIGIN = f"http://{HOST}"


def _subject(tmp_path):
    now = [1_000]
    store = Store(tmp_path)
    work = store.create_work("유튜브 콘텐츠를 기획합니다.")
    sessions = LocalSessionAuthority({HOST}, clock=lambda: now[0])
    launch = sessions.mint_bootstrap()
    exchange = sessions.exchange_bootstrap(
        launch.capability,
        method="POST",
        host=HOST,
        origin=ORIGIN,
        sec_fetch_site="same-origin",
    )
    conversation = Conversation(store, clock_ms=lambda: now[0] * 1_000)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalBoundary, sessions=sessions)
    install_conversation_routes(app, conversation=conversation)
    client = TestClient(app, base_url=ORIGIN)
    client.cookies.set("deeptwin_local_session", exchange.cookie_pair.split("=", 1)[1])
    mutation_headers = {
        "origin": ORIGIN,
        "sec-fetch-site": "same-origin",
        "x-csrf-token": exchange.csrf_token,
    }
    return store, work, conversation, exchange, client, mutation_headers


def _source():
    return EntityRef(
        "source", str(uuid4()), 1, sha256(b"uploaded-source").hexdigest()
    )


def _target():
    return ObjectRef(
        "environment",
        str(uuid4()),
        3,
        sha256(b"environment-v3").hexdigest(),
    )


def _agent_proposal(conversation, work, target):
    agent = TrustedConversationActor(str(uuid4()), "agent")
    message = conversation.add_message(
        work["id"],
        work["revision"],
        "검토된 환경 3을 적용하는 행동을 제안합니다.",
        semantic_origin="command_request",
        actor=agent,
    )
    return conversation.propose_command(
        message["id"],
        command_kind="environment.activate",
        exact_target=target,
        structured_args={"scope": "next_run"},
        proposer=agent,
        required_authority="local_human",
    )


def test_product_app_installs_conversation_service_routes_and_static_module(tmp_path):
    app = create_app(
        tmp_path / "product-vault",
        port=4193,
        understanding_provider_ready=False,
    )
    launch = app.state.local_sessions.mint_bootstrap()

    with TestClient(app, base_url=ORIGIN) as client:
        exchange = client.post(
            "/api/session/bootstrap",
            headers={"origin": ORIGIN, "sec-fetch-site": "same-origin"},
            json={"capability": launch.capability},
        )
        assert exchange.status_code == 201
        headers = {
            "origin": ORIGIN,
            "sec-fetch-site": "same-origin",
            "x-csrf-token": exchange.json()["csrf_token"],
        }
        work = client.post(
            "/api/works", headers=headers, json={"text": "새 업무"}
        ).json()

        recorded = client.post(
            f'/api/v1/works/{work["id"]}/messages',
            headers=headers,
            json={
                "work_revision": work["revision"],
                "content": "업무 맥락을 덧붙입니다.",
                "semantic_origin": "clarification",
                "referenced_entity_refs": [],
            },
        )

        assert recorded.status_code == 201
        assert app.state.conversation.list_messages(work["id"]) == [
            recorded.json()["message"]
        ]
        assert client.get("/chat.mjs").status_code == 200


def test_messages_require_bound_session_and_take_actor_only_from_session(tmp_path):
    _, work, conversation, exchange, client, headers = _subject(tmp_path)
    path = f'/api/v1/works/{work["id"]}/messages'

    anonymous = TestClient(client.app, base_url=ORIGIN)
    assert anonymous.get(path).status_code == 401

    response = client.post(
        path,
        headers=headers,
        json={
            "work_revision": work["revision"],
            "content": "내 설명의 일부를 더 붙입니다.",
            "semantic_origin": "clarification",
            "referenced_entity_refs": [],
        },
    )

    assert response.status_code == 201
    recorded = response.json()["message"]
    assert recorded["actor"] == {
        "id": exchange.session.actor.id,
        "kind": "human",
    }
    assert conversation.list_messages(work["id"]) == [recorded]

    spoofed = client.post(
        path,
        headers=headers,
        json={
            "work_revision": work["revision"],
            "content": "브라우저가 시스템 권한을 주장합니다.",
            "semantic_origin": "clarification",
            "referenced_entity_refs": [],
            "actor": {"id": str(uuid4()), "kind": "system"},
        },
    )
    assert spoofed.status_code == 400
    assert len(conversation.list_messages(work["id"])) == 1


def test_ordinary_acknowledgement_and_explanation_never_infer_a_command(tmp_path):
    _, work, conversation, _, client, headers = _subject(tmp_path)
    path = f'/api/v1/works/{work["id"]}/messages'

    for content in ("응", "좋아", "이 업무는 이런 자료를 먼저 봐야 해요."):
        response = client.post(
            path,
            headers=headers,
            json={
                "work_revision": work["revision"],
                "content": content,
                "semantic_origin": "clarification",
                "referenced_entity_refs": [],
            },
        )
        assert response.status_code == 201
        assert response.json()["message"]["optional_command_ref"] is None

    assert conversation.list_proposed_commands(work["id"]) == []
    assert conversation.list_validations(work["id"]) == []


def test_message_reference_schema_revision_and_json_shape_are_exact(tmp_path):
    store, work, conversation, _, client, headers = _subject(tmp_path)
    path = f'/api/v1/works/{work["id"]}/messages'
    source = _source()

    good = client.post(
        path,
        headers=headers,
        json={
            "work_revision": work["revision"],
            "content": "이 자료를 함께 보세요.",
            "semantic_origin": "work_request",
            "referenced_entity_refs": [source.as_dict()],
        },
    )
    assert good.status_code == 201
    assert good.json()["message"]["referenced_entity_refs"] == [source.as_dict()]

    current = store.update_work(work["id"], "수정된 원 업무", work["revision"])
    stale = client.post(
        path,
        headers=headers,
        json={
            "work_revision": work["revision"],
            "content": "오래된 화면의 말",
            "semantic_origin": "clarification",
            "referenced_entity_refs": [],
        },
    )
    assert stale.status_code == 409
    assert current["revision"] == 2

    duplicate = client.post(
        path,
        headers={**headers, "content-type": "application/json"},
        content=(
            '{"work_revision":2,"content":"첫 값","content":"둘째 값",'
            '"semantic_origin":"clarification","referenced_entity_refs":[]}'
        ),
    )
    assert duplicate.status_code == 400
    assert client.get(
        path + "?actor=system", headers={"sec-fetch-site": "same-origin"}
    ).status_code == 400
    assert len(conversation.list_messages(work["id"])) == 1


def test_generic_message_route_cannot_create_command_request(tmp_path):
    _, work, conversation, _, client, headers = _subject(tmp_path)
    response = client.post(
        f'/api/v1/works/{work["id"]}/messages',
        headers=headers,
        json={
            "work_revision": work["revision"],
            "content": "적용 확인 아무거나",
            "semantic_origin": "command_request",
            "referenced_entity_refs": [],
        },
    )

    assert response.status_code == 400
    assert conversation.list_messages(work["id"]) == []


def test_button_and_chat_use_exact_target_bound_challenge_without_execution(tmp_path):
    _, work, conversation, _, client, headers = _subject(tmp_path)
    target = _target()
    proposal = _agent_proposal(conversation, work, target)

    challenge_response = client.post(
        f'/api/v1/conversation/commands/{proposal["id"]}/challenges',
        headers=headers,
        json={"work_id": work["id"], "exact_target_ref": target.as_dict()},
    )
    assert challenge_response.status_code == 201
    challenge = challenge_response.json()["challenge"]

    wrong_target = _target()
    rejected = client.post(
        f'/api/v1/conversation/commands/{proposal["id"]}/button-validation',
        headers=headers,
        json={
            "work_id": work["id"],
            "challenge_id": challenge["id"],
            "token": challenge["token"],
            "exact_target_ref": wrong_target.as_dict(),
        },
    )
    assert rejected.status_code == 409
    assert conversation.list_validations(work["id"]) == []

    accepted = client.post(
        f'/api/v1/conversation/commands/{proposal["id"]}/button-validation',
        headers=headers,
        json={
            "work_id": work["id"],
            "challenge_id": challenge["id"],
            "token": challenge["token"],
            "exact_target_ref": target.as_dict(),
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["validation"]["command_id"] == proposal["id"]
    assert accepted.json()["executed"] is False


def test_chat_validation_requires_the_server_challenge_text_and_exact_binding(tmp_path):
    store, work, conversation, _, client, headers = _subject(tmp_path)
    target = _target()
    proposal = _agent_proposal(conversation, work, target)
    challenge = client.post(
        f'/api/v1/conversation/commands/{proposal["id"]}/challenges',
        headers=headers,
        json={"work_id": work["id"], "exact_target_ref": target.as_dict()},
    ).json()["challenge"]
    messages_before = conversation.list_messages(work["id"])
    events_before = store.events(work["id"])

    ambiguous = client.post(
        f'/api/v1/works/{work["id"]}/command-responses',
        headers=headers,
        json={
            "work_revision": work["revision"],
            "command_id": proposal["id"],
            "challenge_id": challenge["id"],
            "token": challenge["token"],
            "content": "응",
            "exact_target_ref": target.as_dict(),
        },
    )
    assert ambiguous.status_code == 409
    assert conversation.list_validations(work["id"]) == []
    assert conversation.list_messages(work["id"]) == messages_before
    assert store.events(work["id"]) == events_before

    accepted = client.post(
        f'/api/v1/works/{work["id"]}/command-responses',
        headers=headers,
        json={
            "work_revision": work["revision"],
            "command_id": proposal["id"],
            "challenge_id": challenge["id"],
            "token": challenge["token"],
            "content": challenge["response_text"],
            "exact_target_ref": target.as_dict(),
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["validation"]["route"] == "chat"
    assert accepted.json()["message"]["content"] == challenge["response_text"]
    assert accepted.json()["executed"] is False


def test_read_routes_are_side_effect_free_and_do_not_disclose_challenge_token(tmp_path):
    store, work, conversation, _, client, headers = _subject(tmp_path)
    target = _target()
    proposal = _agent_proposal(conversation, work, target)
    challenge = client.post(
        f'/api/v1/conversation/commands/{proposal["id"]}/challenges',
        headers=headers,
        json={"work_id": work["id"], "exact_target_ref": target.as_dict()},
    ).json()["challenge"]
    before = store.events()

    read_headers = {"sec-fetch-site": "same-origin"}
    messages = client.get(
        f'/api/v1/works/{work["id"]}/messages', headers=read_headers
    )
    commands = client.get(
        f'/api/v1/works/{work["id"]}/conversation-commands',
        headers=read_headers,
    )

    assert messages.status_code == commands.status_code == 200
    assert "token" not in str(commands.json()).lower()
    assert challenge["token"] not in str(commands.json())
    assert store.events() == before
