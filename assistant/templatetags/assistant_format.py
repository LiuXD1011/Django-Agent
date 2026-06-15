import re
import json

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe


register = template.Library()


def _inline_markdown(text):
    escaped = escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


@register.filter
def assistant_markdown(value):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return ""

    html = []
    list_type = None

    def close_list():
        nonlocal list_type
        if list_type:
            html.append(f"</{list_type}>")
            list_type = None

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            close_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        ordered = re.match(r"^(\d+)[.)]\s+(.+)$", line)
        unordered = re.match(r"^[-*]\s+(.+)$", line)
        if heading:
            close_list()
            level = min(len(heading.group(1)) + 2, 6)
            html.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
            continue
        if ordered:
            if list_type != "ol":
                close_list()
                html.append("<ol>")
                list_type = "ol"
            html.append(f"<li>{_inline_markdown(ordered.group(2))}</li>")
            continue
        if unordered:
            if list_type != "ul":
                close_list()
                html.append("<ul>")
                list_type = "ul"
            html.append(f"<li>{_inline_markdown(unordered.group(1))}</li>")
            continue

        close_list()
        html.append(f"<p>{_inline_markdown(line)}</p>")

    close_list()
    return mark_safe("".join(html))


@register.filter
def json_pretty(value):
    try:
        return json.dumps(value or {}, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return str(value)
