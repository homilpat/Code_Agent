"""SEARCH/REPLACE edit blocks: the only change format accepted from a model.

The harness, not the model, writes files. Each SEARCH section must match the current file exactly
once, and a reply is applied all-or-nothing, so a stale or ambiguous edit fails loudly instead of
changing the wrong place.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SEARCH = "<<<<<<< SEARCH"
DIVIDER = "======="
REPLACE = ">>>>>>> REPLACE"


@dataclass(frozen=True)
class Edit:
    path: str
    search: str
    replace: str


class EditError(Exception):
    """Model-facing failure. ``category`` is FORMAT_ERROR or APPLY_ERROR."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


def parse_edits(text: str) -> list[Edit]:
    lines = text.replace("\r\n", "\n").split("\n")
    edits = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != SEARCH:
            index += 1
            continue
        path = _path_before(lines, index)
        search, index = _section(lines, index + 1, DIVIDER)
        replace, index = _section(lines, index + 1, REPLACE)
        edits.append(Edit(path, search, replace))
        index += 1
    if not edits:
        raise EditError("FORMAT_ERROR", "No SEARCH/REPLACE blocks were found in the reply.")
    return edits


def apply_edits(project: Path, edits: list[Edit]) -> dict[str, str | None]:
    """Apply every edit or none. Returns each changed file's previous content (None if new)."""
    updated: dict[str, str] = {}
    for edit in edits:
        relative = _relative_path(project, edit.path)
        content = updated[relative] if relative in updated else _read(project / relative)
        if not edit.search:
            if content is not None:
                raise EditError(
                    "APPLY_ERROR", f"{relative}: an empty SEARCH creates a file, but it exists."
                )
            updated[relative] = edit.replace
            continue
        if content is None:
            raise EditError("APPLY_ERROR", f"{relative}: file does not exist.")
        count = content.count(edit.search)
        if count != 1:
            problem = "did not match" if count == 0 else f"matched {count} times"
            raise EditError(
                "APPLY_ERROR",
                f"{relative}: SEARCH section {problem}. Copy the current lines exactly and "
                "include enough unchanged lines to make the match unique.",
            )
        updated[relative] = content.replace(edit.search, edit.replace, 1)
    previous = {}
    for relative, content in updated.items():
        path = project / relative
        previous[relative] = _read(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
    return previous


def _path_before(lines: list[str], index: int) -> str:
    for line in reversed(lines[:index]):
        candidate = line.strip()
        if not candidate or candidate.startswith("```"):
            continue
        return candidate.strip("`*# ")
    raise EditError("FORMAT_ERROR", "A SEARCH block has no file path on the line above it.")


def _section(lines: list[str], start: int, marker: str) -> tuple[str, int]:
    for end in range(start, len(lines)):
        if lines[end].strip() == marker:
            body = lines[start:end]
            return ("\n".join(body) + "\n") if body else "", end
    raise EditError("FORMAT_ERROR", f"A block is missing its '{marker}' line.")


def _relative_path(project: Path, raw: str) -> str:
    candidate = PurePosixPath(raw.replace("\\", "/"))
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or ":" in raw
        or not (project / candidate).resolve().is_relative_to(project.resolve())
    ):
        raise EditError("APPLY_ERROR", f"{raw}: path must be relative to the project root.")
    return candidate.as_posix()


def _read(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise EditError("APPLY_ERROR", f"{path.name}: cannot read file ({exc}).") from exc
