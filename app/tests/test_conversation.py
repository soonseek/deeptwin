from hashlib import sha256
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef, ObjectRef
from app.services.conversation import (
    Conversation,
    ConversationAuthorityError,
    ConversationConflict,
    TrustedConversationActor,
)
from app.storage import ConflictError, Store


def actor(kind="human", *, authority="none"):
    return TrustedConversationActor(str(uuid4()), kind, authority)


def source_ref():
    return EntityRef(
        "source", str(uuid4()), 1, sha256(b"source-v1").hexdigest()
    )


def exact_target(kind="work"):
    return ObjectRef(
        kind,
        str(uuid4()),
        1,
        sha256(f"{kind}-v1".encode()).hexdigest(),
    )


def subject(tmp_path, *, clock=None):
    store = Store(tmp_path)
    work = store.create_work("내 원 업무")
    return store, work, Conversation(store, clock_ms=clock or (lambda: 1_000))


def test_messages_are_revision_bound_ordered_and_preserve_exact_references(tmp_path):
    store, work, conversation = subject(tmp_path)
    user, agent, evidence = actor(), actor("agent"), source_ref()

    first = conversation.add_message(
        work["id"],
        work["revision"],
        "이 업무를 이렇게 진행하고 싶어요.",
        semantic_origin="work_request",
        actor=user,
        referenced_entities=(evidence,),
    )
    second = conversation.add_message(
        work["id"],
        work["revision"],
        "제가 이해한 결과입니다.",
        semantic_origin="clarification",
        actor=agent,
    )

    assert first["sequence"] == 1 and second["sequence"] == 2
    assert first["referenced_entity_refs"] == [evidence.as_dict()]
    assert conversation.list_messages(work["id"]) == [first, second]
    assert store.get_work(work["id"]) == work


@pytest.mark.parametrize("content", ["응", "좋아", "맞아", "그건 별로야"])
def test_ordinary_conversation_never_infers_alternative_command_or_approval(
    tmp_path, content
):
    _, work, conversation = subject(tmp_path)
    message = conversation.add_message(
        work["id"],
        work["revision"],
        content,
        semantic_origin="clarification",
        actor=actor(),
    )

    assert message["optional_command_ref"] is None
    assert conversation.list_proposed_commands(work["id"]) == []
    assert conversation.list_validations(work["id"]) == []


def test_message_requires_current_work_revision_and_exact_registered_origin(tmp_path):
    store, work, conversation = subject(tmp_path)
    store.update_work(work["id"], "바뀐 원 업무", work["revision"])

    with pytest.raises(ConflictError):
        conversation.add_message(
            work["id"],
            work["revision"],
            "오래된 화면의 말",
            semantic_origin="clarification",
            actor=actor(),
        )
    with pytest.raises(ValueError):
        conversation.add_message(
            work["id"],
            2,
            "내가 승인했다고 간주해",
            semantic_origin="approval",
            actor=actor(),
        )


def test_model_proposal_has_no_human_authority_and_freezes_exact_target(tmp_path):
    _, work, conversation = subject(tmp_path)
    model = actor("agent")
    target = exact_target("environment")
    message = conversation.add_message(
        work["id"],
        work["revision"],
        "환경 1을 적용하는 명령을 제안합니다.",
        semantic_origin="command_request",
        actor=model,
        referenced_entities=(),
    )
    proposal = conversation.propose_command(
        message["id"],
        command_kind="environment.activate",
        exact_target=target,
        structured_args={"scope": "next_run"},
        proposer=model,
        required_authority="local_human",
    )

    assert proposal["validation_state"] == "proposed"
    assert proposal["exact_target_ref"] == target.as_dict()
    with pytest.raises(ConversationAuthorityError):
        conversation.open_challenge(proposal["id"], authority=model)
    assert conversation.get_command(proposal["id"])["validation_state"] == "proposed"


