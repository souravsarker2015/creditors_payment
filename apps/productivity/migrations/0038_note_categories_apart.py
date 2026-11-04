"""Notes get their own tree of categories (NoteCategory), apart from the exam ones.

Each person's categories that hold notes are copied over, with the categories above them (so
Backend › Databases keeps its shape), and every note stays in the same categories. An exam category
that only ever held notes (no question in it or under it) leaves the exam tree; one with questions
stays there as it was."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def copy_note_categories(apps, schema_editor):
    ExamCategory = apps.get_model("productivity", "ExamCategory")
    ExamNote = apps.get_model("productivity", "ExamNote")
    NoteCategory = apps.get_model("productivity", "NoteCategory")
    Note = apps.get_model("productivity", "Note")
    old_links = Note.categories.through
    new_links = Note.note_categories.through

    links = list(old_links.objects.values_list("note_id", "examcategory_id"))
    if not links:
        return
    exam = {c.pk: c for c in ExamCategory.objects.all()}
    wanted = set()                                   # the categories notes are in, and the ones above them
    for _note, cat in links:
        while cat and cat not in wanted and cat in exam:
            wanted.add(cat)
            cat = exam[cat].parent_id
    made = {}

    def copy(pk):                                    # a parent before what's inside it
        if pk not in made:
            old = exam[pk]
            parent = copy(old.parent_id) if old.parent_id in wanted else None
            made[pk] = NoteCategory.objects.create(owner_id=old.owner_id, parent_id=parent, name=old.name).pk
        return made[pk]

    for pk in sorted(wanted):
        copy(pk)
    new_links.objects.bulk_create([new_links(note_id=n, notecategory_id=made[c]) for n, c in links if c in made],
                                  ignore_conflicts=True, batch_size=500)

    # exam categories with no question anywhere in their branch were the notes' own: they go from the exam tree
    with_questions, parents = set(), {pk: c.parent_id for pk, c in exam.items()}
    for cat in ExamNote.categories.through.objects.values_list("examcategory_id", flat=True).distinct():
        while cat and cat not in with_questions:
            with_questions.add(cat)
            cat = parents.get(cat)
    notes_only = [pk for pk in wanted if pk not in with_questions]
    for pk in sorted(notes_only, key=lambda pk: -_depth(pk, parents)):       # the deepest first
        if not ExamCategory.objects.filter(parent_id=pk).exists():
            ExamCategory.objects.filter(pk=pk).delete()


def _depth(pk, parents):
    n, seen = 0, set()
    while parents.get(pk) and pk not in seen:
        seen.add(pk)
        pk, n = parents[pk], n + 1
    return n


class Migration(migrations.Migration):

    dependencies = [
        ("productivity", "0037_note_categories"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="NoteCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, verbose_name="Name")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="children",
                                             to="productivity.notecategory", verbose_name="Inside")),
            ],
            options={"verbose_name": "Note category", "verbose_name_plural": "Note categories", "ordering": ["name", "pk"]},
        ),
        migrations.AddField(
            model_name="note",
            name="note_categories",
            field=models.ManyToManyField(blank=True, related_name="+", to="productivity.notecategory"),
        ),
        migrations.RunPython(copy_note_categories, migrations.RunPython.noop),
        migrations.RemoveField(model_name="note", name="categories"),
        migrations.RenameField(model_name="note", old_name="note_categories", new_name="categories"),
        migrations.AlterField(
            model_name="note",
            name="categories",
            field=models.ManyToManyField(blank=True, related_name="notes", to="productivity.notecategory", verbose_name="Categories"),
        ),
    ]
