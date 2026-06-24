# Milestone 3 — Implementation Steps

Concrete steps for implementing authentication, per-user data isolation,
and audit logging. Each step is independent enough to be committed separately.

---

## Step 1 — Install `djangorestframework-simplejwt`

Add to `requirements.txt` and install into the venv:

```
djangorestframework-simplejwt
```

The token blacklist feature (needed for logout) ships inside this package but
requires its own Django app (`rest_framework_simplejwt.token_blacklist`), which
is wired up in Step 3.

---

## Step 2 — New migration: `User → Surgeon` one-to-one field

Add a nullable `OneToOneField(settings.AUTH_USER_MODEL)` to the `Surgeon` model:

```python
user = models.OneToOneField(
    settings.AUTH_USER_MODEL,
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name='surgeon',
)
```

Nullable so existing surgeon rows are not broken. The link is created by an
admin when setting up a surgeon's account — there is no self-registration path.

Generate and apply the migration:

```bash
python manage.py makemigrations timer
python manage.py migrate
```

---

## Step 3 — Update `settings.py`

Three changes:

1. Add `rest_framework_simplejwt.token_blacklist` to `INSTALLED_APPS`.

2. Update the `REST_FRAMEWORK` block:
   ```python
   'DEFAULT_AUTHENTICATION_CLASSES': [
       'rest_framework_simplejwt.authentication.JWTAuthentication',
   ],
   'DEFAULT_PERMISSION_CLASSES': [
       'rest_framework.permissions.IsAuthenticated',
   ],
   ```

3. Add a `SIMPLE_JWT` config block:
   ```python
   from datetime import timedelta

   SIMPLE_JWT = {
       'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
       'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
       'ROTATE_REFRESH_TOKENS': True,
       'BLACKLIST_AFTER_ROTATION': True,
   }
   ```

After this step, all non-health endpoints will require a valid bearer token.
The `GET /health/` endpoint is kept open in Step 6.

---

## Step 4 — Custom login view

Subclass `TokenObtainPairView` to emit `timer.audit` events on both login
success and failure. The event must include the source IP so failed login
attempts are traceable:

```python
# success event fields: event, username, user_id, ip
# failure event fields: event, username, ip
```

The source IP is read from `X-Forwarded-For` if present (K8s Ingress sets this),
falling back to `REMOTE_ADDR`.

Override `post()`, call `super()`, and emit the appropriate audit event based on
whether the response succeeded or a `TokenError` / `ValidationError` was raised.

---

## Step 5 — Logout view

A simple `APIView` (requires authentication) that:

1. Reads the refresh token from the request body.
2. Blacklists it via `rest_framework_simplejwt.token_blacklist` so it cannot
   be used to obtain a new access token.
3. Emits a `timer.audit` logout event with `user_id` and IP.
4. Returns HTTP 204.

If the token is already blacklisted or invalid, return HTTP 400 with a
descriptive error.

---

## Step 6 — Wire up auth URLs

Add three new routes to `timer_server/urls.py`:

| Method | URL | View |
|--------|-----|------|
| `POST` | `/api/v1/auth/login/` | Custom login view (Step 4) |
| `POST` | `/api/v1/auth/refresh/` | `TokenRefreshView` (SimpleJWT built-in) |
| `POST` | `/api/v1/auth/logout/` | Custom logout view (Step 5) |

The existing `GET /health/` view must be explicitly exempted from the
`IsAuthenticated` default by decorating it with
`@permission_classes([AllowAny])` or switching it to a class-based view with
`permission_classes = [AllowAny]`.

---

## Step 7 — Per-user data isolation in ViewSets

Override `get_queryset()` in two ViewSets:

**`OperationInstanceViewSet`:**
- If `request.user.is_staff`: return the full queryset (admin sees everything).
- Otherwise: filter to `surgeon__user=request.user`.

**`StepInstanceViewSet`:**
- If `request.user.is_staff`: return the full queryset.
- Otherwise: filter to `operation_instance__surgeon__user=request.user`.

For the reference-data ViewSets (`SurgeonViewSet`, `OperationTypeViewSet`,
`StepViewSet`), restrict write operations to `is_staff` users only by setting
a custom `get_permissions()` that returns `IsAdminUser` for unsafe methods and
`IsAuthenticated` for safe methods.

---

## Step 8 — Audit logging for OperationInstance mutations

Override three methods in `OperationInstanceViewSet`:

```python
def perform_create(self, serializer):
    instance = serializer.save()
    audit_logger.info('operation_create', extra={
        'user_id': self.request.user.id,
        'operation_instance_id': instance.pk,
        ...
    })

def perform_update(self, serializer):
    instance = serializer.save()
    audit_logger.info('operation_update', extra={...})

def perform_destroy(self, instance):
    audit_logger.info('operation_delete', extra={
        'user_id': self.request.user.id,
        'operation_instance_id': instance.pk,
    })
    instance.delete()
```

Also update the existing `complete` action, which already has a
`# M3 will add request.user.id here` placeholder, to include
`'user_id': request.user.id` in the audit event.

---

## Step 9 — Update Django Admin

Add a `UserInline` (StackedInline) to `SurgeonAdmin` so a superuser can create
or link a Django `User` account directly from the Surgeon change page. This
keeps account creation entirely inside the admin — there is no public
registration endpoint in 2.0.

```python
class UserInline(admin.StackedInline):
    model = User  # via the OneToOneField on Surgeon
    ...

class SurgeonAdmin(admin.ModelAdmin):
    inlines = [UserInline]
```

---

## Step 10 — Add tests

New test file `timer/tests/test_auth.py` covering:

| Test | Expected result |
|------|----------------|
| Unauthenticated `GET /api/v1/surgeons/` | 401 |
| Unauthenticated `GET /health/` | 200 (health stays open) |
| Login with valid credentials | 200, `access` and `refresh` tokens returned |
| Login with wrong password | 401, audit log emits failure event |
| Token refresh with valid refresh token | 200, new `access` token returned |
| Logout with valid refresh token | 204, token blacklisted |
| Logout then refresh (blacklisted token) | 401 |
| Surgeon A cannot list Surgeon B's operations | 200 with empty results |
| Surgeon A cannot retrieve Surgeon B's operation | 404 |
| `is_staff` user sees all operations | 200 with all results |
| `perform_create` emits audit event | audit log contains `operation_create` |
| `perform_update` emits audit event | audit log contains `operation_update` |
| `perform_destroy` emits audit event | audit log contains `operation_delete` |
| `complete` action emits audit event with `user_id` | audit log contains `user_id` |

---

## Step 11 — Update `milestones.md` and add running-and-testing doc

- Mark Milestone 3 as **Complete** in `documentation/milestones.md`.
- Create `documentation/milestone-3/running-and-testing.md` covering JWT
  workflow, auth endpoint curl examples, data isolation verification, and
  audit log verification — in the same format as the Milestone 1 and 2 docs.
