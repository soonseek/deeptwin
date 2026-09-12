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