def test_chat_and_button_invocation_share_exact_one_time_validation(tmp_path):
    _, work, conversation = subject(tmp_path)
    human = actor(authority="local_human")
    model = actor("agent")
    target = exact_target("environment")
    proposal_message = conversation.add_message(
        work["id"], work["revision"], "이 환경 적용을 제안합니다.",
        semantic_origin="command_request", actor=model,
    )
    proposal = conversation.propose_command(
        proposal_message["id"], command_kind="environment.activate",
        exact_target=target, structured_args={"scope": "next_run"},
        proposer=model, required_authority="local_human",
    )
    challenge = conversation.open_challenge(proposal["id"], authority=human)
    response = conversation.add_message(
        work["id"], work["revision"], challenge["response_text"],
        semantic_origin="command_request", actor=human,
        referenced_entities=(), optional_command_id=proposal["id"],
        exact_target=target,
    )

    chat_receipt = conversation.validate_invocation(
        proposal["id"], challenge["id"], challenge["token"],
        authority=human, response_message_id=response["id"], route="chat",
    )
    same_receipt = conversation.validate_invocation(
        proposal["id"], challenge["id"], challenge["token"],
        authority=human, response_message_id=response["id"], route="chat",
    )

    assert chat_receipt == same_receipt
    assert chat_receipt["validation_state"] == "validated"
    assert chat_receipt["command_id"] == proposal["id"]

    # A button uses the same validator. A new exact command is required because the
    # first command/challenge pair was consumed by the chat route.
    second_message = conversation.add_message(
        work["id"], work["revision"], "같은 대상의 새 명령",
        semantic_origin="command_request", actor=model,
    )
    second = conversation.propose_command(
        second_message["id"], command_kind="environment.activate",
        exact_target=target, structured_args={"scope": "next_run"},
        proposer=model, required_authority="local_human",
    )
    second_challenge = conversation.open_challenge(second["id"], authority=human)
    button_receipt = conversation.validate_invocation(
        second["id"], second_challenge["id"], second_challenge["token"],
        authority=human, response_message_id=None, route="button",
    )
    assert button_receipt["validation_state"] == "validated"


def test_atomic_chat_invocation_rolls_back_failed_message_and_exact_retry(tmp_path):
    store, work, conversation = subject(tmp_path)
    human = actor(authority="local_human")
    model = actor("agent")
    target = exact_target("environment")
    proposal_message = conversation.add_message(
        work["id"], work["revision"], "환경 적용 제안",
        semantic_origin="command_request", actor=model,
    )
    proposal = conversation.propose_command(
        proposal_message["id"], command_kind="environment.activate",
        exact_target=target, structured_args={}, proposer=model,
        required_authority="local_human",
    )
    challenge = conversation.open_challenge(proposal["id"], authority=human)
    messages_before = conversation.list_messages(work["id"])
    events_before = store.events(work["id"])

    with pytest.raises(ConversationConflict):
        conversation.record_and_validate_chat_invocation(
            work["id"], work["revision"], "응", proposal["id"],
            challenge["id"], challenge["token"], authority=human,
            exact_target=target,
        )

    assert conversation.list_messages(work["id"]) == messages_before
    assert conversation.list_validations(work["id"]) == []
    assert store.events(work["id"]) == events_before

    response, receipt = conversation.record_and_validate_chat_invocation(
        work["id"], work["revision"], challenge["response_text"],
        proposal["id"], challenge["id"], challenge["token"], authority=human,
        exact_target=target,
    )
    accepted_messages = conversation.list_messages(work["id"])
    accepted_events = store.events(work["id"])
    assert response["optional_command_ref"] == proposal["id"]
    assert receipt["response_message_ref"] == response["id"]

    with pytest.raises(ConversationConflict):
        conversation.record_and_validate_chat_invocation(
            work["id"], work["revision"], challenge["response_text"],
            proposal["id"], challenge["id"], challenge["token"],
            authority=human, exact_target=target,
        )
    assert conversation.list_messages(work["id"]) == accepted_messages
    assert store.events(work["id"]) == accepted_events


