import json
from collections.abc import Mapping

from .document_processing import normalized_chunking_config


PROCESS_CONFIG_KEYS = ("process_config", "processConfig")
SUPPORTED_PARSER_ENGINES = frozenset({"", "builtin", "plain"})


class InvalidProcessConfig(ValueError):
    pass


def _validate_process_config(value, knowledge_base_config) -> dict:
    if not isinstance(value, Mapping):
        raise InvalidProcessConfig("process configuration must be a JSON object")
    config = dict(value)
    parser_engine = config.get("parser_engine", "")
    if not isinstance(parser_engine, str) or parser_engine not in SUPPORTED_PARSER_ENGINES:
        raise InvalidProcessConfig("unsupported parser engine")
    for key in ("chunking_config", "chunkingConfig"):
        if key in config and not isinstance(config[key], Mapping):
            raise InvalidProcessConfig("chunking override must be a JSON object")
    try:
        normalized_chunking_config(knowledge_base_config, config)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidProcessConfig("invalid chunking override") from exc
    return config


def parse_multipart_process_config(post_data, knowledge_base_config) -> dict:
    raw = None
    present = False
    for key in PROCESS_CONFIG_KEYS:
        if key in post_data:
            raw = post_data.get(key)
            present = True
            break
    if not present:
        return {}
    if not isinstance(raw, str):
        raise InvalidProcessConfig("process configuration must be encoded JSON")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidProcessConfig("process configuration is malformed JSON") from exc
    return _validate_process_config(value, knowledge_base_config)


def parse_json_reparse_request(request, knowledge_base_config) -> tuple[dict, dict | None]:
    if not request.body:
        data = {}
    else:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidProcessConfig("request body is malformed JSON") from exc
    if not isinstance(data, Mapping):
        raise InvalidProcessConfig("request body must be a JSON object")
    data = dict(data)
    for key in PROCESS_CONFIG_KEYS:
        if key in data:
            return data, _validate_process_config(data[key], knowledge_base_config)
    return data, None
