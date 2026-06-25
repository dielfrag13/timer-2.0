from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """
    Extends the standard header-based JWT auth to also accept the access token
    from the 'timer_access' httpOnly cookie set by CookieTokenObtainPairView.

    Priority: Authorization header first (keeps API clients and all existing
    tests working unchanged), then cookie (for the browser SPA).
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            return result

        raw_token = request.COOKIES.get('timer_access')
        if not raw_token:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except Exception:
            return None
