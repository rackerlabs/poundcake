import { z } from "zod";

const unknownRecord = z.record(z.unknown());
const stringRecord = z.record(z.string());

export const deleteResponseSchema = z.object({
  status: z.string(),
  message: z.string().nullable().optional(),
});

export const appSettingsSchema = z.object({
  auth_enabled: z.boolean(),
  prometheus_use_crds: z.boolean(),
  prometheus_crd_namespace: z.string(),
  prometheus_url: z.string(),
  git_enabled: z.boolean(),
  git_provider: z.string().nullable(),
  stackstorm_enabled: z.boolean(),
  version: z.string(),
  global_communications_configured: z.boolean(),
});

export const communicationRouteSchema = z.object({
  id: z.string(),
  label: z.string(),
  execution_target: z.string(),
  destination_target: z.string(),
  provider_config: unknownRecord,
  enabled: z.boolean(),
  position: z.number(),
});

export const communicationPolicySchema = z.object({
  configured: z.boolean(),
  routes: z.array(communicationRouteSchema),
  lifecycle_summary: stringRecord,
});

export const componentHealthSchema = z.object({
  status: z.string(),
  message: z.string().nullable().optional(),
  details: unknownRecord.nullable().optional(),
});

export const healthResponseSchema = z.object({
  status: z.string(),
  version: z.string(),
  instance_id: z.string(),
  timestamp: z.string(),
  components: z.record(componentHealthSchema),
});

export const statsResponseSchema = z.object({
  total_alerts: z.number(),
  total_recipes: z.number(),
  total_executions: z.number(),
  alerts_by_processing_status: z.record(z.number()),
  alerts_by_alert_status: z.record(z.number()),
  executions_by_status: z.record(z.number()),
  recent_alerts: z.number(),
});

export const observabilityOverviewResponseSchema = z.object({
  health: unknownRecord,
  queue: z.record(z.number()),
  failures: z.object({
    orders_failed: z.number(),
    dishes_failed: z.number(),
    top_errors: z.array(z.object({ error: z.string(), count: z.number() })),
    runbook_hints: z.array(z.string()),
  }),
  bakery: z.object({
    summary_failures: z.number(),
    order_dead_letters: z.number(),
  }),
  suppressions: z.object({
    active: z.number(),
    retrying_operations: z.number(),
    dead_letter: z.number(),
  }),
});

export const observabilityActivityRecordSchema = z.object({
  type: z.string(),
  status: z.string(),
  title: z.string(),
  summary: z.string().nullable().optional(),
  timestamp: z.string().nullable().optional(),
  target_kind: z.string(),
  target_id: z.string(),
  link_hint: z.string().nullable().optional(),
  metadata: unknownRecord,
});

export const communicationActivityRecordSchema = z.object({
  communication_id: z.string(),
  reference_type: z.string(),
  reference_id: z.string(),
  reference_name: z.string().nullable().optional(),
  channel: z.string(),
  destination: z.string().nullable().optional(),
  ticket_id: z.string().nullable().optional(),
  provider_reference_id: z.string().nullable().optional(),
  operation_id: z.string().nullable().optional(),
  lifecycle_state: z.string().nullable().optional(),
  remote_state: z.string().nullable().optional(),
  last_error: z.string().nullable().optional(),
  writable: z.boolean().nullable().optional(),
  reopenable: z.boolean().nullable().optional(),
  updated_at: z.string().nullable().optional(),
});

