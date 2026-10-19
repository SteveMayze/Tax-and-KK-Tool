from django.conf import settings


class StripUrlPrefixMiddleware:
    """Accept URLs that still carry the URL prefix (FORCE_SCRIPT_NAME), as well as ones the proxy already stripped.

    With FORCE_SCRIPT_NAME set, Django generates /prefix/... URLs but routes on the path it is given. A proxy that
    strips the prefix needs nothing; a client that reaches the app directly (the app's own port) sends the prefix,
    which is removed here. Must be the first middleware. Does nothing when no prefix is configured.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        prefix = (settings.FORCE_SCRIPT_NAME or '').rstrip('/')
        if prefix and (request.path_info == prefix or request.path_info.startswith(prefix + '/')):
            request.path_info = request.path_info[len(prefix):] or '/'
            request.path = prefix + request.path_info
        return self.get_response(request)
