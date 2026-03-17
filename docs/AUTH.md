# Authentication And Access

PoundCake supports these auth sources at the same time in one install:

- Local superuser
- Active Directory
- Auth0
- Azure AD

The local superuser is the immutable recovery account. It is always managed from the PoundCake admin secret and is not controlled through normal RBAC bindings.

## Roles

- `reader`: read-only access across the UI, CLI, and API.
- `operator`: `reader` plus workflow, action, suppression, and alert-rule create/update/delete.
- `admin`: `operator` plus access management and all remaining configuration.
- `service`: internal PoundCake microservice role only. No UI or CLI login.

## Important Model

- Provider enablement is a deploy-time setting.
- The Access page manages RBAC bindings, not provider connections.
- External users only receive access after an `admin` creates a user or group binding.
- Observed-user bindings require the user to log in once first.
- Group bindings can be created before first login.

## Helm Configuration

Provider setup lives under `auth` in [helm/values.yaml](/Users/aedan/Documents/GitHub/poundcake/helm/values.yaml).
In the lab, the deploy-time override file is `/etc/genestack/helm-configs/poundcake/poundcake-helm-overrides.yaml`.

### Local Superuser

The local superuser is enabled by default:

```yaml
auth:
  enabled: true
  local:
    enabled: true
```

The credentials live in the generated admin secret:

```bash
kubectl get secret <release>-poundcake-admin -n <namespace> -o jsonpath='{.data.username}' | base64 -d; echo
kubectl get secret <release>-poundcake-admin -n <namespace> -o jsonpath='{.data.password}' | base64 -d; echo
```

The same secret also stores the service token under the `internal-api-key` key, which PoundCake uses as `X-Auth-Token`.

### Active Directory

Minimal configuration:

```yaml
auth:
  activeDirectory:
    enabled: true
    serverUri: "ldaps://ad.example.com:636"
    userBaseDn: "DC=example,DC=com"
    bindDn: "CN=poundcake,OU=Service Accounts,DC=example,DC=com"
    existingSecret: "poundcake-ad-auth"
```

Create the bind-password secret:

```bash
kubectl -n <namespace> create secret generic poundcake-ad-auth \
  --from-literal=bind-password='<bind-password>'
```

Optional CA bundle:

```yaml
auth:
  activeDirectory:
    caBundle:
      existingSecret: "poundcake-ad-ca"
      key: "ca.crt"
```

```bash
kubectl -n <namespace> create secret generic poundcake-ad-ca \
  --from-file=ca.crt=/path/to/ad-ca.crt
```

Useful AD knobs:

- `userFilter`
- `groupAttribute`
- `displayNameAttribute`
- `usernameAttribute`
- `subjectAttribute`
- `useSsl`
- `validateTls`
- `groupNameRegex`

By default, PoundCake extracts group names from the AD `CN=...` component.

### Auth0

PoundCake uses one Auth0 tenant with two applications:

- UI/browser login: `Regular Web Application`
- CLI/device login: `Native Application`

Minimal split-client configuration:

```yaml
auth:
  auth0:
    enabled: true
    shared:
      domain: "tenant.us.auth0.com"
      audience: "https://poundcake-api"
      scope: "openid profile email"
      organization: ""
      connection: ""
    ui:
      enabled: true
      clientId: "<regular-web-client-id>"
      callbackUrl: "https://poundcake.api.ord.cloudmunchers.net/api/v1/auth/oidc/callback"
      existingSecret: "poundcake-auth0-ui"
    cli:
      enabled: true
      clientId: "<native-client-id>"
      existingSecret: ""
```

Create the UI client-secret secret when your Auth0 web app is confidential:

```bash
kubectl -n <namespace> create secret generic poundcake-auth0-ui \
  --from-literal=client-secret='<client-secret>'
```

If your Auth0 native app policy also requires a client secret for device flow, create a second secret:

```bash
kubectl -n <namespace> create secret generic poundcake-auth0-cli \
  --from-literal=client-secret='<client-secret>'
```

Optional Auth0 shared settings:

- `scope`
- `organization`
- `connection`
- `usernameClaim`
- `displayNameClaim`
- `groupsClaim`
- `subjectClaim`

If `ui.callbackUrl` is blank, PoundCake derives the OIDC callback URL from the incoming request host.

### Auth0 App Settings For The Lab

For the lab host `https://poundcake.api.ord.cloudmunchers.net`:

- UI Auth0 app type: `Regular Web Application`
- CLI Auth0 app type: `Native Application`
- UI Allowed Callback URLs:
  - `https://poundcake.api.ord.cloudmunchers.net/api/v1/auth/oidc/callback`
- UI Allowed Logout URLs:
  - `https://poundcake.api.ord.cloudmunchers.net/`
- UI Allowed Web Origins:
  - `https://poundcake.api.ord.cloudmunchers.net`
- UI Allowed Origins (CORS):
  - `https://poundcake.api.ord.cloudmunchers.net`

For first lab validation, start with an Auth0 database connection and create three test users:

- `reader`
- `operator`
- `admin`

Those are Auth0 users only. PoundCake roles are granted later through Access bindings.

### Azure AD

PoundCake uses one single-tenant Azure AD / Microsoft Entra app registration set:

- UI/browser login: confidential web app registration
- CLI/device login: public/native client registration

Minimal split-client configuration:

```yaml
auth:
  azureAd:
    enabled: true
    shared:
      tenant: "11111111-1111-1111-1111-111111111111"
      scope: "openid profile email"
      audience: ""
    ui:
      enabled: true
      clientId: "<web-client-id>"
      callbackUrl: "https://poundcake.example.com/api/v1/auth/oidc/callback"
      existingSecret: "poundcake-azure-ui"
    cli:
      enabled: true
      clientId: "<native-client-id>"
```

