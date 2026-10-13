from django.utils import timezone

from .db_retry import retry_on_db_lock
from .models import Message


GENERATION_FAILED_MESSAGE = "生成失败"
# continue-stream 等待超时/流未注册（生成线程已中断）时的明确提示
GENERATION_TIMEOUT_MESSAGE = "生成超时或已中断，请重新发送消息"


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

    def _update():
        return Message.objects.filter(id=message_id, is_completed=False).update(
            content=text,
            rendered_content=text,
            is_completed=True,
            updated_at=timezone.now(),
        )

    return bool(retry_on_db_lock(_update))


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
    def _update():
        return Message.objects.filter(id=message_id, is_completed=False).update(
            content=content,
            rendered_content=content,
            knowledge_references=refs,
            agent_steps=steps,
            agent_duration_ms=duration_ms,
            is_completed=True,
            updated_at=timezone.now(),
        )

    return bool(retry_on_db_lock(_update))
