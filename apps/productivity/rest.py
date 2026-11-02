"""A personal API, for scripts, git hooks and the `ft` command line (templates/work/ft_cli.sh).

Signing in is one secret token, made in Settings: `Authorization: Bearer ftk_…`. Only its hash is kept, and it does
what its owner can do in Productivity, no more. Everything is JSON; with `Accept: text/plain` an answer is the
lines a terminal wants. A task is named by its key (T-42) or its number.
"""
import hashlib
import json
from functools import wraps

from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt

from . import dev, services
from .access import can_use
from .models import Priority, Snippet, Status, Task, TaskActivity, WorkSettings

OPEN = (Status.BACKLOG, Status.TODO, Status.DOING, Status.REVIEW)
LIMIT = 200


def _token(request):
    head = request.headers.get("Authorization", "")
    return head[7:].strip() if head.lower().startswith("bearer ") else ""


def token_api(*methods):
    """The view takes the person whose token came, and what they sent. Answers say what went wrong in `error`."""
    def wrap(view):
        @csrf_exempt
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            token = _token(request)
            found = (WorkSettings.objects.filter(api_token_hash=hashlib.sha256(token.encode()).hexdigest()).select_related("owner").first()
                     if token else None)
            if found is None or not found.owner.is_active or not can_use(found.owner):
                return _fail(request, _("That token isn't valid. Make one in Productivity → Settings → API."), 401)
            if request.method not in methods:
                return _fail(request, _("Use %(methods)s here.") % {"methods": ", ".join(methods)}, 405)
            try:
                body = json.loads(request.body or b"{}")
            except ValueError:
                return _fail(request, _("Send JSON."), 400)
            if not isinstance(body, dict):
                return _fail(request, _("Send a JSON object."), 400)
            now = timezone.now()
            if not found.api_token_used_at or (now - found.api_token_used_at).total_seconds() > 300:
                WorkSettings.objects.filter(pk=found.pk).update(api_token_used_at=now)
            return view(request, found, body, *args, **kwargs)
        return wrapped
    return wrap


def _fail(request, error, status):
    if "text/plain" in request.headers.get("Accept", ""):
        return HttpResponse(f"{error}\n", status=status, content_type="text/plain; charset=utf-8")
    return JsonResponse({"ok": False, "error": str(error)}, status=status)


def _answer(request, data, text):
    """JSON, or `text` for a terminal."""
    if "text/plain" in request.headers.get("Accept", ""):
        return HttpResponse(text.rstrip() + "\n", content_type="text/plain; charset=utf-8")
    return JsonResponse({"ok": True, **data})


def _task(settings, ref):
    """T-42, t-42 or 42 → the person's task, or None."""
    number = str(ref).strip().rsplit("-", 1)[-1]
    return Task.objects.filter(owner=settings.owner, pk=number).select_related("project").first() if number.isdigit() else None


def _json(task, settings, request):
    return {"key": task.key(settings.key_prefix), "id": task.pk, "title": task.title, "status": task.status, "kind": task.kind,
            "priority": task.priority, "points": task.points, "due": task.due_date.isoformat() if task.due_date else None,
            "project": task.project.name if task.project_id else None, "link": task.link, "left_off": task.left_off,
            "branch": dev.branch_name(task, settings), "commit": dev.commit_message(task, settings),
            "url": request.build_absolute_uri(reverse("work:task", args=[task.pk]))}


def _line(task, settings):
    mark = {Priority.URGENT: "!!!", Priority.HIGH: "!!", Priority.MEDIUM: "!"}.get(task.priority, "")
    due = f"  due {task.due_date.isoformat()}" if task.due_date else ""
    return f"{task.key(settings.key_prefix):<8}{task.status:<8}{mark:<4}{task.title}{due}"


def _timer_text(entry):
    if entry is None:
        return _("No timer is running.")
    minutes = entry.seconds // 60
    return f"{entry.label}  {minutes // 60}h {minutes % 60:02d}m"


@token_api("GET")
def me(request, settings, body):
    from .api import _today_seconds

    entry = services.running_entry(settings.owner)
    seconds = _today_seconds(settings.owner)
    return _answer(request, {"user": settings.owner.get_username(), "key_prefix": settings.key_prefix, "today_seconds": seconds, "running": entry.label if entry else None},
                   f"{settings.owner.get_username()}: {seconds // 3600}h {seconds % 3600 // 60:02d}m today · {_timer_text(entry)}")


