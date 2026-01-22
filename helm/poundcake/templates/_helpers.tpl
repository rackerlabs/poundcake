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
Get the secret name for Redis credentials
*/}}
{{- define "poundcake.redisSecretName" -}}
{{- if .Values.redis.existingSecret }}
{{- .Values.redis.existingSecret }}
{{- else if and (not .Values.redis.deploy) .Values.redis.external.existingSecret }}
{{- .Values.redis.external.existingSecret }}
{{- else }}
{{- include "poundcake.fullname" . }}-redis
{{- end }}
{{- end }}

{{/*
Get the Redis URL
*/}}
{{- define "poundcake.redisUrl" -}}
{{- if .Values.redis.deploy }}
{{- printf "redis://%s-redis:6379/0" (include "poundcake.fullname" .) }}
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
Get the Celery broker URL
*/}}
{{- define "poundcake.celeryBrokerUrl" -}}
{{- if .Values.celery.brokerUrl }}
{{- .Values.celery.brokerUrl }}
{{- else if .Values.redis.enabled }}
{{- include "poundcake.redisUrl" . }}
{{- else }}
{{- "redis://localhost:6379/0" }}
{{- end }}
{{- end }}

{{/*
Get the Celery result backend URL
*/}}
{{- define "poundcake.celeryResultBackend" -}}
{{- if .Values.celery.resultBackend }}
{{- .Values.celery.resultBackend }}
{{- else if .Values.redis.enabled }}
{{- include "poundcake.redisUrl" . }}
{{- else }}
{{- "redis://localhost:6379/0" }}
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
