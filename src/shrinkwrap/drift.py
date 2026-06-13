from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DriftResult:
    score: float
    changed_public_symbols: list[str]
    structure_changes: list[str]

    @property
    def threshold_exceeded(self) -> bool:
        return self.score >= 0.35


def extract_public_symbols(source: str) -> set[str]:
    """Return the set of top-level public symbol names in Python source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    symbols: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                symbols.add(node.name)
    return symbols


def compute_symbol_drift(
    before: str, after: str
) -> tuple[list[str], list[str], list[str]]:
    """
    Compare public symbol sets. Returns (added, removed, renamed).
    renamed is always empty — rename detection is not implemented.
    """
    before_symbols = extract_public_symbols(before)
    after_symbols = extract_public_symbols(after)

    added = sorted(after_symbols - before_symbols)
    removed = sorted(before_symbols - after_symbols)
    return added, removed, []


_CONFIG_FILES = frozenset(
    ["pyproject.toml", "setup.cfg", "setup.py", "package.json", "Cargo.toml"]
)
_SOURCE_EXTS = frozenset([".py", ".ts", ".js", ".go", ".rs", ".java"])
_TEST_PATTERNS = ("test_", "_test.", "spec.", ".spec.")


def _git_run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    return result.stdout if result.returncode == 0 else ""


def _git_file_at(commit: str, path: str, cwd: Path) -> str:
    return _git_run(["show", f"{commit}:{path}"], cwd)


def score_commit(
    repo_root: Path,
    commit_sha: str = "HEAD",
    watched_paths: list[str] | None = None,
) -> DriftResult:
    """
    Score how much the public API surface drifted in commit_sha.
    Uses `git diff --name-only <commit>~1..<commit>` to find changed files.
    If watched_paths is provided, only files under those paths are analyzed.
    """
    parent = f"{commit_sha}~1"
    changed_files_raw = _git_run(
        ["diff", "--name-only", f"{parent}..{commit_sha}"], cwd=repo_root
    )
    changed_files = [f.strip() for f in changed_files_raw.splitlines() if f.strip()]

    # Filter to watched paths if specified (non-empty list)
    if watched_paths:
        changed_files = [
            f for f in changed_files
            if any(f.startswith(wp) for wp in watched_paths)
        ]

    all_added: list[str] = []
    all_removed: list[str] = []
    structure_changes: list[str] = []
    config_changed = False

    for fpath in changed_files:
        fname = Path(fpath).name
        ext = Path(fpath).suffix

        if fname in _CONFIG_FILES:
            config_changed = True
            continue

        if any(pat in fpath for pat in _TEST_PATTERNS):
            continue

        # Check for new/deleted top-level directories
        parts = Path(fpath).parts
        if len(parts) == 2 and parts[0] not in (".", "src", "lib"):
            structure_changes.append(f"dir:{parts[0]}")

        if ext not in _SOURCE_EXTS:
            continue

        if ext == ".py":
            before = _git_file_at(parent, fpath, repo_root)
            after = _git_file_at(commit_sha, fpath, repo_root)
            added, removed, _ = compute_symbol_drift(before, after)
            all_added.extend(added)
            all_removed.extend(removed)

    all_changed = all_added + all_removed
    public_api_change_ratio = min(1.0, len(all_changed) / max(len(changed_files), 1))
    structure_ratio = min(1.0, len(set(structure_changes)) * 0.5)
    config_ratio = 0.15 if config_changed else 0.0

    stat_output = _git_run(["diff", "--stat", f"{parent}..{commit_sha}"], cwd=repo_root)
    total_lines = int(stat_output.count("\n"))
    volume_ratio = min(1.0, total_lines / max(len(changed_files) * 50, 1))

    score = (
        public_api_change_ratio * 0.40
        + structure_ratio * 0.35
        + config_ratio * 0.15
        + volume_ratio * 0.10
    )
    score = round(min(1.0, score), 3)

    return DriftResult(
        score=score,
        changed_public_symbols=all_changed,
        structure_changes=list(set(structure_changes)),
    )
