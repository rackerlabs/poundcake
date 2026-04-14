# Azure AD Configuration

This guide covers the override-file deployment path for enabling Azure AD / Microsoft Entra authentication in PoundCake.

Use this when you want:

- UI/browser login through Azure AD
- CLI/device login through Azure AD
- RBAC bindings for Azure AD users or groups after first login

## Assumptions

- PoundCake is deployed into a Kubernetes environment.
- The active auth override file is `/etc/poundcake/helm-configs/poundcake/20-auth-overrides.yaml`.
- PoundCake is published at `https://<poundcake-public-url-host>`.
- The PoundCake namespace is `<namespace>`.

## Important Azure AD Model

- PoundCake currently expects a single-tenant Azure AD deployment.
- Use a specific tenant ID, not `common` or `organizations`.
- Group-backed RBAC depends on Azure AD emitting `groups` claims in the token.
- PoundCake does not call Microsoft Graph for group overage fallback in this version.

## 1. Create The Azure AD App Registrations

PoundCake usually uses two Azure AD applications:

- UI/browser login: confidential web app registration
- CLI/device login: public/native client registration

For the UI app:

- Redirect URI:
  - `https://<poundcake-public-url-host>/api/v1/auth/oidc/callback`
- Create a client secret if you are using a confidential web app registration

For the CLI app:

- Enable device code / public client flow
- Collect the client ID

Collect these values:

- Azure tenant ID
- UI client ID
- UI client secret if used
- CLI client ID

If you want group-based RBAC, configure the app registration to emit `groups` claims.

## 2. Write The Auth Override File

Create or update `/etc/poundcake/helm-configs/poundcake/20-auth-overrides.yaml`:

```yaml
auth:
  enabled: true
  local:
    enabled: true
  azureAd:
    enabled: true
    shared:
      tenant: "<azure-tenant-id>"
      audience: ""
      scope: "openid profile email"
      usernameClaim: "preferred_username"
      displayNameClaim: "name"
      groupsClaim: "groups"
      subjectClaim: "sub"
    ui:
      enabled: true
      clientId: "<azure-ui-client-id>"
      callbackUrl: "https://<poundcake-public-url-host>/api/v1/auth/oidc/callback"
      existingSecret: "poundcake-azure-ui"
    cli:
      enabled: true
      clientId: "<azure-cli-client-id>"
```

Notes:

- `tenant` must be a specific tenant identifier.
- If you do not need CLI device login, set `auth.azureAd.cli.enabled: false`.
- If you do not need UI login, set `auth.azureAd.ui.enabled: false`.

## 3. Create The UI Client Secret

For the recommended confidential web app path:

```bash
kubectl -n <namespace> create secret generic poundcake-azure-ui \
  --from-literal=client-secret='<azure-ui-client-secret>'
```

If your Azure AD browser app does not use a client secret, leave `auth.azureAd.ui.existingSecret` empty.

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

- `auth.azureAd.enabled: true`
- `auth.azureAd.shared.tenant: <azure-tenant-id>`
- `auth.azureAd.ui.enabled: true`
- `auth.azureAd.ui.clientId: <azure-ui-client-id>`
- `auth.azureAd.cli.enabled: true` if CLI device login is desired
- `auth.azureAd.cli.clientId: <azure-cli-client-id>` if CLI device login is desired

Check that the provider appears:

```bash
curl -fsS https://<poundcake-public-url-host>/api/v1/auth/providers
poundcake --url https://<poundcake-public-url-host> auth providers
```

## 6. Test UI And CLI Login

UI login:

- Open `https://<poundcake-public-url-host>/login`
- Choose `Azure AD`
- Complete the browser login

CLI device login:

```bash
poundcake --url https://<poundcake-public-url-host> auth login --provider azure_ad
poundcake --url https://<poundcake-public-url-host> auth me
```

## 7. Grant RBAC Access

Azure AD authentication proves identity, but PoundCake roles still come from Access bindings.

UI path:

- Open `Configuration -> Access`
- Create the needed `reader`, `operator`, or `admin` binding

CLI examples:

```bash
poundcake --url https://<poundcake-public-url-host> auth principals list --provider azure_ad

poundcake --url https://<poundcake-public-url-host> auth bindings create \
  --provider azure_ad \
  --type group \
  --role operator \
  --group <azure-ad-group-name>
```

## Troubleshooting

- If the UI does not show an Azure AD button, verify `auth.azureAd.enabled=true`, `auth.azureAd.ui.enabled=true`, `auth.azureAd.ui.clientId`, and `auth.azureAd.shared.tenant`.
- If CLI device login is rejected, verify `auth.azureAd.cli.enabled=true` and `auth.azureAd.cli.clientId`.
- If Azure AD group bindings do not match, verify the app registration is emitting `groups` claims and not only group overage markers.
- If login fails unexpectedly, confirm the redirect URI and tenant are correct and that you are not using `common` or `organizations`.
