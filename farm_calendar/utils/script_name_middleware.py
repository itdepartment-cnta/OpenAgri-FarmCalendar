from django.urls import set_script_prefix


class ScriptNameMiddleware:
    """
    Read the X-Script-Name header set by the reverse proxy (nginx) and call
    set_script_prefix() so that {% url %} template tags and reverse() produce
    URLs that include the sub-path prefix (e.g. /farmcalendar/farms/).

    This must be listed FIRST in MIDDLEWARE so the prefix is set before any
    other middleware or view generates redirects or renders templates.

    Note: Django's StaticFilesHandler runs before all middleware and is not
    affected by this — static file serving remains unbroken.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        script_name = request.META.get("HTTP_X_SCRIPT_NAME", "").rstrip("/")
        if script_name:
            set_script_prefix(script_name)
        return self.get_response(request)
