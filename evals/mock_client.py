"""Fake Anthropic client for the mocked suite and `run_cases.py --mock`.

It mimics the surface TriageService uses: `await client.messages.create(**kwargs)` returning
an object with `.content` (tool_use block), `.usage`, `.stop_reason`, `.model`. Each call is
recorded in `client.calls`. Outputs are chosen by matching the operator text in the last
user turn against the golden cases; `queue_output()` / `queue_error()` override the next call.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

HERE = Path(__file__).resolve().parent
GOLDEN_CASES = HERE / "golden" / "cases.json"
MOCK_OUTPUTS = HERE / "mock_outputs.json"


def load_cases(path: Path | str = GOLDEN_CASES) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_mock_outputs(path: Path | str = MOCK_OUTPUTS) -> dict[str, dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


class FakeAnthropic:
    def __init__(
        self,
        outputs: dict[str, dict[str, Any]] | None = None,
        cases: list[dict[str, Any]] | None = None,
        *,
        model: str = "fake-model",
        usage: tuple[int, int] = (900, 180),
    ) -> None:
        self.outputs = outputs if outputs is not None else load_mock_outputs()
        self.cases = cases if cases is not None else load_cases()
        self.max_retries = 0
        self.timeout = 20.0
        self.model = model
        self.usage = usage
        self.calls: list[dict[str, Any]] = []
        self._queue: list[Any] = []
        self.messages = _Messages(self)

    # -- scripting ------------------------------------------------------------------
    def queue_output(self, raw: dict[str, Any] | None, *, stop_reason: str = "tool_use") -> None:
        """Next call returns this raw tool input (None -> a response with no tool_use block)."""
        self._queue.append(("output", raw, stop_reason))

    def queue_error(self, exc: BaseException) -> None:
        self._queue.append(("error", exc, None))

    # -- selection ------------------------------------------------------------------
    def case_for(self, messages: list[dict[str, str]]) -> str | None:
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        for case in self.cases:
            if case["request"]["text"] in last_user:
                return case["id"]
        return None

    def respond(self, kwargs: dict[str, Any]) -> Any:
        self.calls.append(kwargs)
        if self._queue:
            kind, payload, stop_reason = self._queue.pop(0)
            if kind == "error":
                raise payload
            return self._response(payload, stop_reason)
        case_id = self.case_for(kwargs.get("messages", []))
        if case_id is None or case_id not in self.outputs:
            raise LookupError("no canned output for this operator text")
        return self._response(json.loads(json.dumps(self.outputs[case_id])), "tool_use")

    def _response(self, raw: dict[str, Any] | None, stop_reason: str) -> Any:
        content: list[Any] = []
        if raw is not None:
            content.append(
                SimpleNamespace(type="tool_use", id="toolu_fake", name="propose_draft", input=raw)
            )
        return SimpleNamespace(
            id="msg_fake",
            model=self.model,
            stop_reason=stop_reason,
            content=content,
            usage=SimpleNamespace(input_tokens=self.usage[0], output_tokens=self.usage[1]),
        )


class _Messages:
    def __init__(self, parent: FakeAnthropic) -> None:
        self._parent = parent

    async def create(self, **kwargs: Any) -> Any:
        return self._parent.respond(kwargs)