def test_ambiguous_or_spoofed_chat_approval_cannot_validate_command(tmp_path):
    _, work, conversation = subject(tmp_path)
    human = actor(authority="local_human")
    imposter = actor("agent", authority="local_human")
    model = actor("agent")
    target = exact_target("environment")
    message = conversation.add_message(
        work["id"], work["revision"], "환경 적용 제안",
        semantic_origin="command_request", actor=model,
    )
    proposal = conversation.propose_command(
        message["id"], command_kind="environment.activate",
        exact_target=target, structured_args={}, proposer=model,
        required_authority="local_human",
    )
    challenge = conversation.open_challenge(proposal["id"], authority=human)
    ordinary_yes = conversation.add_message(
        work["id"], work["revision"], "응",
        semantic_origin="clarification", actor=human,
    )
    spoofed = conversation.add_message(
        work["id"], work["revision"], challenge["response_text"],
        semantic_origin="command_request", actor=imposter,
        optional_command_id=proposal["id"], exact_target=target,
    )

    with pytest.raises(ConversationConflict):
        conversation.validate_invocation(
            proposal["id"], challenge["id"], challenge["token"],
            authority=human, response_message_id=ordinary_yes["id"], route="chat",
        )
    with pytest.raises(ConversationAuthorityError):
        conversation.validate_invocation(
            proposal["id"], challenge["id"], challenge["token"],
            authority=imposter, response_message_id=spoofed["id"], route="chat",
        )
    assert conversation.get_command(proposal["id"])["validation_state"] == "challenge_open"


def test_wrong_target_command_token_and_expired_challenge_fail_closed(tmp_path):
    now = [1_000]
    _, work, conversation = subject(tmp_path, clock=lambda: now[0])
    human, model = actor(authority="local_human"), actor("agent")
    target = exact_target("environment")
    message = conversation.add_message(
        work["id"], work["revision"], "환경 적용 제안",
        semantic_origin="command_request", actor=model,
    )
    proposal = conversation.propose_command(
        message["id"], command_kind="environment.activate",
        exact_target=target, structured_args={}, proposer=model,
        required_authority="local_human",
    )
    challenge = conversation.open_challenge(
        proposal["id"], authority=human, ttl_ms=10
    )
    with pytest.raises(ConversationConflict):
        conversation.add_message(
            work["id"], work["revision"], challenge["response_text"],
            semantic_origin="command_request", actor=human,
            optional_command_id=proposal["id"],
            exact_target=exact_target("environment"),
        )
    exact_response = conversation.add_message(
        work["id"], work["revision"], challenge["response_text"],
        semantic_origin="command_request", actor=human,
        optional_command_id=proposal["id"], exact_target=target,
    )

    for command_id, challenge_id, token in [
        (str(uuid4()), challenge["id"], challenge["token"]),
        (proposal["id"], str(uuid4()), challenge["token"]),
        (proposal["id"], challenge["id"], "wrong-token"),
    ]:
        with pytest.raises(ConversationConflict):
            conversation.validate_invocation(
                command_id, challenge_id, token, authority=human,
                response_message_id=exact_response["id"], route="chat",
            )

    now[0] = 1_011
    with pytest.raises(ConversationConflict):
        conversation.validate_invocation(
            proposal["id"], challenge["id"], challenge["token"],
            authority=human, response_message_id=exact_response["id"],
            route="chat",
        )
    assert conversation.get_command(proposal["id"])["validation_state"] == "challenge_open"


def test_work_change_makes_an_unvalidated_proposal_stale(tmp_path):
    store, work, conversation = subject(tmp_path)
    human, model = actor(authority="local_human"), actor("agent")
    target = exact_target("environment")
    message = conversation.add_message(
        work["id"], work["revision"], "현재 업무의 환경 적용 제안",
        semantic_origin="command_request", actor=model,
    )
    proposal = conversation.propose_command(
        message["id"], command_kind="environment.activate",
        exact_target=target, structured_args={}, proposer=model,
        required_authority="local_human",
    )
    store.update_work(work["id"], "업무 조건이 바뀜", work["revision"])

    with pytest.raises(ConversationConflict):
        conversation.open_challenge(proposal["id"], authority=human)
    assert conversation.get_command(proposal["id"])["validation_state"] == "proposed"