export const orderCommunicationSchema = z.object({
  id: z.number(),
  order_id: z.number(),
  execution_target: z.string(),
  destination_target: z.string(),
  bakery_ticket_id: z.string().nullable().optional(),
  bakery_operation_id: z.string().nullable().optional(),
  lifecycle_state: z.string(),
  remote_state: z.string().nullable().optional(),
  writable: z.boolean(),
  reopenable: z.boolean(),
  last_error: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const orderResponseSchema = z.object({
  id: z.number(),
  req_id: z.string(),
  fingerprint: z.string(),
  alert_status: z.string(),
  alert_group_name: z.string(),
  processing_status: z.string(),
  is_active: z.boolean(),
  remediation_outcome: z.string(),
  clear_timeout_sec: z.number().nullable().optional(),
  clear_deadline_at: z.string().nullable().optional(),
  clear_timed_out_at: z.string().nullable().optional(),
  auto_close_eligible: z.boolean(),
  severity: z.string().nullable().optional(),
  instance: z.string().nullable().optional(),
  counter: z.number(),
  bakery_ticket_id: z.string().nullable().optional(),
  bakery_operation_id: z.string().nullable().optional(),
  bakery_ticket_state: z.string().nullable().optional(),
  bakery_permanent_failure: z.boolean(),
  bakery_last_error: z.string().nullable().optional(),
  bakery_comms_id: z.string().nullable().optional(),
  labels: unknownRecord,
  annotations: unknownRecord.nullable().optional(),
  raw_data: unknownRecord.nullable().optional(),
  starts_at: z.string(),
  ends_at: z.string().nullable().optional(),
  communications: z.array(orderCommunicationSchema),
  created_at: z.string(),
  updated_at: z.string(),
});

export const incidentTimelineEventSchema = z.object({
  timestamp: z.string().nullable().optional(),
  event_type: z.string(),
  status: z.string(),
  title: z.string(),
  details: unknownRecord,
  correlation_ids: z.record(z.string()),
});

export const incidentTimelineResponseSchema = z.object({
  order: orderResponseSchema,
  events: z.array(incidentTimelineEventSchema),
});

export const suppressionMatcherSchema = z.object({
  label_key: z.string(),
  operator: z.string(),
  value: z.string().nullable().optional(),
});

export const suppressionRecordSchema = z.object({
  id: z.number(),
  name: z.string(),
  reason: z.string().nullable().optional(),
  scope: z.string(),
  status: z.string(),
  enabled: z.boolean(),
  starts_at: z.string(),
  ends_at: z.string(),
  canceled_at: z.string().nullable().optional(),
  created_by: z.string().nullable().optional(),
  summary_ticket_enabled: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
  matchers: z.array(suppressionMatcherSchema),
});

export const dishRecordSchema = z.object({
  id: z.number(),
  req_id: z.string(),
  order_id: z.number().nullable().optional(),
  recipe_id: z.number(),
  recipe: z.object({ id: z.number(), name: z.string() }).nullable().optional(),
  execution_ref: z.string().nullable().optional(),
  execution_status: z.string().nullable().optional(),
  processing_status: z.string(),
  run_phase: z.string(),
  expected_duration_sec: z.number().nullable().optional(),
  actual_duration_sec: z.number().nullable().optional(),
  error_message: z.string().nullable().optional(),
  retry_attempt: z.number(),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const prometheusRuleSchema = z.object({
  group: z.string(),
  crd: z.string().optional(),
  file: z.string().optional(),
  namespace: z.string().optional(),
  interval: z.string().optional(),
  name: z.string(),
  query: z.string(),
  duration: z.string().optional(),
  labels: stringRecord.optional(),
  annotations: stringRecord.optional(),
  state: z.string().optional(),
  health: z.string().optional(),
});

export const prometheusRuleListResponseSchema = z.object({
  rules: z.array(prometheusRuleSchema),
  source: z.string(),
});

export const ingredientRecordSchema = z.object({
  id: z.number(),
  execution_target: z.string(),
  destination_target: z.string(),
  task_key_template: z.string(),
  execution_id: z.string().nullable().optional(),
  execution_payload: unknownRecord.nullable().optional(),
  execution_parameters: unknownRecord.nullable().optional(),
  execution_engine: z.string(),
  execution_purpose: z.string(),
  is_default: z.boolean(),
  is_blocking: z.boolean(),
  expected_duration_sec: z.number(),
  timeout_duration_sec: z.number(),
  retry_count: z.number(),
  retry_delay: z.number(),
  on_failure: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  deleted: z.boolean(),
  deleted_at: z.string().nullable().optional(),
});

export const recipeStepRecordSchema = z.object({
  id: z.number(),
  recipe_id: z.number(),
  ingredient_id: z.number(),
  step_order: z.number(),
  on_success: z.string(),
  parallel_group: z.number(),
  depth: z.number(),
  execution_parameters_override: unknownRecord.nullable().optional(),
  run_phase: z.string(),
  run_condition: z.string(),
  ingredient: ingredientRecordSchema.nullable().optional(),
});

export const recipeCommunicationsRecordSchema = z.object({
  mode: z.enum(["inherit", "local"]),
  effective_source: z.enum(["global", "local"]).nullable().optional(),
  routes: z.array(communicationRouteSchema),
});

export const recipeRecordSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string().nullable().optional(),
  enabled: z.boolean(),
  clear_timeout_sec: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  deleted: z.boolean(),
  deleted_at: z.string().nullable().optional(),
  recipe_ingredients: z.array(recipeStepRecordSchema),
  communications: recipeCommunicationsRecordSchema,
});
