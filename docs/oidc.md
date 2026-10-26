# Optional single sign-on (OIDC)

Off by default. When on, the login page gets a "Sign in with <provider>" button next to the password form. It works with any OpenID Connect provider that publishes a discovery document: Keycloak, Microsoft Entra ID, Google, Okta...

## How it works

Authorization-code flow with PKCE (S256), handled by the backend; the browser is only redirected.

1. `GET /api/v1/auth/oidc/login` creates a random `state`, `nonce` and PKCE verifier, stores them in a signed, `HttpOnly`, `SameSite=Lax` cookie (10 minutes, scoped to `/api/v1/auth/oidc`, `Secure` when the redirect URI is https) and redirects to the provider.
2. The provider redirects to `OIDC_REDIRECT_URI` (`/api/v1/auth/oidc/callback`). The backend checks `state` against the cookie, exchanges the code (sending the verifier and, if configured, the client secret), and verifies the ID token: **signature against the provider's JWKS** (asymmetric algorithms only, so `alg: none` and HS256-with-public-key are refused; one JWKS refetch on an unknown key id), **issuer**, **audience** (and `azp` when there are several), **expiry**, **issued-at**, and the **nonce**.
3. The user is found by the provider's subject, else by **verified e-mail**. An unverified or missing e-mail is refused. A user that does not exist is created only if `OIDC_AUTO_CREATE_USERS=true` (the account gets an unknown random password: it can only be entered through the provider).
4. The browser is redirected to the web app with a CiteSure token in the URL **fragment** (`/#oidc_token=...`; a fragment is never sent to a server or in a Referer), which the login page moves into the session and removes from the address bar. A failure redirects with `/#oidc_error=<code>`.

Every outcome is written to the audit log (`auth.oidc_login`, `auth.oidc_failed` with a reason code).

## Settings

| Variable | Meaning |
|---|---|
| `OIDC_ENABLED` | `true` turns the feature on (needs the three below) |
| `OIDC_ISSUER` | issuer URL, for example `https://keycloak.example/realms/acme`; discovery is read from `<issuer>/.well-known/openid-configuration` and its `issuer` must match exactly. `https` only (plain `http` only on a private network) |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | the client; leave the secret empty for a public client (PKCE only) |
| `OIDC_REDIRECT_URI` | `https://<your host>/api/v1/auth/oidc/callback`; register exactly this in the provider |
| `OIDC_SCOPES` | default `openid email profile` |
| `OIDC_GROUPS_CLAIM` | ID-token claim with group names, default `groups`; a dotted path such as `realm_access.roles` works |
| `OIDC_AUTO_CREATE_USERS` | create the local account on first login (default `false`) |
| `OIDC_REQUIRE_EMAIL_VERIFIED` | default `true`. Entra ID does not send `email_verified`; set `false` only if every account in your tenant has an address the tenant itself controls |
| `OIDC_ONLY` | `true` switches password login **and** registration off (`403`). Service accounts that use passwords, such as the MCP agent user, stop working |
| `OIDC_PROVIDER_NAME` | label on the button |
| `OIDC_POST_LOGIN_URL` | where the browser returns; default is the first `CORS_ORIGINS` entry. Behind one reverse proxy set your public URL |

The server refuses to start with `OIDC_ENABLED` and a missing issuer, client id or redirect URI, with `OIDC_ONLY` and OIDC off, or with a non-https public issuer. `GET /api/v1/auth/config` tells the login page what to show.

## Groups

Group names in the claim are matched to CiteSure groups that **already exist** in workspaces the user belongs to (a leading `/` is dropped, so Keycloak's `/hr` matches `hr`). Nothing is ever created from a claim. Memberships granted this way are remembered and **revoked** when the claim stops listing the group; memberships an admin added by hand are never touched. Because only workspaces the user already belongs to are considered, a newly added member gets their groups at their next login.

## Network: the provider is not on the egress allow-list

Discovery, JWKS and token requests go **directly** to the provider from the API container. They are not part of the public-research lane: `app/egress` and `deploy/egress/allowlist.txt` control what *company text* may leave, and nothing from your documents is ever sent to the identity provider. Consequences:

- **Normal deployment:** the API container needs outbound HTTPS to the provider.
- **Private mode:** the API has no route to the internet by design, so the provider has to run on the private network (a Keycloak container on the `internal` network, issuer like `http://keycloak:8080/realms/acme`). `PRIVATE_MODE` refuses to start with a public issuer. Do not add a public provider's host to the egress allow-list to get around this: that list is for scholarly sources and would also open the proxy for it.
- Keycloak behind two names (browser sees `localhost`, API sees `keycloak`) needs the provider's frontend URL set so the discovery `issuer` is the same for both.
- Multi-tenant Entra endpoints (`/common`) put a placeholder in the issuer and are not supported; use your tenant id.

## Keycloak quick start

Create a client (confidential, standard flow, PKCE S256), valid redirect URI `https://<host>/api/v1/auth/oidc/callback`; add a "Group Membership" mapper (claim `groups`, full group path off) to the client scope. Set the variables above.

## Tests

`tests/unit/test_oidc.py` and `tests/integration/test_oidc_flow.py` run against a mocked provider (`tests/idp.py`: `httpx.MockTransport` and a locally generated RSA key); they never touch the network.
