"""The job search pages (jobs.py): the board of applications, one application with its interview
rounds, and the STAR stories with a practice round of behavioural questions."""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_POST

from apps.trash.services import trash

from . import jobs, patterns
from .access import work_required
from .forms import JobApplicationForm, JobRoundForm, StoryForm
from .models import Difficulty, JobApplication, JobRound, JobStage, Story
from .views import render_work


# ── The board ─────────────────────────────────────────────────────────────
@work_required
def jobs_view(request):
    user, today = request.user, timezone.localdate()
    if request.method == "POST":                       # the quick add at the top of the board
        company, role = request.POST.get("company", "").strip()[:120], request.POST.get("role", "").strip()[:160]
        stage = request.POST.get("stage") if request.POST.get("stage") in JobStage.values else JobStage.WISHLIST
        if not company or not role:
            messages.error(request, _("Write the company and the role."))
            return redirect("work:jobs")
        same = (JobApplication.objects.filter(owner=user, company__iexact=company, role__iexact=role)
                .exclude(stage=JobStage.CLOSED).first())
        if same:                                       # already on the board: open it instead of making a second
            messages.info(request, _("It's on your board already — here it is."))
            return redirect("work:job", pk=same.pk)
        url = request.POST.get("url", "").strip()[:500]
        app = JobApplication.objects.create(owner=user, company=company, role=role, stage=stage, url=url if url.startswith(("http://", "https://")) else "",
                                            applied_on=today if stage != JobStage.WISHLIST else None, order=0)
        messages.success(request, _("Added — fill in the rest when you have it."))
        return redirect("work:job", pk=app.pk)
    show_closed = request.GET.get("closed") == "1"
    apps = list(JobApplication.objects.filter(owner=user).prefetch_related("rounds").order_by("order", "-updated_at"))
    now = timezone.now()
    for a in apps:
        a.quiet = a.stage == JobStage.APPLIED and a.days_quiet(today) >= jobs.QUIET_DAYS
        a.next_round = next((r for r in a.rounds.all() if r.at and r.at >= now), None)
        a.late = bool(a.next_on and a.next_on <= today and a.stage not in (JobStage.ACCEPTED, JobStage.CLOSED))
    stages = [s for s in JobStage.choices if show_closed or s[0] not in (JobStage.CLOSED,)]
    columns = [(value, label, [a for a in apps if a.stage == value]) for value, label in stages]
    return render_work(request, "work/jobs.html", {
        "columns": columns, "funnel": jobs.funnel(user), "coming": jobs.coming_up(user, today), "show_closed": show_closed,
        "closed_count": sum(1 for a in apps if a.stage == JobStage.CLOSED), "stages": JobStage.choices, "total": len(apps), "today": today,
    })


@work_required
def offers_view(request):
    """The offers side by side: what each pays in a normal year and in the first, and when to answer."""
    rows, comparable = jobs.offers(request.user)
    return render_work(request, "work/offers.html", {"rows": rows, "comparable": comparable, "today": timezone.localdate()})


@work_required
@require_POST
def job_move(request, pk):
    """A card dragged to another column (and its place there): {stage, order: [ids in the column]}."""
    app = get_object_or_404(JobApplication, pk=pk, owner=request.user)
    if not jobs.move(app, request.POST.get("stage", "")):
        return JsonResponse({"ok": False, "error": "stage"}, status=400)
    ids = [int(x) for x in request.POST.get("order", "").split(",") if x.strip().isdigit()]
    for i, pk_ in enumerate(ids):
        JobApplication.objects.filter(owner=request.user, pk=pk_).update(order=i)
    return JsonResponse({"ok": True, "stage": app.stage})


