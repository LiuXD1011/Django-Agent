"""Convert uploaded chat images to reusable context with the configured VLM."""

from personal_knowledge_base import model_providers, observability
from personal_knowledge_base.agent_history import _attachment_summary


def prepare_image_query(message, query: str, tenant) -> str:
    if message is None or not message.images:
        return query

    images = []
    descriptions = []
    prompt = (
        "请识别用户上传的图片，为后续对话提供准确的文字上下文。"
        "逐字转写可读文字，描述主体、颜色、形状和相对位置。"
        "特别关注下面的用户问题；无法辨认时明确说明，不要猜测。\n\n"
        f"用户问题：{query}"
    )
    token = observability.set_llm_call_context(
        session_id=str(message.session_id), request_id=message.request_id,
    )
    try:
        for index, item in enumerate(message.images, start=1):
            image = dict(item) if isinstance(item, dict) else {"url": item}
            if not image.get("url"):
                raise ValueError("上传图片缺少图片地址")
            caption = image.get("caption") or model_providers.vision_completion(
                tenant, image["url"], prompt, "chat_image",
            )
            if not isinstance(caption, str) or not caption.strip():
                raise ValueError("视觉模型未返回图片识别结果")
            image["caption"] = caption.strip()
            images.append(image)
            descriptions.append(f"[图片 {index}]\n{image['caption']}")
    finally:
        observability.reset_llm_call_context(token)

    rendered_query = query + "\n\n[用户上传图片内容]\n" + "\n\n".join(descriptions)
    attachment_text = _attachment_summary(message.attachments or [])
    if attachment_text:
        rendered_query += "\n\n[用户上传附件]\n" + attachment_text
    message.images = images
    message.rendered_content = rendered_query
    message.save(update_fields=["images", "rendered_content", "updated_at"])
    return rendered_query
