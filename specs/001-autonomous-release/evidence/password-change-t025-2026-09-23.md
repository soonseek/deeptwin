# T025 tail — password change and revoke-others (2026-09-23)

## What landed

### Server

`PersistentOwnerAuthority.change_password` and `revoke_others`, exposed as `POST session/password`
and `POST session/revoke-others`. The web boundary admits exact bodies only: the two password
fields, bounded like login; and an empty body or the empty object.

- **`change_password`**:
  - The session must be CSRF-verified and bound.
  - The current password is re-verified with the owner's authenticator, and the new password is
    hashed. Both run as **one** operation of the single Argon2 lane, through the same source and
    account rate buckets as login.
  - One writer then does three things:
    - seals the next authenticator revision (the `previous_revision` chain)
    - advances the account's `auth_epoch`, so every earlier session stops authenticating — other
      browsers and this browser's old cookie alike
    - issues this browser a fresh session on the new authenticator, with `session.revoked` and
      `session.created` events
  - The response carries the rotated CSRF value and sets the new cookie.
  - If the state moved underneath (another change, or a login), the result is `conflict`.
  - A lost response leaves the new password in force (api.md: rotation after a password change;
    re-entry by password login).
- **`revoke_others`** revokes every other unrevoked session of the owner, keeps this one, and
  reports the count.
- No private-auth schema change was needed. The existing CHECKs, the authenticator chain and the
  account epoch carry both operations.

### GUI

`app/static/account.mjs` is mounted on the records page as "계정과 세션".

- The ≥15-scalar rule, the mismatch check and the same-as-current check all run before any
  request.
- The password fields are cleared after every attempt; passwords are never stored or echoed.
- The rotated CSRF value is adopted through the new `session.mjs` `adopt()`.

## Observed

- `test_owner_password_change.py` **4 passed**:
  - Old sessions in another browser end; this browser continues; the old password no longer
    logs in.
  - The new password logs in, tested on its own server because login shares bounded buckets.
  - A wrong current password gets 401. A short, unchanged or extra-field body gets 400. A request
    without CSRF is refused.
  - Revoke-others ends one other session and keeps this one; a second call reports 0.
- `account.test.mjs` **4 passed**. The session, records-page, assets, session-mirror and
  owner-integration suites passed too (108).

## Still open in T025

The offline bootstrap page's vectors, the intake screen's §5.1.4 guidance, and the browser case.

## Browser case (same day)

`app/tests/browser-owner-lifecycle-t025.test.mjs` runs in real Chromium against the real supported
server (`app/tests/fixtures/owner_lifecycle_server.py`). **1 passed.**

1. The offline `deploy/bootstrap/index.html` is opened from `file://`. It makes no network request
   at all, and it generates the one-time capability and the non-secret block. The block does not
   contain the capability.
2. The server starts from that block alone and verifies it is the exact canonical block. The raw
   capability never reaches the server process.
3. The owner types the capability into the first screen, chooses a password, and lands on the
   work screen. A second browser logs in.
4. On the records page, "다른 세션 모두 끝내기" ends the second browser's session, which then gets
   401.
5. The password change succeeds, and the form fields are left empty.
6. The next command in this browser succeeds with the adopted CSRF value, and reports no other
   session.
7. The old password gets 401; the new one gets 200.

This case found a real defect: sessions voided by the epoch were still counted as "other sessions".
Fixes:

- A password change now also marks every earlier session revoked.
- Revoke-others counts only sessions that still authenticate: same epoch, not expired.

## Still open in T025 (re-checked 2026-09-23)

The offline bootstrap vectors and the §5.1.4 intake guidance were already implemented:
`test_bootstrap_delivery.py` has 14 passing tests and `bootstrap-helper.test.mjs` has 8, and
`work.mjs` carries the notices. The browser case is now done.

What remains is the deployment-authority recovery port: `app/services/deployment_control.py`,
`app/operations/deployment_control.py`, the typed `credential_client.py`, and their tests
(`test_deployment_control.py`, `test_owner_sessions.py`, `test_session_security.py`). That covers
the request-bound signed-receipt recovery with a strictly higher epoch and atomic revocation.
