"""For software work: task keys (T-42), branch names and commit messages made
from a task, release notes from what's done, and a Git webhook (GitHub or
GitLab) that ties commits and pull requests back to their tasks — as Jira's
smart commits and Linear's Git integration do.

A commit that mentions T-42 leaves a comment on the task; "fixes T-42"
(closes, resolves…) also ticks it off. A pull/merge request that names a
task (title, branch or description) puts its link on the task and marks it
in review (a draft: in progress); once merged, the task is done.
"""
import hashlib
import hmac
import re
import unicodedata

from django.utils.translation import gettext as _

from .models import KIND_BRANCH, Status, Task, TaskActivity, TaskKind

COMMIT_TYPE = {"feature": "feat", "bug": "fix", "docs": "docs"}      # conventional commit types; the rest are chores
CLOSE_WORDS = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|done|complete[sd]?)"
SECTIONS = [     # in English on purpose: release notes go into repositories and changelogs
(TaskKind.FEATURE, "Features"), (TaskKind.BUG, "Bug fixes"), (TaskKind.CHORE, "Maintenance"),
            (TaskKind.DOCS, "Docs"), (TaskKind.RESEARCH, "Research"), (TaskKind.TASK, "Other")]


def slug(text, limit=40):
    """'Fix the login redirect loop!' → 'fix-the-login-redirect-loop' (ASCII; Bangla falls away)."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    out = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    return out[:limit].rstrip("-")


def branch_name(task, settings):
    fmt = settings.branch_format or "{type}/{key}-{slug}"
    name = (fmt.replace("{type}", KIND_BRANCH.get(task.kind, "task")).replace("{key}", task.key(settings.key_prefix))
            .replace("{id}", str(task.pk)).replace("{slug}", slug(task.title) or "task"))
    name = re.sub(r"[\s~^:?*\[\\]+", "-", name)       # what git won't take in a branch name
    return re.sub(r"-{2,}", "-", name).strip("-/.")


def commit_message(task, settings):
    """A conventional commit line: 'fix: the login redirect loop (T-42)'."""
    title = task.title.strip()
    title = title[:1].lower() + title[1:] if title[:2] != title[:2].upper() else title     # keep "API…", lower "Fix…"
    return f"{COMMIT_TYPE.get(task.kind, 'chore')}: {title} ({task.key(settings.key_prefix)})"


def pr_description(task, settings):
    """A pull request's text, ready to paste: the commit line as its title, the task's notes (with the
    to-dos as a checklist), its link, and "Closes T-42" so the webhook ticks the task off on merge."""
    key = task.key(settings.key_prefix)
    parts = [commit_message(task, settings), ""]
    if task.notes.strip():
        parts += [task.notes.strip(), ""]
    if task.link and not task.link_label.startswith(("PR ", "MR ")):      # the issue it's for (not this pull request itself)
        parts += [f"Ticket: {task.link}", ""]
    parts.append(f"Closes {key}")
    return "\n".join(parts)


def repo_links(task, settings):
    """With the project's repository: where the task's branch is, and the page that opens a pull request
    from it (GitHub, GitLab, Bitbucket — any other host: just the repository). {} without one."""
    from urllib.parse import quote

    repo = (task.project.repo_url if task.project_id else "").strip().rstrip("/").removesuffix(".git")
    if not repo:
        return {}
    name = branch_name(task, settings)
    path, query = quote(name, safe="/"), quote(name, safe="")         # "feat/T-4-x" stays a path; in a query it's encoded
    host = repo.lower()
    if "gitlab" in host:
        links = {"branch": f"{repo}/-/tree/{path}", "new_pr": f"{repo}/-/merge_requests/new?merge_request%5Bsource_branch%5D={query}"}
    elif "bitbucket" in host:
        links = {"branch": f"{repo}/branch/{path}", "new_pr": f"{repo}/pull-requests/new?source={query}"}
    elif "github" in host:
        links = {"branch": f"{repo}/tree/{path}", "new_pr": f"{repo}/compare/{path}?expand=1"}
    else:
        links = {}
    return {"repo": repo, **links}


# ── Quick add: a conventional-commit start ("fix(auth): login loop") ────────
PREFIX = re.compile(r"^(feat|feature|fix|bug|bugfix|hotfix|chore|refactor|perf|test|tests|ci|build|style|docs?|spike|research)(?:\(([\w./-]{1,30})\))?!?:\s*", re.I)
PREFIX_KIND = {"feat": TaskKind.FEATURE, "feature": TaskKind.FEATURE, "fix": TaskKind.BUG, "bug": TaskKind.BUG, "bugfix": TaskKind.BUG,
               "hotfix": TaskKind.BUG, "docs": TaskKind.DOCS, "doc": TaskKind.DOCS, "spike": TaskKind.RESEARCH, "research": TaskKind.RESEARCH}


def take_prefix(text):
    """(kind, scope, the rest) when the line starts like a conventional commit, else (None, '', text)."""
    m = PREFIX.match(text.strip())
    if not m:
        return None, "", text
    return PREFIX_KIND.get(m.group(1).lower(), TaskKind.CHORE), (m.group(2) or "").lower(), text.strip()[m.end():]


def bug_template():
    """What a bug report needs, put in an empty task's notes when it's made a bug."""
    return (f"**{_('Steps to reproduce')}**\n1. \n\n**{_('Expected')}**\n\n\n**{_('Actual')}**\n\n\n"
            f"**{_('Where')}** ({_('browser, device, version')})\n")


# ── Release notes ─────────────────────────────────────────────────────────
def release_notes(tasks, title, settings):
    """Markdown: the done tasks grouped as a changelog (Features, Bug fixes…)."""
    done = [t for t in tasks if t.status == Status.DONE and t.parent_id is None]
    lines = [f"## {title}", ""]
    for kind, heading in SECTIONS:
        items = [t for t in done if t.kind == kind]
        if not items:
            continue
        lines.append(f"### {heading}")
        for t in sorted(items, key=lambda t: t.completed_at or t.updated_at):
            ref = f" ({t.link})" if t.link else ""
            lines.append(f"- {t.title} — {t.key(settings.key_prefix)}{ref}")
        lines.append("")
    if len(lines) == 2:
        lines.append("_Nothing finished yet._")
    return "\n".join(lines).rstrip() + "\n"


# ── Git webhook ───────────────────────────────────────────────────────────
def signed(request, secret):
    """GitHub signs the body with the secret (X-Hub-Signature-256); GitLab sends the secret itself (X-Gitlab-Token)."""
    sig = request.headers.get("X-Hub-Signature-256", "")
    if sig.startswith("sha256="):
        good = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig[7:], good)
    token = request.headers.get("X-Gitlab-Token", "")
    return bool(token) and hmac.compare_digest(token, secret)


def _keys(text, prefix):
    return {int(n) for n in re.findall(rf"(?<![\w-]){re.escape(prefix)}-(\d+)\b", text or "", re.I)}


def _closing(text, prefix):
    return {int(n) for n in re.findall(rf"\b{CLOSE_WORDS}:?\s+{re.escape(prefix)}-(\d+)\b", text or "", re.I)}


def _tasks(user, ids):
    return {t.pk: t for t in Task.objects.filter(owner=user, pk__in=ids)} if ids else {}


def _note(task, text, **git):
    """A comment on the task; git={"git": "commit" | "pr" | "merged", "ref": …} marks what Git did (the standup counts it)."""
    TaskActivity.objects.create(task=task, kind=TaskActivity.Kind.COMMENT, text=text[:4000], data=git)


def _finish(task, why, **git):
    from .services import set_done

    if not task.is_done:
        set_done(task, True)
        _note(task, why, **git)
        return True
    return False


def handle(user, settings, event, data):
    """Applies one webhook delivery. Returns what it did, for the reply (and tests)."""
    prefix = settings.key_prefix or "T"
    out = {"comments": 0, "done": 0, "started": 0, "linked": 0, "review": 0}
    if event in ("push", "Push Hook"):
        branch = (data.get("ref") or "").removeprefix("refs/heads/")
        repo = (data.get("repository") or {}).get("full_name") or (data.get("project") or {}).get("path_with_namespace") or ""
        commits = data.get("commits") or []
        mentioned = set().union(*[_keys(c.get("message"), prefix) for c in commits]) if commits else set()
        for_branch = _keys(branch, prefix)
        tasks = _tasks(user, mentioned | for_branch)
        for c in commits[:50]:
            msg = (c.get("message") or "").strip()
            first = msg.splitlines()[0][:200] if msg else ""
            sha = (c.get("id") or "")[:7]
            author = ((c.get("author") or {}).get("name") or "").strip()
            for pk in _keys(msg, prefix):
                t = tasks.get(pk)
                if not t:
                    continue
                _note(t, _("Commit %(sha)s on %(branch)s%(by)s: %(msg)s\n%(url)s") % {
                    "sha": sha, "branch": branch or repo, "by": f" ({author})" if author else "", "msg": first, "url": c.get("url") or ""},
                      git="commit", ref=sha)
                out["comments"] += 1
            for pk in _closing(msg, prefix):
                t = tasks.get(pk)
                if t and _finish(t, _("Done by commit %(sha)s.") % {"sha": sha}, git="commit", ref=sha):
                    out["done"] += 1
        for pk in for_branch:            # work pushed to the task's own branch: it has started
            t = tasks.get(pk)
            if t and t.status in (Status.TODO, Status.BACKLOG):
                t.status = Status.DOING
                t.save(update_fields=["status", "updated_at"])
                out["started"] += 1
        return out
    pr = data.get("pull_request") if event == "pull_request" else (data.get("object_attributes") if event in ("merge_request", "Merge Request Hook") else None)
    if pr is None:
        return out
    if event == "pull_request":
        action, url, merged = data.get("action"), pr.get("html_url") or "", bool(pr.get("merged"))
        branch = (pr.get("head") or {}).get("ref") or ""
        number = f"PR #{pr.get('number')}"
    else:
        action, url = pr.get("action"), pr.get("url") or ""
        merged = action == "merge" or pr.get("state") == "merged"
        branch = pr.get("source_branch") or ""
        number = f"MR !{pr.get('iid')}"
    text = " ".join([pr.get("title") or "", branch, pr.get("body") or pr.get("description") or ""])
    tasks = _tasks(user, _keys(text, prefix))
    for t in tasks.values():
        if action in ("opened", "open", "reopened", "reopen", "ready_for_review"):
            if not t.link and url:
                t.link = url[:500]
                out["linked"] += 1
            draft = bool(pr.get("draft") or pr.get("work_in_progress"))
            if t.status in (Status.TODO, Status.BACKLOG, Status.DOING):     # a pull request open: waiting on code review
                t.status = Status.DOING if draft else Status.REVIEW
                out["started" if draft else "review"] += 1
            t.save(update_fields=["link", "status", "updated_at"])
            _note(t, _("%(pr)s opened: %(title)s\n%(url)s") % {"pr": number, "title": (pr.get("title") or "")[:200], "url": url}, git="pr", ref=number)
            out["comments"] += 1
        elif action == "converted_to_draft" and t.status == Status.REVIEW:     # back to work on it
            t.status = Status.DOING
            t.save(update_fields=["status", "updated_at"])
        elif merged and action in ("closed", "merge"):
            if _finish(t, _("%(pr)s merged — done.\n%(url)s") % {"pr": number, "url": url}, git="merged", ref=number):
                out["done"] += 1
    return out