Create the optional UI client-secret secret when your Azure web app is confidential:

```bash
kubectl -n <namespace> create secret generic poundcake-azure-ui \
  --from-literal=client-secret='<client-secret>'
```

Useful Azure AD knobs:

- `tenant`
- `scope`
- `audience`
- `usernameClaim`
- `displayNameClaim`
- `groupsClaim`
- `subjectClaim`

Important Azure AD notes:

- v1 is single-tenant only. Do not use `common` or `organizations`.
- Group-backed RBAC depends on the `groups` claim being emitted in the token.
- PoundCake does not call Microsoft Graph for group overage fallback in this version.
- If Azure AD omits group claims or returns overage markers, explicit user bindings still work after first login, but group bindings will not match.

### Combined Example

```yaml
auth:
  enabled: true
  sessionTimeout: 86400
  oidcStateTtl: 600
  local:
    enabled: true
  activeDirectory:
    enabled: true
    serverUri: "ldaps://ad.example.com:636"
    userBaseDn: "DC=example,DC=com"
    bindDn: "CN=poundcake,OU=Service Accounts,DC=example,DC=com"
    existingSecret: "poundcake-ad-auth"
  auth0:
    enabled: true
    shared:
      domain: "tenant.us.auth0.com"
      audience: "https://poundcake-api"
      organization: ""
      connection: ""
    ui:
      enabled: true
      clientId: "<regular-web-client-id>"
      callbackUrl: "https://poundcake.api.ord.cloudmunchers.net/api/v1/auth/oidc/callback"
      existingSecret: "poundcake-auth0-ui"
    cli:
      enabled: true
      clientId: "<native-client-id>"
      existingSecret: ""
  azureAd:
    enabled: true
    shared:
      tenant: "11111111-1111-1111-1111-111111111111"
      scope: "openid profile email"
    ui:
      enabled: true
      clientId: "<web-client-id>"
      callbackUrl: "https://poundcake.example.com/api/v1/auth/oidc/callback"
      existingSecret: "poundcake-azure-ui"
    cli:
      enabled: true
      clientId: "<native-client-id>"
```

Apply provider overrides using the normal install flow:

```bash
./install/install-poundcake-helm.sh \
  -f /etc/genestack/helm-configs/poundcake/poundcake-helm-overrides.yaml
```

## Granting Access

Once a provider is enabled:

1. Deploy PoundCake with the provider values and any required secrets.
2. Log in as the local superuser.
3. Open `Configuration -> Access`.
4. Create either:
   - a group binding, or
   - an observed-user binding

The Access page now includes help bubbles for:

- provider setup vs role binding
- group vs observed-user bindings
- role meaning
- operator/admin scope

You can do the same from the CLI:

```bash
poundcake --url https://poundcake.example.com auth bindings create \
  --provider active_directory \
  --type group \
  --role operator \
  --group monitoring-operators
```

Or inspect observed users first:

```bash
poundcake --url https://poundcake.example.com auth principals list --provider auth0
poundcake --url https://poundcake.example.com auth principals list --provider azure_ad
```

## UI And CLI Login

- Local superuser: username/password form
- Active Directory: username/password form
- Auth0 in UI: browser redirect flow through the Auth0 regular web app
- Auth0 in CLI: device login flow through the Auth0 native app
- Azure AD in UI: browser redirect flow through the Azure AD web app
- Azure AD in CLI: device login flow through the Azure AD native app

Useful CLI commands:

```bash
poundcake --url https://poundcake.example.com auth providers
poundcake --url https://poundcake.example.com auth login --provider local --username admin
poundcake --url https://poundcake.example.com auth login --provider active_directory --username alice
poundcake --url https://poundcake.example.com auth login --provider auth0
poundcake --url https://poundcake.example.com auth login --provider azure_ad
poundcake --url https://poundcake.example.com auth me
```

## Internal Services

Internal PoundCake services authenticate to `poundcake-api` with `X-Auth-Token`.

The shared token is exposed to workloads as `POUNDCAKE_AUTH_SERVICE_TOKEN`, and Helm persists it in the admin secret:

```bash
kubectl get secret <release>-poundcake-admin -n <namespace> -o jsonpath='{.data.internal-api-key}' | base64 -d; echo
```

## Troubleshooting

- If Access shows no external providers, check your deployed `auth.activeDirectory.*`, `auth.auth0.*`, and `auth.azureAd.*` Helm values.
- If Access shows no observed users, the user has not logged in successfully yet.
- If the UI does not show an Auth0 button, confirm `auth.auth0.ui.enabled=true` and `auth.auth0.ui.clientId` are set.
- If `poundcake auth login --provider auth0` is rejected, confirm `auth.auth0.cli.enabled=true` and `auth.auth0.cli.clientId` are set.
- If Auth0 browser login loops, verify the public host, callback URL, and Auth0 application type.
- If the UI does not show an Azure AD button, confirm `auth.azureAd.ui.enabled=true`, `auth.azureAd.ui.clientId`, and `auth.azureAd.shared.tenant` are set.
- If `poundcake auth login --provider azure_ad` is rejected, confirm `auth.azureAd.cli.enabled=true`, `auth.azureAd.cli.clientId`, and `auth.azureAd.shared.tenant` are set.
- If Azure AD group bindings never match, verify the app registration is emitting `groups` claims and the token is not returning group overage markers.
- If AD login fails, verify `serverUri`, `userBaseDn`, bind credentials, and CA bundle/TLS settings.
- If workers return `401`, confirm `POUNDCAKE_AUTH_SERVICE_TOKEN` is wired to every PoundCake worker and the API.
