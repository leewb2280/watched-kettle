"""Pure lifecycle record normalization without prompt retention."""

import json

from watched_kettle.integrations.codex_hooks import sanitize_pet_event
from watched_kettle.state.event_names import outcome_reason
from datetime import datetime, timezone

MAX_TRACKED_ASYNC_QUESTIONS = 4096


def normalize_codex_log_record(
    record,
    session_id,
    pending_user_calls=None,
    agent_scope="unknown",
    pending_async_questions=None,
    active_turn_id="",
):
    """Map one rollout record without retaining prompt or response content."""
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None

    record_type = record.get("type")
    payload_type = payload.get("type")
    metadata = payload.get("internal_chat_message_metadata_passthrough")
    metadata_turn = metadata.get("turn_id") if isinstance(metadata, dict) else None
    turn_id = payload.get("turn_id") or metadata_turn
    event_id = payload.get("call_id") or payload.get("id")
    event = None

    if record_type == "event_msg":
        event = {
            "task_complete": "ended",
            "context_compacted": "review",
        }.get(payload_type if isinstance(payload_type, str) else "")
        if payload_type == "turn_aborted":
            reason = str(payload.get("reason") or "").strip().lower()
            event = "cancelled" if reason == "interrupted" else "failed"
            detail = payload.get("error")
            code = (
                detail.get("codex_error_info", detail.get("codexErrorInfo"))
                if isinstance(detail, dict)
                else payload.get("codex_error_info")
            )
            if outcome_reason(code) != "unknown":
                event = "failed"
    elif record_type == "response_item":
        if payload_type == "compaction":
            event = "review"
        elif payload_type == "message" and payload.get("role") == "user":
            if pending_async_questions is not None:
                for call_id, (
                    question_turn,
                    pending,
                ) in pending_async_questions.items():
                    if pending and question_turn == (turn_id or active_turn_id):
                        pending_async_questions[call_id] = (question_turn, False)
                        event, event_id = "question_resolved", call_id
                        turn_id = question_turn
                        break
        elif payload_type in {"function_call", "custom_tool_call"}:
            call_id = str(payload.get("call_id") or "")
            if (
                payload.get("name") == "request_user_input_async"
                and pending_async_questions is not None
                and call_id
            ):
                if len(pending_async_questions) >= MAX_TRACKED_ASYNC_QUESTIONS:
                    for old_call, (_, pending) in tuple(
                        pending_async_questions.items()
                    ):
                        if not pending:
                            pending_async_questions.pop(old_call)
                        if len(pending_async_questions) < MAX_TRACKED_ASYNC_QUESTIONS:
                            break
                if len(pending_async_questions) < MAX_TRACKED_ASYNC_QUESTIONS:
                    turn_id = turn_id or active_turn_id
                    pending_async_questions[call_id] = (turn_id, True)
                    event = "question_wait"
                else:
                    event = "tool_start"
            elif payload.get("name") == "request_user_input":
                event = "waiting"
                if pending_user_calls is not None and call_id:
                    pending_user_calls.add(call_id)
            else:
                event = "tool_start"
        elif payload_type in {
            "function_call_output",
            "custom_tool_call_output",
        }:
            call_id = str(payload.get("call_id") or "")
            if (
                pending_async_questions is not None
                and call_id in pending_async_questions
            ):
                question_turn, pending = pending_async_questions[call_id]
                try:
                    result = json.loads(payload.get("output") or "")
                except (TypeError, ValueError):
                    result = None
                if pending and not (
                    isinstance(result, dict) and result.get("accepted") is True
                ):
                    pending_async_questions[call_id] = (question_turn, False)
                    event = "question_resolved"
                    turn_id = question_turn
            elif pending_user_calls is not None and call_id in pending_user_calls:
                pending_user_calls.discard(call_id)
                event = "tool_end"
            else:
                event = "tool_end"

    if event is None:
        return None

    normalized = {
        "source": "codex",
        "event": event,
        "session_id": session_id,
        "agent_scope": agent_scope,
    }
    if payload_type == "turn_aborted":
        normalized["outcome_reason"] = outcome_reason(code)
    if event == "review" and payload_type in {"context_compacted", "compaction"}:
        normalized["compaction_phase"] = "end"
    if event in {
        "review",
        "tool_start",
        "tool_end",
        "waiting",
        "question_wait",
        "question_resolved",
    }:
        try:
            stamp = datetime.fromisoformat(
                str(record.get("timestamp", "")).replace("Z", "+00:00")
            )
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            normalized["collected_at"] = stamp.timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    if event == "tool_start":
        normalized["tool_status"] = "started"
    elif event == "tool_end":
        normalized["tool_status"] = "succeeded"
        normalized["success"] = True
    elif event == "waiting":
        normalized["tool_status"] = "waiting"
    elif event == "question_wait":
        normalized["tool_status"] = "waiting"

    if turn_id:
        normalized["turn_id"] = turn_id
    if event_id:
        normalized["event_id"] = event_id
    return sanitize_pet_event(normalized)
