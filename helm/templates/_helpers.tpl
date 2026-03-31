{{- define "poundcake.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "poundcake.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "poundcake.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
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

{{- define "poundcake.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "poundcake.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.stackstormActionrunnerServiceAccountName" -}}
{{- $cfg := .Values.stackstormActionrunner | default dict -}}
{{- $serviceAccount := $cfg.serviceAccount | default dict -}}
{{- $name := $serviceAccount.name | default "" -}}
{{- $create := $serviceAccount.create | default true -}}
{{- if $create -}}
{{- default (printf "%s-stackstorm-actionrunner" (include "poundcake.fullname" .) | trunc 63 | trimSuffix "-") $name -}}
{{- else -}}
{{- default "default" $name -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.stackstormSubchartPrefix" -}}
{{- default "stackstorm" .Values.stackstorm.releaseName -}}
{{- end -}}

{{- define "poundcake.stackstormApiUrl" -}}
{{- if .Values.stackstorm.url -}}
{{- .Values.stackstorm.url -}}
{{- else if .Values.stackstorm.releaseName -}}
{{- printf "http://%s-st2api:9101" (include "poundcake.stackstormSubchartPrefix" .) -}}
{{- else -}}
{{- printf "http://stackstorm-api:%v" .Values.services.stackstormApi.port -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.stackstormAuthUrl" -}}
{{- if .Values.stackstorm.authUrl -}}
{{- .Values.stackstorm.authUrl -}}
{{- else if .Values.stackstorm.releaseName -}}
{{- printf "http://%s-st2auth:9100" (include "poundcake.stackstormSubchartPrefix" .) -}}
{{- else -}}
{{- printf "http://stackstorm-auth:%v" .Values.services.stackstormAuth.port -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.apiServiceUrl" -}}
{{- printf "http://poundcake-api:%v" .Values.services.api.port -}}
{{- end -}}

{{- define "poundcake.validateUniqueUrlServicePorts" -}}
{{- $urlServices := list
  (dict "name" "services.api.port" "port" (int .Values.services.api.port))
  (dict "name" "services.ui.port" "port" (int .Values.services.ui.port))
  (dict "name" "services.stackstormApi.port" "port" (int .Values.services.stackstormApi.port))
  (dict "name" "services.stackstormAuth.port" "port" (int .Values.services.stackstormAuth.port))
-}}
{{- if eq (include "poundcake.stackstormServiceEnabled" (dict "root" . "name" "stream")) "true" -}}
{{- $urlServices = append $urlServices (dict "name" "services.stackstormStream.port" "port" (int .Values.services.stackstormStream.port)) -}}
{{- end -}}
{{- if eq (include "poundcake.stackstormServiceEnabled" (dict "root" . "name" "web")) "true" -}}
{{- $urlServices = append $urlServices (dict "name" "services.stackstormWeb.port" "port" (int .Values.services.stackstormWeb.port)) -}}
{{- end -}}
{{- $seen := dict -}}
{{- range $service := $urlServices -}}
{{- $name := get $service "name" -}}
{{- $port := get $service "port" -}}
{{- $key := printf "%d" $port -}}
{{- if hasKey $seen $key -}}
{{- fail (printf "URL-addressable service ports must be unique. %s and %s both use port %d." (get $seen $key) $name $port) -}}
{{- end -}}
{{- $_ := set $seen $key $name -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.stackstormAuthSecretName" -}}
{{- if .Values.stackstorm.adminPasswordSecret -}}
{{- .Values.stackstorm.adminPasswordSecret -}}
{{- else if .Values.stackstorm.releaseName -}}
{{- printf "%s-st2-auth" (include "poundcake.stackstormSubchartPrefix" .) -}}
{{- else -}}
{{- printf "stackstorm-secrets" -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.stackstormApiKeySecret" -}}
{{- if .Values.stackstorm.apiKeySecretName -}}
{{- .Values.stackstorm.apiKeySecretName -}}
{{- else if .Values.stackstorm.releaseName -}}
{{- printf "%s-st2-apikeys" (include "poundcake.stackstormSubchartPrefix" .) -}}
{{- else -}}
{{- printf "stackstorm-apikeys" -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.stackstormApiKeySecretKey" -}}
{{- if .Values.stackstorm.apiKeySecretKey -}}
{{- .Values.stackstorm.apiKeySecretKey -}}
{{- else if .Values.stackstorm.releaseName -}}
{{- printf "api-key" -}}
{{- else -}}
{{- printf "st2_api_key" -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.stackstormPackConfigSecretName" -}}
{{- printf "stackstorm-pack-configs" -}}
{{- end -}}

{{- define "poundcake.stackstormThirdPartyPacksEnabled" -}}
{{- $bootstrap := .Values.stackstorm.bootstrap | default dict -}}
{{- $packs := $bootstrap.packs | default dict -}}
{{- $kubernetes := $packs.kubernetes | default dict -}}
{{- $openstack := $packs.openstack | default dict -}}
{{- ternary "true" "false" (or ($kubernetes.enabled | default false) ($openstack.enabled | default false)) -}}
{{- end -}}

{{- define "poundcake.stackstormThirdPartyPackConfigSecretEnabled" -}}
{{- $bootstrap := .Values.stackstorm.bootstrap | default dict -}}
{{- $packs := $bootstrap.packs | default dict -}}
{{- $kubernetes := $packs.kubernetes | default dict -}}
{{- $openstack := $packs.openstack | default dict -}}
{{- $kubernetesConfig := $kubernetes.config | default dict -}}
{{- $openstackConfig := $openstack.config | default dict -}}
{{- $enabled := eq (include "poundcake.stackstormThirdPartyPacksEnabled" .) "true" -}}
{{- ternary "true" "false" (or $enabled (ne ($kubernetesConfig.kubeconfig | default "") "") (ne ($kubernetesConfig.caCert | default "") "") (ne ($openstackConfig.cloudsYaml | default "") "") (ne ($openstackConfig.caCert | default "") "")) -}}
{{- end -}}

{{- define "poundcake.stackstormThirdPartyPackInitContainer" -}}
- name: install-third-party-packs
  image: {{ .Values.stackstormImage.repository }}:{{ .Values.stackstormImage.tag }}
  imagePullPolicy: {{ .Values.stackstormImage.pullPolicy }}
  securityContext:
    {{- toYaml .Values.utilitySecurityContext | nindent 4 }}
  envFrom:
    - secretRef:
        name: stackstorm-secrets
  env:
    - name: ST2_INSTALL_KUBERNETES_PACK
      value: {{ default false .Values.stackstorm.bootstrap.packs.kubernetes.enabled | quote }}
    - name: ST2_INSTALL_KUBERNETES_PACK_VERSION
      value: {{ default "" .Values.stackstorm.bootstrap.packs.kubernetes.version | quote }}
    - name: ST2_INSTALL_OPENSTACK_PACK
      value: {{ default false .Values.stackstorm.bootstrap.packs.openstack.enabled | quote }}
    - name: ST2_INSTALL_OPENSTACK_PACK_VERSION
      value: {{ default "" .Values.stackstorm.bootstrap.packs.openstack.version | quote }}
    - name: ST2_CONFIG_FILE
      value: /tmp/st2/st2.conf
  command: ["/bin/bash", "/st2-entrypoint.sh"]
  args: ["/install-third-party-packs.sh"]
  volumeMounts:
    - name: stackstorm-config
      mountPath: /etc/st2/st2.conf.template
      subPath: st2.conf.template
    - name: scripts
      mountPath: /st2-entrypoint.sh
      subPath: st2-entrypoint.sh
    - name: scripts
      mountPath: /install-third-party-packs.sh
      subPath: install-third-party-packs.sh
    - name: stackstorm-pack-configs
      mountPath: /opt/stackstorm/configs
      readOnly: true
    - name: stackstorm-pack-kubernetes
      mountPath: /opt/stackstorm/packs/kubernetes
    - name: stackstorm-pack-openstack
      mountPath: /opt/stackstorm/packs/openstack
    - name: stackstorm-virtualenv-kubernetes
      mountPath: /opt/stackstorm/virtualenvs/kubernetes
    - name: stackstorm-virtualenv-openstack
      mountPath: /opt/stackstorm/virtualenvs/openstack
    - name: app-config
      mountPath: /app/config
{{- end -}}

{{- define "poundcake.stackstormThirdPartyPackVolumeMounts" -}}
- name: stackstorm-pack-configs
  mountPath: /opt/stackstorm/configs
  readOnly: true
- name: stackstorm-pack-kubernetes
  mountPath: /opt/stackstorm/packs/kubernetes
- name: stackstorm-pack-openstack
  mountPath: /opt/stackstorm/packs/openstack
- name: stackstorm-virtualenv-kubernetes
  mountPath: /opt/stackstorm/virtualenvs/kubernetes
- name: stackstorm-virtualenv-openstack
  mountPath: /opt/stackstorm/virtualenvs/openstack
{{- end -}}

{{- define "poundcake.stackstormThirdPartyPackVolumes" -}}
- name: stackstorm-pack-configs
  secret:
    secretName: {{ include "poundcake.stackstormPackConfigSecretName" . }}
    optional: true
- name: stackstorm-pack-kubernetes
  emptyDir: {}
- name: stackstorm-pack-openstack
  emptyDir: {}
- name: stackstorm-virtualenv-kubernetes
  emptyDir: {}
- name: stackstorm-virtualenv-openstack
  emptyDir: {}
{{- end -}}

{{- define "poundcake.stackstormMongoName" -}}
{{- if .Values.stackstorm.resourceNames.mongodb -}}
{{- .Values.stackstorm.resourceNames.mongodb -}}
{{- else -}}
{{- printf "stackstorm-mongodb" -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.rabbitmqSecretName" -}}
{{- if .Values.rabbitmq.existingSecret -}}
{{- .Values.rabbitmq.existingSecret -}}
{{- else -}}
{{- printf "stackstorm-rabbitmq" -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.bakeryBaseUrl" -}}
{{- .Values.bakery.client.baseUrl | default "" -}}
{{- end -}}

{{- define "poundcake.bakerySecretName" -}}
{{- printf "%s-bakery-secret" (include "poundcake.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "poundcake.databaseMode" -}}
{{- $database := .Values.database | default dict -}}
{{- $mode := $database.mode | default "embedded" -}}
{{- if eq $mode "shared_operator" -}}
shared_operator
{{- else -}}
embedded
{{- end -}}
{{- end -}}

{{- define "poundcake.databaseServerName" -}}
{{- if eq (include "poundcake.databaseMode" .) "shared_operator" -}}
{{- .Values.database.sharedOperator.serverName | default "" -}}
{{- else -}}
poundcake-mariadb
{{- end -}}
{{- end -}}

{{- define "poundcake.databaseServiceNamespace" -}}
{{- if eq (include "poundcake.databaseMode" .) "shared_operator" -}}
{{- .Values.database.sharedOperator.namespace | default .Release.Namespace -}}
{{- else -}}
{{- .Release.Namespace -}}
{{- end -}}
{{- end -}}

{{- define "poundcake.databaseHost" -}}
{{- $mode := include "poundcake.databaseMode" . -}}
{{- $serverName := include "poundcake.databaseServerName" . -}}
{{- $namespace := include "poundcake.databaseServiceNamespace" . -}}
{{- if eq $mode "shared_operator" -}}
  {{- if and $serverName (ne $namespace .Release.Namespace) -}}
{{ printf "%s.%s.svc.cluster.local" $serverName $namespace }}
  {{- else -}}
{{ $serverName }}
  {{- end -}}
{{- else -}}
poundcake-mariadb
{{- end -}}
{{- end -}}

{{- define "poundcake.secretChecksumMaterial" -}}
{{- $bakery := .Values.bakery | default dict -}}
{{- $material := dict
  "databaseMode" (include "poundcake.databaseMode" .)
  "databaseHost" (include "poundcake.databaseHost" .)
  "secrets" (.Values.secrets | default dict)
  "auth" (.Values.auth | default dict)
  "stackstorm" (.Values.stackstorm | default dict)
  "stackstormServices" (.Values.stackstormServices | default dict)
  "bakeryClient" ($bakery.client | default dict)
-}}
{{ toYaml $material }}
{{- end -}}

{{- define "poundcake.logGroupLabel" -}}
poundcake.io/log-group: "bakery"
{{- end -}}

{{- define "poundcake.logRoleApi" -}}
poundcake.io/log-subgroup: "app"
poundcake.io/log-role: "api"
{{- end -}}

{{- define "poundcake.logRoleWorker" -}}
poundcake.io/log-subgroup: "app"
poundcake.io/log-role: "worker"
{{- end -}}

{{- define "poundcake.logRoleInfra" -}}
poundcake.io/log-subgroup: "data"
poundcake.io/log-role: "infra"
{{- end -}}

{{- define "poundcake.storageClass" -}}
{{- if .Values.persistence.storageClassName }}
storageClassName: {{ .Values.persistence.storageClassName | quote }}
{{- end }}
{{- end -}}

{{- define "poundcake.poundcakePullSecrets" -}}
{{- $pullSecrets := .Values.poundcakeImage.pullSecrets | default list -}}
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

{{- define "poundcake.podPlacement" -}}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
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

{{- define "poundcake.poundcakeImageVersion" -}}
{{- $digest := .Values.poundcakeImage.digest | default "" -}}
{{- if $digest -}}
{{- $digest -}}
{{- else -}}
{{- default .Chart.AppVersion .Values.poundcakeImage.tag -}}
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
  "client" true
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

gate_wait_for_http_status() {
  gate_url="$1"
  gate_name="$2"
  gate_detail="$3"
  shift 3
  gate_log_wait_start "${gate_name}" "${gate_detail}"
  while true; do
    gate_resp="$(wget -S -O /dev/null "${gate_url}" 2>&1 || true)"
    for gate_code in "$@"; do
      case "${gate_resp}" in
        *" ${gate_code} "*)
          gate_log_wait_ready "${gate_name}"
          return 0
          ;;
      esac
    done
    gate_log_wait_tick "${gate_name}" "${gate_detail}"
    sleep 2
  done
}
{{- end -}}
