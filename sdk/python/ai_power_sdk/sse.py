import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SSEEvent:
    event: str
    data: str

    def json(self) -> dict[str, Any]:
        if not self.data:
            return {}
        parsed = json.loads(self.data)
        return parsed if isinstance(parsed, dict) else {"data": parsed}


def iter_sse(lines: Iterable[str]) -> Iterator[SSEEvent]:
    event = "message"
    data: list[str] = []
    for line in lines:
        if line == "":
            if data:
                yield SSEEvent(event=event, data="\n".join(data))
            event = "message"
            data = []
        elif line.startswith("event:"):
            event = line[6:].strip() or "message"
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield SSEEvent(event=event, data="\n".join(data))
