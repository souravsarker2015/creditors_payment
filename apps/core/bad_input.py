"""An address or a value that can't mean anything (?year=99999, ?project=abc, a number too long for the
database) gets the "couldn't find that" page, not a crash: nothing went wrong on our side.

It only answers requests that carried something to read, and each one is still written to the log, so a real
fault hiding here can be found. A request with nothing in it that fails is a real fault, and stays a 500."""
import json
import logging
from decimal import InvalidOperation

from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.utils.translation import gettext as _
from django.views.defaults import page_not_found

logger = logging.getLogger("django.request")
UNREADABLE = (ValueError, OverflowError, InvalidOperation, ValidationError, json.JSONDecodeError)


class BadInputMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        carried = request.GET or request.POST or request.META.get("CONTENT_LENGTH") not in (None, "", "0")
        if not isinstance(exception, UNREADABLE) or not carried:
            return None
        logger.warning("Couldn't read a request: %s %s", request.method, request.path, exc_info=exception)
        if "/api/" in request.path:
            return JsonResponse({"ok": False, "error": _("That value can't be used here.")}, status=400)
        response = page_not_found(request, Http404())
        response.status_code = 404 if request.method == "GET" else 400
        return response
