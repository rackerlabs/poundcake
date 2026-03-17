import {
  createContext,
  type FocusEvent,
  type FormEvent,
  useContext,
  useDeferredValue,
  useEffect,
  useId,
  useState,
  startTransition,
} from "react";
import {
  Link,
  NavLink,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import {
  apiFetch,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  ApiError,
} from "./api";
import {
  compactJson,
  formatDate,
  formatLongDate,
  statusTone,
  titleize,
} from "./format";
import type {
  AppSettings,
  AuthMeRecord,
  AuthPrincipalRecord,
  AuthProviderRecord,
  AuthRoleBindingRecord,
  CommunicationActivityRecord,
  CommunicationPolicyRecord,
  CommunicationRouteRecord,
  DishRecord,
  HealthResponse,
  IncidentTimelineResponse,
  IncidentTimelineEvent,
  ObservabilityActivityRecord,
  ObservabilityOverviewResponse,
  OrderResponse,
  PrometheusRule,
  PrometheusRuleListResponse,
  RecipeRecord,
  StatsResponse,
  SuppressionRecord,
  IngredientRecord,
} from "./types";

const SettingsContext = createContext<AppSettings | null>(null);
const PrincipalContext = createContext<AuthMeRecord | null>(null);
const ToastContext = createContext<(tone: "success" | "error", message: string) => void>(
  () => undefined,
);

interface DeleteResponse {
  status: string;
  message?: string | null;
}

interface ToastMessage {
  id: number;
  tone: "success" | "error";
  message: string;
}

const ruleSchema = z.object({
  name: z.string().min(1, "Rule name is required"),
  group: z.string().min(1, "Group name is required"),
  file: z.string().min(1, "Rule file or CRD is required"),
  expr: z.string().min(1, "PromQL expression is required"),
  duration: z.string().optional(),
  labels: z.string().optional(),
  annotations: z.string().optional(),
});

const workflowStepSchema = z.object({
  ingredient_id: z.coerce.number().min(1, "Choose an action"),
  step_order: z.coerce.number().min(1),
  on_success: z.string().min(1),
  run_phase: z.string().min(1),
  run_condition: z.string().min(1),
  parallel_group: z.coerce.number().min(0),
  depth: z.coerce.number().min(0),
  execution_parameters_override_text: z.string().optional(),
});

const communicationRouteSchema = z.object({
  id: z.string().optional(),
  label: z.string().min(1, "Route label is required"),
  execution_target: z.string().min(1, "Provider is required"),
  destination_target: z.string().optional(),
  provider_config: z.record(z.any()).default({}),
  enabled: z.boolean(),
  position: z.coerce.number().min(1),
});

const workflowSchema = z.object({
  name: z.string().min(1, "Workflow name is required"),
  description: z.string().optional(),
  enabled: z.boolean(),
  clear_timeout_sec: z.string().optional(),
  recipe_ingredients: z.array(workflowStepSchema).min(1, "Add at least one action"),
  communications_mode: z.enum(["inherit", "local"]),
  communications_routes: z.array(communicationRouteSchema),
});

const actionSchema = z.object({
  template: z.enum(["ticket", "chat", "remediation", "custom"]),
  task_key_template: z.string().min(1, "Action name is required"),
  execution_target: z.string().min(1, "Target is required"),
  destination_target: z.string().optional(),
  execution_engine: z.string().min(1, "Execution engine is required"),
  execution_purpose: z.string().min(1, "Purpose is required"),
  execution_id: z.string().optional(),
  is_blocking: z.boolean(),
  on_failure: z.string().min(1),
  expected_duration_sec: z.coerce.number().min(1),
  timeout_duration_sec: z.coerce.number().min(1),
  retry_count: z.coerce.number().min(0),
  retry_delay: z.coerce.number().min(0),
  execution_payload_text: z.string().optional(),
  execution_parameters_text: z.string().optional(),
});

const suppressionSchema = z.object({
  name: z.string().min(1, "Suppression name is required"),
  reason: z.string().optional(),
  starts_at: z.string().min(1, "Start time is required"),
  ends_at: z.string().min(1, "End time is required"),
  scope: z.string().min(1),
  summary_ticket_enabled: z.boolean(),
  matcher_key: z.string().optional(),
  matcher_operator: z.string().min(1),
  matcher_value: z.string().optional(),
});

const communicationsPolicySchema = z.object({
  routes: z.array(communicationRouteSchema),
});

const communicationTargetOptions = [
  "rackspace_core",
  "teams",
  "discord",
  "servicenow",
  "jira",
  "github",
  "pagerduty",
] as const;

function App() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  function notify(tone: "success" | "error", message: string) {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, tone, message }]);
  }

  useEffect(() => {
    if (!toasts.length) {
      return;
    }
    const timers = toasts.map((toast) =>
      window.setTimeout(() => {
        setToasts((current) => current.filter((item) => item.id !== toast.id));
      }, 3800),
    );
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [toasts]);

  return (
    <ToastContext.Provider value={notify}>
      <SessionGate />
      <div className="toast-stack" aria-live="polite" aria-atomic="true">
        {toasts.map((toast) => (
          <div className={`toast-card ${toast.tone}`} key={toast.id}>
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function SessionGate() {
  const location = useLocation();

  if (isLoginPath(location.pathname)) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  const bootstrapQuery = useQuery({
    queryKey: ["settings", "auth-me"],
    queryFn: async () => {
      const [settings, principal] = await Promise.all([
        apiGet<AppSettings>("/api/v1/settings"),
        apiGet<AuthMeRecord>("/api/v1/auth/me"),
      ]);
      return { settings, principal };
    },
  });

  if (bootstrapQuery.isLoading) {
    return <FullscreenState title="Loading monitoring console" message="Checking session and loading workspace state." />;
  }

  if (bootstrapQuery.isError || !bootstrapQuery.data) {
    if (bootstrapQuery.error instanceof ApiError && bootstrapQuery.error.status === 401) {
      const nextTarget = `${location.pathname}${location.search}${location.hash}`;
      return <Navigate to={`/login?next=${encodeURIComponent(nextTarget)}`} replace />;
    }
    return (
      <FullscreenState
        title="Unable to load PoundCake"
        message={getErrorMessage(bootstrapQuery.error)}
        tone="error"
      />
    );
  }

  return (
    <SettingsContext.Provider value={bootstrapQuery.data.settings}>
      <PrincipalContext.Provider value={bootstrapQuery.data.principal}>
        <Routes>
          <Route element={<ShellLayout />}>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<OverviewPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/incidents/:incidentId" element={<IncidentsPage />} />
            <Route path="/communications" element={<CommunicationsPage />} />
            <Route path="/suppressions" element={<SuppressionsPage />} />
            <Route path="/activity" element={<ActivityPage />} />
            <Route path="/config/alert-rules" element={<AlertRulesPage />} />
            <Route path="/config/communications" element={<GlobalCommunicationsPage />} />
            <Route path="/config/workflows" element={<WorkflowsPage />} />
            <Route path="/config/actions" element={<ActionsPage />} />
            <Route path="/config/access" element={<AccessPage />} />
            <Route path="*" element={<Navigate to="/overview" replace />} />
          </Route>
        </Routes>
      </PrincipalContext.Provider>
    </SettingsContext.Provider>
  );
}

function LoginPage() {
  const [searchParams] = useSearchParams();
  const nextTarget = getLoginNextTarget(searchParams);
  const providersQuery = useQuery({
    queryKey: ["auth-providers"],
    queryFn: () => apiFetch<AppSettings["auth_providers"]>("/api/v1/auth/providers", {}, { allowUnauthorized: true }),
  });
  const passwordProviders = (providersQuery.data || []).filter((provider) => provider.password_login);
  const browserProviders = (providersQuery.data || []).filter((provider) => provider.browser_login);
  const [provider, setProvider] = useState<string>("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [sessionMessage, setSessionMessage] = useState(
    "Sign in with a configured PoundCake auth provider to open the monitoring console.",
  );

  useEffect(() => {
    if (passwordProviders.length === 1) {
      setProvider(passwordProviders[0].name);
    }
  }, [passwordProviders]);

  useEffect(() => {
    let active = true;

    fetch("/api/v1/auth/me", {
      credentials: "same-origin",
    })
      .then((response) => {
        if (!active) {
          return;
        }

        if (response.ok) {
          setSessionMessage("Active session detected. Returning you to the monitoring console.");
          window.location.replace(nextTarget);
          return;
        }

        if (response.status !== 401) {
          setSessionMessage(`Session check returned ${response.status}. You can still sign in below.`);
        }
      })
      .catch(() => {
        if (active) {
          setSessionMessage("Session check is unavailable right now. You can still sign in below.");
        }
      });

    return () => {
      active = false;
    };
  }, [nextTarget]);

  const loginMutation = useMutation({
    mutationFn: async (credentials: { provider: string; username: string; password: string }) => {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(credentials),
      });

      const contentType = response.headers.get("content-type") || "";
      const body = contentType.includes("application/json")
        ? await response.json().catch(() => null)
        : await response.text().catch(() => "");

      if (!response.ok) {
        const detail =
          typeof body === "object" && body && "detail" in body
            ? String((body as { detail: unknown }).detail)
            : response.statusText;
        throw new Error(detail || "Sign in failed.");
      }

      return body;
    },
    onSuccess: () => {
      setSessionMessage("Sign-in successful. Opening your monitoring workspace.");
      window.location.replace(nextTarget);
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitAttempted(true);
    loginMutation.reset();

    if (!username.trim() || !password || !provider) {
      return;
    }

    loginMutation.mutate({
      provider,
      username: username.trim(),
      password,
    });
  }

  const credentialError =
    !provider
      ? "Choose an auth provider to continue."
      : !username.trim() || !password
        ? "Username and password are required."
        : undefined;

  function handleBrowserLogin(providerName: string) {
    window.location.assign(
      `/api/v1/auth/oidc/login?provider=${encodeURIComponent(providerName)}&next=${encodeURIComponent(nextTarget)}`,
    );
  }

  return (
    <div className="login-screen">
      <div className="login-layout">
        <section className="login-hero-panel">
          <div className="eyebrow">Mission Control</div>
          <h1>See incidents, communications, ticket state, and automation health in one place.</h1>
          <p>
            PoundCake&apos;s monitoring console is built for fast triage. Sign in to drill into live incidents,
            verify whether tickets were created, and confirm Teams or Discord updates were delivered.
          </p>

          <div className="login-highlight-grid">
            <div className="hint-card">
              <strong>Incident drilldowns</strong>
              <p>Open a single incident and follow its timeline, communication routes, and latest automation outcome.</p>
            </div>
            <div className="hint-card">
              <strong>Communication visibility</strong>
              <p>Track Core ticket IDs, remote delivery status, provider references, and last errors without hunting through logs.</p>
            </div>
            <div className="hint-card">
              <strong>Clear configuration tools</strong>
              <p>Edit alert rules, workflows, and actions with inline help that explains each field in plain language.</p>
            </div>
          </div>
        </section>

        <section className="login-panel">
          <div className="eyebrow">Secure access</div>
          <h2>Sign in to the monitoring console</h2>
          <p>{sessionMessage}</p>
          <div className="login-meta">
            <span className="version-chip">Next stop: {getRouteName(nextTarget)}</span>
          </div>

          {providersQuery.isError ? (
            <PageError compact message={getErrorMessage(providersQuery.error)} />
          ) : null}

          {passwordProviders.length ? (
            <form className="form-stack" onSubmit={handleSubmit}>
              {passwordProviders.length > 1 ? (
                <FormField label="Provider">
                  <select
                    onChange={(event) => {
                      if (loginMutation.isError) {
                        loginMutation.reset();
                      }
                      setSubmitAttempted(false);
                      setProvider(event.target.value);
                    }}
                    value={provider}
                  >
                    <option value="">Choose a provider</option>
                    {passwordProviders.map((option) => (
                      <option key={option.name} value={option.name}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </FormField>
              ) : null}

              <FormField label="Username">
                <input
                  autoComplete="username"
                  autoFocus
                  onChange={(event) => {
                    if (loginMutation.isError) {
                      loginMutation.reset();
                    }
                    setSubmitAttempted(false);
                    setUsername(event.target.value);
                  }}
                  placeholder="Enter your username"
                  type="text"
                  value={username}
                />
              </FormField>

              <FormField label="Password">
                <input
                  autoComplete="current-password"
                  onChange={(event) => {
                    if (loginMutation.isError) {
                      loginMutation.reset();
                    }
                    setSubmitAttempted(false);
                    setPassword(event.target.value);
                  }}
                  placeholder="Enter your password"
                  type="password"
                  value={password}
                />
              </FormField>

              {loginMutation.isError ? <PageError compact message={getErrorMessage(loginMutation.error)} /> : null}
              {!loginMutation.isError && submitAttempted && credentialError ? (
                <div className="login-note">{credentialError}</div>
              ) : null}

              <div className="form-actions">
                <button className="primary-button" disabled={loginMutation.isPending} type="submit">
                  {loginMutation.isPending ? "Signing in..." : "Sign in"}
                </button>
              </div>
            </form>
          ) : null}

          {browserProviders.length ? (
            <div className="form-stack">
              {passwordProviders.length ? <div className="login-note">Or continue with single sign-on.</div> : null}
              <div className="form-actions">
                {browserProviders.map((browserProvider) => (
                  <button
                    className="ghost-button"
                    key={browserProvider.name}
                    type="button"
                    onClick={() => handleBrowserLogin(browserProvider.name)}
                  >
                    Sign in with {browserProvider.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {!providersQuery.isError && !passwordProviders.length && !browserProviders.length ? (
            <div className="login-note">No browser-capable login providers are configured right now.</div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function ShellLayout() {
  const settings = useSettings();
  const principal = usePrincipal();
  const location = useLocation();

  async function handleLogout() {
    await fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    }).catch(() => undefined);
    window.location.assign("/login");
  }

  const routeName = getRouteName(location.pathname);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand-card">
          <div className="eyebrow">PoundCake</div>
          <h1>Monitoring Console</h1>
          <p>One place to triage incidents, track communications, and manage response logic.</p>
          <div className="version-chip">v{settings.version}</div>
          <div className="login-note">
            {principal.display_name || principal.username} • {principal.is_superuser ? "superuser" : principal.role}
          </div>
        </div>

        <nav className="nav-stack" aria-label="Primary navigation">
          <NavGroup
            title="Operations"
            items={[
              { to: "/overview", label: "Overview" },
              { to: "/incidents", label: "Incidents" },
              { to: "/communications", label: "Communications" },
              { to: "/suppressions", label: "Suppressions" },
              { to: "/activity", label: "Activity" },
            ]}
          />
          <NavGroup
            title="Configuration"
            items={[
              { to: "/config/alert-rules", label: "Alert Rules" },
              { to: "/config/communications", label: "Global Communications" },
              { to: "/config/workflows", label: "Workflows" },
              { to: "/config/actions", label: "Actions" },
              ...(canManageAccess(principal) ? [{ to: "/config/access", label: "Access" }] : []),
            ]}
          />
        </nav>

        <div className="sidebar-footer">
          <button className="ghost-button" type="button" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </aside>

      <div className="content-shell">
        <header className="topbar">
          <div>
            <div className="eyebrow">Mission Control</div>
            <h2>{routeName}</h2>
          </div>
          <div className="topbar-meta">
            <StatusBadge status={settings.prometheus_use_crds ? "active" : "degraded"}>
              {settings.prometheus_use_crds ? "CRD-backed rules" : "API-backed rules"}
            </StatusBadge>
            <StatusBadge status={settings.git_enabled ? "active" : "new"}>
              {settings.git_enabled ? `Git: ${settings.git_provider}` : "Git disabled"}
            </StatusBadge>
          </div>
        </header>

        <main className="page-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function OverviewPage() {
  const dataQuery = useQuery({
    queryKey: ["overview-dashboard"],
    queryFn: async () => {
      const [health, stats, overview, activity, incidents, communications, suppressions] =
        await Promise.all([
          apiGet<HealthResponse>("/api/v1/health"),
          apiGet<StatsResponse>("/api/v1/stats"),
          apiGet<ObservabilityOverviewResponse>("/api/v1/observability/overview"),
          apiGet<ObservabilityActivityRecord[]>("/api/v1/observability/activity?limit=10"),
          apiGet<OrderResponse[]>("/api/v1/orders?limit=8"),
          apiGet<CommunicationActivityRecord[]>("/api/v1/communications/activity?limit=8"),
          apiGet<SuppressionRecord[]>("/api/v1/suppressions?limit=8"),
        ]);
      return { health, stats, overview, activity, incidents, communications, suppressions };
    },
  });

  if (dataQuery.isLoading) {
    return <PageLoading message="Loading overview signal, incident flow, and recent activity." />;
  }

  if (dataQuery.isError || !dataQuery.data) {
    return <PageError message={getErrorMessage(dataQuery.error)} />;
  }

  const { health, stats, overview, activity, incidents, communications, suppressions } = dataQuery.data;
  const activeIncidents = incidents.filter((item) => item.is_active).slice(0, 5);
  const failedCommunications = communications.filter(
    (item) => statusTone(item.remote_state || item.lifecycle_state) === "bad",
  );

  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div>
          <div className="eyebrow">Operations overview</div>
          <h3>What needs attention right now</h3>
          <p>
            Use this workspace to jump from system health to active incidents, outbound communications,
            and recent automation activity without losing context.
          </p>
        </div>
        <div className="hero-strip">
          <MetricPill label="Platform" value={health.status} />
          <MetricPill label="Open incidents" value={String(activeIncidents.length)} />
          <MetricPill label="Failed automations" value={String(overview.failures.dishes_failed)} />
          <MetricPill label="Active suppressions" value={String(overview.suppressions.active)} />
        </div>
      </section>

      <div className="status-grid">
        <MetricCard title="Alerts tracked" value={String(stats.total_alerts)} tone={health.status}>
          Recent alerts: {stats.recent_alerts}
        </MetricCard>
        <MetricCard title="Communication health" value={String(communications.length)} tone={failedCommunications.length ? "failed" : "healthy"}>
          Failed routes: {failedCommunications.length}
        </MetricCard>
        <MetricCard title="Automation runs" value={String(stats.total_executions)} tone={overview.failures.orders_failed ? "warning" : "healthy"}>
          Order failures: {overview.failures.orders_failed}
        </MetricCard>
        <MetricCard title="Workflows" value={String(stats.total_recipes)} tone="active">
          Summary failures: {overview.bakery.summary_failures}
        </MetricCard>
      </div>

      <div className="overview-grid">
        <Panel title="Active incidents" subtitle="Click any incident to open its full drilldown.">
          <div className="list-stack">
            {activeIncidents.length ? (
              activeIncidents.map((incident) => (
                <Link className="feed-row" to={`/incidents/${incident.id}`} key={incident.id}>
                  <div>
                    <strong>{incident.alert_group_name}</strong>
                    <p>{incident.instance || "No instance"} • {incident.severity || "unknown severity"}</p>
                  </div>
                  <StatusBadge status={incident.processing_status}>{incident.processing_status}</StatusBadge>
                </Link>
              ))
            ) : (
              <EmptyState message="No active incidents right now." />
            )}
          </div>
        </Panel>

        <Panel title="Recent activity" subtitle="The feed combines incidents, communications, suppressions, and workflow runs.">
          <div className="list-stack">
            {activity.map((item) => (
              <Link className="feed-row" key={`${item.type}-${item.target_id}`} to={item.link_hint || "/overview"}>
                <div>
                  <div className="feed-title-row">
                    <strong>{item.title}</strong>
                    <span className="feed-type">{item.type}</span>
                  </div>
                  <p>{item.summary || "No summary available."}</p>
                </div>
                <div className="feed-meta">
                  <StatusBadge status={item.status}>{item.status}</StatusBadge>
                  <span>{formatDate(item.timestamp)}</span>
                </div>
              </Link>
            ))}
          </div>
        </Panel>

        <Panel title="Communication watch" subtitle="Track ticketable routes and chat notifications in one feed.">
          <div className="list-stack">
            {communications.slice(0, 6).map((item) => (
              <Link className="feed-row" key={item.communication_id} to={item.reference_type === "incident" ? `/incidents/${item.reference_id}` : "/communications"}>
                <div>
                  <strong>{item.reference_name || item.reference_id}</strong>
                  <p>
                    {titleize(item.channel)} • {item.destination || "No destination"} •{" "}
                    {item.ticket_id || item.provider_reference_id || "Pending reference"}
                  </p>
                </div>
                <div className="feed-meta">
                  <StatusBadge status={item.remote_state || item.lifecycle_state}>{item.remote_state || item.lifecycle_state || "unknown"}</StatusBadge>
                  <span>{formatDate(item.updated_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        </Panel>

        <Panel title="Suppressions" subtitle="Time-boxed monitoring suppressions and their impact.">
          <div className="list-stack">
            {suppressions.slice(0, 6).map((item) => (
              <Link className="feed-row" key={item.id} to={`/suppressions?suppression=${item.id}`}>
                <div>
                  <strong>{item.name}</strong>
                  <p>{item.reason || "No reason provided."}</p>
                </div>
                <div className="feed-meta">
                  <StatusBadge status={item.status}>{item.status}</StatusBadge>
                  <span>{formatDate(item.ends_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Runbook hints" subtitle="Operational hints from the observability overview endpoint.">
        <div className="hint-grid">
          {overview.failures.runbook_hints.length ? (
            overview.failures.runbook_hints.map((hint) => <div className="hint-card" key={hint}>{hint}</div>)
          ) : (
            <EmptyState message="No runbook hints at the moment." />
          )}
        </div>
      </Panel>
    </div>
  );
}

function IncidentsPage() {
  const { incidentId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const incidentsQuery = useQuery({
    queryKey: ["incidents"],
    queryFn: () => apiGet<OrderResponse[]>("/api/v1/orders?limit=100"),
  });

  const selectedId = incidentId ? Number(incidentId) : null;
  const selectedFromRoute = selectedId && incidentsQuery.data
    ? incidentsQuery.data.find((item) => item.id === selectedId)
    : undefined;

  const selectedIncidentQuery = useQuery({
    queryKey: ["incident", selectedId],
    enabled: Boolean(selectedId) && Boolean(incidentsQuery.data) && !selectedFromRoute,
    queryFn: () => apiGet<OrderResponse>(`/api/v1/orders/${selectedId}`),
  });

  const incidentRows = incidentsQuery.data || [];
  const filtered = incidentRows.filter((incident) => {
    if (statusFilter && incident.processing_status !== statusFilter) {
      return false;
    }
    if (!deferredSearch) {
      return true;
    }
    const haystack = [
      incident.alert_group_name,
      incident.instance,
      incident.severity,
      incident.req_id,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(deferredSearch.toLowerCase());
  });

  const activeSelection = selectedFromRoute || selectedIncidentQuery.data || filtered[0];
  const timelineTargetId = activeSelection?.id || selectedId;
  const timelineQuery = useQuery({
    queryKey: ["incident-timeline", timelineTargetId],
    enabled: Boolean(timelineTargetId),
    queryFn: () => apiGet<IncidentTimelineResponse>(`/api/v1/orders/${timelineTargetId}/timeline`),
  });

  useEffect(() => {
    if (!selectedId && activeSelection) {
      startTransition(() => {
        navigate(`/incidents/${activeSelection.id}`, { replace: true });
      });
    }
  }, [activeSelection, navigate, selectedId]);

  if (incidentsQuery.isLoading) {
    return <PageLoading message="Loading incidents and current workflow state." />;
  }

  if (incidentsQuery.isError || !incidentsQuery.data) {
    return <PageError message={getErrorMessage(incidentsQuery.error)} />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        title="Incidents"
        description="Track live alert incidents, drill into workflow progress, and see every communication route tied to the incident."
      />

      <div className="toolbar">
        <label>
          Lifecycle
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">All</option>
            <option value="new">New</option>
            <option value="processing">Processing</option>
            <option value="complete">Complete</option>
            <option value="failed">Failed</option>
            <option value="canceled">Canceled</option>
          </select>
        </label>
        <label className="toolbar-search">
          Search
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Alert name, instance, request id"
          />
        </label>
      </div>

      <div className="master-detail">
        <Panel title="Incident queue" subtitle={`${filtered.length} incidents in view.`}>
          <div className="list-stack incident-list">
            {filtered.length ? (
              filtered.map((incident) => (
                <button
                  className={`incident-row ${timelineTargetId === incident.id ? "active" : ""}`}
                  key={incident.id}
                  type="button"
                  onClick={() => startTransition(() => navigate(`/incidents/${incident.id}`))}
                >
                  <div>
                    <strong>{incident.alert_group_name}</strong>
                    <p>
                      {incident.instance || "No instance"} • {incident.severity || "unknown severity"} •{" "}
                      {incident.communications.length} route(s)
                    </p>
                  </div>
                  <div className="feed-meta">
                    <StatusBadge status={incident.processing_status}>{incident.processing_status}</StatusBadge>
                    <span>{formatDate(incident.updated_at)}</span>
                  </div>
                </button>
              ))
            ) : (
              <EmptyState message="No incidents match the current filters." />
            )}
          </div>
        </Panel>

        <Panel title="Incident drilldown" subtitle="Status, ticketing, chat routes, and full timeline in one place.">
          {!timelineTargetId ? (
            <EmptyState message="Select an incident to inspect its current state." />
          ) : timelineQuery.isLoading || selectedIncidentQuery.isLoading ? (
            <EmptyState message="Select an incident to inspect its current state." />
          ) : timelineQuery.isError || selectedIncidentQuery.isError || !timelineQuery.data ? (
            <PageError message={getErrorMessage(timelineQuery.error || selectedIncidentQuery.error)} compact />
          ) : (
            <IncidentDetail
              data={timelineQuery.data}
              highlightedCommunicationId={searchParams.get("communication") || undefined}
              highlightedDishId={searchParams.get("dish") || undefined}
            />
          )}
        </Panel>
      </div>
    </div>
  );
}

function IncidentDetail({
  data,
  highlightedCommunicationId,
  highlightedDishId,
}: {
  data: IncidentTimelineResponse;
  highlightedCommunicationId?: string;
  highlightedDishId?: string;
}) {
  const order = data.order;

  return (
    <div className="detail-stack">
      <section className="detail-hero">
        <div>
          <div className="eyebrow">Incident #{order.id}</div>
          <h3>{order.alert_group_name}</h3>
          <p>
            {order.instance || "No instance"} • {order.severity || "unknown severity"} • started{" "}
            {formatLongDate(order.starts_at)}
          </p>
        </div>
        <div className="hero-strip">
          <MetricPill label="Lifecycle" value={order.processing_status} />
          <MetricPill label="Alert state" value={order.alert_status} />
          <MetricPill label="Workflow" value={order.remediation_outcome} />
          <MetricPill label="Routes" value={String(order.communications.length)} />
        </div>
      </section>

      <div className="kv-grid">
        <KeyValue label="Request ID" value={order.req_id} />
        <KeyValue label="Counter" value={String(order.counter)} />
        <KeyValue label="Auto-close eligible" value={String(order.auto_close_eligible)} />
        <KeyValue label="Clear deadline" value={formatLongDate(order.clear_deadline_at)} />
      </div>

      <section>
        <div className="section-heading">
          <h4>Communication routes</h4>
          <p>Ticketing and chat delivery status for this incident.</p>
        </div>
        <div className="route-grid">
          {order.communications.length ? (
            order.communications.map((route) => (
              <div
                className={`route-card ${
                  highlightedCommunicationId === String(route.id) ? "highlighted" : ""
                }`}
                key={route.id}
              >
                <div className="route-card-head">
                  <strong>{titleize(route.execution_target)}</strong>
                  <StatusBadge status={route.remote_state || route.lifecycle_state}>
                    {route.remote_state || route.lifecycle_state}
                  </StatusBadge>
                </div>
                <KeyValue label="Destination" value={route.destination_target || route.execution_target} />
                <KeyValue label="Reference" value={route.bakery_ticket_id || "-"} />
                <KeyValue label="Operation ID" value={route.bakery_operation_id || "-"} />
                <KeyValue label="Writable" value={String(route.writable)} />
                <KeyValue label="Reopenable" value={String(route.reopenable)} />
                <KeyValue label="Last update" value={formatLongDate(route.updated_at)} />
                <KeyValue label="Last error" value={route.last_error || "-"} />
              </div>
            ))
          ) : (
            <EmptyState message="No communication routes are tracked for this incident yet." />
          )}
        </div>
      </section>

      <section>
        <div className="section-heading">
          <h4>Timeline</h4>
          <p>Workflow tasks, communication updates, and order state transitions in chronological order.</p>
        </div>
        {highlightedDishId ? (
          <div className="helper-card">
            <strong>Selected workflow run</strong>
            <p>Timeline events related to workflow run #{highlightedDishId} are highlighted below.</p>
          </div>
        ) : null}
        <div className="timeline">
          {data.events.map((event, index) => (
            <div
              className={`timeline-row ${
                isTimelineEventHighlighted(event, highlightedCommunicationId, highlightedDishId) ? "highlighted" : ""
              }`}
              key={`${event.event_type}-${index}-${event.timestamp}`}
            >
              <div className="timeline-dot" />
              <div className="timeline-body">
                <div className="timeline-head">
                  <strong>{event.title}</strong>
                  <div className="feed-meta">
                    <StatusBadge status={event.status}>{event.status}</StatusBadge>
                    <span>{formatDate(event.timestamp)}</span>
                  </div>
                </div>
                <p>{titleize(event.event_type)}</p>
                {Object.keys(event.details || {}).length > 0 ? (
                  <pre className="json-block">{compactJson(event.details)}</pre>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function CommunicationsPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const deferredSearch = useDeferredValue(search);

  const query = useQuery({
    queryKey: ["communications-activity"],
    queryFn: () => apiGet<CommunicationActivityRecord[]>("/api/v1/communications/activity?limit=200"),
  });

  if (query.isLoading) {
    return <PageLoading message="Loading ticketing and chat delivery history." />;
  }

  if (query.isError || !query.data) {
    return <PageError message={getErrorMessage(query.error)} />;
  }

  const rows = query.data.filter((item) => {
    if (statusFilter && statusFilter !== (item.remote_state || item.lifecycle_state || "")) {
      return false;
    }
    if (channelFilter && channelFilter !== item.channel) {
      return false;
    }
    if (!deferredSearch) {
      return true;
    }
    const haystack = [
      item.reference_name,
      item.destination,
      item.ticket_id,
      item.provider_reference_id,
      item.channel,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(deferredSearch.toLowerCase());
  });

  const selected = rows.find((item) => item.communication_id === selectedId) || rows[0];
  const channels = Array.from(new Set(query.data.map((item) => item.channel))).sort();

  return (
    <div className="page-stack">
      <PageHeader
        title="Communications"
        description="Unified outbound history for ticketing and chat channels, with ticket numbers, provider references, and latest delivery state."
      />
      <div className="toolbar">
        <label>
          Channel
          <select value={channelFilter} onChange={(event) => setChannelFilter(event.target.value)}>
            <option value="">All</option>
            {channels.map((channel) => (
              <option value={channel} key={channel}>
                {titleize(channel)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">All</option>
            {Array.from(new Set(query.data.map((item) => item.remote_state || item.lifecycle_state || "unknown"))).map((status) => (
              <option value={status} key={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label className="toolbar-search">
          Search
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Destination, ticket number, incident" />
        </label>
      </div>

      <div className="master-detail">
        <Panel title="Outbound history" subtitle={`${rows.length} records in view.`}>
          <div className="list-stack incident-list">
            {rows.map((item) => (
              <button
                className={`incident-row ${selected?.communication_id === item.communication_id ? "active" : ""}`}
                key={item.communication_id}
                type="button"
                onClick={() => setSelectedId(item.communication_id)}
              >
                <div>
                  <strong>{item.reference_name || item.reference_id}</strong>
                  <p>
                    {titleize(item.channel)} • {item.destination || "No destination"} •{" "}
                    {item.ticket_id || item.provider_reference_id || "Pending reference"}
                  </p>
                </div>
                <div className="feed-meta">
                  <StatusBadge status={item.remote_state || item.lifecycle_state}>
                    {item.remote_state || item.lifecycle_state || "unknown"}
                  </StatusBadge>
                  <span>{formatDate(item.updated_at)}</span>
                </div>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title="Selected route" subtitle="Current status, provider references, and last known error.">
          {selected ? (
            <div className="detail-stack">
              <div className="kv-grid">
                <KeyValue label="Reference type" value={selected.reference_type} />
                <KeyValue label="Channel" value={titleize(selected.channel)} />
                <KeyValue label="Destination" value={selected.destination || "-"} />
                <KeyValue label="Ticket number" value={selected.ticket_id || "-"} />
                <KeyValue label="Provider reference" value={selected.provider_reference_id || "-"} />
                <KeyValue label="Operation ID" value={selected.operation_id || "-"} />
                <KeyValue label="Lifecycle state" value={selected.lifecycle_state || "-"} />
                <KeyValue label="Remote state" value={selected.remote_state || "-"} />
                <KeyValue label="Writable" value={selected.writable === null || selected.writable === undefined ? "-" : String(selected.writable)} />
                <KeyValue label="Reopenable" value={selected.reopenable === null || selected.reopenable === undefined ? "-" : String(selected.reopenable)} />
                <KeyValue label="Last update" value={formatLongDate(selected.updated_at)} />
                <KeyValue label="Last error" value={selected.last_error || "-"} />
              </div>
            </div>
          ) : (
            <EmptyState message="Select a communication record to inspect it." />
          )}
        </Panel>
      </div>
    </div>
  );
}

function SuppressionsPage() {
  const notify = useToast();
  const principal = usePrincipal();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const canEdit = canManageSuppressions(principal);

  const suppressionsQuery = useQuery({
    queryKey: ["suppressions"],
    queryFn: () => apiGet<SuppressionRecord[]>("/api/v1/suppressions?limit=100"),
  });

  const form = useForm<z.infer<typeof suppressionSchema>>({
    resolver: zodResolver(suppressionSchema),
    defaultValues: {
      name: "",
      reason: "",
      starts_at: "",
      ends_at: "",
      scope: "matchers",
      summary_ticket_enabled: true,
      matcher_key: "alertname",
      matcher_operator: "eq",
      matcher_value: "",
    },
  });

  const createMutation = useMutation({
    mutationFn: async (values: z.infer<typeof suppressionSchema>) =>
      apiPost<SuppressionRecord>("/api/v1/suppressions", {
        name: values.name,
        reason: values.reason || null,
        starts_at: values.starts_at,
        ends_at: values.ends_at,
        scope: values.scope,
        enabled: true,
        created_by: "ui-v2",
        summary_ticket_enabled: values.summary_ticket_enabled,
        matchers:
          values.scope === "matchers" && values.matcher_key
            ? [
                {
                  label_key: values.matcher_key,
                  operator: values.matcher_operator,
                  value: values.matcher_value || null,
                },
              ]
            : [],
      }),
    onSuccess: async () => {
      notify("success", "Suppression created.");
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["suppressions"] });
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: number) => apiPost<SuppressionRecord>(`/api/v1/suppressions/${id}/cancel`),
    onSuccess: async () => {
      notify("success", "Suppression canceled.");
      await queryClient.invalidateQueries({ queryKey: ["suppressions"] });
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  if (suppressionsQuery.isLoading) {
    return <PageLoading message="Loading suppression windows and impact status." />;
  }

  if (suppressionsQuery.isError || !suppressionsQuery.data) {
    return <PageError message={getErrorMessage(suppressionsQuery.error)} />;
  }

  const focusedId = searchParams.get("suppression");

  return (
    <div className="page-stack">
      <PageHeader
        title="Suppressions"
        description="Manage temporary monitoring suppressions and see which windows are active, scheduled, or already expired."
      />

      <div className="editor-grid">
        <Panel title="Create suppression" subtitle="Use clear dates and matcher scope so operators know exactly what is being muted.">
          {!canEdit ? (
            <div className="helper-card">
              <strong>Read-only access</strong>
              <p>Your role can review suppressions but cannot create or cancel them.</p>
            </div>
          ) : null}
          <form className="form-stack" onSubmit={form.handleSubmit((values) => createMutation.mutate(values))}>
            <fieldset disabled={!canEdit}>
            <FormField label="Suppression name" help="Use a human-readable maintenance or outage label.">
              <input {...form.register("name")} placeholder="Database maintenance" />
              <FieldError message={form.formState.errors.name?.message} />
            </FormField>
            <FormField label="Reason" help="Explain why alerts are being suppressed and who requested it.">
              <textarea {...form.register("reason")} rows={3} />
            </FormField>
            <div className="grid-two">
              <FormField label="Starts at" help="Start of the suppression window in local time.">
                <input type="datetime-local" {...form.register("starts_at")} />
                <FieldError message={form.formState.errors.starts_at?.message} />
              </FormField>
              <FormField label="Ends at" help="End of the suppression window in local time.">
                <input type="datetime-local" {...form.register("ends_at")} />
                <FieldError message={form.formState.errors.ends_at?.message} />
              </FormField>
            </div>
            <div className="grid-two">
              <FormField label="Scope" help="Matcher scope targets alerts by label rather than silencing everything globally.">
                <select {...form.register("scope")}>
                  <option value="matchers">Matchers</option>
                  <option value="all">All</option>
                </select>
              </FormField>
              <FormField label="Summary communication" help="Enable this when you want the suppression lifecycle summarized into a ticket.">
                <label className="toggle-row">
                  <input type="checkbox" {...form.register("summary_ticket_enabled")} />
                  <span>Send summary communication</span>
                </label>
              </FormField>
            </div>
            <div className="grid-three">
              <FormField label="Matcher key" help="The alert label to match, such as alertname or cluster.">
                <input {...form.register("matcher_key")} />
              </FormField>
              <FormField label="Operator" help="eq matches exact values; regex allows pattern matching.">
                <select {...form.register("matcher_operator")}>
                  <option value="eq">eq</option>
                  <option value="neq">neq</option>
                  <option value="regex">regex</option>
                  <option value="nregex">nregex</option>
                  <option value="exists">exists</option>
                  <option value="not_exists">not_exists</option>
                </select>
              </FormField>
              <FormField label="Matcher value" help="Leave value blank for exists and not_exists operators.">
                <input {...form.register("matcher_value")} />
              </FormField>
            </div>
            <div className="form-actions">
              <button className="primary-button" disabled={createMutation.isPending} type="submit">
                {createMutation.isPending ? "Creating..." : "Create suppression"}
              </button>
            </div>
            </fieldset>
          </form>
        </Panel>

        <Panel title="Suppression windows" subtitle="Click any window to see its current status and cancel active ones.">
          <div className="list-stack">
            {suppressionsQuery.data.map((item) => (
              <div className={`feed-row card-row ${focusedId === String(item.id) ? "highlighted" : ""}`} key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <p>
                    {item.reason || "No reason provided."} • {formatDate(item.starts_at)} to{" "}
                    {formatDate(item.ends_at)}
                  </p>
                </div>
                <div className="feed-meta">
                  <StatusBadge status={item.status}>{item.status}</StatusBadge>
                  <button
                    className="ghost-button"
                    disabled={!canEdit || cancelMutation.isPending || item.status === "canceled"}
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Cancel suppression "${item.name}"?`)) {
                        cancelMutation.mutate(item.id);
                      }
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function ActivityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState("");
  const [phaseFilter, setPhaseFilter] = useState("");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const query = useQuery({
    queryKey: ["activity-dishes"],
    queryFn: () => apiGet<DishRecord[]>("/api/v1/dishes?limit=100"),
  });

  const selectedDishId = searchParams.get("dish");
  const activityRows = query.data || [];
  const rows = activityRows.filter((item) => {
    if (statusFilter && statusFilter !== (item.execution_status || item.processing_status || "")) {
      return false;
    }
    if (phaseFilter && phaseFilter !== item.run_phase) {
      return false;
    }
    if (!deferredSearch) {
      return true;
    }
    const haystack = [
      item.recipe?.name,
      item.execution_ref,
      item.error_message,
      item.run_phase,
      item.order_id ? `incident ${item.order_id}` : "",
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(deferredSearch.toLowerCase());
  });

  const selected =
    (selectedDishId ? activityRows.find((item) => String(item.id) === selectedDishId) : undefined) || rows[0];

  useEffect(() => {
    if (!selectedDishId && rows[0]) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("dish", String(rows[0].id));
      setSearchParams(nextParams, { replace: true });
    }
  }, [rows, searchParams, selectedDishId, setSearchParams]);

  function selectDish(dishId: number) {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("dish", String(dishId));
    setSearchParams(nextParams);
  }

  if (query.isLoading) {
    return <PageLoading message="Loading workflow activity and execution history." />;
  }

  if (query.isError || !query.data) {
    return <PageError message={getErrorMessage(query.error)} />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        title="Activity"
        description="Workflow execution history across incidents, with quick links back to the originating incident when one exists."
      />
      <div className="toolbar">
        <label>
          Phase
          <select value={phaseFilter} onChange={(event) => setPhaseFilter(event.target.value)}>
            <option value="">All</option>
            {Array.from(new Set(query.data.map((item) => item.run_phase))).sort().map((phase) => (
              <option key={phase} value={phase}>
                {titleize(phase)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">All</option>
            {Array.from(new Set(query.data.map((item) => item.execution_status || item.processing_status || "unknown"))).sort().map((status) => (
              <option key={status} value={status}>
                {titleize(status)}
              </option>
            ))}
          </select>
        </label>
        <label className="toolbar-search">
          Search
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Workflow, execution ref, incident, error"
          />
        </label>
      </div>

      <div className="master-detail">
        <Panel title="Workflow runs" subtitle={`${rows.length} activity records in view.`}>
          <div className="list-stack incident-list">
            {rows.length ? (
              rows.map((item) => (
                <button
                  className={`incident-row ${selected?.id === item.id ? "active" : ""}`}
                  key={item.id}
                  type="button"
                  onClick={() => selectDish(item.id)}
                >
                  <div>
                    <strong>{item.recipe?.name || `Workflow #${item.recipe_id}`}</strong>
                    <p>
                      {titleize(item.run_phase)} • {item.execution_ref || "Execution pending"} •{" "}
                      {item.order_id ? `Incident #${item.order_id}` : "No incident linked"}
                    </p>
                  </div>
                  <div className="feed-meta">
                    <StatusBadge status={item.execution_status || item.processing_status}>
                      {item.execution_status || item.processing_status}
                    </StatusBadge>
                    <span>{formatDate(item.updated_at)}</span>
                  </div>
                </button>
              ))
            ) : (
              <EmptyState message="No workflow runs match the current filters." />
            )}
          </div>
        </Panel>

        <Panel title="Activity drilldown" subtitle="Execution details, incident linkage, and the latest workflow outcome.">
          {selected ? (
            <div className="detail-stack">
              <section className="detail-hero">
                <div>
                  <div className="eyebrow">Workflow run #{selected.id}</div>
                  <h3>{selected.recipe?.name || `Workflow #${selected.recipe_id}`}</h3>
                  <p>
                    {titleize(selected.run_phase)} phase • retry attempt {selected.retry_attempt} • updated{" "}
                    {formatLongDate(selected.updated_at)}
                  </p>
                </div>
                <div className="hero-strip">
                  <MetricPill label="Processing" value={selected.processing_status} />
                  <MetricPill label="Execution" value={selected.execution_status || "pending"} />
                  <MetricPill label="Duration" value={selected.actual_duration_sec ? `${selected.actual_duration_sec}s` : "Pending"} />
                  <MetricPill label="Incident" value={selected.order_id ? `#${selected.order_id}` : "Unlinked"} />
                </div>
              </section>

              <div className="form-actions">
                {selected.order_id ? (
                  <Link className="primary-button" to={`/incidents/${selected.order_id}?dish=${selected.id}`}>
                    Open incident drilldown
                  </Link>
                ) : null}
              </div>

              <div className="kv-grid">
                <KeyValue label="Workflow" value={selected.recipe?.name || `Workflow #${selected.recipe_id}`} />
                <KeyValue label="Incident" value={selected.order_id ? `Incident #${selected.order_id}` : "-"} />
                <KeyValue label="Phase" value={titleize(selected.run_phase)} />
                <KeyValue label="Execution ref" value={selected.execution_ref || "-"} />
                <KeyValue label="Processing status" value={selected.processing_status} />
                <KeyValue label="Execution status" value={selected.execution_status || "-"} />
                <KeyValue label="Expected duration" value={selected.expected_duration_sec ? `${selected.expected_duration_sec}s` : "-"} />
                <KeyValue label="Actual duration" value={selected.actual_duration_sec ? `${selected.actual_duration_sec}s` : "-"} />
                <KeyValue label="Started" value={formatLongDate(selected.started_at)} />
                <KeyValue label="Completed" value={formatLongDate(selected.completed_at)} />
                <KeyValue label="Created" value={formatLongDate(selected.created_at)} />
                <KeyValue label="Updated" value={formatLongDate(selected.updated_at)} />
              </div>

              {selected.error_message ? (
                <div className="helper-card">
                  <strong>Latest error</strong>
                  <p>{selected.error_message}</p>
                </div>
              ) : (
                <div className="helper-card">
                  <strong>Latest outcome</strong>
                  <p>
                    This run is currently {selected.execution_status || selected.processing_status}. Use the incident drilldown
                    to see communications and the rest of the lifecycle around this workflow run.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <EmptyState message="Select a workflow run to inspect its details." />
          )}
        </Panel>
      </div>
    </div>
  );
}

function AlertRulesPage() {
  const notify = useToast();
  const principal = usePrincipal();
  const queryClient = useQueryClient();
  const [editingRule, setEditingRule] = useState<PrometheusRule | null>(null);
  const canEdit = canManageAlertRules(principal);

  const rulesQuery = useQuery({
    queryKey: ["prometheus-rules"],
    queryFn: () => apiGet<PrometheusRuleListResponse>("/api/v1/prometheus/rules"),
  });

  const form = useForm<z.infer<typeof ruleSchema>>({
    resolver: zodResolver(ruleSchema),
    defaultValues: {
      name: "",
      group: "",
      file: "",
      expr: "",
      duration: "",
      labels: "",
      annotations: "",
    },
  });

  useEffect(() => {
    if (!editingRule) {
      return;
    }
    form.reset({
      name: editingRule.name,
      group: editingRule.group,
      file: editingRule.crd || editingRule.file || "",
      expr: editingRule.query,
      duration: editingRule.duration || "",
      labels: editingRule.labels ? compactJson(editingRule.labels) : "",
      annotations: editingRule.annotations ? compactJson(editingRule.annotations) : "",
    });
  }, [editingRule, form]);

  const saveMutation = useMutation({
    mutationFn: async (values: z.infer<typeof ruleSchema>) => {
      const body = {
        alert: values.name,
        expr: values.expr,
        for: values.duration || undefined,
        labels: parseJsonObject(values.labels, "Labels"),
        annotations: parseJsonObject(values.annotations, "Annotations"),
      };
      if (editingRule) {
        return apiPut(
          `/api/v1/prometheus/rules/${encodeURIComponent(values.name)}?group_name=${encodeURIComponent(values.group)}&file_name=${encodeURIComponent(values.file)}`,
          body,
        );
      }
      return apiPost(
        `/api/v1/prometheus/rules?rule_name=${encodeURIComponent(values.name)}&group_name=${encodeURIComponent(values.group)}&file_name=${encodeURIComponent(values.file)}`,
        body,
      );
    },
    onSuccess: async () => {
      notify("success", editingRule ? "Alert rule updated." : "Alert rule created.");
      setEditingRule(null);
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["prometheus-rules"] });
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (rule: PrometheusRule) =>
      apiDelete(
        `/api/v1/prometheus/rules/${encodeURIComponent(rule.name)}?group_name=${encodeURIComponent(rule.group)}&file_name=${encodeURIComponent(rule.crd || rule.file || "")}`,
      ),
    onSuccess: async () => {
      notify("success", "Alert rule deleted.");
      setEditingRule(null);
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["prometheus-rules"] });
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  if (rulesQuery.isLoading) {
    return <PageLoading message="Loading alert rules and editing controls." />;
  }

  if (rulesQuery.isError || !rulesQuery.data) {
    return <PageError message={getErrorMessage(rulesQuery.error)} />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        title="Alert Rules"
        description="Create, update, and retire alert definitions with monitoring-first labels and inline PromQL help."
      />
      <div className="editor-grid">
        <Panel title={editingRule ? `Edit ${editingRule.name}` : "Create alert rule"} subtitle="Prometheus details stay available, but the workflow is written for operators.">
          {!canEdit ? (
            <div className="helper-card">
              <strong>Read-only access</strong>
              <p>Your role can inspect alert rules but cannot create, update, or delete them.</p>
            </div>
          ) : null}
          <form className="form-stack" onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}>
            <fieldset disabled={!canEdit}>
            <div className="grid-two">
              <FormField label="Rule name" help="Human-readable alert identifier shown to operators.">
                <input {...form.register("name")} placeholder="NodeFilesystemAlmostOutOfSpace" />
                <FieldError message={form.formState.errors.name?.message} />
              </FormField>
              <FormField label="Rule group" help="Prometheus group name used for storage and organization.">
                <input {...form.register("group")} placeholder="node-filesystem" />
                <FieldError message={form.formState.errors.group?.message} />
              </FormField>
            </div>
            <div className="grid-two">
              <FormField label="Rule file / CRD" help="Backing PrometheusRule CRD or file name.">
                <input {...form.register("file")} placeholder="kubernetes-resources" />
                <FieldError message={form.formState.errors.file?.message} />
              </FormField>
              <FormField label="For duration" help="How long the expression must be true before the alert fires.">
                <input {...form.register("duration")} placeholder="5m" />
              </FormField>
            </div>
            <FormField label="Expression" help="PromQL expression that drives the alert condition.">
              <textarea {...form.register("expr")} rows={5} placeholder='node_filesystem_avail_bytes{fstype!="tmpfs"} < 10737418240' />
              <FieldError message={form.formState.errors.expr?.message} />
            </FormField>
            <FormField label="Labels (JSON)" help="Use labels for routing, grouping, and severity.">
              <textarea {...form.register("labels")} rows={4} placeholder='{"severity":"critical","team":"platform"}' />
            </FormField>
            <FormField label="Annotations (JSON)" help="Annotations become the operator-facing description and runbook context.">
              <textarea {...form.register("annotations")} rows={4} placeholder='{"summary":"Disk is filling up","runbook":"https://..."}' />
            </FormField>
            <div className="form-actions">
              <button className="primary-button" disabled={saveMutation.isPending} type="submit">
                {saveMutation.isPending ? "Saving..." : editingRule ? "Save rule" : "Create rule"}
              </button>
              {editingRule ? (
                <button className="ghost-button" type="button" onClick={() => {
                  setEditingRule(null);
                  form.reset();
                }}>
                  Clear
                </button>
              ) : null}
            </div>
            </fieldset>
          </form>
        </Panel>

        <HelpRail
          title="Alert-rule help"
          items={[
            {
              label: "What operators should understand",
              description: "Keep rule names readable, make severity explicit in labels, and put the human explanation in annotations.",
            },
            {
              label: "Expression guidance",
              description: "Use the expression field for PromQL only. Keep labels and annotations out of the query itself.",
            },
            {
              label: "Common mistake",
              description: "For durations, use Prometheus formats such as 30s, 5m, or 1h instead of plain integers.",
            },
          ]}
        />
      </div>

      <Panel title="Alert inventory" subtitle={`Source: ${rulesQuery.data.source}. Select a rule to edit or remove it.`}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Group</th>
                <th>For</th>
                <th>Source</th>
                <th>Status</th>
                <th>Query</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rulesQuery.data.rules.map((rule) => (
                <tr key={`${rule.group}-${rule.name}`}>
                  <td>{rule.name}</td>
                  <td>{rule.group}</td>
                  <td>{rule.duration || "-"}</td>
                  <td>{rule.crd || rule.file || "-"}</td>
                  <td>
                    <StatusBadge status={rule.state || "unknown"}>{rule.state || "unknown"}</StatusBadge>
                  </td>
                  <td className="query-cell">{rule.query}</td>
                  <td className="action-cell">
                    <button className="ghost-button" disabled={!canEdit} type="button" onClick={() => setEditingRule(rule)}>
                      Edit
                    </button>
                    <button
                      className="danger-button"
                      disabled={!canEdit}
                      type="button"
                      onClick={() => {
                        if (window.confirm(`Delete alert rule "${rule.name}"?`)) {
                          deleteMutation.mutate(rule);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function GlobalCommunicationsPage() {
  const notify = useToast();
  const principal = usePrincipal();
  const queryClient = useQueryClient();
  const canEdit = canManageGlobalCommunications(principal);

  const policyQuery = useQuery({
    queryKey: ["communications-policy"],
    queryFn: () => apiGet<CommunicationPolicyRecord>("/api/v1/communications/policy"),
  });

  const form = useForm<z.infer<typeof communicationsPolicySchema>>({
    resolver: zodResolver(communicationsPolicySchema),
    defaultValues: {
      routes: [],
    },
  });

  const routes = useFieldArray({
    control: form.control,
    name: "routes",
  });

  useEffect(() => {
    if (!policyQuery.data) {
      return;
    }
    form.reset({
      routes: policyQuery.data.routes.map((route) => ({
        id: route.id,
        label: route.label,
        execution_target: route.execution_target,
        destination_target: route.destination_target || "",
        provider_config: normalizeProviderConfigForForm(route.execution_target, route.provider_config),
        enabled: route.enabled,
        position: route.position,
      })),
    });
  }, [form, policyQuery.data]);

  const saveMutation = useMutation({
    mutationFn: async (values: z.infer<typeof communicationsPolicySchema>) => {
      return apiPut<CommunicationPolicyRecord>("/api/v1/communications/policy", {
        routes: values.routes.map((route, index) => ({
          id: route.id || undefined,
          label: route.label,
          execution_target: route.execution_target,
          destination_target: route.destination_target || "",
          provider_config: route.provider_config || {},
          enabled: route.enabled,
          position: index + 1,
        })),
      });
    },
    onSuccess: async () => {
      notify("success", "Global communications policy updated.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["communications-policy"] }),
        queryClient.invalidateQueries({ queryKey: ["settings"] }),
        queryClient.invalidateQueries({ queryKey: ["workflows"] }),
      ]);
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  if (policyQuery.isLoading) {
    return <PageLoading message="Loading global communications policy." />;
  }

  if (policyQuery.isError || !policyQuery.data) {
    return <PageError message={getErrorMessage(policyQuery.error)} />;
  }

  const watchedRoutes = form.watch("routes");
  const enabledCount = watchedRoutes.filter((route) => route.enabled).length;

  return (
    <div className="page-stack">
      <PageHeader
        title="Global Communications"
        description="Define the default communication routes inherited by workflows that do not supply a workflow-specific override."
      />
      <div className="editor-grid">
        <Panel
          title="Default route set"
          subtitle="This policy is optional. If it is empty, enabled workflows must define workflow-specific communications."
        >
          {!canEdit ? (
            <div className="helper-card">
              <strong>Read-only access</strong>
              <p>Your role can review the global policy but only admins can change it.</p>
            </div>
          ) : null}
          <form className="form-stack" onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}>
            <fieldset disabled={!canEdit}>
            <div className="builder-header">
              <div>
                <h4>Communication routes</h4>
                <p>Any enabled route counts. Core, Teams, Discord, and mixed route sets are all valid.</p>
              </div>
              <button
                className="ghost-button"
                disabled={!canEdit}
                type="button"
                onClick={() => routes.append({ ...emptyCommunicationRoute(), position: routes.fields.length + 1 })}
              >
                Add route
              </button>
            </div>

            <div className="builder-stack">
              {routes.fields.length ? (
                routes.fields.map((field, index) => (
                  <div className="builder-card" key={field.id}>
                    <div className="builder-card-head">
                      <strong>Route {index + 1}</strong>
                      <div className="inline-actions">
                        <button className="ghost-button" type="button" onClick={() => moveCommunicationRoute(routes, index, -1)}>
                          Up
                        </button>
                        <button className="ghost-button" type="button" onClick={() => moveCommunicationRoute(routes, index, 1)}>
                          Down
                        </button>
                        <button className="danger-button" type="button" onClick={() => routes.remove(index)}>
                          Remove
                        </button>
                      </div>
                    </div>
                    <div className="grid-two">
                      <FormField label="Route label" help="Give the route a plain-language name that operators will recognize in workflow and communications views.">
                        <input {...form.register(`routes.${index}.label` as const)} placeholder="Primary on-call route" />
                        <FieldError message={form.formState.errors.routes?.[index]?.label?.message} />
                      </FormField>
                      <FormField label="Provider" help="Choose the communication provider or destination type such as rackspace_core, teams, or discord.">
                        <select
                          {...form.register(`routes.${index}.execution_target` as const, {
                            onChange: () => form.setValue(`routes.${index}.provider_config` as any, {}),
                          })}
                        >
                          {communicationTargetOptions.map((target) => (
                            <option key={target} value={target}>
                              {target}
                            </option>
                          ))}
                        </select>
                      </FormField>
                    </div>
                    <div className="grid-two">
                      <FormField label="Destination" help="Optional route target such as a queue, channel, room, or project. Leave blank when the provider uses its own default destination.">
                        <input {...form.register(`routes.${index}.destination_target` as const)} placeholder="ops-alerts" />
                      </FormField>
                      <FormField label="Enabled" help="Disabled routes are kept in the policy but are ignored by runtime dispatch.">
                        <label className="toggle-row">
                          <input type="checkbox" {...form.register(`routes.${index}.enabled` as const)} />
                          <span>Route is enabled</span>
                        </label>
                      </FormField>
                    </div>
                    <CommunicationRouteProviderConfigFields
                      form={form as ReturnType<typeof useForm<any>>}
                      basePath={`routes.${index}`}
                      executionTarget={watchedRoutes[index]?.execution_target || field.execution_target}
                    />
                  </div>
                ))
              ) : (
                <EmptyState message="No global routes are configured. Enabled workflows will need workflow-specific communications." />
              )}
            </div>

            <div className="preview-card">
              <div className="eyebrow">Policy preview</div>
              <p>
                {enabledCount
                  ? `${enabledCount} enabled route(s) will open on escalation, open then close after successful auto-remediation clears, and post clear notifications after escalation clears.`
                  : "This global policy is empty. Enabled workflows must define workflow-specific communications to be valid."}
              </p>
            </div>

            <div className="form-actions">
              <button className="primary-button" disabled={saveMutation.isPending} type="submit">
                {saveMutation.isPending ? "Saving..." : "Save global policy"}
              </button>
            </div>
            </fieldset>
          </form>
        </Panel>

        <HelpRail
          title="Global comms help"
          items={[
            {
              label: "Optional by design",
              description: "If you leave the global policy empty, each enabled workflow must define its own local communications override.",
            },
            {
              label: "Fixed lifecycle",
              description: "Global and local policies share the same runtime lifecycle: open on escalation, open plus close after successful resolve, and notify only after escalation clears.",
            },
            {
              label: "Any route type",
              description: "Ticket-backed and chat-only destinations are both valid. PoundCake tracks ticket numbers when available and generic provider references otherwise.",
            },
          ]}
        />
      </div>

      <Panel title="Lifecycle summary" subtitle="What PoundCake does with the effective communications policy at runtime.">
        <div className="kv-grid">
          {Object.entries(policyQuery.data.lifecycle_summary).map(([key, value]) => (
            <KeyValue key={key} label={titleize(key.replace(/_/g, " "))} value={value} />
          ))}
        </div>
      </Panel>
    </div>
  );
}

function WorkflowsPage() {
  const notify = useToast();
  const principal = usePrincipal();
  const settings = useSettings();
  const queryClient = useQueryClient();
  const [editingWorkflow, setEditingWorkflow] = useState<RecipeRecord | null>(null);
  const [mode, setMode] = useState<"simple" | "advanced">("simple");
  const canEdit = canManageWorkflows(principal);

  const recipesQuery = useQuery({
    queryKey: ["workflows"],
    queryFn: () => apiGet<RecipeRecord[]>("/api/v1/recipes/?limit=200"),
  });
  const actionsQuery = useQuery({
    queryKey: ["actions"],
    queryFn: () => apiGet<IngredientRecord[]>("/api/v1/ingredients/?limit=500"),
  });
  const policyQuery = useQuery({
    queryKey: ["communications-policy"],
    queryFn: () => apiGet<CommunicationPolicyRecord>("/api/v1/communications/policy"),
  });

  const form = useForm<z.infer<typeof workflowSchema>>({
    resolver: zodResolver(workflowSchema),
    defaultValues: {
      name: "",
      description: "",
      enabled: true,
      clear_timeout_sec: "",
      communications_mode: settings.global_communications_configured ? "inherit" : "local",
      communications_routes: [],
      recipe_ingredients: [
        {
          ingredient_id: 0,
          step_order: 1,
          on_success: "continue",
          run_phase: "both",
          run_condition: "always",
          parallel_group: 0,
          depth: 0,
          execution_parameters_override_text: "",
        },
      ],
    },
  });

  const steps = useFieldArray({
    control: form.control,
    name: "recipe_ingredients",
  });
  const communicationRoutes = useFieldArray({
    control: form.control,
    name: "communications_routes",
  });

  useEffect(() => {
    if (!editingWorkflow) {
      return;
    }
    form.reset({
      name: editingWorkflow.name,
      description: editingWorkflow.description || "",
      enabled: editingWorkflow.enabled,
      clear_timeout_sec: editingWorkflow.clear_timeout_sec ? String(editingWorkflow.clear_timeout_sec) : "",
      communications_mode: editingWorkflow.communications.mode,
      communications_routes:
        editingWorkflow.communications.mode === "local"
          ? editingWorkflow.communications.routes.map((route) => ({
              id: route.id,
              label: route.label,
              execution_target: route.execution_target,
              destination_target: route.destination_target || "",
              provider_config: normalizeProviderConfigForForm(route.execution_target, route.provider_config),
              enabled: route.enabled,
              position: route.position,
            }))
          : [],
      recipe_ingredients: editingWorkflow.recipe_ingredients.map((step) => ({
        ingredient_id: step.ingredient_id,
        step_order: step.step_order,
        on_success: step.on_success,
        run_phase: step.run_phase,
        run_condition: step.run_condition,
        parallel_group: step.parallel_group,
        depth: step.depth,
        execution_parameters_override_text: step.execution_parameters_override
          ? compactJson(step.execution_parameters_override)
          : "",
      })),
    });
  }, [editingWorkflow, form]);

  useEffect(() => {
    if (editingWorkflow || settings.global_communications_configured) {
      return;
    }
    if (form.getValues("communications_mode") === "inherit") {
      form.setValue("communications_mode", "local");
    }
  }, [editingWorkflow, form, settings.global_communications_configured]);

  const saveMutation = useMutation({
    mutationFn: async (values: z.infer<typeof workflowSchema>) => {
      if (values.enabled && values.communications_mode === "inherit" && !settings.global_communications_configured) {
        throw new Error("Configure a global communications policy or switch this workflow to workflow-specific communications.");
      }
      if (values.enabled && values.communications_mode === "local" && !values.communications_routes.some((route) => route.enabled)) {
        throw new Error("Enabled workflows need at least one enabled workflow-specific communication route.");
      }
      const payload = {
        name: values.name,
        description: values.description || null,
        enabled: values.enabled,
        clear_timeout_sec: values.clear_timeout_sec ? Number(values.clear_timeout_sec) : null,
        communications: {
          mode: values.communications_mode,
          routes:
            values.communications_mode === "local"
              ? values.communications_routes.map((route, index) => ({
                  id: route.id || undefined,
                  label: route.label,
                  execution_target: route.execution_target,
                  destination_target: route.destination_target || "",
                  provider_config: route.provider_config || {},
                  enabled: route.enabled,
                  position: index + 1,
                }))
              : [],
        },
        recipe_ingredients: values.recipe_ingredients.map((step, index) => ({
          ingredient_id: Number(step.ingredient_id),
          step_order: index + 1,
          on_success: step.on_success,
          parallel_group: step.parallel_group,
          depth: step.depth,
          execution_parameters_override: parseOptionalJson(
            step.execution_parameters_override_text,
            "Step override JSON",
          ),
          run_phase: step.run_phase,
          run_condition: step.run_condition,
        })),
      };
      if (editingWorkflow) {
        return apiPut<RecipeRecord>(`/api/v1/recipes/${editingWorkflow.id}`, payload);
      }
      return apiPost<RecipeRecord>("/api/v1/recipes/", payload);
    },
    onSuccess: async () => {
      notify("success", editingWorkflow ? "Workflow updated." : "Workflow created.");
      setEditingWorkflow(null);
      resetWorkflowForm(form, steps, communicationRoutes, settings.global_communications_configured);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workflows"] }),
        queryClient.invalidateQueries({ queryKey: ["communications-policy"] }),
      ]);
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (workflowId: number) => apiDelete<DeleteResponse>(`/api/v1/recipes/${workflowId}`),
    onSuccess: async () => {
      notify("success", "Workflow deleted.");
      setEditingWorkflow(null);
      resetWorkflowForm(form, steps, communicationRoutes, settings.global_communications_configured);
      await queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  if (recipesQuery.isLoading || actionsQuery.isLoading || policyQuery.isLoading) {
    return <PageLoading message="Loading workflows, actions, and builder controls." />;
  }

  if (recipesQuery.isError || actionsQuery.isError || policyQuery.isError || !recipesQuery.data || !actionsQuery.data || !policyQuery.data) {
    return <PageError message={getErrorMessage(recipesQuery.error || actionsQuery.error || policyQuery.error)} />;
  }

  const availableActions = actionsQuery.data.filter((action) => !isCommunicationAction(action));
  const watchedSteps = form.watch("recipe_ingredients");
  const watchedCommunicationMode = form.watch("communications_mode");
  const watchedCommunicationRoutes = form.watch("communications_routes");
  const workflowPreview = buildWorkflowPreview(
    watchedSteps,
    availableActions,
    form.watch("name"),
    watchedCommunicationMode,
    watchedCommunicationMode === "local" ? watchedCommunicationRoutes : policyQuery.data.routes,
  );

  return (
    <div className="page-stack">
      <PageHeader
        title="Workflows"
        description="Build remediation and utility workflows, then choose whether they inherit global communications or define a workflow-specific override."
      />
      <div className="editor-grid">
        <Panel title={editingWorkflow ? `Edit ${editingWorkflow.name}` : "Create workflow"} subtitle="Simple mode keeps the common path short. Advanced mode exposes execution plumbing when you need it.">
          {!canEdit ? (
            <div className="helper-card">
              <strong>Read-only access</strong>
              <p>Your role can inspect workflows, but only operators and admins can change them.</p>
            </div>
          ) : null}
          <div className="mode-toggle">
            <button className={mode === "simple" ? "primary-button" : "ghost-button"} disabled={!canEdit} onClick={() => setMode("simple")} type="button">
              Simple
            </button>
            <button className={mode === "advanced" ? "primary-button" : "ghost-button"} disabled={!canEdit} onClick={() => setMode("advanced")} type="button">
              Advanced
            </button>
          </div>

          <form className="form-stack" onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}>
            <fieldset disabled={!canEdit}>
            <div className="grid-two">
              <FormField label="Workflow name" help="Use the alert or handling pattern name operators will recognize.">
                <input {...form.register("name")} placeholder="Node filesystem response" />
                <FieldError message={form.formState.errors.name?.message} />
              </FormField>
              <FormField label="Resolve wait (sec)" help="How long PoundCake should wait before resolve-side handling applies.">
                <input {...form.register("clear_timeout_sec")} placeholder="300" />
              </FormField>
            </div>
            <FormField label="Description" help="Explain the intent so responders can understand why this workflow exists.">
              <textarea {...form.register("description")} rows={3} />
            </FormField>
            <FormField label="Enabled" help="Disable a workflow without deleting it when you want to keep its history and structure.">
              <label className="toggle-row">
                <input type="checkbox" {...form.register("enabled")} />
                <span>Workflow is enabled</span>
              </label>
            </FormField>

            <div className="builder-header">
              <div>
                <h4>Communications</h4>
                <p>Communications are policy-driven. Use the global default or replace it with workflow-specific routes.</p>
              </div>
            </div>

            <div className="builder-stack">
              <div className="builder-card">
                <div className="grid-two">
                  <FormField label="Communications source" help="Use the global route set when possible, or replace it entirely for this workflow with workflow-specific communications.">
                    <select {...form.register("communications_mode")}>
                      <option value="inherit">Use global default</option>
                      <option value="local">Use workflow-specific communications</option>
                    </select>
                  </FormField>
                  <div className="helper-card">
                    <strong>Current effective policy</strong>
                    <p>
                      {watchedCommunicationMode === "inherit"
                        ? policyQuery.data.configured
                          ? `${policyQuery.data.routes.filter((route) => route.enabled).length} global route(s) are available to this workflow.`
                          : "No global routes are configured yet. Switch this workflow to workflow-specific communications before enabling it."
                        : `${watchedCommunicationRoutes.filter((route) => route.enabled).length} workflow-specific route(s) are currently enabled.`}
                    </p>
                  </div>
                </div>

                {watchedCommunicationMode === "inherit" ? (
                  policyQuery.data.routes.length ? (
                    <div className="route-grid">
                      {policyQuery.data.routes.map((route) => (
                        <div className="route-card" key={route.id}>
                          <div className="route-card-head">
                            <strong>{route.label}</strong>
                            <StatusBadge status={route.enabled ? "active" : "canceled"}>
                              {route.enabled ? "enabled" : "disabled"}
                            </StatusBadge>
                          </div>
                          <KeyValue label="Provider" value={route.execution_target} />
                          <KeyValue label="Destination" value={route.destination_target || "-"} />
                          <KeyValue label="Route config" value={providerConfigSummary(route.execution_target, route.provider_config)} />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <EmptyState message="No global communications are configured. Use workflow-specific communications or configure the global policy first." />
                  )
                ) : (
                  <>
                    <div className="builder-header">
                      <div>
                        <h4>Workflow-specific routes</h4>
                        <p>These routes replace the global default entirely for this workflow.</p>
                      </div>
                      <button
                        className="ghost-button"
                        type="button"
                        onClick={() =>
                          communicationRoutes.append({
                            ...emptyCommunicationRoute(),
                            position: communicationRoutes.fields.length + 1,
                          })
                        }
                      >
                        Add route
                      </button>
                    </div>

                    <div className="builder-stack">
                      {communicationRoutes.fields.length ? (
                        communicationRoutes.fields.map((field, index) => (
                          <div className="builder-card" key={field.id}>
                            <div className="builder-card-head">
                              <strong>Route {index + 1}</strong>
                              <div className="inline-actions">
                                <button className="ghost-button" type="button" onClick={() => moveCommunicationRoute(communicationRoutes, index, -1)}>
                                  Up
                                </button>
                                <button className="ghost-button" type="button" onClick={() => moveCommunicationRoute(communicationRoutes, index, 1)}>
                                  Down
                                </button>
                                <button className="danger-button" type="button" onClick={() => communicationRoutes.remove(index)}>
                                  Remove
                                </button>
                              </div>
                            </div>
                            <div className="grid-two">
                              <FormField label="Route label" help="Name this route the way operators will recognize it later in incidents and communications history.">
                                <input {...form.register(`communications_routes.${index}.label` as const)} placeholder="Primary escalation route" />
                                <FieldError message={form.formState.errors.communications_routes?.[index]?.label?.message} />
                              </FormField>
                              <FormField label="Provider" help="Provider or destination type such as rackspace_core, teams, or discord.">
                                <select
                                  {...form.register(`communications_routes.${index}.execution_target` as const, {
                                    onChange: () =>
                                      form.setValue(`communications_routes.${index}.provider_config` as any, {}),
                                  })}
                                >
                                  {communicationTargetOptions.map((target) => (
                                    <option key={target} value={target}>
                                      {target}
                                    </option>
                                  ))}
                                </select>
                              </FormField>
                            </div>
                            <div className="grid-two">
                              <FormField label="Destination" help="Optional queue, channel, project, or room for this route.">
                                <input {...form.register(`communications_routes.${index}.destination_target` as const)} placeholder="ops-alerts" />
                              </FormField>
                              <FormField label="Enabled" help="Disabled routes stay in the workflow definition but do not run.">
                                <label className="toggle-row">
                                  <input type="checkbox" {...form.register(`communications_routes.${index}.enabled` as const)} />
                                  <span>Route is enabled</span>
                                </label>
                              </FormField>
                            </div>
                            <CommunicationRouteProviderConfigFields
                              form={form as ReturnType<typeof useForm<any>>}
                              basePath={`communications_routes.${index}`}
                              executionTarget={watchedCommunicationRoutes[index]?.execution_target || field.execution_target}
                            />
                          </div>
                        ))
                      ) : (
                        <EmptyState message="Add at least one route if this workflow should override the global default." />
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="builder-header">
              <div>
                <h4>Workflow steps</h4>
                <p>Workflow steps should focus on remediation and utility logic. Communications are managed separately above.</p>
              </div>
              <button
                className="ghost-button"
                type="button"
                onClick={() =>
                  steps.append({
                    ingredient_id: 0,
                    step_order: steps.fields.length + 1,
                    on_success: "continue",
                    run_phase: "both",
                    run_condition: "always",
                    parallel_group: 0,
                    depth: 0,
                    execution_parameters_override_text: "",
                  })
                }
              >
                Add step
              </button>
            </div>

            <div className="builder-stack">
              {steps.fields.map((field, index) => (
                <div className="builder-card" key={field.id}>
                  <div className="builder-card-head">
                    <strong>Step {index + 1}</strong>
                    <div className="inline-actions">
                      <button className="ghost-button" type="button" onClick={() => moveField(steps, index, -1)}>
                        Up
                      </button>
                      <button className="ghost-button" type="button" onClick={() => moveField(steps, index, 1)}>
                        Down
                      </button>
                      <button className="danger-button" type="button" onClick={() => steps.remove(index)}>
                        Remove
                      </button>
                    </div>
                  </div>
                  <div className="grid-three">
                    <FormField label="Action" help="The reusable action this step will run.">
                      <select {...form.register(`recipe_ingredients.${index}.ingredient_id` as const)}>
                        <option value={0}>Choose an action</option>
                        {availableActions.map((action) => (
                          <option key={action.id} value={action.id}>
                            {action.task_key_template} ({titleize(action.execution_target)})
                          </option>
                        ))}
                      </select>
                    </FormField>
                    <FormField label="Run phase" help="Choose whether this runs when the alert fires, resolves, escalates, or both.">
                      <select {...form.register(`recipe_ingredients.${index}.run_phase` as const)}>
                        <option value="firing">firing</option>
                        <option value="escalation">escalation</option>
                        <option value="resolving">resolving</option>
                        <option value="both">both</option>
                      </select>
                    </FormField>
                    <FormField label="Run condition" help="Fine-grained control over whether this step runs after success, failure, timeout, or always.">
                      <select {...form.register(`recipe_ingredients.${index}.run_condition` as const)}>
                        <option value="always">always</option>
                        <option value="remediation_failed">remediation_failed</option>
                        <option value="clear_timeout_expired">clear_timeout_expired</option>
                        <option value="resolved_after_success">resolved_after_success</option>
                        <option value="resolved_after_failure">resolved_after_failure</option>
                        <option value="resolved_after_no_remediation">resolved_after_no_remediation</option>
                        <option value="resolved_after_timeout">resolved_after_timeout</option>
                      </select>
                    </FormField>
                  </div>
                  <div className="grid-two">
                    <FormField label="On success" help="Continue keeps the workflow moving; stop ends the workflow after this step succeeds.">
                      <select {...form.register(`recipe_ingredients.${index}.on_success` as const)}>
                        <option value="continue">continue</option>
                        <option value="stop">stop</option>
                      </select>
                    </FormField>
                    {mode === "advanced" ? (
                      <FormField label="Override JSON" help="Optional execution-parameter override for this specific step invocation.">
                        <textarea {...form.register(`recipe_ingredients.${index}.execution_parameters_override_text` as const)} rows={3} />
                      </FormField>
                    ) : (
                      <div className="helper-card">
                        <strong>Plain-English step</strong>
                        <p>{describeWorkflowStep(watchedSteps[index], availableActions)}</p>
                      </div>
                    )}
                  </div>
                  {mode === "advanced" ? (
                    <div className="grid-two">
                      <FormField label="Parallel group" help="Steps with the same group can be planned together. Use 0 for default sequential handling.">
                        <input type="number" min={0} {...form.register(`recipe_ingredients.${index}.parallel_group` as const)} />
                      </FormField>
                      <FormField label="Depth" help="Execution depth for more advanced branching patterns. Leave at 0 for standard ordered workflows.">
                        <input type="number" min={0} {...form.register(`recipe_ingredients.${index}.depth` as const)} />
                      </FormField>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>

            <div className="preview-card">
              <div className="eyebrow">Workflow preview</div>
              <p>{workflowPreview}</p>
            </div>

            <div className="form-actions">
              <button className="primary-button" disabled={saveMutation.isPending} type="submit">
                {saveMutation.isPending ? "Saving..." : editingWorkflow ? "Save workflow" : "Create workflow"}
              </button>
              {editingWorkflow ? (
                <button
                  className="ghost-button"
                  type="button"
                  onClick={() => {
                    setEditingWorkflow(null);
                    resetWorkflowForm(
                      form,
                      steps,
                      communicationRoutes,
                      settings.global_communications_configured,
                    );
                  }}
                >
                  Clear
                </button>
              ) : null}
            </div>
            </fieldset>
          </form>
        </Panel>

        <HelpRail
          title="Workflow help"
          items={[
            {
              label: "Global vs local",
              description: "Use the global default when the workflow should follow the platform-wide route set. Switch to workflow-specific communications only when this workflow needs its own route list.",
            },
            {
              label: "Lifecycle",
              description: "Communications do not fire when the workflow starts. PoundCake opens routes on escalation, opens then closes after successful resolve, and posts clear notifications after escalation clears.",
            },
            {
              label: "Step scope",
              description: "Keep workflow steps focused on remediation and utility actions. Configure ticketing, Teams, Discord, and similar destinations in the communications section instead of as ordinary steps.",
            },
          ]}
        />
      </div>

      <Panel title="Workflow inventory" subtitle="Select a workflow to edit it or remove it when it is no longer used.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Enabled</th>
                <th>Communications</th>
                <th>Steps</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {recipesQuery.data.map((workflow) => (
                <tr key={workflow.id}>
                  <td>{workflow.name}</td>
                  <td>{workflow.description || "-"}</td>
                  <td>
                    <StatusBadge status={workflow.enabled ? "active" : "canceled"}>
                      {workflow.enabled ? "enabled" : "disabled"}
                    </StatusBadge>
                  </td>
                  <td>
                    {workflow.communications.mode === "local"
                      ? `${workflow.communications.routes.filter((route) => route.enabled).length} local route(s)`
                      : workflow.communications.routes.filter((route) => route.enabled).length
                        ? `${workflow.communications.routes.filter((route) => route.enabled).length} global route(s)`
                        : "none"}
                  </td>
                  <td>{workflow.recipe_ingredients.length}</td>
                  <td>{formatDate(workflow.updated_at)}</td>
                  <td className="action-cell">
                    <button className="ghost-button" disabled={!canEdit} type="button" onClick={() => setEditingWorkflow(workflow)}>
                      Edit
                    </button>
                    <button
                      className="danger-button"
                      disabled={!canEdit}
                      type="button"
                      onClick={() => {
                        if (window.confirm(`Delete workflow "${workflow.name}"?`)) {
                          deleteMutation.mutate(workflow.id);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function ActionsPage() {
  const notify = useToast();
  const principal = usePrincipal();
  const queryClient = useQueryClient();
  const [editingAction, setEditingAction] = useState<IngredientRecord | null>(null);
  const canEdit = canManageActions(principal);

  const actionsQuery = useQuery({
    queryKey: ["actions"],
    queryFn: () => apiGet<IngredientRecord[]>("/api/v1/ingredients/?limit=500"),
  });

  const form = useForm<z.infer<typeof actionSchema>>({
    resolver: zodResolver(actionSchema),
    defaultValues: {
      template: "remediation",
      task_key_template: "",
      execution_target: "",
      destination_target: "",
      execution_engine: "stackstorm",
      execution_purpose: "remediation",
      execution_id: "",
      is_blocking: true,
      on_failure: "stop",
      expected_duration_sec: 60,
      timeout_duration_sec: 300,
      retry_count: 0,
      retry_delay: 5,
      execution_payload_text: "",
      execution_parameters_text: "",
    },
  });

  const template = form.watch("template");
  const actionPreview = buildActionPreview(form.watch());

  useEffect(() => {
    if (template === "ticket" && !editingAction) {
      form.setValue("execution_engine", "bakery");
      form.setValue("execution_target", "rackspace_core");
      form.setValue("execution_purpose", "comms");
      form.setValue("execution_parameters_text", compactJson({ operation: "open" }));
    }
    if (template === "chat" && !editingAction) {
      form.setValue("execution_engine", "bakery");
      form.setValue("execution_target", "teams");
      form.setValue("execution_purpose", "comms");
      form.setValue("execution_parameters_text", compactJson({ operation: "notify" }));
    }
    if (template === "remediation" && !editingAction) {
      form.setValue("execution_engine", "stackstorm");
      form.setValue("execution_purpose", "remediation");
      form.setValue("execution_parameters_text", compactJson({}));
    }
  }, [editingAction, form, template]);

  useEffect(() => {
    if (!editingAction) {
      return;
    }
    form.reset({
      template: classifyActionTemplate(editingAction),
      task_key_template: editingAction.task_key_template,
      execution_target: editingAction.execution_target,
      destination_target: editingAction.destination_target || "",
      execution_engine: editingAction.execution_engine,
      execution_purpose: editingAction.execution_purpose,
      execution_id: editingAction.execution_id || "",
      is_blocking: editingAction.is_blocking,
      on_failure: editingAction.on_failure,
      expected_duration_sec: editingAction.expected_duration_sec,
      timeout_duration_sec: editingAction.timeout_duration_sec,
      retry_count: editingAction.retry_count,
      retry_delay: editingAction.retry_delay,
      execution_payload_text: editingAction.execution_payload
        ? compactJson(editingAction.execution_payload)
        : "",
      execution_parameters_text: editingAction.execution_parameters
        ? compactJson(editingAction.execution_parameters)
        : "",
    });
  }, [editingAction, form]);

  const saveMutation = useMutation({
    mutationFn: async (values: z.infer<typeof actionSchema>) => {
      const payload = {
        execution_target: values.execution_target,
        destination_target: values.destination_target || "",
        task_key_template: values.task_key_template,
        execution_id: values.execution_id || null,
        execution_payload: parseOptionalJson(values.execution_payload_text, "Execution payload"),
        execution_parameters: parseOptionalJson(values.execution_parameters_text, "Execution parameters"),
        execution_engine: values.execution_engine,
        execution_purpose: values.execution_purpose,
        is_blocking: values.is_blocking,
        expected_duration_sec: values.expected_duration_sec,
        timeout_duration_sec: values.timeout_duration_sec,
        retry_count: values.retry_count,
        retry_delay: values.retry_delay,
        on_failure: values.on_failure,
      };
      if (editingAction) {
        return apiPut<IngredientRecord>(`/api/v1/ingredients/${editingAction.id}`, payload);
      }
      return apiPost<IngredientRecord>("/api/v1/ingredients/", payload);
    },
    onSuccess: async () => {
      notify("success", editingAction ? "Action updated." : "Action created.");
      setEditingAction(null);
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["actions"] });
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (actionId: number) => apiDelete<DeleteResponse>(`/api/v1/ingredients/${actionId}`),
    onSuccess: async () => {
      notify("success", "Action deleted.");
      setEditingAction(null);
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["actions"] });
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  if (actionsQuery.isLoading) {
    return <PageLoading message="Loading reusable actions and templates." />;
  }

  if (actionsQuery.isError || !actionsQuery.data) {
    return <PageError message={getErrorMessage(actionsQuery.error)} />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        title="Actions"
        description="Reusable remediation and utility actions for workflows. Communication routes now live in Global Communications and the workflow communications section."
      />
      <div className="editor-grid">
        <Panel title={editingAction ? `Edit ${editingAction.task_key_template}` : "Create action"} subtitle="Start with remediation or custom automation templates. Ticket and chat actions remain available only for legacy compatibility.">
          {!canEdit ? (
            <div className="helper-card">
              <strong>Read-only access</strong>
              <p>Your role can inspect actions, but only operators and admins can change them.</p>
            </div>
          ) : null}
          <form className="form-stack" onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}>
            <fieldset disabled={!canEdit}>
            <FormField label="Action type" help="Use remediation or custom for new workflow actions. Communications are configured in communications policy screens instead of ordinary workflow steps.">
              <select {...form.register("template")}>
                <option value="remediation">Remediation</option>
                <option value="custom">Custom</option>
                <option value="ticket">Ticket</option>
                <option value="chat">Chat notification</option>
              </select>
            </FormField>
            <div className="grid-two">
              <FormField label="Action name" help="The operator-facing name for this reusable action.">
                <input {...form.register("task_key_template")} placeholder="core.create-ticket" />
                <FieldError message={form.formState.errors.task_key_template?.message} />
              </FormField>
              <FormField label="Target" help="Provider or target identifier such as rackspace_core, teams, discord, or an action ref.">
                <input {...form.register("execution_target")} placeholder="rackspace_core" />
                <FieldError message={form.formState.errors.execution_target?.message} />
              </FormField>
            </div>
            <div className="grid-three">
              <FormField label="Destination" help="Optional route target such as a team channel, queue, project, or thread.">
                <input {...form.register("destination_target")} placeholder="ops-alerts" />
              </FormField>
              <FormField label="Execution engine" help="Choose bakery for communications and stackstorm for remediation actions.">
                <input {...form.register("execution_engine")} />
              </FormField>
              <FormField label="Purpose" help="Purpose helps explain how the action should be used in workflows.">
                <select {...form.register("execution_purpose")}>
                  <option value="comms">comms</option>
                  <option value="remediation">remediation</option>
                  <option value="utility">utility</option>
                </select>
              </FormField>
            </div>
            <div className="grid-two">
              <FormField label="Execution ID" help="Optional provider-specific action or workflow identifier.">
                <input {...form.register("execution_id")} placeholder="optional" />
              </FormField>
              <FormField label="Blocking" help="Blocking actions must complete before the next workflow step moves on.">
                <label className="toggle-row">
                  <input type="checkbox" {...form.register("is_blocking")} />
                  <span>Action is blocking</span>
                </label>
              </FormField>
            </div>
            <div className="grid-four">
              <FormField label="Expected sec" help="Normal runtime used for operator expectations and workflow planning.">
                <input type="number" min={1} {...form.register("expected_duration_sec")} />
              </FormField>
              <FormField label="Timeout sec" help="Maximum runtime before the action is treated as timed out.">
                <input type="number" min={1} {...form.register("timeout_duration_sec")} />
              </FormField>
              <FormField label="Retries" help="How many retry attempts PoundCake should allow.">
                <input type="number" min={0} {...form.register("retry_count")} />
              </FormField>
              <FormField label="Retry delay" help="Delay in seconds between retries.">
                <input type="number" min={0} {...form.register("retry_delay")} />
              </FormField>
            </div>
            <FormField label="On failure" help="Choose whether the workflow stops, continues, or retries when this action fails.">
              <select {...form.register("on_failure")}>
                <option value="stop">stop</option>
                <option value="continue">continue</option>
                <option value="retry">retry</option>
              </select>
            </FormField>
            <FormField label="Execution payload (JSON)" help="Structured provider payload body. Leave blank when the action only needs parameters.">
              <textarea {...form.register("execution_payload_text")} rows={4} />
            </FormField>
            <FormField label="Execution parameters (JSON)" help="Provider-specific execution parameters such as operation=open or notify.">
              <textarea {...form.register("execution_parameters_text")} rows={4} />
            </FormField>

            <div className="preview-card">
              <div className="eyebrow">Action preview</div>
              <p>{actionPreview}</p>
            </div>

            <div className="form-actions">
              <button className="primary-button" disabled={saveMutation.isPending} type="submit">
                {saveMutation.isPending ? "Saving..." : editingAction ? "Save action" : "Create action"}
              </button>
              {editingAction ? (
                <button className="ghost-button" type="button" onClick={() => {
                  setEditingAction(null);
                  form.reset();
                }}>
                  Clear
                </button>
              ) : null}
            </div>
            </fieldset>
          </form>
        </Panel>

        <HelpRail
          title="Action help"
          items={[
            {
              label: "Workflow comms",
              description: "For new workflows, configure Core, Teams, Discord, and other communication routes in Global Communications or the workflow communications override instead of ordinary actions.",
            },
            {
              label: "Primary use",
              description: "This page is now best suited for remediation and utility actions that do real workflow work.",
            },
            {
              label: "Legacy compatibility",
              description: "Ticket and chat action templates remain here only so older actions can still be inspected or updated during the transition.",
            },
          ]}
        />
      </div>

      <Panel title="Action inventory" subtitle="Reusable actions available to workflows.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Target</th>
                <th>Engine</th>
                <th>Purpose</th>
                <th>Blocking</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {actionsQuery.data.map((action) => (
                <tr key={action.id}>
                  <td>{action.task_key_template}</td>
                  <td>{action.destination_target ? `${action.execution_target}:${action.destination_target}` : action.execution_target}</td>
                  <td>{action.execution_engine}</td>
                  <td>{action.execution_purpose}</td>
                  <td>{String(action.is_blocking)}</td>
                  <td>{formatDate(action.updated_at)}</td>
                  <td className="action-cell">
                    <button className="ghost-button" disabled={!canEdit} type="button" onClick={() => setEditingAction(action)}>
                      Edit
                    </button>
                    <button
                      className="danger-button"
                      disabled={!canEdit}
                      type="button"
                      onClick={() => {
                        if (window.confirm(`Delete action "${action.task_key_template}"?`)) {
                          deleteMutation.mutate(action.id);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function AccessPage() {
  const principal = usePrincipal();
  const settings = useSettings();
  const notify = useToast();
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState<string>(
    settings.auth_providers.find((item) => item.name !== "local" && item.name !== "service")?.name || "",
  );
  const [bindingType, setBindingType] = useState<"group" | "user">("group");
  const [role, setRole] = useState<"reader" | "operator" | "admin">("reader");
  const [externalGroup, setExternalGroup] = useState("");
  const [selectedPrincipalId, setSelectedPrincipalId] = useState("");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const providers = settings.auth_providers.filter((item) => item.name !== "service");
  const externalProviders = providers.filter((item) => item.name !== "local");

  useEffect(() => {
    if (externalProviders.length === 0) {
      if (provider) setProvider("");
      return;
    }
    if (!provider || !externalProviders.some((item) => item.name === provider)) {
      setProvider(externalProviders[0].name);
    }
  }, [externalProviders, provider]);

  const principalsQuery = useQuery({
    queryKey: ["auth-principals", provider, deferredSearch],
    queryFn: () =>
      apiGet<AuthPrincipalRecord[]>(
        `/api/v1/auth/principals?limit=200${provider ? `&provider=${encodeURIComponent(provider)}` : ""}${deferredSearch ? `&search=${encodeURIComponent(deferredSearch)}` : ""}`,
      ),
    placeholderData: (previousData) => previousData,
    enabled: canManageAccess(principal),
  });
  const bindingsQuery = useQuery({
    queryKey: ["auth-bindings"],
    queryFn: () => apiGet<AuthRoleBindingRecord[]>("/api/v1/auth/bindings"),
    enabled: canManageAccess(principal),
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      const payload =
        bindingType === "group"
          ? {
              provider,
              binding_type: "group",
              role,
              external_group: externalGroup,
            }
          : {
              provider,
              binding_type: "user",
              role,
              principal_id: Number(selectedPrincipalId),
            };
      return apiPost<AuthRoleBindingRecord>("/api/v1/auth/bindings", payload);
    },
    onSuccess: async () => {
      notify("success", "Role binding created.");
      setExternalGroup("");
      setSelectedPrincipalId("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["auth-bindings"] }),
        queryClient.invalidateQueries({ queryKey: ["auth-principals"] }),
      ]);
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, nextRole }: { id: number; nextRole: string }) =>
      apiPatch<AuthRoleBindingRecord>(`/api/v1/auth/bindings/${id}`, { role: nextRole }),
    onSuccess: async () => {
      notify("success", "Role binding updated.");
      await queryClient.invalidateQueries({ queryKey: ["auth-bindings"] });
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiDelete<DeleteResponse>(`/api/v1/auth/bindings/${id}`),
    onSuccess: async () => {
      notify("success", "Role binding deleted.");
      await queryClient.invalidateQueries({ queryKey: ["auth-bindings"] });
    },
    onError: (error) => notify("error", getErrorMessage(error)),
  });

  if (!canManageAccess(principal)) {
    return <PageError message="You do not have access to manage PoundCake role bindings." />;
  }

  if (bindingsQuery.isLoading || (principalsQuery.isLoading && !principalsQuery.data)) {
    return <PageLoading message="Loading provider status, observed principals, and role bindings." />;
  }

  if (principalsQuery.isError || bindingsQuery.isError || !principalsQuery.data || !bindingsQuery.data) {
    return <PageError message={getErrorMessage(principalsQuery.error || bindingsQuery.error)} />;
  }

  const principalFilter = search.trim().toLowerCase();
  const visiblePrincipals = (principalsQuery.data || []).filter((item) => {
    if (!principalFilter) {
      return true;
    }
    const haystack = [item.username, item.display_name, item.subject_id]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(principalFilter);
  });
  const hasExternalProviders = externalProviders.length > 0;
  const createDisabled =
    createMutation.isPending
    || !hasExternalProviders
    || (bindingType === "group" ? !externalGroup.trim() : !selectedPrincipalId);

  return (
    <div className="page-stack">
      <PageHeader
        title="Access"
        description="Manage provider-backed RBAC bindings for readers, operators, and admins. External providers are enabled at deploy time; this page manages who gets access after they appear in PoundCake."
      />

      <div className="status-grid">
        {providers.map((item) => (
          <MetricCard key={item.name} title={item.label} value={titleize(item.login_mode)} tone="active">
            {describeAuthProviderModes(item)}
          </MetricCard>
        ))}
      </div>

      <div className="editor-grid">
        <Panel title="Create role binding" subtitle="Bind either an observed user or an external group to a PoundCake role.">
          <div className="form-stack">
            {!hasExternalProviders ? (
              <EmptyState message="No external auth providers are enabled yet. Add Active Directory, Auth0, or Azure AD in Helm auth values, redeploy PoundCake, then create bindings here." />
            ) : null}
            <div className="grid-two">
              <FormField
                label="Provider"
                help="Providers are enabled in Helm and appear here after redeploy. The local superuser is always available for recovery, but role bindings only apply to external providers."
              >
                <select
                  disabled={!hasExternalProviders}
                  value={provider}
                  onChange={(event) => setProvider(event.target.value)}
                >
                  {externalProviders.map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField
                label="Binding type"
                help="Use group bindings to pre-provision access before a user logs in. Use observed user bindings after someone has already authenticated successfully."
              >
                <select value={bindingType} onChange={(event) => setBindingType(event.target.value as "group" | "user")}>
                  <option value="group">Group</option>
                  <option value="user">Observed user</option>
                </select>
              </FormField>
            </div>
            <div className="grid-two">
              <FormField
                label="Role"
                help="Readers are read-only. Operators can manage workflows, actions, suppressions, and alert rules. Admins can also manage access and all remaining configuration."
              >
                <select value={role} onChange={(event) => setRole(event.target.value as "reader" | "operator" | "admin")}>
                  <option value="reader">Reader</option>
                  <option value="operator">Operator</option>
                  <option value="admin">Admin</option>
                </select>
              </FormField>
              <FormField
                label="Principal search"
                help="Observed users appear here after a successful login through Auth0, Azure AD, or Active Directory. Search narrows the stored principal list before you choose a user binding."
              >
                <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter observed users" />
              </FormField>
            </div>

            {bindingType === "group" ? (
              <FormField
                label="External group"
                help="Enter the group name exactly as PoundCake sees it after provider normalization. For Active Directory this is usually the extracted CN; for Auth0 and Azure AD it is usually the exact group claim value."
              >
                <input
                  value={externalGroup}
                  onChange={(event) => setExternalGroup(event.target.value)}
                  placeholder="monitoring-operators"
                />
              </FormField>
            ) : (
              <FormField
                label="Observed user"
                help="Choose a user who has already logged in and been recorded by PoundCake. If the person is missing here, have them authenticate once or create a group binding instead."
              >
                <select
                  disabled={!hasExternalProviders}
                  value={selectedPrincipalId}
                  onChange={(event) => setSelectedPrincipalId(event.target.value)}
                >
                  <option value="">Choose a user</option>
                  {visiblePrincipals.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.display_name || item.username}
                    </option>
                  ))}
                </select>
              </FormField>
            )}

            <div className="form-actions">
              <button
                className="primary-button"
                disabled={createDisabled}
                type="button"
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending ? "Saving..." : "Create binding"}
              </button>
            </div>
          </div>
        </Panel>

        <HelpRail
          title="Access help"
          items={[
            {
              label: "Operator scope",
              description: "Operators can manage workflows, actions, suppressions, and alert rules, but they cannot change access or global communications.",
            },
            {
              label: "Admin scope",
              description: "Admins can do everything operators can, plus manage role bindings and global communications.",
            },
            {
              label: "Superuser safety",
              description: "The local superuser remains outside normal RBAC binding changes so there is always a recovery path.",
            },
            {
              label: "Adding providers",
              description: "Auth0, Azure AD, and Active Directory are enabled through Helm auth settings and secrets, then they appear here for binding management. This page does not create provider connections by itself.",
            },
          ]}
        />
      </div>

      <Panel title="Role bindings" subtitle="Change roles inline or remove bindings that are no longer needed.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Type</th>
                <th>Target</th>
                <th>Role</th>
                <th>Created by</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {bindingsQuery.data.map((binding) => (
                <tr key={binding.id}>
                  <td>{binding.provider}</td>
                  <td>{binding.binding_type}</td>
                  <td>{binding.binding_type === "group" ? binding.external_group || "-" : binding.principal?.display_name || binding.principal?.username || "-"}</td>
                  <td>
                    <select
                      value={binding.role}
                      onChange={(event) => updateMutation.mutate({ id: binding.id, nextRole: event.target.value })}
                    >
                      <option value="reader">Reader</option>
                      <option value="operator">Operator</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td>{binding.created_by || "-"}</td>
                  <td>{formatDate(binding.updated_at)}</td>
                  <td className="action-cell">
                    <button
                      className="danger-button"
                      disabled={deleteMutation.isPending}
                      type="button"
                      onClick={() => {
                        if (window.confirm("Delete this role binding?")) {
                          deleteMutation.mutate(binding.id);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Observed principals" subtitle="Users appear here after a successful external-provider login.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>User</th>
                <th>Groups</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {principalsQuery.data.map((item) => (
                <tr key={item.id}>
                  <td>{item.provider}</td>
                  <td>{item.display_name || item.username}</td>
                  <td>{item.groups.length ? item.groups.join(", ") : "-"}</td>
                  <td>{formatDate(item.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function NavGroup({
  title,
  items,
}: {
  title: string;
  items: Array<{ to: string; label: string }>;
}) {
  return (
    <div className="nav-group">
      <div className="nav-group-title">{title}</div>
      <div className="nav-group-links">
        {items.map((item) => (
          <NavLink
            className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            key={item.to}
            to={item.to}
          >
            {item.label}
          </NavLink>
        ))}
      </div>
    </div>
  );
}

function PageHeader({ title, description }: { title: string; description: string }) {
  return (
    <section className="page-header">
      <div className="eyebrow">Operator workspace</div>
      <h3>{title}</h3>
      <p>{description}</p>
    </section>
  );
}

function HelpRail({
  title,
  items,
}: {
  title: string;
  items: Array<{ label: string; description: string }>;
}) {
  return (
    <aside className="help-rail">
      <div className="eyebrow">Page guide</div>
      <h4>{title}</h4>
      <div className="help-list">
        {items.map((item) => (
          <div className="help-item" key={item.label}>
            <strong>{item.label}</strong>
            <p>{item.description}</p>
          </div>
        ))}
      </div>
    </aside>
  );
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel-card">
      <div className="panel-head">
        <div>
          <h4>{title}</h4>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function MetricCard({
  title,
  value,
  tone,
  children,
}: {
  title: string;
  value: string;
  tone: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={`metric-card tone-${statusTone(tone)}`}>
      <span>{title}</span>
      <strong>{value}</strong>
      <p>{children}</p>
    </div>
  );
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-pill">
      <span>{label}</span>
      <strong>{titleize(value)}</strong>
    </div>
  );
}

function StatusBadge({
  children,
  status,
}: {
  children: React.ReactNode;
  status?: string | null;
}) {
  return <span className={`status-badge tone-${statusTone(status)}`}>{children}</span>;
}

function FormField({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="form-field">
      <span className="field-label">
        {label}
        {help ? <HelpBubble help={help} label={label} /> : null}
      </span>
      {children}
    </label>
  );
}

function HelpBubble({ label, help }: { label: string; help: string }) {
  const [open, setOpen] = useState(false);
  const tooltipId = useId();

  function handleBlur(event: FocusEvent<HTMLSpanElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setOpen(false);
    }
  }

  return (
    <span
      className="help-bubble"
      onBlur={handleBlur}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        aria-describedby={open ? tooltipId : undefined}
        aria-expanded={open}
        aria-label={`Help for ${label}`}
        className="help-dot"
        onClick={() => setOpen((current) => !current)}
        onFocus={() => setOpen(true)}
        type="button"
      >
        ?
      </button>
      <span className={`help-popover ${open ? "open" : ""}`} id={tooltipId} role="tooltip">
        {help}
      </span>
    </span>
  );
}

function FieldError({ message }: { message?: string }) {
  return message ? <span className="field-error">{message}</span> : null;
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="kv-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return <div className="empty-state">{message}</div>;
}

function PageLoading({ message }: { message: string }) {
  return <div className="loading-card">{message}</div>;
}

function PageError({ message, compact = false }: { message: string; compact?: boolean }) {
  return <div className={`error-card ${compact ? "compact" : ""}`}>{message}</div>;
}

function FullscreenState({
  title,
  message,
  tone = "neutral",
}: {
  title: string;
  message: string;
  tone?: "neutral" | "error";
}) {
  return (
    <div className="fullscreen-state">
      <div className={`fullscreen-card ${tone}`}>
        <div className="eyebrow">PoundCake</div>
        <h1>{title}</h1>
        <p>{message}</p>
      </div>
    </div>
  );
}

function useSettings() {
  const settings = useContext(SettingsContext);
  if (!settings) {
    throw new Error("Settings context is missing");
  }
  return settings;
}

function usePrincipal() {
  const principal = useContext(PrincipalContext);
  if (!principal) {
    throw new Error("Principal context is missing");
  }
  return principal;
}

function useToast() {
  return useContext(ToastContext);
}

function hasRole(
  principal: AuthMeRecord,
  role: "reader" | "operator" | "admin",
) {
  if (principal.is_superuser) {
    return true;
  }
  if (principal.role === "service") {
    return false;
  }
  const order = {
    reader: 0,
    operator: 1,
    admin: 2,
  } as const;
  return order[principal.role] >= order[role];
}

function canManageSuppressions(principal: AuthMeRecord) {
  return hasRole(principal, "operator");
}

function canManageAlertRules(principal: AuthMeRecord) {
  return hasRole(principal, "operator");
}

function canManageWorkflows(principal: AuthMeRecord) {
  return hasRole(principal, "operator");
}

function canManageActions(principal: AuthMeRecord) {
  return hasRole(principal, "operator");
}

function canManageGlobalCommunications(principal: AuthMeRecord) {
  return hasRole(principal, "admin");
}

function canManageAccess(principal: AuthMeRecord) {
  return hasRole(principal, "admin");
}

function getRouteName(pathname: string): string {
  if (pathname.startsWith("/incidents")) return "Incidents";
  if (pathname.startsWith("/communications")) return "Communications";
  if (pathname.startsWith("/suppressions")) return "Suppressions";
  if (pathname.startsWith("/activity")) return "Activity";
  if (pathname.startsWith("/config/alert-rules")) return "Alert Rules";
  if (pathname.startsWith("/config/communications")) return "Global Communications";
  if (pathname.startsWith("/config/workflows")) return "Workflows";
  if (pathname.startsWith("/config/actions")) return "Actions";
  if (pathname.startsWith("/config/access")) return "Access";
  return "Overview";
}

function isLoginPath(pathname: string): boolean {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  return normalized === "/login";
}

function getLoginNextTarget(searchParams: URLSearchParams): string {
  const raw = searchParams.get("next");
  if (!raw || !raw.startsWith("/")) {
    return "/overview";
  }
  if (raw === "/login" || raw.startsWith("/login?")) {
    return "/overview";
  }
  return raw;
}

function isTimelineEventHighlighted(
  event: IncidentTimelineEvent,
  highlightedCommunicationId?: string,
  highlightedDishId?: string,
): boolean {
  if (highlightedDishId && event.correlation_ids.dish_id === highlightedDishId) {
    return true;
  }
  if (
    highlightedCommunicationId
    && (event.correlation_ids.bakery_operation_id === highlightedCommunicationId
      || event.correlation_ids.bakery_ticket_id === highlightedCommunicationId)
  ) {
    return true;
  }
  return false;
}

function getErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return "Something went wrong.";
}

function describeAuthProviderModes(provider: AuthProviderRecord): string {
  if (provider.password_login) {
    return "Password login enabled.";
  }
  if (provider.browser_login && provider.device_login) {
    return "Browser login and CLI device login enabled.";
  }
  if (provider.browser_login) {
    return "Browser login enabled.";
  }
  if (provider.device_login) {
    return "CLI device login enabled.";
  }
  return "Provider available.";
}

function parseJsonObject(value?: string, label?: string): Record<string, unknown> | undefined {
  if (!value || !value.trim()) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(value);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error();
    }
    return parsed as Record<string, unknown>;
  } catch {
    throw new Error(`${label || "JSON"} must be a valid object.`);
  }
}

function parseOptionalJson(value?: string, label?: string): Record<string, unknown> | undefined {
  if (!value || !value.trim()) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(value);
    if (Array.isArray(parsed) || typeof parsed !== "object" || parsed === null) {
      throw new Error();
    }
    return parsed as Record<string, unknown>;
  } catch {
    throw new Error(`${label || "JSON"} must be a valid object.`);
  }
}

function normalizeProviderConfigForForm(
  executionTarget: string,
  providerConfig: Record<string, unknown> | undefined,
): Record<string, unknown> {
  const config = { ...(providerConfig || {}) };
  if (executionTarget === "github") {
    if (Array.isArray(config.labels)) {
      config.labels = config.labels.join(", ");
    }
    if (Array.isArray(config.assignees)) {
      config.assignees = config.assignees.join(", ");
    }
  }
  return config;
}

function emptyCommunicationRoute(executionTarget = "rackspace_core") {
  return {
    id: crypto.randomUUID(),
    label: "",
    execution_target: executionTarget,
    destination_target: "",
    provider_config: {},
    enabled: true,
    position: 1,
  };
}

function providerConfigSummary(
  executionTarget: string,
  providerConfig: Record<string, unknown> | undefined,
): string {
  const config = providerConfig || {};
  const pairs = Object.entries(config)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(",") : String(value)}`);
  if (!pairs.length) {
    return executionTarget === "teams" || executionTarget === "discord"
      ? "No provider config required"
      : "No provider config set";
  }
  return pairs.join(" | ");
}

function CommunicationRouteProviderConfigFields({
  form,
  basePath,
  executionTarget,
}: {
  form: ReturnType<typeof useForm<any>>;
  basePath: string;
  executionTarget: string;
}) {
  const register = (suffix: string) => form.register(`${basePath}.provider_config.${suffix}` as any);

  if (executionTarget === "rackspace_core") {
    return (
      <div className="grid-two">
        <FormField label="Account number" help="Required Rackspace Core account number for this route.">
          <input {...register("account_number")} placeholder="1781738" />
        </FormField>
        <FormField label="Queue" help="Optional Core queue. Bakery defaults still apply when this is blank.">
          <input {...register("queue")} placeholder="CloudBuilders Support" />
        </FormField>
        <FormField label="Subcategory" help="Optional Core subcategory. Bakery defaults still apply when this is blank.">
          <input {...register("subcategory")} placeholder="Monitoring" />
        </FormField>
        <FormField label="Source" help="Optional Core source label such as RunBook.">
          <input {...register("source")} placeholder="RunBook" />
        </FormField>
      </div>
    );
  }

  if (executionTarget === "servicenow") {
    return (
      <div className="grid-two">
        <FormField label="Urgency" help="Optional ServiceNow urgency value.">
          <input {...register("urgency")} placeholder="3" />
        </FormField>
        <FormField label="Impact" help="Optional ServiceNow impact value.">
          <input {...register("impact")} placeholder="3" />
        </FormField>
      </div>
    );
  }

  if (executionTarget === "jira") {
    return (
      <div className="grid-two">
        <FormField label="Project key" help="Required Jira project key for this route.">
          <input {...register("project_key")} placeholder="OPS" />
        </FormField>
        <FormField label="Issue type" help="Optional Jira issue type.">
          <input {...register("issue_type")} placeholder="Task" />
        </FormField>
      </div>
    );
  }

  if (executionTarget === "github") {
    return (
      <div className="grid-two">
        <FormField label="Owner" help="Required GitHub org or user name.">
          <input {...register("owner")} placeholder="rackerlabs" />
        </FormField>
        <FormField label="Repo" help="Required GitHub repository name.">
          <input {...register("repo")} placeholder="poundcake" />
        </FormField>
        <FormField label="Labels" help="Optional comma-separated GitHub labels.">
          <input {...register("labels")} placeholder="alert, monitoring" />
        </FormField>
        <FormField label="Assignees" help="Optional comma-separated GitHub assignees.">
          <input {...register("assignees")} placeholder="octocat" />
        </FormField>
      </div>
    );
  }

  if (executionTarget === "pagerduty") {
    return (
      <div className="grid-two">
        <FormField label="Service ID" help="Required PagerDuty service id.">
          <input {...register("service_id")} placeholder="PXXXXXX" />
        </FormField>
        <FormField label="From email" help="Required PagerDuty sender email.">
          <input {...register("from_email")} placeholder="alerts@example.com" />
        </FormField>
        <FormField label="Urgency" help="Optional PagerDuty urgency override.">
          <input {...register("urgency")} placeholder="high" />
        </FormField>
      </div>
    );
  }

  return (
    <div className="helper-card">
      <strong>Provider config</strong>
      <p>This provider does not require extra route configuration.</p>
    </div>
  );
}

function moveField(
  fieldArray: ReturnType<typeof useFieldArray<z.infer<typeof workflowSchema>, "recipe_ingredients">>,
  index: number,
  direction: number,
) {
  const nextIndex = index + direction;
  if (nextIndex < 0 || nextIndex >= fieldArray.fields.length) {
    return;
  }
  fieldArray.move(index, nextIndex);
}

function moveCommunicationRoute(
  fieldArray: {
    fields: Array<{ id: string }>;
    move: (from: number, to: number) => void;
  },
  index: number,
  direction: number,
) {
  const nextIndex = index + direction;
  if (nextIndex < 0 || nextIndex >= fieldArray.fields.length) {
    return;
  }
  fieldArray.move(index, nextIndex);
}

function resetWorkflowForm(
  form: ReturnType<typeof useForm<z.infer<typeof workflowSchema>>>,
  steps: ReturnType<typeof useFieldArray<z.infer<typeof workflowSchema>, "recipe_ingredients">>,
  communicationRoutes: ReturnType<typeof useFieldArray<z.infer<typeof workflowSchema>, "communications_routes">>,
  globalCommunicationsConfigured: boolean,
) {
  form.reset({
    name: "",
    description: "",
    enabled: true,
    clear_timeout_sec: "",
    communications_mode: globalCommunicationsConfigured ? "inherit" : "local",
    communications_routes: [],
    recipe_ingredients: [],
  });
  steps.replace([
    {
      ingredient_id: 0,
      step_order: 1,
      on_success: "continue",
      run_phase: "both",
      run_condition: "always",
      parallel_group: 0,
      depth: 0,
      execution_parameters_override_text: "",
    },
  ]);
  communicationRoutes.replace([]);
}

function describeWorkflowStep(
  step: z.infer<typeof workflowStepSchema> | undefined,
  actions: IngredientRecord[],
): string {
  if (!step) {
    return "No step selected.";
  }
  const action = actions.find((item) => item.id === Number(step.ingredient_id));
  if (!action) {
    return "Choose an action to describe this step.";
  }
  return `Run ${action.task_key_template} during ${step.run_phase} when ${step.run_condition}. If it succeeds, ${step.on_success}.`;
}

function buildWorkflowPreview(
  steps: z.infer<typeof workflowStepSchema>[],
  actions: IngredientRecord[],
  workflowName: string,
  communicationsMode: "inherit" | "local",
  routes: Array<Pick<CommunicationRouteRecord, "label" | "execution_target" | "enabled">>,
): string {
  const fragments = steps
    .map((step, index) => {
      const action = actions.find((item) => item.id === Number(step.ingredient_id));
      if (!action) {
        return `step ${index + 1} is waiting for an action`;
      }
      return `${step.run_phase} -> ${action.task_key_template} (${titleize(action.execution_target)})`;
    })
    .filter(Boolean);
  const enabledRoutes = routes.filter((route) => route.enabled);
  const communicationsSummary = communicationsMode === "inherit"
    ? enabledRoutes.length
      ? `inherit ${enabledRoutes.length} global communication route(s)`
      : "inherit no configured global communication routes yet"
    : enabledRoutes.length
      ? `use ${enabledRoutes.length} workflow-specific communication route(s)`
      : "use workflow-specific communications with no enabled routes yet";
  if (!fragments.length) {
    return `${workflowName || "This workflow"} will ${communicationsSummary} once you add execution steps.`;
  }
  return `${workflowName || "This workflow"} will ${communicationsSummary}, then run ${fragments.join(", then ")}.`;
}

function classifyActionTemplate(action: IngredientRecord): "ticket" | "chat" | "remediation" | "custom" {
  if (action.execution_purpose === "remediation") return "remediation";
  if (["teams", "discord"].includes(action.execution_target)) return "chat";
  if (["rackspace_core", "servicenow", "jira", "github", "pagerduty"].includes(action.execution_target)) {
    return "ticket";
  }
  return "custom";
}

function buildActionPreview(values: z.infer<typeof actionSchema>): string {
  const route = values.destination_target
    ? `${values.execution_target}:${values.destination_target}`
    : values.execution_target;
  return `${titleize(values.template)} action "${values.task_key_template || "unnamed"}" will use ${values.execution_engine} against ${route || "a target"} with ${values.retry_count} retries.`;
}

function isCommunicationAction(action: IngredientRecord): boolean {
  return action.execution_engine === "bakery" && action.execution_purpose === "comms";
}

export default App;