def test_message_and_command_limits_reject_malformed_or_mutable_inputs(tmp_path):
    _, work, conversation = subject(tmp_path)
    human, model = actor(), actor("agent")

    with pytest.raises(ValueError):
        conversation.add_message(
            work["id"], work["revision"], "x" * 20_001,
            semantic_origin="clarification", actor=human,
        )
    message = conversation.add_message(
        work["id"], work["revision"], "제안", semantic_origin="command_request",
        actor=model,
    )
    with pytest.raises(ValueError):
        conversation.propose_command(
            message["id"], command_kind="not a command",
            exact_target=ObjectRef("environment", str(uuid4())),
            structured_args={}, proposer=model, required_authority="local_human",
        )
    with pytest.raises(ValueError):
        conversation.propose_command(
            message["id"], command_kind="unknown.material_action",
            exact_target=exact_target("environment"), structured_args={},
            proposer=model, required_authority="local_human",
        )


def _open_button_challenge(store, work, conversation, human):
    model = actor("agent")
    message = conversation.add_message(
        work["id"], work["revision"], "환경 적용 제안",
        semantic_origin="command_request", actor=model,
    )
    proposal = conversation.propose_command(
        message["id"], command_kind="environment.activate",
        exact_target=exact_target("environment"), structured_args={}, proposer=model,
        required_authority="local_human",
    )
    return proposal, conversation.open_challenge(
        proposal["id"], authority=human, ttl_ms=10,
    )


def test_challenge_rejects_the_exact_expiry_instant(tmp_path):
    now = [1_000]
    store, work, conversation = subject(tmp_path, clock=lambda: now[0])
    human = actor(authority="local_human")
    proposal, challenge = _open_button_challenge(
        store, work, conversation, human,
    )
    now[0] = challenge["expires_at_ms"]
    with pytest.raises(ConversationConflict):
        conversation.validate_invocation(
            proposal["id"], challenge["id"], challenge["token"],
            authority=human, response_message_id=None, route="button",
        )


def test_challenge_rejects_clock_rollback_after_service_restart(tmp_path):
    now = [2_000]
    store, work, conversation = subject(tmp_path, clock=lambda: now[0])
    human = actor(authority="local_human")
    proposal, challenge = _open_button_challenge(
        store, work, conversation, human,
    )
    reopened = Conversation(store, clock_ms=lambda: 1_999)
    with pytest.raises(ConversationConflict):
        reopened.validate_invocation(
            proposal["id"], challenge["id"], challenge["token"],
            authority=human, response_message_id=None, route="button",
        )


def test_persisted_unregistered_command_kind_is_not_returned(tmp_path):
    store, work, conversation = subject(tmp_path)
    model = actor("agent")
    message = conversation.add_message(
        work["id"], work["revision"], "환경 적용 제안",
        semantic_origin="command_request", actor=model,
    )
    proposal = conversation.propose_command(
        message["id"], command_kind="environment.activate",
        exact_target=exact_target("environment"), structured_args={}, proposer=model,
        required_authority="local_human",
    )
    with store._connection() as db:
        db.execute(
            "UPDATE conversation_commands SET command_kind=? WHERE id=?",
            ("unknown.still_well_formed", proposal["id"]),
        )

    with pytest.raises(ConversationConflict):
        conversation.get_command(proposal["id"])


