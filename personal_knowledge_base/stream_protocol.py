from django.utils import timezone

from .models import Message


GENERATION_FAILED_MESSAGE = "生成失败"


def tool_stream_payload(response_type, assistant_message_id, event_data):
    payload = {
        "response_type": response_type,
        "assistant_message_id": assistant_message_id,
        "tool_call_id": event_data.get("tool_call_id", ""),
        "name": event_data.get("name", ""),
        "iteration": event_data.get("iteration", 0),
    }
    if response_type == "tool_call":
        payload["arguments"] = event_data.get("arguments", {})
    else:
        payload.update(
            {
                "output": event_data.get("output", ""),
                "error": event_data.get("error", ""),
                "duration_ms": event_data.get("duration_ms", 0),
            }
        )
    return payload


def complete_message_with_error(message_id, content=GENERATION_FAILED_MESSAGE):
    text = str(content or GENERATION_FAILED_MESSAGE)
    return bool(
        Message.objects.filter(id=message_id, is_completed=False).update(
            content=text,
            rendered_content=text,
            is_completed=True,
            updated_at=timezone.now(),
        )
    )


def terminal_error_payload(message_id, content=GENERATION_FAILED_MESSAGE):
    text = str(content or GENERATION_FAILED_MESSAGE)
    if complete_message_with_error(message_id, text):
        return {
            "response_type": "error",
            "assistant_message_id": message_id,
            "content": text,
            "done": True,
        }

    message = Message.objects.filter(id=message_id, is_completed=True).first()
    if message:
        from .serializers import message_dict

        return message_dict(message)
    return {
        "response_type": "error",
        "assistant_message_id": message_id,
        "content": text,
        "done": True,
    }


def complete_message_with_result(message_id, content, refs, steps, duration_ms):
    return bool(
        Message.objects.filter(id=message_id, is_completed=False).update(
            content=content,
            rendered_content=content,
            knowledge_references=refs,
            agent_steps=steps,
            agent_duration_ms=duration_ms,
            is_completed=True,
            updated_at=timezone.now(),
        )
    )
