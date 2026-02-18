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
Get StackStorm API URL - either from subchart service or external URL
*/}}
{{- define "poundcake.stackstormSubchartPrefix" -}}
{{- default "stackstorm" .Values.stackstorm.releaseName -}}
{{- end }}

{{/*
Get StackStorm auth secret name from subchart
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
Get StackStorm Auth URL - either from subchart service or external URL
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
