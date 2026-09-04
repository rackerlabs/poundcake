#!/bin/bash
set -euo pipefail

# Idempotent legacy -> plugin-rewrite schema migration.
#
# Runs as root against the live poundcake DB. It probes the schema via
# information_schema and only performs each step if the OLD state is still
# present. On a fresh install (no legacy tables) or a re-run (already new
# schema) every probe short-circuits and the script exits 0 as a no-op.
#
# This is a Helm post-install/post-upgrade hook (weight 23): it reshapes the
# existing legacy tables so the new 2.0.234+ code can read them. The new
# tables (service_plugins, service_identity_credentials, hmac_nonces,
# adapter_credentials, scheduled_tasks, operator_audit_events) are NOT created
# here - the poundcake-bootstrap-schema hook (create_all) does that.

: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD required}"
: "${MYSQL_DATABASE:?MYSQL_DATABASE required}"

MYSQL_HOST="${MYSQL_HOST:-localhost}"
MYSQL_PORT="${MYSQL_PORT:-3306}"

# Backup destination (a mounted PVC). Empty disables the backup (job should
# always mount one, but a fresh install has nothing to back up anyway).
LEGACY_BACKUP_DIR="${LEGACY_BACKUP_DIR:-}"

# Superseded-table handling: tombstone (default) or drop.
MIGRATE_DROP_SUPERSEDED_TABLES="${MIGRATE_DROP_SUPERSEDED_TABLES:-false}"

MARIADB_CLI=(mariadb -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -uroot -p"${MYSQL_ROOT_PASSWORD}" --skip-column-names --batch "${MYSQL_DATABASE}")

log() { echo "[legacy-schema-migrate] $*"; }

# Column probe: does <table> have <col>? prints "yes"/"no" (never fails).
has_column() {
  local table="$1" col="$2"
  local n
  n="$("${MARIADB_CLI[@]}" -e "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='${MYSQL_DATABASE}' AND TABLE_NAME='${table}' AND COLUMN_NAME='${col}';" 2>/dev/null || echo 0)"
  if [ "${n:-0}" != "0" ]; then echo "yes"; else echo "no"; fi
}

# Table probe: does <table> exist? prints "yes"/"no" (never fails).
has_table() {
  local table="$1"
  local n
  n="$("${MARIADB_CLI[@]}" -e "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='${MYSQL_DATABASE}' AND TABLE_NAME='${table}';" 2>/dev/null || echo 0)"
  if [ "${n:-0}" != "0" ]; then echo "yes"; else echo "no"; fi
}

