"""Reading uploaded models: in arrival order, a few at a time, each IFC in its own process.

Reading a model takes about 20x its file size in memory. The queue caps how many reads run at once
(Settings.geom_jobs); everyone else waits in line and can see their place (ReadQueue.status). Each
IFC is read in a child process, so a model too heavy for the server ends that process only, never
the server or anyone else's check.

One geometry pass per upload: the child reads the model, builds the viewer mesh and the project
thumbnail from the same pass, and stores the IFC and the mesh gzip-compressed (lossless).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import multiprocessing
import shutil
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

# Files the child leaves next to the uploaded IFC (see store_outputs).
IFC_GZ, MESH_GZ, THUMB, META = "model.ifc.gz", "mesh.json.gz", "thumb.png", "meta.json"


class Busy(Exception):
    """The line is full, or this project already has a model being read."""


class ReadFailed(Exception):
    """The file couldn't be read (or needed more memory than the server has)."""


@dataclass
class Ticket:
    key: str
    pct: float = 0.0
    msg: str | None = None


class ReadQueue:
    """First come, first served, `slots` at a time; at most `max_waiting` in line."""

    def __init__(self, slots: int, max_waiting: int = 10) -> None:
        self.slots = max(1, slots)
        self.max_waiting = max_waiting
        self._line: deque[Ticket] = deque()
        self._running: list[Ticket] = []
        self._cond: asyncio.Condition | None = None
        # Reads that outlive their upload request: per project, the task and how it ended.
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.outcomes: dict[str, dict[str, Any]] = {}

    def status(self, key: str) -> dict[str, Any] | None:
        """Where this project's read is: in line (and how many are ahead), how far along, or
        how it ended ({state: done, result} or {state: failed, status, detail})."""
        for t in self._running:
            if t.key == key:
                return {"state": "reading", "pct": round(t.pct), "msg": t.msg}
        for i, t in enumerate(self._line):
            if t.key == key:
                return {"state": "queued", "ahead": i, "reading": len(self._running)}
        return self.outcomes.get(key)

    async def run(self, key: str, job: Callable[[Ticket], Awaitable[T]]) -> T:
        if self._cond is None:
            self._cond = asyncio.Condition()
        if any(t.key == key for t in (*self._line, *self._running)):
            raise Busy("A model for this project is already being read.")
        if len(self._line) >= self.max_waiting:
            raise Busy("The server is busy reading other models. Try again in a few minutes.")
        ticket = Ticket(key)
        async with self._cond:
            self._line.append(ticket)
            try:
                await self._cond.wait_for(
                    lambda: self._line[0] is ticket and len(self._running) < self.slots
                )
            except BaseException:
                self._line.remove(ticket)
                self._cond.notify_all()
                raise
            self._line.popleft()
            self._running.append(ticket)
            self._cond.notify_all()  # the next in line may fit too
        try:
            return await job(ticket)
        finally:
            async with self._cond:
                self._running.remove(ticket)
                self._cond.notify_all()


# ------------------------------------------------------------------ the child process


def _child(src: str, out: str, conn: Any) -> None:
    """Runs in a fresh process: read the IFC once, write the outputs, send the model back."""
    try:
        import ifcopenshell

        from compliance.adapters import ifc as ifc_adapter
        from compliance.adapters import mesh
        from compliance.thumbnail import mesh_png

        def say(pct: float, msg: str) -> None:
            conn.send(("progress", pct, msg))

        say(2, "opening the file")
        f = ifcopenshell.open(src)
        say(5, "reading the geometry")
        shapes = mesh.tessellate(f, progress=lambda p: say(5 + p * 0.75, "reading the geometry"))
        say(80, "reading floors, rooms, doors and stairs")
        model, warnings = ifc_adapter.read(src, ifc=f, shapes=shapes)
        say(90, "preparing the 3D view")
        view = mesh.mesh_from(f, shapes)
        del shapes
        folder = Path(out)
        with gzip.open(folder / MESH_GZ, "wt", encoding="utf-8", compresslevel=6) as fh:
            json.dump(view, fh, separators=(",", ":"))
        try:
            (folder / THUMB).write_bytes(mesh_png(view))
        except Exception:  # noqa: BLE001 - a missing thumbnail is only cosmetic
            pass
        try:
            north = ifc_adapter.north_deg(src, f)
        except Exception:  # noqa: BLE001 - an unreadable north is just not known
            north = None
        (folder / META).write_text(json.dumps({"north_deg": north}), encoding="utf-8")
        with open(src, "rb") as raw, gzip.open(folder / IFC_GZ, "wb", compresslevel=6) as gz:
            shutil.copyfileobj(raw, gz)
        conn.send(("done", model, warnings))
    except Exception as e:  # noqa: BLE001 - any parser failure is the file's problem
        conn.send(("error", str(e) or e.__class__.__name__, None))
    finally:
        conn.close()


def _mesh_child(src_gz: str, out: str, conn: Any) -> None:
    """Runs in a fresh process: rebuild the viewer mesh of a stored IFC (older uploads)."""
    try:
        import tempfile

        from compliance.adapters import mesh

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "model.ifc"
            with gzip.open(src_gz, "rb") as gz, open(src, "wb") as raw:
                shutil.copyfileobj(gz, raw)
            view = mesh.ifc_to_mesh(src)
        with gzip.open(Path(out) / MESH_GZ, "wt", encoding="utf-8", compresslevel=6) as fh:
            json.dump(view, fh, separators=(",", ":"))
        conn.send(("done", None, None))
    except Exception as e:  # noqa: BLE001
        conn.send(("error", str(e) or e.__class__.__name__, None))
    finally:
        conn.close()


async def _in_child(target: Callable[..., None], args: tuple, ticket: Ticket) -> tuple[Any, Any]:
    """Run target in a child process, passing its progress to the ticket."""
    ctx = multiprocessing.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=target, args=(*args, send), daemon=True)
    proc.start()
    send.close()  # the child holds the only writing end now
    try:
        while True:
            ready = await asyncio.to_thread(recv.poll, 0.5)
            if ready:
                try:
                    kind, a, b = recv.recv()
                except EOFError:
                    break
                if kind == "progress":
                    ticket.pct, ticket.msg = a, b
                elif kind == "done":
                    return a, b
                else:
                    raise ReadFailed(f"Couldn't read this IFC file: {a}")
            elif not proc.is_alive():
                break
        await asyncio.to_thread(proc.join, 5)
        if proc.exitcode and proc.exitcode < 0:  # killed: almost always out of memory
            raise ReadFailed(
                "This model needed more memory than the server has. Export only the "
                "building (no linked models, furniture or site context), or check it in Revit "
                "with the add-in."
            )
        raise ReadFailed("Reading the model stopped unexpectedly. Please try again.")
    finally:
        recv.close()
        if proc.is_alive():
            proc.kill()
        await asyncio.to_thread(proc.join, 5)


async def read_ifc(src: Path, out: Path, ticket: Ticket) -> tuple[dict[str, Any], list[str]]:
    """Read an uploaded IFC in a child process; outputs land in `out` (see the names above)."""
    out.mkdir(parents=True, exist_ok=True)
    return await _in_child(_child, (str(src), str(out)), ticket)


async def build_mesh(src_gz: Path, out: Path, ticket: Ticket) -> None:
    await _in_child(_mesh_child, (str(src_gz), str(out)), ticket)
