"""Testable stopwatch logic for the Study Session Clock add-on."""

from __future__ import annotations

from dataclasses import dataclass


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass
class SessionTimer:
    running: bool = True
    session_seconds: float = 0.0
    active_seconds: float = 0.0
    last_tick: float | None = None

    def begin(self, now: float) -> None:
        self.last_tick = now

    def tick(
        self,
        now: float,
        *,
        reviewing: bool,
        app_active: bool,
        count_background: bool,
    ) -> None:
        if self.last_tick is None:
            self.last_tick = now
            return
        elapsed = max(0.0, now - self.last_tick)
        self.last_tick = now
        if not self.running:
            return
        if count_background or app_active:
            self.session_seconds += elapsed
        # A queued timer can arrive after sleep, a full sync, or a blocked UI.
        # Elapsed stopwatch time remains real; such gaps are not focused study.
        if reviewing and app_active and elapsed <= 5.0:
            self.active_seconds += elapsed

    def pause(self, now: float) -> None:
        self.last_tick = now
        self.running = False

    def resume(self, now: float) -> None:
        self.last_tick = now
        self.running = True

    def reset(self, now: float) -> None:
        self.session_seconds = 0.0
        self.active_seconds = 0.0
        self.last_tick = now
