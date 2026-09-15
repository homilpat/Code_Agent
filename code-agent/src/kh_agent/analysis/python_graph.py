import ast
import io
import os
import tokenize

from kh_agent.core.canonical import canonical_hash, decode_path, encode_path
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.repository.snapshot import SourceSnapshot

# v2 records the names imported by `from x import y`, which impact needs.
BUILDER_VERSION = "python-ast-v2"


def dotted_name(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *reversed(parts)])
    return None


def inspect_python(data: bytes) -> dict:
    if len(data) > 256 * 1024:
        return {
            "coverage": "UNAVAILABLE",
            "reason": "PYTHON_INPUT_LIMIT",
            "definitions": [],
            "imports": [],
            "calls": [],
        }
    try:
        for count, _ in enumerate(tokenize.tokenize(io.BytesIO(data).readline)):
            if count >= 10000:
                return {
                    "coverage": "UNAVAILABLE",
                    "reason": "PYTHON_TOKEN_LIMIT",
                    "definitions": [],
                    "imports": [],
                    "calls": [],
                }
        tree = ast.parse(data)
    except (SyntaxError, ValueError, UnicodeError, RecursionError, tokenize.TokenError):
        return {
            "coverage": "UNAVAILABLE",
            "reason": "PYTHON_PARSE_FAILED",
            "definitions": [],
            "imports": [],
            "calls": [],
        }
    definitions, imports, calls = [], [], []
    stack: list[tuple[ast.AST, str]] = [(tree, "")]
    count = 0
    while stack:
        node, scope = stack.pop()
        count += 1
        if count > 30000:
            return {
                "coverage": "UNAVAILABLE",
                "reason": "AST_NODE_LIMIT",
                "definitions": [],
                "imports": [],
                "calls": [],
            }
        child_scope = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            child_scope = f"{scope}.{node.name}" if scope else node.name
            definitions.append(
                {
                    "symbol": child_scope,
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                }
            )
        elif isinstance(node, ast.Import):
            imports.extend(
                {"module": alias.name, "relative_level": 0, "line": node.lineno}
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            imports.append(
                {
                    "module": node.module or "",
                    "names": sorted(alias.name for alias in node.names),
                    "relative_level": node.level,
                    "line": node.lineno,
                }
            )
        elif isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name:
                calls.append(
                    {
                        "caller": scope or "<module>",
                        "callee_expression": name,
                        "line": node.lineno,
                        "resolution": "UNRESOLVED_STATIC_EXPRESSION",
                    }
                )
        body = (
            getattr(node, "body", [])
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            else []
        )
        stack.extend(
            (child, child_scope if child in body else scope)
            for child in reversed(list(ast.iter_child_nodes(node)))
        )
    return {
        "coverage": "PYTHON_SYNTAX_ONLY",
        "definitions": definitions,
        "imports": imports,
        "calls": calls,
    }


def build_graph(snapshot: SourceSnapshot) -> dict:
    modules = []
    for source in snapshot.files:
        modules.append(
            {
                "path": encode_path(source.path),
                "content_hash": source.content_hash,
                **inspect_python(source.content),
            }
        )
    graph = {
        "builder_version": BUILDER_VERSION,
        "source_snapshot_hash": snapshot.snapshot_hash,
        "ingestion_policy_version": snapshot.policy_version,
        "modules": modules,
        "completeness": "PARTIAL",
        "limitations": [
            *snapshot.limitations,
            "PYTHON_ONLY",
            "CALL_TARGETS_NOT_RESOLVED",
            "NO_RUNTIME_EVIDENCE",
        ],
    }
    return {**graph, "graph_hash": canonical_hash(graph, "python-graph-v1").digest}


def explain(graph: dict, target: str) -> dict:
    if not target or target.startswith(("/", "\\")) or "\\" in target:
        raise DomainError(ErrorCode.INVALID_INPUT, "Use a repository-relative POSIX file path")
    encoded = encode_path(os.fsencode(target))
    matches = [module for module in graph["modules"] if module["path"] == encoded]
    if not matches:
        raise DomainError(
            ErrorCode.CAPABILITY_NOT_AVAILABLE,
            "Target has no included Python evidence under the ingestion policy",
        )
    return {
        "target": target,
        "evidence_type": "STATIC_AST",
        "module": matches[0],
        "source_snapshot_hash": graph["source_snapshot_hash"],
        "graph_hash": graph["graph_hash"],
        "completeness": graph["completeness"],
        "limitations": graph["limitations"],
    }


def module_names(path: str, packages: set[str]) -> set[str]:
    """Dotted names a file can be imported as: from the scan root and from its package root.

    `src/pkg/util.py` with `src/pkg/__init__.py` is both `src.pkg.util` and `pkg.util`. A bare
    file name is only used at the scan root, so an unrelated `import util` is not a match.
    """
    parts = path[:-3].split("/")
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    if not parts:
        return set()
    names = {".".join(parts)}
    root = len(parts) - 1
    while root > 0 and "/".join(parts[:root]) + "/__init__.py" in packages:
        root -= 1
    if root < len(parts) - 1 or is_package:
        names.add(".".join(parts[root:]))
    return names


def imported_names(module: str, imported: dict) -> set[str]:
    """`from pkg import util` references both `pkg` and `pkg.util`."""
    names = {module} if module else set()
    names.update(
        f"{module}.{name}" if module else name for name in imported.get("names", []) if name != "*"
    )
    return names


def relative_import_names(importer: str, imported: dict) -> set[str]:
    package = importer[:-3].split("/")[:-1]
    keep = len(package) - (imported["relative_level"] - 1)
    if keep < 0:
        return set()
    base = package[:keep] + (imported["module"].split(".") if imported["module"] else [])
    return imported_names(".".join(base), imported)


def impact(graph: dict, target: str) -> dict:
    target_view = explain(graph, target)
    if not target.endswith(".py"):
        raise DomainError(ErrorCode.INVALID_INPUT)
    paths = [os.fsdecode(decode_path(module["path"])) for module in graph["modules"]]
    packages = {path for path in paths if path == "__init__.py" or path.endswith("/__init__.py")}
    targets = module_names(target, packages)
    candidates = []
    for path, module in zip(paths, graph["modules"], strict=True):
        if path == target:
            continue
        for imported in module["imports"]:
            relative = imported["relative_level"] > 0
            referenced = (
                relative_import_names(path, imported)
                if relative
                else imported_names(imported["module"], imported)
            )
            if targets & referenced:
                candidates.append(
                    {
                        "path": module["path"],
                        "line": imported["line"],
                        "evidence": (
                            "RELATIVE_IMPORT_RESOLVED" if relative else "ABSOLUTE_IMPORT_NAME_MATCH"
                        ),
                        "confidence": "CANDIDATE_REQUIRES_IMPORT_ROOT_RESOLUTION",
                    }
                )
    return {
        **target_view,
        "import_candidates": candidates,
        "risk": "NOT_AVAILABLE",
        "impact_complete": False,
    }
