from dataclasses import dataclass
from typing import ClassVar, Self
from uuid import UUID, uuid4


@dataclass(frozen=True)
class TypedId:
    value: str
    prefix: ClassVar[str] = "id"

    def __post_init__(self) -> None:
        prefix, separator, value = self.value.partition("_")
        if not separator or prefix != self.prefix:
            raise ValueError(f"Expected {self.prefix} identifier")
        parsed = UUID(value)
        if parsed.version != 4 or parsed.hex != value:
            raise ValueError("Expected canonical UUID4 identifier")

    @classmethod
    def new(cls) -> Self:
        return cls(f"{cls.prefix}_{uuid4().hex}")

    def __str__(self) -> str:
        return self.value


class UserId(TypedId):
    prefix = "usr"


class CommandRequestId(TypedId):
    prefix = "cmd"


class RepositoryId(TypedId):
    prefix = "repo"


class RepositoryRootId(TypedId):
    prefix = "root"


class RequestIntentId(TypedId):
    prefix = "intent"


class PatchId(TypedId):
    prefix = "patch"


class VerificationResultId(TypedId):
    prefix = "result"


class VerificationBasisId(TypedId):
    prefix = "basis"


class ApprovalBindingId(TypedId):
    prefix = "approval"


class ArtifactId(TypedId):
    prefix = "artifact"


class GraphSnapshotId(TypedId):
    prefix = "graph"


class AuditEventId(TypedId):
    prefix = "event"


@dataclass(frozen=True, order=True)
class PatchRevision:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise ValueError("Patch revision must be a positive integer")