def test_command_and_message_work_links_are_rechecked(tmp_path):
    store, work, conversation = subject(tmp_path)
    other = store.create_work("다른 업무")
    human = actor(authority="local_human")
    model = actor("agent")
    message = conversation.add_message(
        work["id"], work["revision"], "환경 적용 제안",
        semantic_origin="command_request", actor=model,
    )
    proposal = conversation.propose_command(
        message["id"], command_kind="environment.activate",
        exact_target=exact_target("environment"), structured_args={}, proposer=model,
        required_authority="local_human",
    )
    with store._connection() as db:
        db.execute(
            "UPDATE conversation_commands SET work_id=? WHERE id=?",
            (other["id"], proposal["id"]),
        )
    with pytest.raises(ConversationConflict):
        conversation.open_challenge(proposal["id"], authority=human)


def test_validation_and_command_work_links_are_rechecked(tmp_path):
    store, work, conversation = subject(tmp_path)
    other = store.create_work("다른 업무")
    human = actor(authority="local_human")
    proposal, challenge = _open_button_challenge(
        store, work, conversation, human,
    )
    receipt = conversation.validate_invocation(
        proposal["id"], challenge["id"], challenge["token"],
        authority=human, response_message_id=None, route="button",
    )
    with store._connection() as db:
        db.execute(
            "UPDATE conversation_validations SET work_id=? WHERE id=?",
            (other["id"], receipt["id"]),
        )
    with pytest.raises(ConversationConflict):
        conversation.list_validations(other["id"])


# =====================================================================================
# The supported factory's shared conversation (`conversations-v1`, T023): messages bound
# to the current revision and exact same-work records, referenced-object commands, and
# owner approval inside the conversation — ambiguous and spoofed approvals refused, with
# nothing changed. The executed command is the same work-model decision the panel's
# button makes. A mock Claude transport; no network, key or paid call.
# =====================================================================================

from contextlib import contextmanager as _contextmanager


@_contextmanager
def supported_conversation(tmp_path):
    from app.tests.test_claude_live_path import connected
    from app.tests.test_work_models import app_with, authored, draft_body, sourced_work
    from app.tests.test_work_models import post as model_post

    _spy, context = app_with(tmp_path, authored())
    with context as subject:
        choice = connected(subject)
        work_ref, sources = sourced_work(subject)
        drafted = model_post(subject, "api/v1/work-models", draft_body(work_ref, choice))
        assert drafted.status_code == 200, drafted.text
        subject.work_ref, subject.sources, subject.model = work_ref, sources, drafted.json()
        subject.service = subject.app.state.first_party_exports["conversations.service"]
        yield subject


def _headers(subject, csrf=True):
    from app.tests.test_web_owner_integration import headers

    return headers(subject.profile, subject.csrf if csrf else None)


def conv_post(subject, suffix, body):
    return subject.client.post(subject.profile.base_path + f"api/v1/conversations/{subject.work_ref.id}/{suffix}",
                               json=body, headers=_headers(subject))


def conv_read(subject):
    response = subject.client.get(subject.profile.base_path + f"api/v1/conversations/{subject.work_ref.id}",
                                  headers=_headers(subject, csrf=False))
    assert response.status_code == 200, response.text
    return response.json()


def model_state(subject):
    response = subject.client.get(subject.profile.base_path + f"api/v1/work-models/{subject.model['work_model_id']}",
                                  headers=_headers(subject, csrf=False))
    return response.json()["state"]


def message_body(subject, text, references=(), *, revision=None, command_id=None):
    return {"schema_version": "conversation-message-command-v1", "command_id": command_id or str(uuid4()),
            "expected_revision": revision or subject.work_ref.version, "text": text, "references": list(references)}


def proposal_body(message_id, target, kind="work_model.confirm"):
    return {"schema_version": "conversation-proposal-command-v1", "command_id": str(uuid4()),
            "message_id": message_id, "command_kind": kind, "target_ref": target}


def approval_body(proposal, challenge, *, route="chat", text=None, token=None, challenge_id=None):
    return {"schema_version": "conversation-approval-command-v1", "command_id": str(uuid4()),
            "proposal_id": proposal["proposal_id"], "challenge_id": challenge_id or challenge["challenge_id"],
            "token": token or challenge["token"], "route": route, "text": text}


