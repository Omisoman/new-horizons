"""Patch replay — tier-1's committed work applied onto tier-2's own tree.

Tier-1 has no git remote, no Gitea credentials and no volume shared with
tier-2. What crosses the boundary is a `git format-patch` text plus its
sha256; this module replays it onto tier-2's copy of the same baked base
commit (`sojourner-base`), in code — a patch never enters a model prompt.

The tree is rebuilt from the base on every call, so replaying the same
request twice yields the same tree and no earlier task can drift into a
build. `git clean -fd` deliberately omits `-x`: ignored paths (.venv)
survive, since the sandbox cannot reinstall them offline.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

COMMITTER = {
    "GIT_COMMITTER_NAME": "sojourner tier-2 ops",
    "GIT_COMMITTER_EMAIL": "ops@sojourner.local",
}


def patch_sha256(patch: str) -> str:
    return hashlib.sha256(patch.encode()).hexdigest()


def git(project: Path, *args: str, timeout: int = 120) -> str:
    p = subprocess.run(["git", *args], cwd=str(project), capture_output=True,
                       text=True, timeout=timeout, env={**os.environ, **COMMITTER})
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: "
                           f"{(p.stderr or p.stdout).strip()[:400]}")
    return p.stdout.strip()


def reset_to_base(*, project_dir: Path | str, base_ref: str = "sojourner-base",
                  branch: str = "baseline") -> dict:
    """Rebuild the work tree AT the baseline, with no patch applied.

    A deploy request carrying no patch means "ship the baseline" (the rollback
    shape in the release playbook). That has to be enforced, not assumed: the
    work tree still holds whatever the previous request's patch left, so
    without this a "baseline" deploy silently rebuilds and ships the last
    change — which is exactly what it did, and only an API response gave it
    away.
    """
    project = Path(project_dir)
    try:
        subprocess.run(["git", "am", "--abort"], cwd=str(project),
                       capture_output=True, text=True)
        git(project, "checkout", "-f", base_ref)
        git(project, "clean", "-fd")
        git(project, "checkout", "-B", branch, base_ref)
        return {"ok": True, "baseline": True, "commits": [], "files": [],
                "diffstat": "", "head": git(project, "rev-parse", "--short", "HEAD")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:600]}


def apply_patch(patch: str, *, project_dir: Path | str, base_ref: str = "sojourner-base",
                sha_stated: str = "", branch: str = "deploy") -> dict:
    """Replay `patch` onto `project_dir`, rebuilt from `base_ref`.

    Returns {ok, sha256, head, author, commits, files, diffstat} or
    {ok: False, error, sha256}. Never raises.
    """
    project = Path(project_dir)
    sha = patch_sha256(patch)
    if sha_stated and sha_stated != sha:
        return {"ok": False, "sha256": sha, "stated": sha_stated,
                "error": "patch sha256 mismatch — refusing to apply"}
    path = ""
    try:
        # An interrupted earlier apply would otherwise block checkout.
        subprocess.run(["git", "am", "--abort"], cwd=str(project),
                       capture_output=True, text=True)
        git(project, "checkout", "-f", base_ref)
        git(project, "clean", "-fd")
        git(project, "checkout", "-B", branch, base_ref)
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as fh:
            fh.write(patch if patch.endswith("\n") else patch + "\n")
            path = fh.name
        git(project, "am", "--3way", "--committer-date-is-author-date", path)
        return {
            "ok": True,
            "sha256": sha,
            "head": git(project, "rev-parse", "--short", "HEAD"),
            "author": git(project, "log", "-1", "--format=%an <%ae>"),
            # --reverse: the artifact an operator approves reads in the order
            # the developer committed, not newest-first.
            "commits": git(project, "log", "--reverse", "--format=%s",
                           f"{base_ref}..HEAD").splitlines(),
            "files": [f for f in git(project, "diff", "--name-only",
                                     f"{base_ref}..HEAD").splitlines() if f],
            "diffstat": git(project, "diff", "--stat", f"{base_ref}..HEAD")[-1200:],
        }
    except Exception as exc:
        return {"ok": False, "sha256": sha, "error": str(exc)[:600]}
    finally:
        if path and os.path.exists(path):
            os.unlink(path)
