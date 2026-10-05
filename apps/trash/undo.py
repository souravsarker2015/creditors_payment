from django.contrib import messages

from .services import trash


def delete_with_undo(request, obj, message, label=None, back_url=None):
    """Delete `obj` into Recently deleted and say so, with an Undo button.

    `message` is what the person reads ("Expense of ৳500 deleted."); `label`
    is how it's listed in Recently deleted (defaults to the message)."""
    item = trash(request.user, obj, label or message, back_url or request.get_full_path())
    messages.success(request, message, extra_tags=f"undo:{item.pk}")
    return item