def proposed(subject, kind="work_model.confirm"):
    target = subject.model["record_ref"]
    message = conv_post(subject, "messages", message_body(subject, "이 작업 모델을 확정하자", [target]))
    assert message.status_code == 201, message.text
    opened = conv_post(subject, "proposals", proposal_body(message.json()["message"]["message_id"], target, kind))
    assert opened.status_code == 201, opened.text
    return opened.json()["proposal"], opened.json()["challenge"]


def conversation_rows(subject):
    with subject.domain._connection() as db:
        return {kind: db.execute("SELECT count(*) FROM domain_records WHERE kind=?", (kind,)).fetchone()[0]
                for kind in ("chat_message", "proposed_command", "decision_record")}


def test_supported_messages_bind_the_revision_and_exact_same_work_records_and_carry_no_authority(tmp_path):
    with supported_conversation(tmp_path) as subject:
        refs = [subject.work_ref.as_dict(), subject.sources[0], subject.model["record_ref"]]
        body = message_body(subject, "응", refs)
        sent = conv_post(subject, "messages", body)
        assert sent.status_code == 201, sent.text
        message = sent.json()["message"]
        assert message["text"] == "응" and message["semantic_origin"] == "owner_message"
        assert message["actor"] == {"kind": "human", "role": "owner"} and message["references"] == refs
        assert message["work_revision"] == subject.work_ref.version and message["sequence"] == 1
        # an ordinary acknowledgement mints nothing and decides nothing
        assert conv_read(subject)["proposals"] == [] and model_state(subject) == "unconfirmed"
        # exact replay; the same command naming other text is a conflict
        assert conv_post(subject, "messages", body).json()["message"] == message
        assert conv_post(subject, "messages", {**body, "text": "아니"}).status_code == 409
        # the browser never supplies actor, authority or origin: those are not members
        for smuggled in ({"actor": {"kind": "human"}}, {"authority": "local_human"},
                         {"semantic_origin": "command_request"}, {"approved": True}):
            assert conv_post(subject, "messages", {**message_body(subject, "승인"), **smuggled}).status_code == 400
        # references are exact records of this same work
        forged = {**subject.sources[0], "sha256": "0" * 64}
        assert conv_post(subject, "messages", message_body(subject, "x", [forged])).status_code == 409
        other = subject.client.post(subject.profile.base_path + "api/v1/works", headers=_headers(subject), json={
            "schema_version": "work-create-command-v1", "command_id": str(uuid4()), "text": "다른 업무"}).json()
        assert conv_post(subject, "messages", message_body(subject, "x", [other["ref"]])).status_code == 409
        run_kind = {"kind": "run_manifest", "id": str(uuid4()), "version": 1, "sha256": "a" * 64}
        assert conv_post(subject, "messages", message_body(subject, "x", [run_kind])).status_code == 400
        assert conv_post(subject, "messages", message_body(subject, "x", [refs[0], refs[0]])).status_code == 400
        # a message binds the revision the owner saw: a stale one is a conflict
        assert conv_post(subject, "messages", message_body(subject, "x", revision=1)).status_code == 409
        assert conv_post(subject, "messages", message_body(subject, "   ")).status_code == 400
        assert [item["text"] for item in conv_read(subject)["messages"]] == ["응"]


