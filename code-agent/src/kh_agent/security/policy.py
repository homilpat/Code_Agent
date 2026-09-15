import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from kh_agent.analysis.risk import FactorRule, RiskPolicy
from kh_agent.core.canonical import canonical_hash
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.security.ingestion import IngestionPolicy
from kh_agent.security.linux_fs import open_no_alias


class _StrictLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if type(key) is not str or key in mapping:
            raise ValueError("Policy keys must be unique strings")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


@dataclass(frozen=True)
class TrustedPolicy:
    version: str
    content_hash: str
    ingestion: IngestionPolicy
    risk: RiskPolicy


def _keys(value: dict, expected: set[str]) -> None:
    if type(value) is not dict or value.keys() != expected:
        raise ValueError("Policy has missing or unknown fields")


def parse_policy(data: bytes) -> TrustedPolicy:
    """Parse bounded declarative data only. No aliases, tags, duplicate/unknown keys."""
    if len(data) > 65536:
        raise DomainError(ErrorCode.INVALID_INPUT, "Policy exceeds size limit")
    try:
        depth = 0
        for count, token in enumerate(yaml.scan(data)):
            if count > 10000 or isinstance(
                token, (yaml.AliasToken, yaml.AnchorToken, yaml.TagToken)
            ):
                raise ValueError("Unsafe YAML feature or token limit")
            if isinstance(
                token,
                (
                    yaml.BlockMappingStartToken,
                    yaml.BlockSequenceStartToken,
                    yaml.FlowMappingStartToken,
                    yaml.FlowSequenceStartToken,
                ),
            ):
                depth += 1
            elif isinstance(
                token, (yaml.BlockEndToken, yaml.FlowMappingEndToken, yaml.FlowSequenceEndToken)
            ):
                depth -= 1
            if depth > 20:
                raise ValueError("Policy depth limit")
        value = yaml.load(data, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
        _keys(value, {"schema_version", "version", "ingestion", "risk"})
        if (
            value["schema_version"] != "security-policy-v1"
            or type(value["version"]) is not str
            or not 1 <= len(value["version"]) <= 100
        ):
            raise ValueError("Unsupported policy schema")
        ingestion = value["ingestion"]
        _keys(
            ingestion,
            {
                "version",
                "excluded_directories",
                "max_entries",
                "max_file_bytes",
                "max_total_bytes",
                "max_depth",
                "max_seconds",
            },
        )
        if (
            type(ingestion["version"]) is not str
            or type(ingestion["excluded_directories"]) is not list
            or any(
                type(item) is not str or "/" in item or "\\" in item or not item
                for item in ingestion["excluded_directories"]
            )
        ):
            raise ValueError("Invalid ingestion fields")
        for field, ceiling in (
            ("max_entries", 100000),
            ("max_file_bytes", 262144),
            ("max_total_bytes", 67108864),
            ("max_depth", 64),
            ("max_seconds", 60),
        ):
            if type(ingestion[field]) is not int or not 1 <= ingestion[field] <= ceiling:
                raise ValueError("Unsafe ingestion resource ceiling")
        # Mandatory security boundaries cannot be removed by an ingestion tuning policy.
        exclusions = frozenset(ingestion["excluded_directories"]) | {".git", ".knowledge-hub"}
        ingestion_policy = IngestionPolicy(**{**ingestion, "excluded_directories": exclusions})
        risk = value["risk"]
        _keys(risk, {"rule_version", "threshold_version", "medium_at", "high_at", "factors"})
        if (
            type(risk["factors"]) is not list
            or len(risk["factors"]) > 30
            or type(risk["rule_version"]) is not str
            or type(risk["threshold_version"]) is not str
        ):
            raise ValueError("Invalid risk policy")
        rules = []
        for factor in risk["factors"]:
            _keys(factor, {"name", "weight", "normalization", "count_cap"})
            if type(factor["name"]) is not str or type(factor["normalization"]) is not str:
                raise ValueError("Invalid risk factor")
            rules.append(FactorRule(**factor))
        risk_policy = RiskPolicy(**{**risk, "factors": tuple(rules)})
        digest = canonical_hash(value, "security-policy-v1").digest
        return TrustedPolicy(value["version"], digest, ingestion_policy, risk_policy)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise DomainError(ErrorCode.INVALID_INPUT, "Invalid trusted policy document") from exc


def load_policy(trusted_root: Path, repository_roots: tuple[Path, ...]) -> TrustedPolicy:
    """Read only the fixed owner-private policy under the external trusted store."""
    if sys.platform != "linux":
        raise DomainError(ErrorCode.UNSUPPORTED_PLATFORM)
    root = trusted_root.resolve(strict=True)
    # A deleted or moved registration cannot contain the store, so it must not block loading.
    existing = tuple(repo.resolve() for repo in repository_roots if repo.exists())
    if any(root.is_relative_to(repo) for repo in existing):
        raise DomainError(ErrorCode.ACCESS_DENIED, "Repository files cannot be policy authority")
    path = trusted_root.absolute() / "policy" / "security.yaml"
    fd = open_no_alias(os.fsencode(path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 65536
        ):
            raise DomainError(ErrorCode.ACCESS_DENIED, "Policy must be a private regular file")
        data = stream.read(65537)
    return parse_policy(data)