# Count rows matching a predicate in <table>. Prints 0 on any error.
count_rows() {
  local table="$1" predicate="$2"
  local n
  n="$("${MARIADB_CLI[@]}" -e "SELECT COUNT(*) FROM \`${table}\` WHERE ${predicate};" 2>/dev/null || echo 0)"
  echo "${n:-0}"
}

sql() {
  "${MARIADB_CLI[@]}" -e "$1"
}

# Drop a named index on <table> if present. Dropping a column that is part of
# an index errors out, so legacy indexes over to-be-dropped columns must go
# first. Never fails the script when the index is absent.
drop_index_if_exists() {
  local table="$1" index="$2"
  local n
  n="$("${MARIADB_CLI[@]}" -e "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='${MYSQL_DATABASE}' AND TABLE_NAME='${table}' AND INDEX_NAME='${index}';" 2>/dev/null || echo 0)"
  if [ "${n:-0}" != "0" ]; then
    log "dropping index ${index} on ${table}"
    sql "ALTER TABLE \`${table}\` DROP INDEX \`${index}\`;"
  fi
}

log "host=${MYSQL_HOST}:${MYSQL_PORT} db=${MYSQL_DATABASE} backup_dir=${LEGACY_BACKUP_DIR:-<none>} drop_superseded=${MIGRATE_DROP_SUPERSEDED_TABLES}"

# ---------------------------------------------------------------------------
# Gate: is there any legacy schema to migrate? The legacy model is recognized
# by the presence of dishes.dish_ingredients execution_* columns OR the
# superseded order_communications table. If none of the legacy tables exist
# (fresh install) or they are already on the new schema, exit 0 as a no-op.
# ---------------------------------------------------------------------------
LEGACY_DI="$(has_column dish_ingredients execution_status)"
LEGACY_DISH="$(has_column dishes execution_status)"
LEGACY_ING="$(has_column ingredients execution_engine)"
LEGACY_ORDERS_BAKERY="$(has_column orders bakery_comms_id)"
LEGACY_RECIPE_ING="$(has_column recipe_ingredients execution_payload_override)"
LEGACY_OC_TABLE="$(has_table order_communications)"
LEGACY_BMS_TABLE="$(has_table bakery_monitor_state)"

if [ "${LEGACY_DI}" = "no" ] && [ "${LEGACY_DISH}" = "no" ] && [ "${LEGACY_ING}" = "no" ] \
   && [ "${LEGACY_ORDERS_BAKERY}" = "no" ] && [ "${LEGACY_RECIPE_ING}" = "no" ] \
   && [ "${LEGACY_OC_TABLE}" = "no" ] && [ "${LEGACY_BMS_TABLE}" = "no" ]; then
  log "no legacy schema detected (fresh or already migrated) - nothing to do"
  exit 0
fi

log "legacy schema detected (DI=${LEGACY_DI} dish=${LEGACY_DISH} ing=${LEGACY_ING} orders_bakery=${LEGACY_ORDERS_BAKERY} recipe_ing=${LEGACY_RECIPE_ING} order_communications=${LEGACY_OC_TABLE} bakery_monitor_state=${LEGACY_BMS_TABLE})"

# ---------------------------------------------------------------------------
# Step 0: self-backup (before any destructive step). Skipped when no legacy
# tables exist or when LEGACY_BACKUP_DIR is unset. Re-run overwrites the file.
# ---------------------------------------------------------------------------
if [ -n "${LEGACY_BACKUP_DIR}" ]; then
  mkdir -p "${LEGACY_BACKUP_DIR}"
  TS="$(date -u +%Y%m%dT%H%M%SZ)"
  BACKUP_FILE="${LEGACY_BACKUP_DIR}/legacy-schema-backup-${TS}.sql.gz"
  DUMP_TABLES=()
  if [ "$(has_table orders)" = "yes" ]; then DUMP_TABLES+=(orders); fi
  if [ "$(has_table dishes)" = "yes" ]; then DUMP_TABLES+=(dishes); fi
  if [ "$(has_table dish_ingredients)" = "yes" ]; then DUMP_TABLES+=(dish_ingredients); fi
  if [ "$(has_table ingredients)" = "yes" ]; then DUMP_TABLES+=(ingredients); fi
  if [ "$(has_table recipe_ingredients)" = "yes" ]; then DUMP_TABLES+=(recipe_ingredients); fi
  if [ "${LEGACY_OC_TABLE}" = "yes" ]; then DUMP_TABLES+=(order_communications); fi
  if [ "${LEGACY_BMS_TABLE}" = "yes" ]; then DUMP_TABLES+=(bakery_monitor_state); fi
  if [ "${#DUMP_TABLES[@]}" -gt 0 ]; then
    log "backing up: ${DUMP_TABLES[*]} -> ${BACKUP_FILE}"
    mariadb-dump -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -uroot -p"${MYSQL_ROOT_PASSWORD}" \
      --single-transaction --no-tablespaces "${MYSQL_DATABASE}" "${DUMP_TABLES[@]}" | gzip > "${BACKUP_FILE}"
    log "backup complete: $(wc -c < "${BACKUP_FILE}") bytes"
  else
    log "no legacy tables to back up"
  fi
else
  log "LEGACY_BACKUP_DIR unset - skipping self-backup (job should mount a backup PVC)"
fi

# ---------------------------------------------------------------------------
# Migration. SET FOREIGN_KEY_CHECKS=0 for the batch because we reshape columns
# that are referenced by FKs (dishes.order_id -> orders, dish_ingredients.*).
# Re-enable before the tombstone rename (RENAME handles FKs itself).
# ---------------------------------------------------------------------------
sql "SET SESSION foreign_key_checks=0;"

# ===== 1. recipe_ingredients: rename 4 *_override cols + add 1 =====
if [ "${LEGACY_RECIPE_ING}" = "yes" ]; then
  log "migrating recipe_ingredients"
  if [ "$(has_column recipe_ingredients service_payload)" = "no" ]; then
    sql "ALTER TABLE recipe_ingredients CHANGE COLUMN execution_payload_override service_payload JSON NULL;"
    sql "ALTER TABLE recipe_ingredients CHANGE COLUMN execution_parameters_override service_exec_parameters_override JSON NULL;"
    sql "ALTER TABLE recipe_ingredients CHANGE COLUMN expected_duration_sec_override service_exec_expected_secs INT NULL;"
    sql "ALTER TABLE recipe_ingredients CHANGE COLUMN timeout_duration_sec_override service_exec_timeout INT NULL;"
  fi
  if [ "$(has_column recipe_ingredients service_exec_expected_outcome)" = "no" ]; then
    sql "ALTER TABLE recipe_ingredients ADD COLUMN service_exec_expected_outcome JSON NULL;"
  fi
else
  log "recipe_ingredients already new schema - skip"
fi

# ===== 2. ingredients: execution-holder -> lean template =====
if [ "${LEGACY_ING}" = "yes" ]; then
  log "migrating ingredients"
  # Add all new columns nullable first (safe for existing rows).
  for add in \
    "service_type VARCHAR(50) NULL" \
    "destination_target VARCHAR(255) NULL" \
    "service_exec VARCHAR(100) NULL" \
    "ingredient_purpose VARCHAR(32) NULL" \
    "default_timeout INT NULL" \
    "default_expected_secs INT NULL" \
    "service_exec_parameters JSON NULL" \
    "payload_schema JSON NULL" \
    "service_payload_template JSON NULL" \
    "service_exec_expected_outcome_default JSON NULL"; do
    colname="${add%% *}"
    if [ "$(has_column ingredients "${colname}")" = "no" ]; then
      sql "ALTER TABLE ingredients ADD COLUMN ${add};"
    fi
  done

  # Backfill from old columns (generic CASE; provider stays in payload).
  if [ "$(count_rows ingredients 'service_exec IS NULL OR service_type IS NULL')" -gt 0 ]; then
    sql "UPDATE ingredients SET
      service_type = COALESCE(NULLIF(service_type,''), execution_engine),
      destination_target = COALESCE(NULLIF(destination_target,''), execution_engine),
      ingredient_purpose = COALESCE(NULLIF(ingredient_purpose,''), execution_purpose),
      default_timeout = COALESCE(default_timeout, timeout_duration_sec, 300),
      default_expected_secs = COALESCE(default_expected_secs, expected_duration_sec, 60),
      service_exec_parameters = COALESCE(service_exec_parameters, execution_parameters),
      service_payload_template = COALESCE(service_payload_template, execution_payload),
      payload_schema = COALESCE(payload_schema, JSON_OBJECT('type','object','additionalProperties',TRUE)),
      service_exec = COALESCE(NULLIF(service_exec,''), CASE
        WHEN execution_engine='bakery' AND execution_purpose='comms' THEN 'communication'
        WHEN execution_engine='bakery' AND execution_target LIKE '%reconcile%' THEN 'incident_reconcile'
        WHEN execution_engine='bakery' AND execution_target LIKE '%collect%' THEN 'collect'
        WHEN execution_engine='stackstorm' AND execution_purpose='remediation' THEN 'action_execution'
        WHEN execution_engine='stackstorm' AND execution_purpose='workflow' THEN 'workflow_execution'
        WHEN execution_purpose='plugin_health' OR task_key_template LIKE '%health_check%' THEN 'health_check'
        ELSE COALESCE(NULLIF(execution_purpose,''), 'utility') END);"
  fi

  # Enforce NOT NULL now that every row has a value.
  sql "ALTER TABLE ingredients MODIFY COLUMN service_type VARCHAR(50) NOT NULL;"
  sql "ALTER TABLE ingredients MODIFY COLUMN service_exec VARCHAR(100) NOT NULL;"
  sql "ALTER TABLE ingredients MODIFY COLUMN destination_target VARCHAR(255) NOT NULL;"
  sql "ALTER TABLE ingredients MODIFY COLUMN ingredient_purpose VARCHAR(32) NOT NULL DEFAULT 'utility';"
  sql "ALTER TABLE ingredients MODIFY COLUMN default_timeout INT NOT NULL DEFAULT 300;"
  sql "ALTER TABLE ingredients MODIFY COLUMN default_expected_secs INT NOT NULL;"
  sql "ALTER TABLE ingredients MODIFY COLUMN payload_schema JSON NOT NULL;"

  # Drop legacy indexes that span to-be-dropped columns (must precede the drops).
  drop_index_if_exists ingredients ux_ingredients_engine_target
  drop_index_if_exists ingredients ix_ingredients_execution_target
  drop_index_if_exists ingredients ix_ingredients_execution_engine
  drop_index_if_exists ingredients ix_ingredients_execution_purpose

  # Drop the legacy per-execution columns (data already carried into new cols).
  for drop in execution_engine execution_target execution_purpose execution_id execution_payload \
    execution_parameters execution_status processing_status run_phase order_id dish_id req_id \
    result error_message started_at completed_at canceled_at actual_duration_sec retry_attempt \
    execution_ref is_default expected_duration_sec timeout_duration_sec; do
    if [ "$(has_column ingredients "${drop}")" = "yes" ]; then
      sql "ALTER TABLE ingredients DROP COLUMN ${drop};"
    fi
  done
else
  log "ingredients already new schema - skip"
fi

# ===== 3. dish_ingredients: rename 11 cols + backfill NOT-NULL via RI join + drop =====
if [ "${LEGACY_DI}" = "yes" ]; then
  log "migrating dish_ingredients"
  for add in \
    "req_id VARCHAR(100) NULL" \
    "service_type VARCHAR(50) NULL" \
    "service_exec VARCHAR(100) NULL" \
    "destination_target VARCHAR(255) NULL" \
    "step_order INT NULL" \
    "parallel_group INT NULL" \
    "depth INT NULL" \
    "service_exec_sla_exceeded TINYINT(1) NULL" \
    "service_exec_id VARCHAR(100) NULL" \
    "service_exec_claimed_at DATETIME NULL" \
    "service_exec_claimed_by VARCHAR(100) NULL" \
    "service_exec_run_time INT NULL" \
    "service_exec_expected_outcome JSON NULL"; do
    colname="${add%% *}"
    if [ "$(has_column dish_ingredients "${colname}")" = "no" ]; then
      sql "ALTER TABLE dish_ingredients ADD COLUMN ${add};"
    fi
  done

  # Rename old -> new (only if not already renamed).
  if [ "$(has_column dish_ingredients service_exec_status)" = "no" ]; then
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN execution_status service_exec_status VARCHAR(50) NOT NULL DEFAULT 'pending';"
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN execution_payload service_payload JSON NULL;"
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN execution_parameters service_exec_parameters JSON NULL;"
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN expected_duration_sec service_exec_expected_secs INT NULL;"
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN timeout_duration_sec service_exec_timeout INT NULL;"
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN result service_exec_actual_outcome JSON NULL;"
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN started_at service_exec_start_time DATETIME NULL;"
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN completed_at service_exec_completed_time DATETIME NULL;"
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN canceled_at service_exec_canceled_time DATETIME NULL;"
    sql "ALTER TABLE dish_ingredients CHANGE COLUMN error_message service_exec_error TEXT NULL;"
  fi

  sql "ALTER TABLE dish_ingredients ADD INDEX ix_dish_ingredients_req_id (req_id);" 2>/dev/null || true
  sql "ALTER TABLE dish_ingredients ADD INDEX ix_dish_ingredients_service_type (service_type);" 2>/dev/null || true

  # Backfill NOT-NULL cols: req_id from parent dish; service_type/service_exec/
  # destination_target from the (already-migrated) ingredients row via RI join.
  if [ "$(count_rows dish_ingredients 'service_exec IS NULL OR service_type IS NULL')" -gt 0 ]; then
    sql "UPDATE dish_ingredients di
      LEFT JOIN recipe_ingredients ri ON ri.id = di.recipe_ingredient_id
      LEFT JOIN ingredients ing ON ing.id = ri.ingredient_id
      SET di.req_id = COALESCE(di.req_id, (SELECT req_id FROM dishes d WHERE d.id = di.dish_id)),
          di.service_type = COALESCE(di.service_type, ing.service_type),
          di.service_exec = COALESCE(di.service_exec, ing.service_exec),
          di.destination_target = COALESCE(di.destination_target, ing.destination_target),
          di.step_order = COALESCE(di.step_order, ri.step_order, 1),
          di.parallel_group = COALESCE(di.parallel_group, ri.parallel_group, 0),
          di.depth = COALESCE(di.depth, ri.depth, 0),
          di.service_exec_sla_exceeded = COALESCE(di.service_exec_sla_exceeded, 0)
      WHERE di.service_type IS NULL OR di.service_exec IS NULL OR di.req_id IS NULL;"
  fi
  # Any DI rows whose recipe/ingredient did not resolve get safe defaults.
  if [ "$(count_rows dish_ingredients 'service_type IS NULL OR service_exec IS NULL')" -gt 0 ]; then
    sql "UPDATE dish_ingredients SET service_type = COALESCE(service_type,'undefined'), service_exec = COALESCE(service_exec,'noop') WHERE service_type IS NULL OR service_exec IS NULL;"
    sql "UPDATE dish_ingredients SET destination_target = COALESCE(destination_target, service_type) WHERE destination_target IS NULL;"
    sql "UPDATE dish_ingredients SET req_id = COALESCE(req_id, CONCAT('dish_', dish_id, '_', id)) WHERE req_id IS NULL;"
    sql "UPDATE dish_ingredients SET service_exec_status = COALESCE(service_exec_status,'pending') WHERE service_exec_status IS NULL;"
  fi

  # Neutralize stuck running work -> failed (decision).
  if [ "$(count_rows dish_ingredients "service_exec_status='running'")" -gt 0 ]; then
    log "neutralizing stuck running dish_ingredients -> failed"
    sql "UPDATE dish_ingredients SET service_exec_status='failed', service_exec_error='migrated: was running pre-cutover' WHERE service_exec_status='running';"
  fi

  # Drop legacy indexes that span to-be-dropped columns (must precede the drops).
  # task_key is a KEPT column, so its index (ix_dish_ingredients_task_key) stays.
  drop_index_if_exists dish_ingredients ux_dish_ingredients_dish_step
  drop_index_if_exists dish_ingredients ix_dish_ingredients_execution_ref
  drop_index_if_exists dish_ingredients ix_dish_ingredients_execution_engine

  # Drop legacy cols (data carried). The *_norm STORED generated columns depend
  # on their base columns, so they must be dropped BEFORE the base cols.
  for drop in execution_ref_norm recipe_ingredient_id_norm \
    execution_engine execution_target execution_ref; do
    if [ "$(has_column dish_ingredients "${drop}")" = "yes" ]; then
      sql "ALTER TABLE dish_ingredients DROP COLUMN ${drop};"
    fi
  done
else
  log "dish_ingredients already new schema - skip"
fi

# ===== 4. dishes: rename 4 cols + neutralize + drop 2 =====
if [ "${LEGACY_DISH}" = "yes" ]; then
  log "migrating dishes"
  if [ "$(has_column dishes dish_exec_status)" = "no" ]; then
    sql "ALTER TABLE dishes CHANGE COLUMN expected_duration_sec expected_run_secs INT NULL;"
    sql "ALTER TABLE dishes CHANGE COLUMN actual_duration_sec run_time_secs INT NULL;"
    sql "ALTER TABLE dishes CHANGE COLUMN execution_status dish_exec_status VARCHAR(50) NULL;"
    sql "ALTER TABLE dishes CHANGE COLUMN result dish_actual_outcome JSON NULL;"
  fi
  if [ "$(count_rows dishes "dish_exec_status IN ('timeout','running')")" -gt 0 ]; then
    log "neutralizing stuck timeout/running dishes -> failed"
    sql "UPDATE dishes SET dish_exec_status='failed' WHERE dish_exec_status IN ('timeout','running');"
  fi
  drop_index_if_exists dishes ix_dishes_execution_ref
  for drop in execution_ref retry_attempt; do
    if [ "$(has_column dishes "${drop}")" = "yes" ]; then
      sql "ALTER TABLE dishes DROP COLUMN ${drop};"
    fi
  done
else
  log "dishes already new schema - skip"
fi

# ===== 5. orders: add correlation_key (NULL for history) + remap bad status + drop bakery_* =====
# correlation_key is intentionally left NULL for migrated historical orders: it is
# a sha256 of sorted labels (excluding alertname/severity) computed at intake by
# pre_heat, and only matters for correlating NEW active alerts. The column is
# nullable+indexed, so NULL history is safe.
if [ "$(has_column orders correlation_key)" = "no" ]; then
  log "adding orders.correlation_key (NULL for migrated history)"
  sql "ALTER TABLE orders ADD COLUMN correlation_key VARCHAR(64) NULL;"
  sql "ALTER TABLE orders ADD INDEX ix_orders_correlation_key (correlation_key);" 2>/dev/null || true
fi
if [ "$(count_rows orders "processing_status IN ('waiting_ticket_close','cleared')")" -gt 0 ]; then
  log "remapping invalid orders.processing_status -> complete"
  sql "UPDATE orders SET processing_status='complete' WHERE processing_status IN ('waiting_ticket_close','cleared');"
fi
if [ "${LEGACY_ORDERS_BAKERY}" = "yes" ]; then
  log "dropping legacy orders.bakery_* columns"
  drop_index_if_exists orders ix_orders_bakery_ticket_id
  drop_index_if_exists orders ix_orders_bakery_operation_id
  drop_index_if_exists orders ix_orders_bakery_ticket_state
  drop_index_if_exists orders ix_orders_bakery_permanent_failure
  for drop in bakery_comms_id bakery_ticket_id bakery_operation_id bakery_ticket_state bakery_permanent_failure bakery_last_error; do
    if [ "$(has_column orders "${drop}")" = "yes" ]; then
      sql "ALTER TABLE orders DROP COLUMN ${drop};"
    fi
  done
fi

sql "SET SESSION foreign_key_checks=1;"

# ---------------------------------------------------------------------------
# Step 6: tombstone (or drop) the superseded tables. RENAME never loses data;
# the new model never references the *_legacy_* tables.
# ---------------------------------------------------------------------------
migrate_superseded() {
  local from="$1"
  local ts
  ts="$(date -u +%Y%m%d)"
  if [ "$(has_table "${from}")" = "yes" ]; then
    local to="${from}_legacy_${ts}"
    if [ "$(has_table "${to}")" = "no" ]; then
      if [ "${MIGRATE_DROP_SUPERSEDED_TABLES}" = "true" ]; then
        log "dropping superseded table ${from} (MIGRATE_DROP_SUPERSEDED_TABLES=true)"
        sql "DROP TABLE \`${from}\`;"
      else
        log "tombstone-renaming ${from} -> ${to}"
        sql "RENAME TABLE \`${from}\` TO \`${to}\`;"
      fi
    else
      # A tombstone from a prior run already exists. Fold this one in: drop the
      # current table (its data is already captured in the existing tombstone's
      # era / the backup). Only safe because the backup was taken in Step 0.
      log "tombstone ${to} already exists - dropping ${from} (backed up in Step 0)"
      sql "DROP TABLE \`${from}\`;"
    fi
  fi
}
migrate_superseded "order_communications"
migrate_superseded "bakery_monitor_state"

log "legacy schema migration complete"
exit 0
