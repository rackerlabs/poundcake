# Auth0 Configuration

This guide covers the override-file deployment path for enabling Auth0 in PoundCake.

Use this when you want:

- UI/browser login through Auth0
- CLI/device login through Auth0
- RBAC bindings for Auth0 users or groups after first login

## Assumptions

- PoundCake is deployed into a Kubernetes environment.
- The active auth override file is `/etc/poundcake/helm-configs/poundcake/20-auth-overrides.yaml`.
- PoundCake is published at `https://<poundcake-public-url-host>`.
- The PoundCake namespace is `<namespace>`.

## What Auth0 Objects You Need

PoundCake expects one Auth0 tenant and usually two applications:

- UI/browser login: `Regular Web Application`
- CLI/device login: `Native Application`

You can enable only UI or only CLI, but if both are enabled they should be configured together in the same override file.

## 1. Create The Auth0 Applications

For the UI app:

- Application type: `Regular Web Application`
- Allowed Callback URLs:
  - `https://<poundcake-public-url-host>/api/v1/auth/oidc/callback`
- Allowed Logout URLs:
  - `https://<poundcake-public-url-host>/`
- Allowed Web Origins:
  - `https://<poundcake-public-url-host>`
- Allowed Origins (CORS):
  - `https://<poundcake-public-url-host>`

For the CLI app:

- Application type: `Native Application`
- Device flow enabled in Auth0

Collect these values:

- Auth0 domain
- UI client ID
- UI client secret
- CLI client ID
- optional CLI client secret if your Auth0 policy requires one for device flow

## 2. Write The Auth Override File

Create or update `/etc/poundcake/helm-configs/poundcake/20-auth-overrides.yaml`:

```yaml
auth:
  enabled: true
  local:
    enabled: true
  auth0:
    enabled: true
    shared:
      domain: "<auth0-domain>"
      audience: "<auth0-audience-or-empty>"
      scope: "openid profile email"
      organization: ""
      connection: ""
      usernameClaim: "email"
      displayNameClaim: "name"
      groupsClaim: "groups"
      subjectClaim: "sub"
    ui:
      enabled: true
      clientId: "<auth0-ui-client-id>"
      callbackUrl: "https://<poundcake-public-url-host>/api/v1/auth/oidc/callback"
      existingSecret: "poundcake-auth0-ui"
    cli:
      enabled: true
      clientId: "<auth0-cli-client-id>"
      existingSecret: ""
```

Notes:

- If `ui.callbackUrl` is left blank, PoundCake can derive it from the request host, but using the explicit public URL is clearer in multi-host deployments.
- Leave `organization` and `connection` empty unless your tenant requires them.
- If you do not need CLI device login, set `auth.auth0.cli.enabled: false`.
- If you do not need UI login, set `auth.auth0.ui.enabled: false`.

## 3. Create The Required Secrets

Create the UI client-secret secret:

```bash
kubectl -n <namespace> create secret generic poundcake-auth0-ui \
  --from-literal=client-secret='<auth0-ui-client-secret>'
```

If your Auth0 native application also needs a client secret for device login, create:

```bash
kubectl -n <namespace> create secret generic poundcake-auth0-cli \
  --from-literal=client-secret='<auth0-cli-client-secret>'
```

Then set this in `20-auth-overrides.yaml`:

```yaml
auth:
  auth0:
    cli:
      existingSecret: "poundcake-auth0-cli"
```

## 4. Reinstall PoundCake

```bash
./install/install-poundcake-helm.sh
```

## 5. Verify Provider Configuration

Check the rendered values:

```bash
helm get values <release-name> -n <namespace> -o yaml
```

Things to confirm:

- `auth.auth0.enabled: true`
- `auth.auth0.shared.domain: <auth0-domain>`
- `auth.auth0.ui.enabled: true`
- `auth.auth0.ui.clientId: <auth0-ui-client-id>`
- `auth.auth0.cli.enabled: true` if CLI device login is desired
- `auth.auth0.cli.clientId: <auth0-cli-client-id>` if CLI device login is desired

Check that the provider appears:

```bash
curl -fsS https://<poundcake-public-url-host>/api/v1/auth/providers
poundcake --url https://<poundcake-public-url-host> auth providers
```

## 6. Test UI And CLI Login

UI login:

- Open `https://<poundcake-public-url-host>/login`
- Choose `Auth0`
- Complete the browser login

CLI device login:

```bash
poundcake --url https://<poundcake-public-url-host> auth login --provider auth0
poundcake --url https://<poundcake-public-url-host> auth me
```

## 7. Grant RBAC Access

Auth0 login only proves identity. PoundCake roles still come from Access bindings.

After the user logs in once, an admin can:

- create a group binding ahead of time, or
- create an observed-user binding after the first login

UI path:

- Open `Configuration -> Access`
- Create the needed `reader`, `operator`, or `admin` binding

CLI examples:

```bash
poundcake --url https://<poundcake-public-url-host> auth principals list --provider auth0

poundcake --url https://<poundcake-public-url-host> auth bindings create \
  --provider auth0 \
  --type group \
  --role operator \
  --group <auth0-group-name>
```

## Troubleshooting

- If the UI does not show an Auth0 button, verify `auth.auth0.enabled=true`, `auth.auth0.ui.enabled=true`, and `auth.auth0.ui.clientId` are set.
- If CLI device login is rejected, verify `auth.auth0.cli.enabled=true` and `auth.auth0.cli.clientId` are set.
- If browser login loops, verify the public host, callback URL, and Auth0 application type.
- If group bindings do not match, verify Auth0 is emitting the claim named by `auth.auth0.shared.groupsClaim`.
