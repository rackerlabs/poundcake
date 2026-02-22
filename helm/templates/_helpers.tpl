<<<<<<< HEAD
{{/*
Expand the name of the chart.
*/}}
{{- define "poundcake.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "poundcake.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "poundcake.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "poundcake.labels" -}}
helm.sh/chart: {{ include "poundcake.chart" . }}
{{ include "poundcake.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "poundcake.selectorLabels" -}}
app.kubernetes.io/name: {{ include "poundcake.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
PoundCake log selector labels
*/}}
{{- define "poundcake.logGroupLabel" -}}
poundcake.io/log-group: poundcake
{{- end }}

{{- define "poundcake.logRoleApi" -}}
poundcake.io/log-role: api
{{- end }}

{{- define "poundcake.logRoleWorker" -}}
poundcake.io/log-role: worker
{{- end }}

{{- define "poundcake.logRoleInfra" -}}
poundcake.io/log-role: infra
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "poundcake.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "poundcake.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Get the secret name for StackStorm credentials
*/}}
{{- define "poundcake.stackstormSecretName" -}}
{{- if .Values.stackstorm.existingSecret }}
{{- .Values.stackstorm.existingSecret }}
{{- else }}
{{- include "poundcake.fullname" . }}-stackstorm
{{- end }}
{{- end }}

{{/*
Get StackStorm MongoDB resource name
*/}}
{{- define "poundcake.stackstormMongoName" -}}
{{- .Values.stackstorm.resourceNames.mongodb | default "st2-mongodb" }}
{{- end }}

{{/*
Get StackStorm RabbitMQ resource name
*/}}
{{- define "poundcake.stackstormRabbitmqName" -}}
{{- .Values.stackstorm.resourceNames.rabbitmq | default "st2-rabbitmq" }}
{{- end }}

{{/*
Get StackStorm Redis resource name
*/}}
{{- define "poundcake.stackstormRedisName" -}}
{{- .Values.stackstorm.resourceNames.redis | default "st2-redis" }}
{{- end }}

{{/*
Get the secret name for Redis credentials
*/}}
{{- define "poundcake.redisSecretName" -}}
{{- if .Values.redis.existingSecret }}
{{- .Values.redis.existingSecret }}
{{- else if and (not .Values.redis.deploy) .Values.redis.external.existingSecret }}
{{- .Values.redis.external.existingSecret }}
{{- else }}
{{- include "poundcake.stackstormRedisName" . }}
{{- end }}
{{- end }}

{{/*
Get the secret name for RabbitMQ credentials
*/}}
{{- define "poundcake.rabbitmqSecretName" -}}
{{- if .Values.rabbitmq.existingSecret }}
{{- .Values.rabbitmq.existingSecret }}
{{- else }}
{{- include "poundcake.stackstormRabbitmqName" . }}
{{- end }}
{{- end }}

{{/*
Get the Redis URL
*/}}
{{- define "poundcake.redisUrl" -}}
{{- if .Values.redis.deploy }}
{{- printf "redis://%s:6379/0" (include "poundcake.stackstormRedisName" .) }}
{{- else }}
{{- .Values.redis.external.url }}
{{- end }}
{{- end }}

{{/*
Get the secret name for Git credentials
*/}}
{{- define "poundcake.gitSecretName" -}}
{{- if .Values.git.existingSecret }}
{{- .Values.git.existingSecret }}
{{- else }}
{{- include "poundcake.fullname" . }}-git
{{- end }}
{{- end }}

{{/*
Bakery resource names
*/}}
{{- define "poundcake.bakeryName" -}}
bakery
{{- end }}

{{- define "poundcake.bakerySecretName" -}}
{{- printf "%s-secret" (include "poundcake.bakeryName" .) }}
{{- end }}

{{- define "poundcake.bakeryClientSecretName" -}}
{{- if .Values.bakery.client.auth.existingSecret }}
{{- .Values.bakery.client.auth.existingSecret }}
{{- else }}
{{- include "poundcake.bakerySecretName" . }}
{{- end }}
{{- end }}

{{- define "poundcake.bakeryDbHost" -}}
{{- printf "%s-mariadb" (include "poundcake.bakeryName" .) }}
{{- end }}

{{- define "poundcake.bakeryDbSecretName" -}}
{{- printf "%s-db" (include "poundcake.bakeryName" .) }}
{{- end }}

{{- define "poundcake.bakeryBaseUrl" -}}
{{- if .Values.bakery.client.baseUrl }}
{{- .Values.bakery.client.baseUrl }}
{{- else }}
{{- printf "http://%s.%s.svc.cluster.local:%v" (include "poundcake.bakeryName" .) .Release.Namespace .Values.bakery.service.port }}
{{- end }}
{{- end }}

{{/*
MariaDB Operator helpers
*/}}

{{/*
Get the MariaDB instance name
*/}}
{{- define "poundcake.mariadbName" -}}
{{- if .Values.mariadbOperator.server.name }}
{{- .Values.mariadbOperator.server.name }}
{{- else }}
{{- include "poundcake.fullname" . }}-mariadb
{{- end }}
{{- end }}

{{/*
Get the MariaDB namespace
*/}}
{{- define "poundcake.mariadbNamespace" -}}
{{- if .Values.mariadbOperator.namespace }}
{{- .Values.mariadbOperator.namespace }}
{{- else }}
{{- .Release.Namespace }}
{{- end }}
{{- end }}

{{/*
Get the MariaDB root password secret name
*/}}
{{- define "poundcake.mariadbRootSecretName" -}}
{{- if .Values.mariadbOperator.server.rootPasswordSecret }}
{{- .Values.mariadbOperator.server.rootPasswordSecret }}
{{- else }}
{{- include "poundcake.mariadbName" . }}-root
{{- end }}
{{- end }}

{{/*
Get the MariaDB user password secret name
*/}}
{{- define "poundcake.mariadbUserSecretName" -}}
{{- if .Values.mariadbOperator.user.passwordSecret }}
{{- .Values.mariadbOperator.user.passwordSecret }}
{{- else }}
{{- include "poundcake.fullname" . }}-mariadb-user
{{- end }}
{{- end }}

{{/*
Get the MariaDB database name
*/}}
{{- define "poundcake.mariadbDatabaseName" -}}
{{- .Values.mariadbOperator.database.name | default "poundcake" }}
{{- end }}

{{/*
Get the MariaDB username
*/}}
{{- define "poundcake.mariadbUsername" -}}
{{- .Values.mariadbOperator.user.name | default "poundcake" }}
{{- end }}

{{/*
Get the MariaDB service host
*/}}
{{- define "poundcake.mariadbHost" -}}
{{- $namespace := include "poundcake.mariadbNamespace" . }}
{{- $name := include "poundcake.mariadbName" . }}
{{- printf "%s.%s.svc.cluster.local" $name $namespace }}
{{- end }}

{{/*
Check if MariaDB Operator CRDs are available
*/}}
{{- define "poundcake.mariadbOperatorAvailable" -}}
{{- if .Capabilities.APIVersions.Has "k8s.mariadb.com/v1alpha1" }}
{{- true }}
{{- else }}
{{- false }}
{{- end }}
{{- end }}

{{/*
Get the database URL - prioritizes explicit config over operator
*/}}
{{- define "poundcake.databaseUrl" -}}
{{- if .Values.database.url }}
{{- .Values.database.url }}
{{- else if .Values.database.existingSecret }}
{{- /* Will be loaded from secret */ -}}
{{- else if .Values.mariadbOperator.enabled }}
{{- $host := include "poundcake.mariadbHost" . }}
{{- $db := include "poundcake.mariadbDatabaseName" . }}
{{- $user := include "poundcake.mariadbUsername" . }}
{{- /* Password will be injected from secret, this is just for reference */ -}}
{{- printf "mysql+pymysql://%s:$(MARIADB_PASSWORD)@%s:3306/%s" $user $host $db }}
{{- end }}
{{- end }}

{{/*
Get StackStorm API URL - either from explicit values or release-based defaults
*/}}
{{- define "poundcake.stackstormSubchartPrefix" -}}
{{- default "stackstorm" .Values.stackstorm.releaseName -}}
{{- end }}

{{/*
Get StackStorm auth secret name from StackStorm release prefix
*/}}
{{- define "poundcake.stackstormAuthSecretName" -}}
{{- printf "%s-st2-auth" (include "poundcake.stackstormSubchartPrefix" .) -}}
{{- end }}

{{- define "poundcake.stackstormApiUrl" -}}
{{- if .Values.stackstorm.url }}
{{- .Values.stackstorm.url }}
{{- else }}
{{- printf "http://%s-st2api.%s.svc.cluster.local:9101" (include "poundcake.stackstormSubchartPrefix" .) .Release.Namespace }}
{{- end }}
{{- end }}

{{/*
Get StackStorm Auth URL - either from explicit values or release-based defaults
*/}}
{{- define "poundcake.stackstormAuthUrl" -}}
{{- if .Values.stackstorm.authUrl }}
{{- .Values.stackstorm.authUrl }}
{{- else }}
{{- printf "http://%s-st2auth.%s.svc.cluster.local:9100" (include "poundcake.stackstormSubchartPrefix" .) .Release.Namespace }}
{{- end }}
{{- end }}

{{/*
Get StackStorm API key secret name
*/}}
{{- define "poundcake.stackstormApiKeySecret" -}}
{{- .Values.stackstorm.apiKeySecretName | default (printf "%s-st2-apikeys" (include "poundcake.stackstormSubchartPrefix" .)) -}}
{{- end }}

{{/*
Get StackStorm API key secret key
*/}}
{{- define "poundcake.stackstormApiKeySecretKey" -}}
{{- .Values.stackstorm.apiKeySecretKey | default "api-key" -}}
{{- end }}
=======
{{- define "poundcake.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "poundcake.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "poundcake.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "poundcake.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "poundcake.selectorLabels" -}}
app.kubernetes.io/name: {{ include "poundcake.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "poundcake.storageClass" -}}
{{- if .Values.persistence.storageClassName }}
storageClassName: {{ .Values.persistence.storageClassName | quote }}
{{- end }}
{{- end -}}

{{- define "poundcake.poundcakePullSecrets" -}}
{{- $pullSecrets := .Values.poundcakeImage.pullSecrets | default list -}}
{{- if eq (len $pullSecrets) 0 -}}
{{- $pullSecrets = .Values.imagePullSecrets | default list -}}
{{- end -}}
{{- if gt (len $pullSecrets) 0 }}
imagePullSecrets:
{{- range $secret := $pullSecrets }}
  {{- if kindIs "string" $secret }}
  - name: {{ $secret | quote }}
  {{- else if and (kindIs "map" $secret) (hasKey $secret "name") }}
  - name: {{ index $secret "name" | quote }}
  {{- end }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "poundcake.poundcakeImageRef" -}}
{{- $digest := .Values.poundcakeImage.digest | default "" -}}
{{- if $digest -}}
{{- printf "%s@%s" .Values.poundcakeImage.repository $digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.poundcakeImage.repository (default .Chart.AppVersion .Values.poundcakeImage.tag) -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.pvcStorageClass" -}}
{{- $root := .root -}}
{{- $pvcStorageClass := .pvcStorageClass | default "" -}}
{{- if $pvcStorageClass }}
storageClassName: {{ $pvcStorageClass | quote }}
{{- else if $root.Values.persistence.storageClassName }}
storageClassName: {{ $root.Values.persistence.storageClassName | quote }}
{{- end }}
{{- end -}}

{{- define "poundcake.startupHookDeletePolicy" -}}
{{- $policies := list "before-hook-creation" -}}
{{- if and .Values.startupHooks.cleanup.enabled .Values.startupHooks.cleanup.deleteSuccessful -}}
{{- $policies = append $policies "hook-succeeded" -}}
{{- end -}}
{{- if and .Values.startupHooks.cleanup.enabled .Values.startupHooks.cleanup.deleteFailed -}}
{{- $policies = append $policies "hook-failed" -}}
{{- end -}}
{{- join "," $policies -}}
{{- end -}}

{{- define "poundcake.stackstormServiceEnabled" -}}
{{- $root := .root -}}
{{- $name := .name -}}
{{- $services := $root.Values.stackstormServices | default dict -}}
{{- $legacy := $root.Values.stackstormComponents | default dict -}}
{{- $defaults := dict
  "mongodb" true
  "rabbitmq" true
  "redis" true
  "auth" true
  "api" true
  "actionrunner" true
  "rulesengine" true
  "workflowengine" true
  "scheduler" true
  "notifier" false
  "garbagecollector" true
  "timersengine" false
  "sensorcontainer" false
  "register" false
  "stream" false
  "web" false
  "client" false
-}}
{{- if hasKey $services $name -}}
{{- $serviceCfg := index $services $name | default dict -}}
{{- ternary "true" "false" ($serviceCfg.enabled | default false) -}}
{{- else if hasKey $legacy $name -}}
{{- $legacyCfg := index $legacy $name | default dict -}}
{{- ternary "true" "false" ($legacyCfg.enabled | default false) -}}
{{- else -}}
{{- ternary "true" "false" (index $defaults $name | default false) -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.validateStackstormServiceSet" -}}
{{- $required := list "mongodb" "rabbitmq" "redis" "auth" "api" "actionrunner" "rulesengine" "workflowengine" "scheduler" "garbagecollector" -}}
{{- $errors := list -}}
{{- range $svc := $required -}}
  {{- if ne (include "poundcake.stackstormServiceEnabled" (dict "root" $ "name" $svc)) "true" -}}
    {{- $errors = append $errors (printf "stackstormServices.%s.enabled must be true for Poundcake operations" $svc) -}}
  {{- end -}}
{{- end -}}
{{- if gt (len $errors) 0 -}}
{{- fail (printf "invalid stackstorm service profile: %s" (join "; " $errors)) -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.logLabels" -}}
{{- $group := .group | default "other" -}}
{{- $subgroup := .subgroup | default "general" -}}
{{- $role := .role | default "other" -}}
poundcake.io/log-group: {{ $group | quote }}
poundcake.io/log-subgroup: {{ $subgroup | quote }}
poundcake.io/log-role: {{ $role | quote }}
{{- end -}}

{{- define "poundcake.logLabelsForComponent" -}}
{{- $component := .component | default "unknown" -}}
{{- $group := "other" -}}
{{- $subgroup := "general" -}}
{{- $role := $component -}}

{{- if has $component (list "api" "ui" "chef" "prep-chef" "timer" "dishwasher") -}}
  {{- $group = "poundcake" -}}
  {{- $subgroup = "app" -}}
  {{- if eq $component "api" -}}
    {{- $role = "api" -}}
  {{- else if eq $component "ui" -}}
    {{- $role = "ui" -}}
  {{- else -}}
    {{- $role = "worker" -}}
  {{- end -}}
{{- else if has $component (list "mariadb" "stackstorm-mongodb" "stackstorm-rabbitmq" "stackstorm-redis") -}}
  {{- $group = "infra" -}}
  {{- $subgroup = "data" -}}
  {{- if hasPrefix "stackstorm-" $component -}}
    {{- $role = trimPrefix "stackstorm-" $component -}}
  {{- end -}}
{{- else if hasPrefix "stackstorm-" $component -}}
  {{- $role = trimPrefix "stackstorm-" $component -}}
  {{- if has $component (list "stackstorm-auth" "stackstorm-api" "stackstorm-stream" "stackstorm-web") -}}
    {{- $group = "stackstorm-edge" -}}
    {{- $subgroup = "control-api" -}}
  {{- else if has $component (list "stackstorm-actionrunner" "stackstorm-rulesengine" "stackstorm-workflowengine" "stackstorm-scheduler" "stackstorm-register" "stackstorm-garbagecollector" "stackstorm-client" "stackstorm-notifier" "stackstorm-timersengine" "stackstorm-sensorcontainer") -}}
    {{- $group = "stackstorm-exec" -}}
    {{- $subgroup = "control-exec" -}}
  {{- else if has $component (list "stackstorm-startup-markers-reset" "stackstorm-mongodb-user-sync" "stackstorm-infra-ready" "stackstorm-controlplane-ready" "stackstorm-workers-ready" "stackstorm-edge-ready" "stackstorm-bootstrap") -}}
    {{- $group = "startup-hooks" -}}
    {{- $subgroup = "orchestration" -}}
    {{- $role = $component -}}
  {{- end -}}
{{- else if hasPrefix "poundcake-" $component -}}
  {{- $group = "startup-hooks" -}}
  {{- $subgroup = "orchestration" -}}
{{- end -}}

{{- include "poundcake.logLabels" (dict "group" $group "subgroup" $subgroup "role" $role) -}}
{{- end -}}

{{- define "poundcake.gateLogHelpers" -}}
GATE_LOG_ENABLED="{{ ternary "true" "false" .Values.startupHooks.gateLogging.enabled }}"
GATE_LOG_INTERVAL="{{ .Values.startupHooks.gateLogging.intervalSeconds }}"
GATE_LOG_PREFIX={{ .Values.startupHooks.gateLogging.prefix | quote }}
case "${GATE_LOG_INTERVAL}" in
  ''|*[!0-9]*) GATE_LOG_INTERVAL=30 ;;
esac
if [ "${GATE_LOG_INTERVAL}" -lt 1 ]; then
  GATE_LOG_INTERVAL=1
fi

gate_log_wait_start() {
  gate_name="$1"
  gate_detail="$2"
  gate_started_at="$(date +%s)"
  gate_last_log="${gate_started_at}"
  echo "${GATE_LOG_PREFIX} wait=${gate_name} status=waiting elapsed=0s detail=${gate_detail}"
}

gate_log_wait_tick() {
  gate_name="$1"
  gate_detail="$2"
  gate_now="$(date +%s)"
  if [ "${GATE_LOG_ENABLED}" = "true" ] && [ $((gate_now - gate_last_log)) -ge "${GATE_LOG_INTERVAL}" ]; then
    echo "${GATE_LOG_PREFIX} wait=${gate_name} status=waiting elapsed=$((gate_now - gate_started_at))s detail=${gate_detail}"
    gate_last_log="${gate_now}"
  fi
}

gate_log_wait_ready() {
  gate_name="$1"
  gate_now="$(date +%s)"
  echo "${GATE_LOG_PREFIX} wait=${gate_name} status=ready elapsed=$((gate_now - gate_started_at))s"
}

gate_wait_for_true_file() {
  gate_file="$1"
  gate_name="$2"
  gate_detail="$3"
  gate_log_wait_start "${gate_name}" "${gate_detail}"
  until [ "$(cat "${gate_file}" 2>/dev/null)" = "true" ]; do
    gate_log_wait_tick "${gate_name}" "${gate_detail}"
    sleep 2
  done
  gate_log_wait_ready "${gate_name}"
}

gate_wait_for_nonempty_file() {
  gate_file="$1"
  gate_name="$2"
  gate_detail="$3"
  gate_log_wait_start "${gate_name}" "${gate_detail}"
  until [ -n "$(cat "${gate_file}" 2>/dev/null)" ]; do
    gate_log_wait_tick "${gate_name}" "${gate_detail}"
    sleep 2
  done
  gate_log_wait_ready "${gate_name}"
}

gate_wait_for_tcp() {
  gate_host="$1"
  gate_port="$2"
  gate_name="$3"
  gate_detail="$4"
  gate_log_wait_start "${gate_name}" "${gate_detail}"
  until nc -z "${gate_host}" "${gate_port}"; do
    gate_log_wait_tick "${gate_name}" "${gate_detail}"
    sleep 2
  done
  gate_log_wait_ready "${gate_name}"
}
{{- end -}}
>>>>>>> origin/main