@token_api("GET", "POST")
def tasks(request, settings, body):
    user = settings.owner
    if request.method == "POST":
        text = (body.get("text") or "").strip()
        task = services.create_from_quick(user, text) if text else None
        if task is None:
            return _fail(request, _("Send what needs doing as “text”."), 400)
        return _answer(request, {"task": _json(task, settings, request)}, f"Added {_line(task, settings)}")
    rows = Task.objects.filter(owner=user, parent__isnull=True).select_related("project")
    status, q = request.GET.get("status", "open"), request.GET.get("q", "").strip()
    if status == "open":
        rows = rows.filter(status__in=OPEN)
    elif status in Status.values:
        rows = rows.filter(status=status)
    elif status != "all":
        return _fail(request, _("status can be open, all, or one of: %(values)s.") % {"values": ", ".join(Status.values)}, 400)
    if q:
        rows = rows.filter(Q(title__icontains=q) | Q(notes__icontains=q))
    if request.GET.get("project"):
        rows = rows.filter(project__name__icontains=request.GET["project"])
    if request.GET.get("kind"):
        rows = rows.filter(kind=request.GET["kind"])
    rows = list(rows.order_by("-priority", "due_date", "-updated_at")[:min(int(request.GET["limit"]) if request.GET.get("limit", "").isdigit() else 50, LIMIT)])
    return _answer(request, {"tasks": [_json(t, settings, request) for t in rows]}, "\n".join(_line(t, settings) for t in rows) or _("Nothing here."))


@token_api("GET", "POST")
def task(request, settings, body, ref):
    found = _task(settings, ref)
    if found is None:
        return _fail(request, _("There's no task %(ref)s.") % {"ref": ref}, 404)
    field = request.GET.get("field", "")
    if field in ("branch", "commit", "url", "title"):       # one value, for $(ft branch T-42)
        return _answer(request, {field: _json(found, settings, request)[field]}, _json(found, settings, request)[field])
    if request.method == "POST":
        if "status" in body:
            if body["status"] not in Status.values:
                return _fail(request, _("status can be: %(values)s.") % {"values": ", ".join(Status.values)}, 400)
            services.set_done(found, body["status"] == Status.DONE)
            found.status = body["status"]
            found.save(update_fields=["status", "updated_at"])
        if "left_off" in body:
            found.left_off = str(body["left_off"])[:300]
            found.save(update_fields=["left_off", "updated_at"])
        if (body.get("comment") or "").strip():
            TaskActivity.objects.create(task=found, kind=TaskActivity.Kind.COMMENT, text=str(body["comment"]).strip()[:4000])
    text = _line(found, settings) + (f"\nLeft off: {found.left_off}" if found.left_off else "")
    return _answer(request, {"task": _json(found, settings, request)}, text)


@token_api("GET", "POST")
def timer(request, settings, body):
    user = settings.owner
    if request.method == "POST":
        if body.get("stop"):
            entry = services.running_entry(user)
            if entry is not None and entry.task_id and (body.get("left_off") or "").strip():
                entry.task.left_off = str(body["left_off"]).strip()[:300]
                entry.task.save(update_fields=["left_off", "updated_at"])
            services.stop_timer(user)
            return _answer(request, {"running": None}, _("Stopped: %(what)s") % {"what": _timer_text(entry)})
        found = None
        if body.get("task"):
            found = _task(settings, body["task"])
            if found is None:
                return _fail(request, _("There's no task %(ref)s.") % {"ref": body["task"]}, 404)
        entry = services.start_timer(user, task=found, description=str(body.get("description") or "")[:300])
        text = _("Started: %(what)s") % {"what": entry.label}
        return _answer(request, {"running": entry.label, "left_off": found.left_off if found else ""},
                       text + (f"\nLeft off: {found.left_off}" if found and found.left_off else ""))
    entry = services.running_entry(user)
    return _answer(request, {"running": entry.label if entry else None, "seconds": entry.seconds if entry else 0}, _timer_text(entry))


@token_api("POST")
def log(request, settings, body):
    """A line for today's daily note: what was learnt, a command that worked…"""
    from .views import daily_note

    text = (body.get("text") or "").strip()
    if not text:
        return _fail(request, _("Send the line as “text”."), 400)
    note = daily_note(settings.owner)
    stamp = timezone.localtime().strftime("%H:%M")
    note.body = f"{note.body.rstrip()}\n- {stamp} {text}\n"
    note.save(update_fields=["body", "updated_at"])
    return _answer(request, {"note": note.pk}, _("Added to today's note."))


@token_api("GET")
def snippets(request, settings, body):
    rows = Snippet.objects.filter(owner=settings.owner)
    q = request.GET.get("q", "").strip()
    if q:
        rows = rows.filter(Q(title__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
    rows = list(rows.order_by("-is_favorite", "-uses")[:20])
    if len(rows) == 1 and q:      # one found: just the code, to pipe on
        return _answer(request, {"snippets": [{"title": rows[0].title, "language": rows[0].language, "code": rows[0].code}]}, rows[0].code)
    return _answer(request, {"snippets": [{"title": s.title, "language": s.language, "code": s.code} for s in rows]},
                   "\n".join(f"{s.language:<12}{s.title}" for s in rows) or _("Nothing here."))


@token_api("GET")
def standup(request, settings, body):
    data = services.standup(settings.owner)
    text = services.standup_text(data)
    return _answer(request, {"standup": text}, text)


def cli(request):
    """The `ft` command, with this site's address in it. Nothing secret: the token stays on the person's machine."""
    return render(request, "work/ft_cli.sh", {"base": request.build_absolute_uri("/").rstrip("/")}, content_type="text/x-shellscript; charset=utf-8")

