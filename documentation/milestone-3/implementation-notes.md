# Milestone 3 — Implementation Notes

Deviations from the original plan, unexpected problems, and how they were resolved.

---

- **Admin inline direction was reversed (Step 9)**

  The plan called for a `UserInline` on `SurgeonAdmin` so an admin could create a
  login account from the Surgeon page. This is backwards: Django inlines require the
  child model to hold the ForeignKey (or OneToOneField) to the parent. Since the
  `OneToOneField` lives on `Surgeon` pointing to `User`, `Surgeon` is the child —
  so the inline must go on `UserAdmin`, not `SurgeonAdmin`.

  **Fix:** Created `SurgeonInline` (model = `Surgeon`) and attached it to a
  `CustomUserAdmin` subclass of `UserAdmin`. Admins now create a User account
  first and fill in the Surgeon profile (first name, last name, email) inline on
  the same page. Also required calling `admin.site.unregister(User)` before
  re-registering with `CustomUserAdmin`, since Django's auth app registers
  `UserAdmin` automatically at startup.

- **`GET /health/` had to be converted from a plain Django view to a DRF view (Step 6)**

  The plan said to decorate `health` with `@permission_classes([AllowAny])` to
  exempt it from the global `IsAuthenticated` default. That decorator only works
  on DRF views — the original `health` function was a plain Django view returning
  a `JsonResponse`, which DRF's permission system never touches.

  **Fix:** Added `@api_view(['GET'])` and `@permission_classes([AllowAny])` to
  `health` in `timer_server/urls.py`, making it a proper DRF view. The response
  body is unchanged (`{"status": "ok"}`).

- **Enabling `IsAuthenticated` broke all 51 existing tests; test fixtures required a two-phase fix (Steps 3 and 7)**

  Step 3 switched the global permission class to `IsAuthenticated`, which
  immediately caused every existing API test to return 401. The plan noted that
  tests would need updating but didn't anticipate the full scope.

  **Phase 1 (Step 3):** Moved `api_client` out of `test_api.py` and into
  `conftest.py` as an unauthenticated fixture (for future 401 tests). Added
  `user`, `auth_client`, `admin_user`, and `admin_client` fixtures to
  `conftest.py`. Replaced the local `api_client` fixture in `test_api.py` with
  `auth_client` (a force-authenticated regular user).

  **Phase 2 (Step 7):** After implementing per-user data isolation,
  `auth_client` (a standard user with no linked surgeon) could no longer see any
  `OperationInstance` or `StepInstance` records, breaking those tests again. The
  existing tests cover API correctness, not isolation, so the right client for
  them is one that bypasses all filters. Switched `test_api.py` from `auth_client`
  to `admin_client` (`is_staff=True`), which sees the full queryset. Isolation
  behaviour will be exercised explicitly in `test_auth.py` (Step 10).
