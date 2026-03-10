from django.utils.deprecation import MiddlewareMixin

from django.conf import settings


class ImpersonationMiddleware(MiddlewareMixin):
    """
    Allows a superuser to impersonate another user for the duration of the
    session. The ID of the impersonated user is stored in
    request.session['impersonated_user_id'].

    Security rules:
    - Only a real superuser can initiate impersonation (enforced in the view).
    - On each request, we only override request.user if the *current* user is
      authenticated and is_superuser, and the session flag is present.
    - If the current user is not a superuser but the flag is still present, the
      flag is cleared as a safety measure.
    """

    def process_request(self, request):
        # AuthenticationMiddleware must run before this, so request.user exists.
        user = getattr(request, "user", None)
        impersonated_id = request.session.get("impersonated_user_id")

        # If no impersonation requested, nothing to do.
        if not impersonated_id:
            return

        # If the current authenticated user is not a superuser, clear the flag.
        if not (user and user.is_authenticated and user.is_superuser):
            request.session.pop("impersonated_user_id", None)
            return

        # At this point, user is the real superuser.
        from user.models import CustomUser

        try:
            impersonated_user = CustomUser.objects.get(pk=impersonated_id)
        except CustomUser.DoesNotExist:
            request.session.pop("impersonated_user_id", None)
            return

        # Expose both identities on the request for views/templates.
        request.real_user = user
        request.impersonated_user = impersonated_user
        # Override request.user for downstream views, permissions, templates, etc.
        request.user = impersonated_user

