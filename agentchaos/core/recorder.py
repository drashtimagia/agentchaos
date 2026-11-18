"""Streaming JSONL trace writer and reader.

One file per invocation; records from concurrent runs interleave and are keyed
by ``run_id``. Every record is written and flushed as it happens, so a crashed
or interrupted benchmark still leaves a usable trace.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO

from pydantic import BaseModel, TypeAdapter

from agentchaos.core.models import (
    FaultEvent,
    FaultRecord,
    OutcomeRecord,
    RunStart,
    ToolCall,
    ToolCallRecord,
    TraceRecord,
)
from agentchaos.core.policy import Sink

_adapter: TypeAdapter[TraceRecord] = TypeAdapter(TraceRecord)


class Recorder:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: IO[str] = self.path.open("a", encoding="utf-8")

    def write(self, record: BaseModel) -> None:
        self._file.write(record.model_dump_json() + "\n")
        self._file.flush()

    def sink(self, run_id: str) -> Sink:
        """An injector sink that writes that run's calls and fault events."""

        def write(item: ToolCall | FaultEvent) -> None:
            if isinstance(item, ToolCall):
                self.write(ToolCallRecord(run_id=run_id, **item.model_dump()))
            else:
                self.write(FaultRecord(run_id=run_id, **item.model_dump()))

        return write

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> Recorder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_trace(path: str | Path) -> Iterator[TraceRecord]:
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield _adapter.validate_json(line)


class RecordedRun(BaseModel):
    start: RunStart
    calls: list[ToolCallRecord]
    faults: list[FaultRecord]
    outcome: OutcomeRecord | None


def find_run(run_id: str, paths: Iterable[str | Path]) -> RecordedRun:
    """Collect one run's records from trace files. Raises ``KeyError`` if absent."""
    for path in paths:
        records = [r for r in read_trace(path) if r.run_id == run_id]
        starts = [r for r in records if isinstance(r, RunStart)]
        if starts:
            outcomes = [r for r in records if isinstance(r, OutcomeRecord)]
            return RecordedRun(
                start=starts[0],
                calls=[r for r in records if isinstance(r, ToolCallRecord)],
                faults=[r for r in records if isinstance(r, FaultRecord)],
                outcome=outcomes[0] if outcomes else None,
            )
    raise KeyError(f"run '{run_id}' not found")
