from typing import Protocol


class BackgroundJob(Protocol):
    """Small contract that can later be hosted by a durable worker."""

    def run(self) -> int: ...
