export interface AuthProviderRecord {
  name: "local" | "active_directory" | "auth0" | "azure_ad" | "service";
  label: string;
  login_mode: string;
  cli_login_mode: string;
  browser_login: boolean;
  device_login: boolean;
  password_login: boolean;
}

export interface AuthMeRecord {
  username: string;
  display_name?: string | null;
  provider: "local" | "active_directory" | "auth0" | "azure_ad" | "service";
  role: "reader" | "operator" | "admin" | "service";
  principal_type: "user" | "service";
  principal_id?: number | null;
  is_superuser: boolean;
  permissions: string[];
  groups: string[];
  expires_at?: string | null;
}

export interface AuthPrincipalRecord {
  id: number;
  provider: "local" | "active_directory" | "auth0" | "azure_ad" | "service";
  subject_id: string;
  username: string;
  display_name?: string | null;
  principal_type: "user" | "service";
  groups: string[];
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

export interface AuthRoleBindingRecord {
  id: number;
  provider: "local" | "active_directory" | "auth0" | "azure_ad" | "service";
  binding_type: "user" | "group";
  role: "reader" | "operator" | "admin" | "service";
  principal_id?: number | null;
  external_group?: string | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
  principal?: AuthPrincipalRecord | null;
}

export interface AppSettings {
  auth_enabled: boolean;
  rbac_enabled: boolean;
  auth_providers: AuthProviderRecord[];
  prometheus_use_crds: boolean;
  prometheus_crd_namespace: string;
  prometheus_url: string;
  git_enabled: boolean;
  git_provider: string | null;
  stackstorm_enabled: boolean;
  version: string;
  global_communications_configured: boolean;
}

export interface CommunicationRouteRecord {
  id: string;
  label: string;
  execution_target: string;
  destination_target: string;
  provider_config: Record<string, unknown>;
  enabled: boolean;
  position: number;
}

export interface CommunicationPolicyRecord {
  configured: boolean;
  routes: CommunicationRouteRecord[];
  lifecycle_summary: Record<string, string>;
}

export interface RecipeCommunicationsRecord {
  mode: "inherit" | "local";
  effective_source?: "global" | "local" | null;
  routes: CommunicationRouteRecord[];
}

export interface ComponentHealth {
  status: string;
  message?: string | null;
  details?: Record<string, unknown> | null;
}

export interface HealthResponse {
  status: string;
  version: string;
  instance_id: string;
  timestamp: string;
  components: Record<string, ComponentHealth>;
}

export interface StatsResponse {
  total_alerts: number;
  total_recipes: number;
  total_executions: number;
  alerts_by_processing_status: Record<string, number>;
  alerts_by_alert_status: Record<string, number>;
  executions_by_status: Record<string, number>;
  recent_alerts: number;
}

export interface ObservabilityOverviewResponse {
  health: Record<string, unknown>;
  queue: Record<string, number>;
  failures: {
    orders_failed: number;
    dishes_failed: number;
    top_errors: Array<{ error: string; count: number }>;
    runbook_hints: string[];
  };
  bakery: {
    summary_failures: number;
    order_dead_letters: number;
  };
  suppressions: {
    active: number;
    retrying_operations: number;
    dead_letter: number;
  };
}

export interface ObservabilityActivityRecord {
  type: string;
  status: string;
  title: string;
  summary?: string | null;
  timestamp?: string | null;
  target_kind: string;
  target_id: string;
  link_hint?: string | null;
  metadata: Record<string, unknown>;
}

export interface OrderCommunication {
  id: number;
  order_id: number;
  execution_target: string;
  destination_target: string;
  bakery_ticket_id?: string | null;
  bakery_operation_id?: string | null;
  lifecycle_state: string;
  remote_state?: string | null;
  writable: boolean;
  reopenable: boolean;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrderResponse {
  id: number;
  req_id: string;
  fingerprint: string;
  alert_status: string;
  alert_group_name: string;
  processing_status: string;
  is_active: boolean;
  remediation_outcome: string;
  clear_timeout_sec?: number | null;
  clear_deadline_at?: string | null;
  clear_timed_out_at?: string | null;
  auto_close_eligible: boolean;
  severity?: string | null;
  instance?: string | null;
  counter: number;
  bakery_ticket_id?: string | null;
  bakery_operation_id?: string | null;
  bakery_ticket_state?: string | null;
  bakery_permanent_failure: boolean;
  bakery_last_error?: string | null;
  bakery_comms_id?: string | null;
  labels: Record<string, unknown>;
  annotations?: Record<string, unknown> | null;
  raw_data?: Record<string, unknown> | null;
  starts_at: string;
  ends_at?: string | null;
  communications: OrderCommunication[];
  created_at: string;
  updated_at: string;
}

export interface IncidentTimelineEvent {
  timestamp?: string | null;
  event_type: string;
  status: string;
  title: string;
  details: Record<string, unknown>;
  correlation_ids: Record<string, string>;
}

export interface IncidentTimelineResponse {
  order: OrderResponse;
  events: IncidentTimelineEvent[];
}

export interface CommunicationActivityRecord {
  communication_id: string;
  reference_type: string;
  reference_id: string;
  reference_name?: string | null;
  channel: string;
  destination?: string | null;
  ticket_id?: string | null;
  provider_reference_id?: string | null;
  operation_id?: string | null;
  lifecycle_state?: string | null;
  remote_state?: string | null;
  last_error?: string | null;
  writable?: boolean | null;
  reopenable?: boolean | null;
  updated_at?: string | null;
}

export interface SuppressionMatcher {
  label_key: string;
  operator: string;
  value?: string | null;
}

export interface SuppressionRecord {
  id: number;
  name: string;
  reason?: string | null;
  scope: string;
  status: string;
  enabled: boolean;
  starts_at: string;
  ends_at: string;
  canceled_at?: string | null;
  created_by?: string | null;
  summary_ticket_enabled: boolean;
  created_at: string;
  updated_at: string;
  matchers: SuppressionMatcher[];
}

export interface DishRecord {
  id: number;
  req_id: string;
  order_id?: number | null;
  recipe_id: number;
  recipe?: {
    id: number;
    name: string;
  } | null;
  execution_ref?: string | null;
  execution_status?: string | null;
  processing_status: string;
  run_phase: string;
  expected_duration_sec?: number | null;
  actual_duration_sec?: number | null;
  error_message?: string | null;
  retry_attempt: number;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PrometheusRule {
  group: string;
  crd?: string;
  file?: string;
  namespace?: string;
  interval?: string;
  name: string;
  query: string;
  duration?: string;
  labels?: Record<string, string>;
  annotations?: Record<string, string>;
  state?: string;
  health?: string;
}

export interface PrometheusRuleListResponse {
  rules: PrometheusRule[];
  source: string;
}

export interface IngredientRecord {
  id: number;
  execution_target: string;
  destination_target: string;
  task_key_template: string;
  execution_id?: string | null;
  action_id?: string | null;
  execution_payload?: Record<string, unknown> | null;
  execution_parameters?: Record<string, unknown> | null;
  execution_engine: string;
  execution_purpose: string;
  ingredient_kind?: string | null;
  is_default: boolean;
  is_blocking: boolean;
  expected_duration_sec: number;
  timeout_duration_sec: number;
  retry_count: number;
  retry_delay: number;
  on_failure: string;
  created_at: string;
  updated_at: string;
  deleted: boolean;
  deleted_at?: string | null;
}

export interface RecipeStepRecord {
  id: number;
  recipe_id: number;
  ingredient_id: number;
  step_order: number;
  on_success: string;
  parallel_group: number;
  depth: number;
  execution_parameters_override?: Record<string, unknown> | null;
  run_phase: string;
  run_condition: string;
  ingredient?: IngredientRecord | null;
}

export interface RecipeRecord {
  id: number;
  name: string;
  description?: string | null;
  enabled: boolean;
  clear_timeout_sec?: number | null;
  created_at: string;
  updated_at: string;
  deleted: boolean;
  deleted_at?: string | null;
  recipe_ingredients: RecipeStepRecord[];
  communications: RecipeCommunicationsRecord;
}