def test_supported_conversation_approval_refuses_ambiguous_and_spoofed_answers_then_runs_once(tmp_path):
    with supported_conversation(tmp_path) as subject:
        proposal, challenge = proposed(subject)
        assert proposal["state"] == "proposed" and proposal["command_kind"] == "work_model.confirm"
        assert challenge["response_text"].startswith("작업 모델 확정 승인 ") and len(challenge["token"]) >= 32
        assert conv_read(subject)["proposals"][0]["challenge"] == {
            key: challenge[key] for key in ("challenge_id", "response_text", "expires_at_ms")}
        before = conversation_rows(subject)
        # ambiguous replies are never approvals
        for reply in ("응", "네", "승인", "확인", "ok", "네 승인합니다", challenge["response_text"] + "!",
                      challenge["response_text"].replace("승인", "거절")):
            refused = conv_post(subject, "approvals", approval_body(proposal, challenge, text=reply))
            assert refused.status_code == 409 and refused.json()["code"] == "approval_ambiguous", reply
            assert refused.json()["reason"] == "approval_ambiguous"
        # the exact phrase posted as an ordinary message is still only a message
        assert conv_post(subject, "messages", message_body(subject, challenge["response_text"])).status_code == 201
        assert conv_read(subject)["proposals"][0]["state"] == "proposed"
        # spoofed: wrong token, another challenge id, a smuggled authority, a button that says words
        exact = challenge["response_text"]
        assert conv_post(subject, "approvals", approval_body(proposal, challenge, text=exact,
                                                             token="A" * 43)).json()["code"] == "conflict"
        assert conv_post(subject, "approvals", approval_body(proposal, challenge, text=exact,
                                                             challenge_id=str(uuid4()))).status_code == 409
        assert conv_post(subject, "approvals", {**approval_body(proposal, challenge, text=exact),
                                                "approved_by": "owner"}).status_code == 400
        assert conv_post(subject, "approvals", approval_body(proposal, challenge, route="button",
                                                             text=exact)).status_code == 400
        assert conv_post(subject, "approvals", approval_body(proposal, challenge, route="agent",
                                                             text=exact)).status_code == 400
        # nothing changed but the one ordinary message
        after = conversation_rows(subject)
        assert after == {**before, "chat_message": before["chat_message"] + 1}
        assert model_state(subject) == "unconfirmed"
        # the exact phrase in the conversation approves, and the shared decision runs once
        body = approval_body(proposal, challenge, text=exact)
        approved = conv_post(subject, "approvals", body)
        assert approved.status_code == 200, approved.text
        done = approved.json()["proposal"]
        assert done["state"] == "executed" and done["approval"]["route"] == "chat"
        assert done["result"]["work_model_state"] == "confirmed" and done["result"]["confirmation_ref"]
        assert model_state(subject) == "confirmed"
        messages = conv_read(subject)["messages"]
        assert messages[-1]["semantic_origin"] == "approval_response" and messages[-1]["text"] == exact
        assert messages[-1]["proposal_id"] == proposal["proposal_id"]
        # replay returns the same receipt; the consumed challenge never approves again
        assert conv_post(subject, "approvals", body).json()["proposal"] == done
        assert conv_post(subject, "approvals", approval_body(proposal, challenge, text=exact)).status_code == 409
        assert conversation_rows(subject)["decision_record"] == before["decision_record"] + 1


def test_supported_button_approval_rejects_through_the_same_decision_and_other_sessions_cannot_answer(tmp_path):
    from app.tests.test_web_owner_integration import headers

    with supported_conversation(tmp_path) as subject:
        proposal, challenge = proposed(subject, "work_model.reject")
        first_cookies = dict(subject.client.cookies)
        subject.client.cookies.clear()
        login =subject.client.post(subject.profile.base_path + "session/login", headers=headers(subject.profile),
                                    json={"login_name": "owner", "password": "synthetic owner passphrase"})
        assert login.status_code == 200, login.text
        other_csrf = login.json()["csrf_token"]
        foreign = subject.client.post(
            subject.profile.base_path + f"api/v1/conversations/{subject.work_ref.id}/approvals",
            json=approval_body(proposal, challenge, route="button"), headers=headers(subject.profile, other_csrf))
        assert foreign.status_code == 409  # a challenge answers only the session it was issued to
        assert model_state(subject) == "unconfirmed"
        subject.client.cookies.clear()
        subject.client.cookies.update(first_cookies)
        approved = conv_post(subject, "approvals", approval_body(proposal, challenge, route="button"))
        assert approved.status_code == 200, approved.text
        assert approved.json()["proposal"]["result"]["work_model_state"] == "rejected"
        assert model_state(subject) == "rejected"


