# commands/base.py
"""Command dispatch registry.

Each command module registers handlers via register().
The main loop calls dispatch() or drain_commands().
"""
from __future__ import annotations

import queue
import shlex
import socket
import threading
from collections import deque
from typing import TYPE_CHECKING, Callable, NamedTuple

if TYPE_CHECKING:
    from net.connection import NetConnection


# ---------------------------------------------------------------------------
# Shared command log buffer (consumed by dashboard SSE)
# ---------------------------------------------------------------------------

_log_buffer: deque[str] = deque(maxlen=200)
_log_lock = threading.Lock()
_log_event = threading.Event()


def cmd_log(msg: str) -> None:
    """Print to stdout and append to the shared log buffer."""
    print(msg)
    with _log_lock:
        _log_buffer.append(msg)
    _log_event.set()


def drain_log_lines() -> list[str]:
    """Pop all buffered lines (called by dashboard SSE endpoint)."""
    with _log_lock:
        lines = list(_log_buffer)
        _log_buffer.clear()
    _log_event.clear()
    return lines


def wait_for_log(timeout: float = 5.0) -> bool:
    """Block until new log lines are available or timeout expires."""
    return _log_event.wait(timeout)


class CommandContext(NamedTuple):
    """Immutable context passed to every command handler"""
    conn: NetConnection
    sock: socket.socket
    server_addr: tuple[str, int]


# Return type: (sent_packet: bool, should_disconnect: bool)
CommandHandler = Callable[[CommandContext, list[str]], tuple[bool, bool]]

_handlers: dict[str, CommandHandler] = {}

TickHandler = Callable[['NetConnection', socket.socket, tuple[str, int]], bool]

_tick_handlers: list[TickHandler] = []


def register(name: str, handler: CommandHandler) -> None:
    """Register a command handler under the given name (case-insensitive)"""
    key = name.strip().lower()
    if not key:
        raise ValueError("Command name cannot be empty")

    existing = _handlers.get(key)
    if existing is None:
        _handlers[key] = handler
        return
    if existing is handler:
        return
    raise ValueError(
        f"Command {key!r} already registered by "
        f"{existing.__module__}.{existing.__name__}"
    )


def register_aliases(names: list[str], handler: CommandHandler) -> None:
    """Register a single handler under multiple names"""
    for name in names:
        register(name, handler)


def register_tick(handler: TickHandler) -> None:
    """Register a tick handler called every event-loop iteration"""
    if handler not in _tick_handlers:
        _tick_handlers.append(handler)


def tick_all(
    conn: 'NetConnection',
    sock: socket.socket,
    server_addr: tuple[str, int],
) -> bool:
    """Run all registered tick handlers. Returns True if any sent a packet"""
    sent = False
    for handler in _tick_handlers:
        if handler(conn, sock, server_addr):
            sent = True
    return sent


def dispatch(ctx: CommandContext, command_line: str) -> tuple[bool, bool]:
    """Parse and execute a single command line"""
    try:
        tokens = shlex.split(command_line)
    except ValueError as exc:
        cmd_log(f"[CMD] Parse error: {exc}")
        return False, False

    if not tokens:
        return False, False

    cmd = tokens[0].lower()
    handler = _handlers.get(cmd)
    if handler is None:
        cmd_log(f"[CMD] Unknown command: {cmd} (type 'help')")
        return False, False

    try:
        return handler(ctx, tokens)
    except Exception as exc:
        cmd_log(f"[CMD] Error: {exc}")
        return False, False


def drain_commands(
    command_queue: queue.Queue[str],
    ctx: CommandContext,
) -> tuple[bool, bool]:
    """Process all pending commands from the queue"""
    sent_any = False
    should_disconnect = False

    while True:
        try:
            line = command_queue.get_nowait()
        except queue.Empty:
            break
        if not line:
            continue
        sent, disconnect = dispatch(ctx, line)
        sent_any = sent_any or sent
        should_disconnect = should_disconnect or disconnect
        if should_disconnect:
            break

    return sent_any, should_disconnect
