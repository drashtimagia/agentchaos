"""Fake file system holding a few config files."""

from __future__ import annotations

import copy
from typing import Any

from agentchaos.scenarios.base import FakeServer, ToolSpec, obj

FILES = {
    "config/app.yaml": "name: shop\nversion: 1.4.2\nport: 8080\n",
    "config/worker.yaml": "queue: orders\nversion: 1.4.2\nconcurrency: 4\n",
    "config/cron.yaml": "schedule: '*/5 * * * *'\nversion: 1.4.2\n",
}


class FilesServer(FakeServer):
    def __init__(self) -> None:
        self.files = dict(FILES)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy({"files": self.files})

    def list_files(self) -> list[str]:
        return sorted(self.files)

    def read_file(self, path: str) -> dict:
        if path not in self.files:
            raise ValueError(f"no such file: {path}")
        return {"path": path, "content": self.files[path]}

    def write_file(self, path: str, content: str) -> dict:
        if path not in self.files:
            raise ValueError(f"no such file: {path}")
        self.files[path] = content
        return {"path": path, "bytes": len(content.encode())}

    def tools(self) -> list[ToolSpec]:
        string = {"type": "string"}
        return [
            ToolSpec("list_files", "List all file paths.", obj({}), self.list_files),
            ToolSpec("read_file", "Read a file.", obj({"path": string}, ["path"]), self.read_file),
            ToolSpec(
                "write_file",
                "Replace a file's entire content.",
                obj({"path": string, "content": string}, ["path", "content"]),
                self.write_file,
            ),
        ]