def test_supported_challenges_expire_are_reissued_and_follow_the_current_revision(tmp_path):
    with supported_conversation(tmp_path) as subject:
        proposal, challenge = proposed(subject)
        exact = challenge["response_text"]
        real = subject.service._clock
        subject.service._clock = lambda: real() + 10 * 60 * 1000
        assert conv_post(subject, "approvals", approval_body(proposal, challenge, text=exact)).status_code == 409
        subject.service._clock = real
        reissued = conv_post(subject, "challenges", {"schema_version": "conversation-challenge-command-v1",
                                                     "command_id": str(uuid4()),
                                                     "proposal_id": proposal["proposal_id"]})
        assert reissued.status_code == 200, reissued.text
        fresh = reissued.json()["challenge"]
        assert fresh["token"] != challenge["token"]
        # the earlier challenge was revoked by the reissue
        assert conv_post(subject, "approvals", approval_body(proposal, challenge, text=exact)).status_code == 409
        # the work changes: the proposal was made over a revision that is no longer current
        revised = subject.client.post(subject.profile.base_path + f"api/v1/works/{subject.work_ref.id}/revisions",
                                      headers=_headers(subject), json={
                                          "schema_version": "work-revise-command-v2", "command_id": str(uuid4()),
                                          "expected_revision": subject.work_ref.version, "text": "바뀐 설명"})
        assert revised.status_code == 201, revised.text
        stale = conv_post(subject, "approvals", approval_body(proposal, fresh, text=fresh["response_text"]))
        assert stale.status_code == 409
        assert model_state(subject) == "unconfirmed"


def test_supported_panel_and_conversation_share_one_decision(tmp_path):
    from app.tests.test_work_models import confirm_body
    from app.tests.test_work_models import post as model_post

    with supported_conversation(tmp_path) as subject:
        proposal, challenge = proposed(subject)
        # a proposal over a record the message did not name is refused
        message = conv_post(subject, "messages", message_body(subject, "그냥 메모")).json()["message"]
        assert conv_post(subject, "proposals", proposal_body(message["message_id"],
                                                             subject.model["record_ref"])).status_code == 409
        # one open proposal per target
        again = conv_post(subject, "messages", message_body(subject, "다시", [subject.model["record_ref"]]))
        assert conv_post(subject, "proposals", proposal_body(again.json()["message"]["message_id"],
                                                             subject.model["record_ref"])).status_code == 409
        # the owner decides on the panel first; the conversation's approval cannot decide twice
        decided = model_post(subject, f"api/v1/work-models/{subject.model['work_model_id']}/confirm",
                             confirm_body(subject.model["work_model_ref"], "rejected"))
        assert decided.status_code == 200
        refused = conv_post(subject, "approvals", approval_body(proposal, challenge, text=challenge["response_text"]))
        assert refused.status_code == 409 and model_state(subject) == "rejected"
        assert conv_read(subject)["proposals"][0]["state"] == "proposed"


def test_supported_interrupted_execution_stays_approved_and_resumes_on_the_approvals_replay(tmp_path):
    from app.services.work_models import WorkModelServiceError

    with supported_conversation(tmp_path) as subject:
        proposal, challenge = proposed(subject)
        models = subject.service.work_models
        original = models.confirm
        models.confirm = lambda *args, **kwargs: (_ for _ in ()).throw(WorkModelServiceError("unavailable"))
        body = approval_body(proposal, challenge, text=challenge["response_text"])
        interrupted = conv_post(subject, "approvals", body)
        assert interrupted.status_code == 503
        assert conv_read(subject)["proposals"][0]["state"] == "approved" and model_state(subject) == "unconfirmed"
        models.confirm = original
        resumed = conv_post(subject, "approvals", body)
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["proposal"]["state"] == "executed" and model_state(subject) == "confirmed"
