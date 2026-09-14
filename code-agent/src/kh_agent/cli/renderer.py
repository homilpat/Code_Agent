import json
from typing import Any


def render(value: Any) -> str:
    # ASCII JSON escapes ESC/C0/C1, bidi controls, surrogates and Unicode line separators.
    # Never pass source strings through Rich markup, ANSI interpretation or a pager.
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2)
