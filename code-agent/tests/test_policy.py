import pytest

from kh_agent.core.errors import DomainError
from kh_agent.security.policy import parse_policy

POLICY = b"""
schema_version: security-policy-v1
version: local-test-v1
ingestion:
  version: ingestion-test-v1
  excluded_directories: [node_modules, .venv]
  max_entries: 1000
  max_file_bytes: 262144
  max_total_bytes: 1048576
  max_depth: 20
  max_seconds: 10
risk:
  rule_version: risk-test-v1
  threshold_version: thresholds-test-v1
  medium_at: 40
  high_at: 70
  factors:
    - name: security
      weight: 100
      normalization: BOOLEAN
      count_cap: 1
"""


def test_policy_is_typed_versioned_and_content_bound():
    policy = parse_policy(POLICY)
    assert policy.version == "local-test-v1"
    assert ".git" in policy.ingestion.excluded_directories
    assert policy.risk.high_at == 70
    assert (
        parse_policy(POLICY.replace(b"max_entries: 1000", b"max_entries: 1001")).content_hash
        != policy.content_hash
    )


@pytest.mark.parametrize(
    "data",
    [
        POLICY + b"version: duplicate\n",
        POLICY + b"exceptions: [{operation: runtime-read}]\n",
        POLICY + b"object: !!python/object/apply:os.system ['echo unsafe']\n",
        POLICY + b"alias: &x [1]\nreference: *x\n",
        POLICY.replace(b"max_entries: 1000", b"max_entries: true"),
        POLICY.replace(b"weight: 100", b"weight: 0"),
        POLICY.replace(b"high_at: 70", b"high_at: 30"),
        POLICY.replace(b"max_file_bytes: 262144", b"max_file_bytes: 999999999"),
        b"[" * 30 + b"]" * 30,
        b"null",
        POLICY.replace(b"version: local-test-v1", b"version: ''"),
    ],
)
def test_policy_rejects_unsafe_yaml_and_schema(data):
    with pytest.raises(DomainError):
        parse_policy(data)
