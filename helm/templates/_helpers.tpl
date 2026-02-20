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
