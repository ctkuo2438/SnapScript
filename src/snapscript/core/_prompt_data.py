"""Encode untrusted data inside tagged provider prompts."""
import json


def serialize_prompt_data(value: object) -> str:
    """Preserve exact values as JSON without allowing tagged sections to close."""
    return json.dumps(value, indent=2, ensure_ascii=False, default=str).replace(
        "<", "\\u003c",
    ).replace(">", "\\u003e")