# ── One application ───────────────────────────────────────────────────────
@work_required
def job_view(request, pk):
    user = request.user
    app = get_object_or_404(JobApplication, pk=pk, owner=user)
    form = JobApplicationForm(instance=app, prefix="app")
    round_form = JobRoundForm(prefix="round")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save":
            was = app.stage
            form = JobApplicationForm(request.POST, instance=app, prefix="app")
            if form.is_valid():
                obj = form.save(commit=False)
                if obj.stage != was:
                    obj.stage_changed_at = timezone.now()
                    if obj.stage != JobStage.WISHLIST and not obj.applied_on:
                        obj.applied_on = timezone.localdate()
                obj.save()
                messages.success(request, _("Saved."))
                return redirect("work:job", pk=app.pk)
        elif action == "round":
            round_form = JobRoundForm(request.POST, prefix="round")
            if round_form.is_valid():
                rnd = round_form.save(commit=False)
                rnd.application = app
                rnd.save()
                if app.stage in (JobStage.WISHLIST, JobStage.APPLIED, JobStage.SCREEN) and rnd.kind not in ("recruiter", "test"):
                    jobs.move(app, JobStage.INTERVIEW)          # a real interview: it's Interviewing now
                elif app.stage in (JobStage.WISHLIST, JobStage.APPLIED):
                    jobs.move(app, JobStage.SCREEN)
                messages.success(request, _("Round added."))
                return redirect(reverse("work:job", args=[app.pk]) + "#rounds")
        elif action in ("round_save", "round_delete", "to_bank"):
            rnd = get_object_or_404(JobRound, pk=request.POST.get("round") or 0, application=app)
            if action == "round_delete":
                rnd.delete()
                messages.success(request, _("Round deleted."))
            elif action == "to_bank":
                n = jobs.to_bank(rnd)
                messages.success(request, ngettext("%(n)s question is in your question bank now.", "%(n)s questions are in your question bank now.", n) % {"n": n}
                                 if n else _("They're in your question bank already."))
            else:
                f = JobRoundForm(request.POST, instance=rnd, prefix=f"r{rnd.pk}")
                if f.is_valid():
                    f.save()
                    messages.success(request, _("Saved."))
            return redirect(reverse("work:job", args=[app.pk]) + "#rounds")
        elif action == "delete":
            trash(user, app, _("Job application: %(role)s at %(company)s") % {"role": app.role, "company": app.company}, reverse("work:jobs"))
            messages.success(request, _("Deleted. You can bring it back from Recently deleted."))
            return redirect("work:jobs")
    rounds = [(r, JobRoundForm(instance=r, prefix=f"r{r.pk}")) for r in app.rounds.all()]
    skills = jobs.skill_readiness(user, jobs.skills_in(f"{app.role}\n{app.description}"))
    asked = jobs.company_questions(user, app.company)
    return render_work(request, "work/job.html", {
        "app": app, "form": form, "round_form": round_form, "rounds": rounds, "skills": skills,
        "asked": asked[:8], "asked_count": asked.count(), "stages": JobStage.choices, "now": timezone.now(), "today": timezone.localdate(),
        "stories": Story.objects.filter(owner=user)[:6],
    })


# ── STAR stories ──────────────────────────────────────────────────────────
@work_required
def stories_view(request):
    user = request.user
    if request.method == "POST" and request.POST.get("action") == "practised":
        story = get_object_or_404(Story, pk=request.POST.get("story") or 0, owner=user)
        story.practised += 1
        story.practised_at = timezone.now()
        story.save(update_fields=["practised", "practised_at"])
        return JsonResponse({"ok": True, "practised": story.practised})
    stories = list(Story.objects.filter(owner=user))
    labels = {k: str(label) for k, (label, _qs) in jobs.COMPETENCIES.items()}
    deck = jobs.practice_deck()
    return render_work(request, "work/stories.html", {
        "stories": stories, "coverage": jobs.coverage(user), "labels": labels,
        "practice": {"deck": deck, "stories": [{"id": s.pk, "title": s.title, "shows": s.competencies, "situation": s.situation, "task": s.task,
                                                  "action": s.action, "result": s.result, "url": reverse("work:story_edit", args=[s.pk])} for s in stories],
                     "labels": labels, "practisedUrl": reverse("work:stories")},
    })


@work_required
def story_form_view(request, pk=None):
    story = get_object_or_404(Story, pk=pk, owner=request.user) if pk else None
    if request.method == "POST" and request.POST.get("action") == "delete" and story:
        trash(request.user, story, _("Story: %(title)s") % {"title": story.title}, reverse("work:stories"))
        messages.success(request, _("Deleted. You can bring it back from Recently deleted."))
        return redirect("work:stories")
    initial = {}
    if not story and request.GET.get("shows") in jobs.COMPETENCIES:
        initial["shows"] = [request.GET["shows"]]
    form = StoryForm(request.POST or None, instance=story, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.competencies = form.cleaned_data.get("shows") or []
        obj.save()
        messages.success(request, _("Story saved."))
        return redirect(reverse("work:stories") + f"#story-{obj.pk}")
    return render_work(request, "work/story_form.html", {"form": form, "story": story})


# ── Coding patterns ───────────────────────────────────────────────────────
@work_required
def patterns_view(request):
    user = request.user
    if request.method == "POST":
        try:
            minutes, difficulty = int(request.POST.get("minutes") or 0), int(request.POST.get("difficulty") or 2)
        except ValueError:
            minutes, difficulty = 0, 2
        q, is_new = patterns.log(user, request.POST.get("title", ""), request.POST.get("url", ""), request.POST.get("pattern", ""),
                                 difficulty, request.POST.get("outcome", ""), minutes)
        if q is None:
            messages.error(request, _("Write the problem's name and pick its pattern."))
        else:
            messages.success(request, _("Logged. It comes back in your practice when it's time.") if is_new else _("Logged as another try at this problem."))
        return redirect("work:patterns")
    return render_work(request, "work/patterns.html", {"map": patterns.roadmap(user, timezone.localdate()), "patterns": patterns.PATTERNS,
                                                       "outcomes": patterns.OUTCOMES, "difficulties": Difficulty.choices})
