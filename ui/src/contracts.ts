import { z } from "zod";

const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict();

const providerNameSchema = z.enum(["local", "active_directory", "auth0", "azure_ad", "service"]);
const roleSchema = z.enum(["reader", "operator", "admin", "service"]);
const userRoleSchema = z.enum(["reader", "operator", "admin"]);
const principalTypeSchema = z.enum(["user", "service"]);
const bindingTypeSchema = z.enum(["user", "group"]);
const communicationsModeSchema = z.enum(["inherit", "local"]);
const unknownRecordSchema = z.record(z.unknown());
const stringRecordSchema = z.record(z.string());
const numberRecordSchema = z.record(z.number());
const repoSyncExportValueSchema = z.union([z.string(), z.number(), z.null()]);

export const authProviderRecordSchema = strictObject({
  name: providerNameSchema,
  label: z.string(),
  login_mode: z.string(),
  cli_login_mode: z.string(),
  browser_login: z.boolean(),
  device_login: z.boolean(),
  password_login: z.boolean(),
});
export type AuthProviderRecord = z.infer<typeof authProviderRecordSchema>;
export const authProviderRecordArraySchema = z.array(authProviderRecordSchema);

export const authMeRecordSchema = strictObject({
  username: z.string(),
  display_name: z.string().nullable().optional(),
  provider: providerNameSchema,
  role: roleSchema,
  principal_type: principalTypeSchema,
  principal_id: z.number().int().nullable().optional(),
  is_superuser: z.boolean(),
  permissions: z.array(z.string()),
  groups: z.array(z.string()),
  expires_at: z.string().nullable().optional(),
});
export type AuthMeRecord = z.infer<typeof authMeRecordSchema>;

