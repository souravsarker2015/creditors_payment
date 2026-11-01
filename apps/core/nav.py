"""Going back to where someone came from."""
from django.utils.http import url_has_allowed_host_and_scheme


def back_to(request, url, fallback):
    """`url` (a ?next=, a form's next…) if it's a page of this site, else `fallback`. Never another site, and
    never a javascript: address: this also ends up in the href of a "Back" link."""
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return fallback