export const authPrincipalRecordSchema = strictObject({
  id: z.number().int(),
  provider: providerNameSchema,
  subject_id: z.string(),
  username: z.string(),
  display_name: z.string().nullable().optional(),
  principal_type: principalTypeSchema,
  groups: z.array(z.string()),
  last_seen_at: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type AuthPrincipalRecord = z.infer<typeof authPrincipalRecordSchema>;
export const authPrincipalRecordArraySchema = z.array(authPrincipalRecordSchema);

export const authRoleBindingRecordSchema = strictObject({
  id: z.number().int(),
  provider: providerNameSchema,
  binding_type: bindingTypeSchema,
  role: roleSchema,
  principal_id: z.number().int().nullable().optional(),
  external_group: z.string().nullable().optional(),
  created_by: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  principal: authPrincipalRecordSchema.nullable().optional(),
});
export type AuthRoleBindingRecord = z.infer<typeof authRoleBindingRecordSchema>;
export const authRoleBindingRecordArraySchema = z.array(authRoleBindingRecordSchema);

export const appSettingsSchema = strictObject({
  auth_enabled: z.boolean(),
  rbac_enabled: z.boolean(),
  auth_providers: authProviderRecordArraySchema,
  prometheus_use_crds: z.boolean(),
  prometheus_crd_namespace: z.string(),
  prometheus_url: z.string(),
  git_enabled: z.boolean(),
  git_provider: z.string().nullable(),
  git_repo_url: z.string().nullable(),
  git_branch: z.string().nullable(),
  git_rules_path: z.string().nullable(),
  git_workflows_path: z.string().nullable(),
  git_actions_path: z.string().nullable(),
  stackstorm_enabled: z.boolean(),
  version: z.string(),
  global_communications_configured: z.boolean(),
});
export type AppSettings = z.infer<typeof appSettingsSchema>;

const repoSyncPullRequestSchema = strictObject({
  number: z.union([z.number(), z.string(), z.null()]).optional(),
  url: z.string().nullable().optional(),
});

export const repoSyncResponseSchema = strictObject({
  status: z.string(),
  message: z.string(),
  branch: z.string().nullable().optional(),
  pull_request: repoSyncPullRequestSchema.nullable().optional(),
  exported: z.record(repoSyncExportValueSchema).nullable().optional(),
  imported: z.record(z.number()).nullable().optional(),
  cleared: z.record(z.number()).nullable().optional(),
});
export type RepoSyncResponse = z.infer<typeof repoSyncResponseSchema>;

export const communicationRouteRecordSchema = strictObject({
  id: z.string(),
  label: z.string(),
  execution_target: z.string(),
  destination_target: z.string(),
  provider_config: unknownRecordSchema,
  enabled: z.boolean(),
  position: z.number().int(),
});
export type CommunicationRouteRecord = z.infer<typeof communicationRouteRecordSchema>;

export const communicationPolicyRecordSchema = strictObject({
  configured: z.boolean(),
  routes: z.array(communicationRouteRecordSchema),
  lifecycle_summary: stringRecordSchema,
});
export type CommunicationPolicyRecord = z.infer<typeof communicationPolicyRecordSchema>;

export const recipeCommunicationsRecordSchema = strictObject({
  mode: communicationsModeSchema,
  effective_source: z.enum(["global", "local"]).nullable().optional(),
  routes: z.array(communicationRouteRecordSchema),
});
export type RecipeCommunicationsRecord = z.infer<typeof recipeCommunicationsRecordSchema>;

export const componentHealthSchema = strictObject({
  status: z.string(),
  message: z.string().nullable().optional(),
  details: unknownRecordSchema.nullable().optional(),
});
export type ComponentHealth = z.infer<typeof componentHealthSchema>;

export const healthResponseSchema = strictObject({
  status: z.string(),
  version: z.string(),
  instance_id: z.string(),
  timestamp: z.string(),
  components: z.record(componentHealthSchema),
});
export type HealthResponse = z.infer<typeof healthResponseSchema>;

export const statsResponseSchema = strictObject({
  total_alerts: z.number(),
  total_recipes: z.number(),
  total_executions: z.number(),
  alerts_by_processing_status: numberRecordSchema,
  alerts_by_alert_status: numberRecordSchema,
  executions_by_status: numberRecordSchema,
  recent_alerts: z.number(),
});
export type StatsResponse = z.infer<typeof statsResponseSchema>;

export const observabilityOverviewResponseSchema = strictObject({
  health: unknownRecordSchema,
  queue: numberRecordSchema,
  failures: strictObject({
    orders_failed: z.number(),
    dishes_failed: z.number(),
    top_errors: z.array(
      strictObject({
        error: z.string(),
        count: z.number(),
      }),
    ),
    runbook_hints: z.array(z.string()),
  }),
  bakery: strictObject({
    summary_failures: z.number(),
    order_dead_letters: z.number(),
  }),
  suppressions: strictObject({
    active: z.number(),
    retrying_operations: z.number(),
    dead_letter: z.number(),
  }),
});
export type ObservabilityOverviewResponse = z.infer<typeof observabilityOverviewResponseSchema>;

export const observabilityActivityRecordSchema = strictObject({
  type: z.string(),
  status: z.string(),
  title: z.string(),
  summary: z.string().nullable().optional(),
  timestamp: z.string().nullable().optional(),
  target_kind: z.string(),
  target_id: z.string(),
  link_hint: z.string().nullable().optional(),
  metadata: unknownRecordSchema,
});
export type ObservabilityActivityRecord = z.infer<typeof observabilityActivityRecordSchema>;
export const observabilityActivityRecordArraySchema = z.array(observabilityActivityRecordSchema);

export const orderCommunicationSchema = strictObject({
  id: z.number().int(),
  order_id: z.number().int(),
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
export type OrderCommunication = z.infer<typeof orderCommunicationSchema>;

export const orderResponseSchema = strictObject({
  id: z.number().int(),
  req_id: z.string(),
  fingerprint: z.string(),
  fingerprint_when_active: z.string().nullable().optional(),
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
  labels: unknownRecordSchema,
  annotations: unknownRecordSchema.nullable().optional(),
  raw_data: unknownRecordSchema.nullable().optional(),
  starts_at: z.string(),
  ends_at: z.string().nullable().optional(),
  communications: z.array(orderCommunicationSchema),
  created_at: z.string(),
  updated_at: z.string(),
});
export type OrderResponse = z.infer<typeof orderResponseSchema>;
export const orderResponseArraySchema = z.array(orderResponseSchema);

export const incidentTimelineEventSchema = strictObject({
  timestamp: z.string().nullable().optional(),
  event_type: z.string(),
  status: z.string(),
  title: z.string(),
  details: unknownRecordSchema,
  correlation_ids: stringRecordSchema,
});
export type IncidentTimelineEvent = z.infer<typeof incidentTimelineEventSchema>;

export const incidentTimelineResponseSchema = strictObject({
  order: orderResponseSchema,
  events: z.array(incidentTimelineEventSchema),
});
export type IncidentTimelineResponse = z.infer<typeof incidentTimelineResponseSchema>;

export const communicationActivityRecordSchema = strictObject({
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
export type CommunicationActivityRecord = z.infer<typeof communicationActivityRecordSchema>;
export const communicationActivityRecordArraySchema = z.array(communicationActivityRecordSchema);

export const suppressionMatcherSchema = strictObject({
  label_key: z.string(),
  operator: z.string(),
  value: z.string().nullable().optional(),
});
export type SuppressionMatcher = z.infer<typeof suppressionMatcherSchema>;

export const suppressionRecordSchema = strictObject({
  id: z.number().int(),
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
export type SuppressionRecord = z.infer<typeof suppressionRecordSchema>;
export const suppressionRecordArraySchema = z.array(suppressionRecordSchema);

export const dishRecordSchema = strictObject({
  id: z.number().int(),
  req_id: z.string(),
  order_id: z.number().int().nullable().optional(),
  recipe_id: z.number().int(),
  recipe: z
    .object({
      id: z.number().int(),
      name: z.string(),
    })
    .nullable()
    .optional(),
  execution_ref: z.string().nullable().optional(),
  execution_status: z.string().nullable().optional(),
  processing_status: z.string(),
  run_phase: z.string(),
  expected_duration_sec: z.number().nullable().optional(),
  actual_duration_sec: z.number().nullable().optional(),
  result: z.unknown().nullable().optional(),
  error_message: z.string().nullable().optional(),
  retry_attempt: z.number().int(),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type DishRecord = z.infer<typeof dishRecordSchema>;
export const dishRecordArraySchema = z.array(dishRecordSchema);

export const prometheusRuleSchema = strictObject({
  group: z.string(),
  crd: z.string().optional(),
  file: z.string().optional(),
  namespace: z.string().optional(),
  interval: z.string().optional(),
  name: z.string(),
  query: z.string(),
  duration: z.string().optional(),
  labels: stringRecordSchema.optional(),
  annotations: stringRecordSchema.optional(),
  state: z.string().optional(),
  health: z.string().optional(),
});
export type PrometheusRule = z.infer<typeof prometheusRuleSchema>;

export const prometheusRuleListResponseSchema = strictObject({
  rules: z.array(prometheusRuleSchema),
  source: z.string(),
});
export type PrometheusRuleListResponse = z.infer<typeof prometheusRuleListResponseSchema>;

export const ingredientRecordSchema = strictObject({
  id: z.number().int(),
  execution_target: z.string(),
  destination_target: z.string(),
  task_key_template: z.string(),
  execution_id: z.string().nullable().optional(),
  action_id: z.string().nullable().optional(),
  execution_payload: unknownRecordSchema.nullable().optional(),
  execution_parameters: unknownRecordSchema.nullable().optional(),
  execution_engine: z.string(),
  execution_purpose: z.string(),
  ingredient_kind: z.string().nullable().optional(),
  is_default: z.boolean(),
  is_blocking: z.boolean(),
  expected_duration_sec: z.number(),
  timeout_duration_sec: z.number(),
  retry_count: z.number().int(),
  retry_delay: z.number().int(),
  on_failure: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  deleted: z.boolean(),
  deleted_at: z.string().nullable().optional(),
});
export type IngredientRecord = z.infer<typeof ingredientRecordSchema>;
export const ingredientRecordArraySchema = z.array(ingredientRecordSchema);

export const recipeStepRecordSchema = strictObject({
  id: z.number().int(),
  recipe_id: z.number().int(),
  ingredient_id: z.number().int(),
  step_order: z.number().int(),
  on_success: z.string(),
  parallel_group: z.number().int(),
  depth: z.number().int(),
  execution_parameters_override: unknownRecordSchema.nullable().optional(),
  run_phase: z.string(),
  run_condition: z.string(),
  ingredient: ingredientRecordSchema.nullable().optional(),
});
export type RecipeStepRecord = z.infer<typeof recipeStepRecordSchema>;

export const recipeRecordSchema = strictObject({
  id: z.number().int(),
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
export type RecipeRecord = z.infer<typeof recipeRecordSchema>;
export const recipeRecordArraySchema = z.array(recipeRecordSchema);

export const deleteResponseSchema = strictObject({
  status: z.string(),
  id: z.number().int(),
  message: z.string().nullable().optional(),
});
export type DeleteResponse = z.infer<typeof deleteResponseSchema>;

export const communicationRouteRequestSchema = strictObject({
  id: z.string().optional(),
  label: z.string().min(1),
  execution_target: z.string().min(1),
  destination_target: z.string().optional().default(""),
  provider_config: unknownRecordSchema.optional().default({}),
  enabled: z.boolean().optional().default(true),
  position: z.number().int().positive().optional().default(1),
});
export type CommunicationRouteRequest = z.infer<typeof communicationRouteRequestSchema>;

export const communicationPolicyUpdateRequestSchema = strictObject({
  routes: z.array(communicationRouteRequestSchema),
});

export const suppressionCreateRequestSchema = strictObject({
  name: z.string().min(1),
  starts_at: z.string().min(1),
  ends_at: z.string().min(1),
  scope: z.string().min(1),
  matchers: z.array(suppressionMatcherSchema),
  reason: z.string().nullable().optional(),
  created_by: z.string().nullable().optional(),
  summary_ticket_enabled: z.boolean(),
  enabled: z.boolean(),
});

export const prometheusRuleMutationResponseSchema = strictObject({
  status: z.string(),
  message: z.string(),
  crd: unknownRecordSchema.nullable().optional(),
  git: unknownRecordSchema.nullable().optional(),
  git_error: z.string().nullable().optional(),
});

export const prometheusRuleWriteRequestSchema = z
  .object({
    alert: z.string().min(1).optional(),
    record: z.string().min(1).optional(),
    expr: z.string().min(1),
    for: z.string().optional(),
    labels: stringRecordSchema.optional(),
    annotations: stringRecordSchema.optional(),
    keep_firing_for: z.string().optional(),
  })
  .refine((value) => Boolean(value.alert || value.record), {
    message: "either alert or record is required",
  });

export const ingredientCreateRequestSchema = strictObject({
  execution_target: z.string().min(1),
  destination_target: z.string().optional(),
  task_key_template: z.string().min(1),
  execution_id: z.string().nullable().optional(),
  action_id: z.string().nullable().optional(),
  execution_payload: unknownRecordSchema.nullable().optional(),
  execution_parameters: unknownRecordSchema.nullable().optional(),
  execution_engine: z.string().optional(),
  execution_purpose: z.string().optional(),
  ingredient_kind: z.string().nullable().optional(),
  is_default: z.boolean().optional(),
  is_blocking: z.boolean().optional(),
  expected_duration_sec: z.number().int().positive(),
  timeout_duration_sec: z.number().int().positive().optional(),
  retry_count: z.number().int().nonnegative().optional(),
  retry_delay: z.number().int().nonnegative().optional(),
  on_failure: z.string().optional(),
});

export const ingredientUpdateRequestSchema = ingredientCreateRequestSchema.partial();

export const recipeStepRequestSchema = strictObject({
  ingredient_id: z.number().int().positive(),
  step_order: z.number().int().positive(),
  on_success: z.string().optional(),
  parallel_group: z.number().int().nonnegative().optional(),
  depth: z.number().int().nonnegative().optional(),
  execution_parameters_override: unknownRecordSchema.nullable().optional(),
  run_phase: z.string().optional(),
  run_condition: z.string().optional(),
});

export const recipeCommunicationsRequestSchema = strictObject({
  mode: communicationsModeSchema,
  routes: z.array(communicationRouteRequestSchema).default([]),
});

export const recipeCreateRequestSchema = strictObject({
  name: z.string().min(1),
  description: z.string().nullable().optional(),
  enabled: z.boolean().optional(),
  clear_timeout_sec: z.number().int().positive().nullable().optional(),
  recipe_ingredients: z.array(recipeStepRequestSchema).min(1),
  communications: recipeCommunicationsRequestSchema.optional(),
});

export const recipeUpdateRequestSchema = recipeCreateRequestSchema.partial();

export const authRoleBindingCreateRequestSchema = z
  .object({
    provider: providerNameSchema,
    binding_type: bindingTypeSchema,
    role: userRoleSchema,
    principal_id: z.number().int().nullable().optional(),
    external_group: z.string().nullable().optional(),
    created_by: z.string().nullable().optional(),
  })
  .superRefine((value, ctx) => {
    if (value.binding_type === "user" && value.principal_id == null) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "principal_id is required for user bindings",
        path: ["principal_id"],
      });
    }
    if (value.binding_type === "group" && !value.external_group?.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "external_group is required for group bindings",
        path: ["external_group"],
      });
    }
  });

export const authRoleBindingUpdateRequestSchema = strictObject({
  role: userRoleSchema.optional(),
  external_group: z.string().nullable().optional(),
});
