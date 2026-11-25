#!/usr/bin/env bash
# Uma execução do experimento (E-2, issue #33): prepara o modo, faz o checklist
# do protocolo, roda a carga, dispara o processamento, injeta a falha do
# cenário, espera o fim e exporta as séries (D4).
#
#   simulador/run_experiment.sh <cenario> <modo> <run> [opções]
#   simulador/run_experiment.sh E1 C E1-C-2
#   simulador/run_experiment.sh R1 B R1-B-1b --campanha K
#   simulador/run_experiment.sh E1 A E1-A-piloto --piloto
#
# Cenários: E1 E2 R1 R1a R2 R3 M1; modos: A B C. O <run> começa com
# <cenario>-<modo>- e termina com a repetição k (que é também a --seed do
# simulador), com uma letra se a execução foi refeita: E1-C-2b.
#
# Opções:
#   --campanha K|R      parâmetros de simulador/campanhas/<K|R>.env (padrão K)
#   --piloto            execução piloto: resultados em resultados/piloto/, não
#                       exige IMAGEM_DIGEST nem repositórios limpos
#   --teto N            teto do modo C (padrão: o da campanha; D5)
#   --seed N            semente do simulador (padrão: k do <run>)
#   --saida DIR         pasta raiz dos resultados (padrão resultados/)
#   --permitir-sujo     roda com mudanças locais nos repositórios (a execução
#                       fica inválida, salvo no piloto)
#   --so-checklist      prepara o modo, faz o checklist e para
#   --sem-diario        não acrescenta a entrada ao diário de bordo
#
# Saída: 0 = execução válida (ou piloto concluído); 2 = execução inválida
# (arquivos em .../<modo>/invalidas/, entrada no diário); 1 = não rodou
# (checklist falhou, erro de uso ou de ambiente).
#
# Grava em resultados/<cenario>/<modo>/:
#   <run>.json           metadados (parâmetros, commits, digest, instantes,
#                        checklist, falha, validade) + a chave "export" do D4
#   <run>.csv            séries do Prometheus entre t0 e o fim (export_metrics.py)
#   <run>.log            esta saída
#   <run>-postgres.csv   contagem do Postgres durante a execução (--acompanhar)
#   <run>-carga.{json,csv}  registro do simulador
#
# Repositórios irmãos (variáveis de ambiente):
#   QD_DEPLOYMENT_DIR        padrão ../querido-diario-deployment (overlays)
#   QD_DATA_PROCESSING_DIR   padrão ../querido-diario-data-processing (só o commit)
#
# Detalhes: docs/avaliacao/execucao.md.

set -Eeuo pipefail

PASTA_SIM=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RAIZ=$(dirname "$PASTA_SIM")

uso() { sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }

[[ $# -ge 3 ]] || uso
CENARIO=$1 MODO=$2 RUN=$3
shift 3

CAMPANHA=K PILOTO=0 TETO_ARG="" SEED="" SAIDA_ARG="" PERMITIR_SUJO=0 SO_CHECKLIST=0 SEM_DIARIO=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --campanha) CAMPANHA=$2; shift ;;
        --piloto) PILOTO=1 ;;
        --teto) TETO_ARG=$2; shift ;;
        --seed) SEED=$2; shift ;;
        --saida) SAIDA_ARG=$2; shift ;;
        --permitir-sujo) PERMITIR_SUJO=1 ;;
        --so-checklist) SO_CHECKLIST=1 ;;
        --sem-diario) SEM_DIARIO=1 ;;
        -h|--help) uso ;;
        *) echo "opção desconhecida: $1" >&2; uso ;;
    esac
    shift
done

case $CENARIO in E1|E2|R1|R1a|R2|R3|M1) ;; *) echo "cenário inválido: $CENARIO" >&2; exit 1 ;; esac
case $MODO in A|B|C) ;; *) echo "modo inválido: $MODO" >&2; exit 1 ;; esac
[[ $RUN == "$CENARIO-$MODO-"* ]] || { echo "o <run> precisa começar com $CENARIO-$MODO- (ex.: $CENARIO-$MODO-1)" >&2; exit 1; }
[[ $CENARIO == M1 && $MODO == B ]] && { echo "M1 não tem modo B (cenarios.md)" >&2; exit 1; }
CONFIG="$PASTA_SIM/campanhas/$CAMPANHA.env"
[[ -f $CONFIG ]] || { echo "campanha sem configuração: $CONFIG" >&2; exit 1; }
# shellcheck source=campanhas/K.env
source "$CONFIG"
[[ -n $TETO_ARG ]] && TETO=$TETO_ARG
if [[ -z $SEED ]]; then
    if [[ $RUN =~ -([0-9]+)[a-z]?$ ]]; then SEED=${BASH_REMATCH[1]}; else SEED=1; fi
fi

DEP=${QD_DEPLOYMENT_DIR:-$RAIZ/../querido-diario-deployment}
DP=${QD_DATA_PROCESSING_DIR:-$RAIZ/../querido-diario-data-processing}
[[ -d $DEP/k8s ]] || { echo "querido-diario-deployment não encontrado em $DEP (defina QD_DEPLOYMENT_DIR)" >&2; exit 1; }

if [[ -n $SAIDA_ARG ]]; then SAIDA=$(realpath -m "$SAIDA_ARG")
elif [[ $PILOTO == 1 ]]; then SAIDA=$RAIZ/resultados/piloto
else SAIDA=$RAIZ/resultados; fi
PASTA_RUN=$SAIDA/$CENARIO/$MODO
JSON=$PASTA_RUN/$RUN.json
LOG=$PASTA_RUN/$RUN.log
DIARIO=$RAIZ/resultados/diario-de-bordo.md
for antigo in "$JSON" "$PASTA_RUN/invalidas/$RUN.json"; do
    [[ -e $antigo ]] && { echo "a execução $RUN já existe ($antigo): use a próxima letra (ex.: ${RUN}b)" >&2; exit 1; }
done
mkdir -p "$PASTA_RUN" "$RAIZ/resultados"

# Uma execução por vez (o cluster é um só)
exec 9>"$RAIZ/resultados/.experimento.lock"
flock -n 9 || { echo "outra execução está rodando (resultados/.experimento.lock)" >&2; exit 1; }

TMP=$(mktemp -d)
exec > >(tee -a "$LOG" 9>&-) 2>&1

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

kc() { kubectl --context "$CONTEXTO" -n "$NAMESPACE" "$@"; }
# Reativa o agendamento de um CronJob. Sem startingDeadlineSeconds, o
# Kubernetes dispara na hora o último horário perdido enquanto ele estava
# suspenso (visto no teste do E2-A em 24/11/2026: o Job das 22:00 subiu às 22:48)
reativar_cronjob() { kc patch cronjob "$1" -p '{"spec":{"suspend":false,"startingDeadlineSeconds":60}}' >/dev/null; }
kg() { kubectl --context "$CONTEXTO" "$@"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
agora() { date +%s.%3N; }
maior() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a > b) }'; }

# meta '<filtro jq>' [opções do jq]: altera o .json da execução
meta() {
    local filtro=$1; shift
    jq "$@" "$filtro" "$JSON" > "$TMP/meta.json" && mv "$TMP/meta.json" "$JSON"
}

declare -A INST=()
marca() {
    local nome=$1 ts=${2:-$(agora)}
    INST[$nome]=$ts
    meta '.instantes[$n] = ($t | tonumber) | .instantes_iso[$n] = ($t | tonumber | floor | todate)' \
        --arg n "$nome" --arg t "$ts"
    log "$nome = $(date -u -d "@$ts" +%FT%TZ)"
}

INVALIDA=0
invalida() { INVALIDA=1; meta '.validade.motivos += [$m]' --arg m "$*"; log "INVÁLIDA: $*"; }
anomalia() { meta '.validade.anomalias += [$a]' --arg a "$*"; log "anomalia: $*"; }

CHECK_FALHOU=0
check() {  # check <item> <0|1> <detalhe>
    meta '.checklist += [{item: $i, ok: ($o == "1"), detalhe: $d}]' --arg i "$1" --arg o "$2" --arg d "$3"
    if [[ $2 == 1 ]]; then log "  ✔ $1: $3"; else log "  ✘ $1: $3"; CHECK_FALHOU=1; fi
}

PG_POD=""
pg() { kc exec "$PG_POD" -c postgres -- psql -d queridodiario -tAq -F '|' -c "$1"; }
rq() { kc exec deploy/redis-queue -c redis -- redis-cli --raw "$@"; }

ids_dlq() { rq lrange qd:extraction:dead 0 -1 2>/dev/null | jq -Rr 'fromjson? | .id // empty' | paste -sd, -; }

CORROMPIDOS_IDS=""
# "processados|pendentes": pendentes sem os da DLQ (B e C) ou sem os
# corrompidos (A, que não tem DLQ), como em cenarios.md, "Fim da execução"
contagem() {
    local excl=""
    if [[ $MODO == A ]]; then excl=$CORROMPIDOS_IDS; else excl=$(ids_dlq) || return 1; fi
    pg "SELECT count(*) FILTER (WHERE processed),
               count(*) FILTER (WHERE NOT processed AND NOT (id = ANY('{${excl}}'::bigint[])))
        FROM gazettes WHERE file_url LIKE 'sim://%'"
}

PF_PID=""
prom() {  # prom '<PromQL>' → JSON da /api/v1/query
    if [[ $AMBIENTE == kind ]]; then
        curl -sf --get "http://localhost:9092/api/v1/query" --data-urlencode "query=$1"
    else
        kc exec export-metrics -- python3 -c 'import os, sys, urllib.parse, urllib.request
url = os.environ["QD_EXPORT_PROMETHEUS_URL"] + "/api/v1/query?query=" + urllib.parse.quote(sys.argv[1])
print(urllib.request.urlopen(url, timeout=30).read().decode())' "$1"
    fi
}
prom_valor() { prom "$1" | jq -r '.data.result[0].value[1] // empty'; }

commit_repo() {  # JSON {sha, branch, sujo} de um repositório
    local repo=$1 excluir=${2:-}
    if ! git -C "$repo" rev-parse HEAD >/dev/null 2>&1; then echo null; return; fi
    local sujo
    if [[ -n $excluir ]]; then sujo=$(git -C "$repo" status --porcelain -- . ":!$excluir" | head -1)
    else sujo=$(git -C "$repo" status --porcelain | head -1); fi
    jq -n --arg s "$(git -C "$repo" rev-parse HEAD)" --arg b "$(git -C "$repo" branch --show-current)" \
        --argjson d "$([[ -n $sujo ]] && echo true || echo false)" '{sha: $s, branch: $b, sujo: $d}'
}

pods_infra() {  # JSON {pod: {uid, restarts, ready}} dos pods de infraestrutura
    {
        kc get pods -l 'app in (opensearch,garage,redis-queue,apache-tika,redis,pushgateway)' -o json
        kc get pods -l cnpg.io/cluster=postgres -o json
        if [[ $AMBIENTE == kind ]]; then
            kg get pods -n monitoring -l 'app.kubernetes.io/name in (prometheus,prometheus-pushgateway,kube-state-metrics)' -o json
        fi
    } | jq -s '[.[].items[]] | map({key: .metadata.name, value: {
            uid: .metadata.uid,
            restarts: ([.status.containerStatuses[]?.restartCount] | add // 0),
            oom: ([.status.containerStatuses[]?.lastState.terminated.reason // empty] | index("OOMKilled") != null),
            ready: ([.status.containerStatuses[]?.ready] | all)}}) | from_entries'
}

imagens_usadas() {  # digests da imagem do data-processing nos pods da execução
    kc get pods -o json | jq --arg job "${JOB_PREFIXO:-exp-}" '[.items[]
        | select(.metadata.name | test("^(" + $job + "|extraction-worker|enqueue-extraction)"))
        | .metadata.name as $p | .status.containerStatuses[]?
        | select(.image | test("querido-diario-data-processing[:@]"))
        | {pod: $p, imagem: .image, digest: (.imageID | capture("(?<d>sha256:[0-9a-f]+)$").d // .imageID)}]'
}

# ---------------------------------------------------------------------------
# Limpeza na saída: processos em segundo plano e configurações temporárias
# ---------------------------------------------------------------------------

ACOMP_PID="" FALHA_PID="" VT_APLICADO=0 E2_DESSUSPENSO=0 ENQUEUE_SUSPENSO=0 INICIOU=0 TERMINOU=0 ERRO_LINHA=""
trap 'ERRO_LINHA="linha $LINENO: $BASH_COMMAND"' ERR

restaurar() {
    if [[ -n $ACOMP_PID ]]; then
        kill -TERM -- "-$ACOMP_PID" 2>/dev/null || true
        for _ in $(seq 50); do kill -0 -- "-$ACOMP_PID" 2>/dev/null || break; sleep 0.2; done
        ACOMP_PID=""
    fi
    [[ -n $FALHA_PID ]] && { kill -- "-$FALHA_PID" 2>/dev/null || true; FALHA_PID=""; }
    if [[ $VT_APLICADO == 1 ]]; then
        log "restaurando o QUEUE_VISIBILITY_TIMEOUT padrão do extraction-worker"
        kc set env deployment/extraction-worker QUEUE_VISIBILITY_TIMEOUT- >/dev/null 2>&1 || log "aviso: não consegui restaurar o QUEUE_VISIBILITY_TIMEOUT"
        VT_APLICADO=0
    fi
    if [[ $ENQUEUE_SUSPENSO == 1 ]]; then
        log "reativando o agendamento do enqueue-extraction"
        reativar_cronjob enqueue-extraction 2>/dev/null || log "aviso: não consegui reativar o enqueue-extraction"
        ENQUEUE_SUSPENSO=0
    fi
    if [[ $E2_DESSUSPENSO == 1 ]]; then
        log "suspendendo de novo o CronJob data-processing"
        kc patch cronjob data-processing -p '{"spec":{"suspend":true}}' >/dev/null 2>&1 || log "aviso: não consegui suspender o data-processing"
        E2_DESSUSPENSO=0
    fi
    # Uma réplica do Prometheus (port-forward) em kind
    [[ -n $PF_PID ]] && { kill -- "-$PF_PID" 2>/dev/null || true; PF_PID=""; }
}

ao_sair() {
    local codigo=$?
    set +e
    trap - ERR
    restaurar
    if [[ $codigo -ne 0 && $INICIOU == 1 && $TERMINOU == 0 ]]; then
        # Erro depois que a carga começou: a execução aconteceu e fica registrada como inválida
        invalida "erro do run_experiment.sh (${ERRO_LINHA:-código $codigo})"
        finalizar_registro
        codigo=2
    elif [[ $INICIOU == 0 && -e $JSON ]]; then
        if [[ $codigo == 0 ]]; then
            rm -f "$JSON" "$LOG"   # --so-checklist
        else
            # Não rodou (checklist ou ambiente): guarda para diagnóstico e libera o <run>
            local pasta="$SAIDA/nao-executadas"
            mkdir -p "$pasta"
            local sufixo
            sufixo=$(date +%Y%m%dT%H%M%S)
            mv "$JSON" "$pasta/$RUN-$sufixo.json"
            mv "$LOG" "$pasta/$RUN-$sufixo.log"
            log "registro do checklist em $(realpath --relative-to="$RAIZ" "$pasta")/$RUN-$sufixo.{json,log}"
        fi
    fi
    rm -rf "$TMP"
    exit "$codigo"
}
trap ao_sair EXIT
trap 'exit 130' INT TERM

# ---------------------------------------------------------------------------
# Parâmetros e metadados iniciais
# ---------------------------------------------------------------------------

case $CENARIO in
    E1) N=$N_E1 ;; R1) N=$N_R1 ;; E2) N=0 ;; *) N=$N_ROBUSTEZ ;;
esac
CORROMPIDOS=0
[[ $CENARIO == R2 || $CENARIO == M1 ]] && CORROMPIDOS=$CORROMPIDOS_R2
VT=""
[[ $CENARIO == R1 && $MODO != A ]] && VT=$VISIBILITY_TIMEOUT_R1
[[ $CENARIO == R1 && $CAMPANHA == R ]] && log "aviso: o R1 fica fora da campanha R (protocolo, 'Orçamento de tempo')"

jq -n --arg run "$RUN" --arg c "$CENARIO" --arg m "$MODO" --arg camp "$CAMPANHA" \
    --argjson piloto "$([[ $PILOTO == 1 ]] && echo true || echo false)" \
    --argjson k "$SEED" --arg ctx "$CONTEXTO" --arg ns "$NAMESPACE" --arg amb "$AMBIENTE" \
    --argjson inicio "$(agora)" --arg host "$(hostname)" \
    --argjson n "$N" --argjson teto "$([[ $MODO == B ]] && echo 1 || echo "$TETO")" \
    --argjson corr "$CORROMPIDOS" --arg vt "$VT" --arg terr "$TERRITORIO" \
    --argjson passo "$PASSO_S" --argjson timeout "$TIMEOUT_S" --argjson janela "$JANELA_E2_S" \
    --argjson ocioso "$OCIOSO_S" --argjson ind "$INDISPONIBILIDADE_R3_S" \
    --arg fr1 "$FRACAO_FALHA_R1" --arg fr3 "$FRACAO_FALHA_R3" \
    '{run: $run, cenario: $c, modo: $m, campanha: $camp, piloto: $piloto, repeticao: $k,
      ambiente: $amb, contexto: $ctx, namespace: $ns, maquina: $host, inicio_script: $inicio,
      parametros: {n: $n, seed: $k, perfil: (if $n > 0 then "burst" else null end), territorio: $terr,
                   teto: $teto, corrompidos: $corr,
                   visibility_timeout: (if $vt == "" then null else ($vt | tonumber) end),
                   passo_s: $passo, timeout_s: $timeout, ocioso_s: $ocioso,
                   janela_s: (if $c == "E2" then $janela else null end),
                   indisponibilidade_s: (if $c == "R3" then $ind else null end),
                   fracao_falha: (if $c == "R3" then ($fr3 | tonumber)
                                  elif ($c == "R1" or $c == "R1a") then ($fr1 | tonumber) else null end)},
      instantes: {}, instantes_iso: {}, checklist: [], jobs: [],
      validade: {valida: null, motivos: [], anomalias: []}}' > "$JSON"

log "execução $RUN: cenário $CENARIO, modo $MODO, campanha $CAMPANHA ($CONTEXTO/$NAMESPACE)$([[ $PILOTO == 1 ]] && echo ', PILOTO')"
log "N = $N, seed = $SEED, teto = $([[ $MODO == B ]] && echo 1 || echo "$TETO"), corrompidos = $CORROMPIDOS${VT:+, QUEUE_VISIBILITY_TIMEOUT = $VT s}"

# ---------------------------------------------------------------------------
# Ambiente local, commits e acesso ao cluster
# ---------------------------------------------------------------------------

disco=$(df --output=pcent "$RAIZ" | tail -1 | tr -dc 0-9)
mem_livre=$(awk '/MemAvailable/ { printf "%d", $2 / 1024 }' /proc/meminfo)
meta '.maquina_local = {disco_uso_pct: ($d | tonumber), memoria_disponivel_mib: ($m | tonumber), carga_1min: $l}' \
    --arg d "$disco" --arg m "$mem_livre" --arg l "$(cut -d' ' -f1 /proc/loadavg)"
log "máquina local: disco ${disco}% usado, ${mem_livre} MiB de memória disponível, carga $(cut -d' ' -f1 /proc/loadavg)"
if (( disco >= 95 )); then
    log "ERRO: disco com ${disco}% de uso; libere espaço antes de continuar"; exit 1
fi
(( mem_livre < 1024 )) && log "aviso: menos de 1 GiB de memória disponível na máquina local"

meta '.commits = {estados: $e, deployment: $d, data_processing: $p}' \
    --argjson e "$(commit_repo "$RAIZ" resultados)" --argjson d "$(commit_repo "$DEP")" \
    --argjson p "$(commit_repo "$DP")"
sujos=$(jq -r '.commits | to_entries[] | select(.value.sujo == true) | .key' "$JSON" | paste -sd, -)
sem_repo=$(jq -r '.commits | to_entries[] | select(.value == null) | .key' "$JSON" | paste -sd, -)
dep_branch=$(jq -r '.commits.deployment.branch' "$JSON")

kg get namespace "$NAMESPACE" >/dev/null || { log "ERRO: sem acesso ao namespace $NAMESPACE no contexto $CONTEXTO"; exit 1; }
PG_POD=$(kc get pods -l cnpg.io/cluster=postgres,cnpg.io/instanceRole=primary -o name | head -1)
[[ -n $PG_POD ]] || { log "ERRO: pod primário do Postgres não encontrado"; exit 1; }

if [[ $AMBIENTE == kind ]]; then
    ns_prom=${PROMETHEUS_SVC%%/*} svc_prom=${PROMETHEUS_SVC#*/}
    setsid kubectl --context "$CONTEXTO" port-forward -n "$ns_prom" "svc/$svc_prom" 9092:9090 >/dev/null 2>&1 9>&- &
    PF_PID=$!
    for _ in $(seq 50); do curl -sf localhost:9092/-/ready >/dev/null 2>&1 && break; sleep 0.2; done
else
    if ! kc get pod export-metrics >/dev/null 2>&1; then
        log "criando o pod export-metrics (simulador/k8s/export-metrics-pod.yaml)"
        kc apply -f "$PASTA_SIM/k8s/export-metrics-pod.yaml"
    fi
    kc wait --for=condition=Ready pod/export-metrics --timeout=5m >/dev/null
fi

# ---------------------------------------------------------------------------
# Modo: overlay, teto e QUEUE_VISIBILITY_TIMEOUT
# ---------------------------------------------------------------------------

esperar() {  # esperar <timeout_s> <descrição> <comando...>: repete até o comando dar certo
    local limite=$(( $(date +%s) + $1 )) descr=$2; shift 2
    until "$@"; do
        (( $(date +%s) < limite )) || { log "tempo esgotado esperando: $descr"; return 1; }
        sleep 5
    done
}

replicas() { kc get deployment extraction-worker -o jsonpath="{.$1}" 2>/dev/null || true; }
worker_pronto() { [[ $(replicas status.readyReplicas) == 1 && $(replicas spec.replicas) == 1 ]]; }
workers_zero() { [[ $(replicas spec.replicas) == 0 ]] && [[ -z $(kc get pods -l app=extraction-worker -o name 2>/dev/null) ]]; }

aplicar_modo() {
    log "aplicando o modo $MODO"
    if [[ $MODO == A ]]; then
        if kc get scaledobject extraction-worker >/dev/null 2>&1; then
            log "removendo a fila de extração (ScaledObject primeiro)"
            local tipos=scaledobject,deployment,service,cronjob,job,pvc
            kg get crd podmonitors.monitoring.coreos.com >/dev/null 2>&1 && tipos+=,podmonitor
            kc delete "$tipos" -l app.kubernetes.io/part-of=queue-pipeline --ignore-not-found
        fi
        kg apply -k "$DEP/$OVERLAY_A" >/dev/null
        if [[ -n $IMAGEM_MODO_A ]]; then
            kc patch cronjob data-processing --type=strategic -p "$(jq -nc --arg i "$IMAGEM_MODO_A" \
                '{spec: {jobTemplate: {spec: {template: {spec: {containers: [{name: "data-processing", image: $i, imagePullPolicy: "IfNotPresent"}]}}}}}}')" >/dev/null
        fi
        kc rollout status deployment/apache-tika --timeout=10m
    else
        kg apply -k "$DEP/$OVERLAY_FILA" >/dev/null
        [[ -n $OVERLAY_FILA_MONITORAMENTO ]] && kg apply -k "$DEP/$OVERLAY_FILA_MONITORAMENTO" >/dev/null
        kc rollout status deployment/redis-queue --timeout=5m
        # O kubectl apply não desfaz o que foi mudado com patch/set env (merge
        # de três vias), então teto e timeout são sempre fixados explicitamente
        local min=0 max=$TETO
        [[ $MODO == B ]] && min=1 max=1
        kc patch scaledobject extraction-worker --type merge \
            -p "{\"spec\":{\"minReplicaCount\":$min,\"maxReplicaCount\":$max}}" >/dev/null
        if [[ -n $VT ]]; then
            kc set env deployment/extraction-worker "QUEUE_VISIBILITY_TIMEOUT=$VT" >/dev/null
            VT_APLICADO=1
        else
            kc set env deployment/extraction-worker QUEUE_VISIBILITY_TIMEOUT- >/dev/null 2>&1 || true
        fi
        if [[ $MODO == B ]]; then
            esperar 600 "1 worker pronto" worker_pronto
            kc rollout status deployment/extraction-worker --timeout=10m
        else
            esperar "$TIMEOUT_ZERO_S" "workers em 0" workers_zero
        fi
    fi
}

# ---------------------------------------------------------------------------
# Checklist (protocolo, "Antes de cada execução")
# ---------------------------------------------------------------------------

checklist() {
    log "checklist"

    # Repositórios (protocolo, "Registro"): sem mudanças locais
    if [[ -n $sem_repo ]]; then
        check repositorios 0 "repositório(s) não encontrado(s): $sem_repo (QD_DEPLOYMENT_DIR/QD_DATA_PROCESSING_DIR)"
    elif [[ -n $sujos ]]; then
        if [[ $PILOTO == 1 ]]; then
            check repositorios 1 "mudanças locais em: $sujos (aceito no piloto)"
            anomalia "repositórios com mudanças locais: $sujos"
        elif [[ $PERMITIR_SUJO == 1 ]]; then
            check repositorios 1 "mudanças locais em: $sujos (--permitir-sujo)"
            invalida "repositórios com mudanças locais: $sujos"
        else
            check repositorios 0 "mudanças locais em: $sujos (commit antes, ou --permitir-sujo)"
        fi
    else
        check repositorios 1 "sem mudanças locais"
    fi
    [[ $dep_branch != main-estados ]] && anomalia "querido-diario-deployment na branch '$dep_branch', não em main-estados"

    # Máquina dedicada (protocolo, "Campanhas"): no kind, nenhum outro
    # contêiner. Em 24/11/2026 a máquina travou duas vezes nos testes, com
    # outros 6 contêineres de pé e ~7,4 GiB de memória
    if [[ $AMBIENTE == kind ]]; then
        local no_kind="${CONTEXTO#kind-}-control-plane" outros
        outros=$(docker ps --format '{{.Names}}' | grep -vx "$no_kind" | paste -sd, - || true)
        meta '.maquina_local.outros_conteineres = ($o | split(",") | map(select(. != "")))' --arg o "$outros"
        if [[ -z $outros ]]; then
            check maquina_dedicada 1 "só o nó do kind no Docker"
        elif [[ ${PERMITIR_OUTROS_CONTEINERES:-0} == 1 ]]; then
            check maquina_dedicada 1 "outros contêineres: $outros (PERMITIR_OUTROS_CONTEINERES=1)"
            anomalia "outros contêineres de pé na máquina: $outros"
        else
            check maquina_dedicada 0 "outros contêineres de pé: $outros (pare-os, ou PERMITIR_OUTROS_CONTEINERES=1 num teste)"
        fi
    fi

    # 1. Modo
    local so min max pronto
    if [[ $MODO == A ]]; then
        so=$(kc get scaledobject extraction-worker -o name 2>/dev/null || true)
        local tika imagem
        tika=$(kc get deployment apache-tika -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)
        imagem=$(kc get cronjob data-processing -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}')
        if [[ -z $so && $tika == 1 && ( -z $IMAGEM_MODO_A || $imagem == "$IMAGEM_MODO_A" ) ]]; then
            check modo 1 "overlay $OVERLAY_A: sem fila, Tika compartilhado pronto, CronJob com $imagem"
        else
            check modo 0 "ScaledObject='${so}' Tika pronto='${tika}' imagem do CronJob='${imagem}'"
        fi
    else
        read -r min max pronto < <(kc get scaledobject extraction-worker -o json | jq -r \
            '"\(.spec.minReplicaCount) \(.spec.maxReplicaCount) \((.status.conditions // [])[] | select(.type == "Ready") | .status)"')
        local esperado_min=0 esperado_max=$TETO
        [[ $MODO == B ]] && esperado_min=1 esperado_max=1
        if [[ $min == "$esperado_min" && $max == "$esperado_max" && $pronto == True ]]; then
            check modo 1 "ScaledObject min=$min max=$max Ready"
        else
            check modo 0 "ScaledObject min=$min max=$max Ready=$pronto (esperado min=$esperado_min max=$esperado_max Ready=True; KEDA reconciliando?)"
        fi
        local vt_atual
        vt_atual=$(kc get deployment extraction-worker -o json | jq -r '.spec.template.spec.containers[] | select(.name == "worker") | .env[]? | select(.name == "QUEUE_VISIBILITY_TIMEOUT") | .value')
        if [[ $vt_atual == "$VT" ]]; then
            check visibility_timeout 1 "${VT:-padrão (2 h)}"
        else
            check visibility_timeout 0 "QUEUE_VISIBILITY_TIMEOUT='$vt_atual', esperado '${VT:-ausente}'"
        fi
    fi

    # 2. Imagem
    local ref digest
    ref=$(kc get cronjob data-processing -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}')
    if [[ $ref == *@sha256:* ]]; then
        digest=${ref##*@}
    elif [[ $AMBIENTE == kind ]]; then
        local no="${CONTEXTO#kind-}-control-plane"
        digest=$(docker exec "$no" crictl inspecti "$ref" 2>/dev/null | jq -r '.status.repoDigests[0] // .status.id' | grep -o 'sha256:[0-9a-f]*' || true)
    fi
    meta '.imagem.referencia = $r | .imagem.digest_no_cluster = $d | .imagem.esperada = $e' \
        --arg r "$ref" --arg d "${digest:-}" --arg e "$IMAGEM_DIGEST"
    if [[ -z ${digest:-} ]]; then
        check imagem 0 "não consegui o digest de $ref"
    elif [[ -z $IMAGEM_DIGEST ]]; then
        if [[ $PILOTO == 1 ]]; then
            check imagem 1 "$digest (IMAGEM_DIGEST ainda não fixado: copie para campanhas/$CAMPANHA.env)"
        else
            check imagem 0 "$digest em uso, mas IMAGEM_DIGEST não está fixado em campanhas/$CAMPANHA.env"
        fi
    elif [[ $digest == "$IMAGEM_DIGEST" ]]; then
        check imagem 1 "$digest"
    else
        check imagem 0 "$digest em uso, $IMAGEM_DIGEST registrado para a campanha"
    fi

    # 3. Monitoramento. Logo depois de uma troca de modo, o Prometheus ainda
    # não descobriu os alvos recriados (PodMonitor novo): espera até 4 min
    local alvos=(pushgateway) faltando=()
    [[ $MODO != A ]] && alvos+=(redis-queue)
    [[ $MODO == B ]] && alvos+=(extraction-worker)
    monitoramento_ok() {
        faltando=()
        local alvo chave
        for alvo in "${alvos[@]}"; do
            [[ $(prom_valor "min(up{job=~\".*$alvo.*\"})" || true) == 1 ]] || faltando+=("$alvo")
        done
        if [[ $MODO != A ]]; then
            for chave in extraction qd:extraction:dead; do
                [[ -n $(prom_valor "count(redis_key_size{namespace=\"$NAMESPACE\", key=\"$chave\"})" || true) ]] || faltando+=("redis_key_size{key=$chave}")
            done
        fi
        [[ ${#faltando[@]} -eq 0 ]]
    }
    esperar 240 "alvos no Prometheus" monitoramento_ok || true
    if [[ ${#faltando[@]} -eq 0 ]]; then
        check monitoramento 1 "up == 1 para ${alvos[*]}"
    else
        check monitoramento 0 "sem dados de: ${faltando[*]}"
    fi

    # 4. Infraestrutura
    local saude nao_prontos
    saude=$(kc exec opensearch-0 -c opensearch -- curl -s localhost:9200/_cluster/health 2>/dev/null | jq -r '.status // empty' || true)
    INFRA_INICIO=$(pods_infra)
    nao_prontos=$(jq -r 'to_entries[] | select(.value.ready | not) | .key' <<<"$INFRA_INICIO" | paste -sd, -)
    if [[ ($saude == green || $saude == yellow) && -z $nao_prontos ]]; then
        check infraestrutura 1 "OpenSearch $saude; $(jq length <<<"$INFRA_INICIO") pods de infraestrutura prontos"
    else
        check infraestrutura 0 "OpenSearch '${saude}'; não prontos: ${nao_prontos:-nenhum}"
    fi
    meta '.infra_inicio = $i' --argjson i "$INFRA_INICIO"
    local anterior="$SAIDA/.infra-$CAMPANHA.json"
    if [[ -f $anterior ]]; then
        local mudou
        mudou=$(jq -r --slurpfile a "$anterior" '. as $agora | $a[0] | to_entries[]
            | select($agora[.key] != null and ($agora[.key].uid != .value.uid or $agora[.key].restarts != .value.restarts))
            | .key' <<<"$INFRA_INICIO" | paste -sd, -)
        [[ -n $mudou ]] && anomalia "pods de infraestrutura reiniciados ou recriados desde a execução anterior: $mudou"
    fi

    # 5. Diários sintéticos da execução anterior
    log "load_simulator.py --cleanup"
    (cd "$RAIZ" && uv run -q simulador/load_simulator.py --cleanup --port-forward \
        --namespace "$NAMESPACE" --context "$CONTEXTO")

    # 6. Fila vazia, nenhum worker ocupado e FLUSHDB (B e C)
    if [[ $MODO != A ]]; then
        rq del extraction >/dev/null
        local ocupados
        ocupado() { [[ $(rq hlen unacked) == 0 ]]; }
        if ! esperar 300 "nenhuma mensagem em unacked" ocupado; then
            ocupados=$(rq hlen unacked)
            anomalia "$ocupados mensagem(ns) em unacked antes do FLUSHDB (órfã de execução anterior?)"
        fi
        rq flushdb >/dev/null
        local fila dlq
        fila=$(rq llen extraction) dlq=$(rq llen qd:extraction:dead)
        if [[ $fila == 0 && $dlq == 0 && $(rq hlen unacked) == 0 ]]; then
            check redis_fila 1 "FLUSHDB; fila, DLQ e unacked vazias"
        else
            check redis_fila 0 "fila=$fila dlq=$dlq depois do FLUSHDB"
        fi
    fi

    # 7. CronJobs e Jobs anteriores
    kc patch cronjob data-processing -p '{"spec":{"suspend":true}}' >/dev/null
    if [[ $MODO != A ]]; then
        kc patch cronjob themes-from-queue -p '{"spec":{"suspend":true}}' >/dev/null
        # O agendamento do produtor (5 em 5 min) enfileiraria durante a
        # inserção e o processamento começaria antes do t0, o que não acontece
        # no A. Fica suspenso até o disparo manual e volta logo depois dele
        # (no E2, fica ativo: é parte do repouso do B e do C)
        if [[ $CENARIO != E2 ]]; then
            kc patch cronjob enqueue-extraction -p '{"spec":{"suspend":true}}' >/dev/null
            ENQUEUE_SUSPENSO=1
        else
            reativar_cronjob enqueue-extraction
        fi
    fi
    local ativos
    jobs_ativos() {
        ativos=$(kc get jobs -o json | jq -r '.items[] | select((.status.active // 0) > 0)
            | select(.metadata.name | test("^(exp-|data-processing|themes-from-queue)")) | .metadata.name' | paste -sd, -)
        [[ -z $ativos ]]
    }
    if esperar 900 "Jobs de processamento terminarem" jobs_ativos; then
        local suspensos
        suspensos="data-processing=$(kc get cronjob data-processing -o jsonpath='{.spec.suspend}')"
        [[ $MODO != A ]] && suspensos+=" themes-from-queue=$(kc get cronjob themes-from-queue -o jsonpath='{.spec.suspend}')"
        [[ $MODO != A && $CENARIO != E2 ]] && suspensos+=" enqueue-extraction=$(kc get cronjob enqueue-extraction -o jsonpath='{.spec.suspend}')"
        if [[ $suspensos != *false* ]]; then check cronjobs 1 "suspensos: $suspensos"; else check cronjobs 0 "$suspensos"; fi
    else
        check cronjobs 0 "Jobs ainda ativos: $ativos"
    fi
    # Jobs de execuções anteriores (os pods já terminaram; só limpa o namespace)
    kc get jobs -o name | grep '^job.batch/exp-' | xargs -r kubectl --context "$CONTEXTO" -n "$NAMESPACE" delete >/dev/null || true

    # 8. Nenhum diário sintético
    local restantes
    restantes=$(pg "SELECT count(*) FROM gazettes WHERE file_url LIKE 'sim://%'")
    if [[ $restantes == 0 ]]; then check sinteticos 1 "0 diários sintéticos"; else check sinteticos 0 "$restantes diários sintéticos depois do --cleanup"; fi
}

aplicar_modo
checklist

if [[ $CHECK_FALHOU == 1 ]]; then
    log "checklist falhou: a execução não roda (protocolo, 'Antes de cada execução')"
    meta '.validade.valida = false | .validade.motivos += ["checklist falhou"]'
    exit 1
fi
if [[ $SO_CHECKLIST == 1 ]]; then
    log "checklist ok (--so-checklist): parando aqui"
    exit 0
fi

# 9. Espera ociosa
if [[ $MODO == C ]]; then esperar "$TIMEOUT_ZERO_S" "workers em 0" workers_zero; fi
log "espera ociosa de ${OCIOSO_S} s"
sleep "$OCIOSO_S"
if [[ $MODO == C ]] && ! workers_zero; then
    log "ERRO: workers subiram durante a espera ociosa"; exit 1
fi

# ---------------------------------------------------------------------------
# Finalização (também chamada pela saída com erro)
# ---------------------------------------------------------------------------

exportar() {
    local inicio=$1 fim=$2
    meta '.export_janela = {inicio: ($i | tonumber), fim: ($f | tonumber)}' --arg i "$inicio" --arg f "$fim"
    log "exportando as séries ($(date -u -d "@$inicio" +%T) → $(date -u -d "@$fim" +%T) UTC)"
    if [[ $AMBIENTE == kind ]]; then
        (cd "$RAIZ" && uv run -q simulador/export_metrics.py --start "$inicio" --end "$fim" \
            --cenario "$CENARIO" --modo "$MODO" --run "$RUN" --step "$PASSO_S" \
            --namespace "$NAMESPACE" --context "$CONTEXTO" --port-forward \
            --prometheus-svc "$PROMETHEUS_SVC" --saida "$SAIDA")
    else
        # No Revoada, de dentro do pod export-metrics (docs/avaliacao/exportacao.md)
        local remoto=/work/resultados/$CENARIO/$MODO
        kc exec export-metrics -- mkdir -p "$remoto"
        kc cp "$PASTA_SIM/export_metrics.py" "export-metrics:/work/export_metrics.py"
        kc cp "$PASTA_SIM/load_simulator.py" "export-metrics:/work/load_simulator.py"
        kc cp "$JSON" "export-metrics:$remoto/$RUN.json"
        [[ -f $PASTA_RUN/$RUN-postgres.csv ]] && kc cp "$PASTA_RUN/$RUN-postgres.csv" "export-metrics:$remoto/$RUN-postgres.csv"
        kc exec export-metrics -- uv run -q /work/export_metrics.py --start "$inicio" --end "$fim" \
            --cenario "$CENARIO" --modo "$MODO" --run "$RUN" --step "$PASSO_S" \
            --namespace "$NAMESPACE" --saida /work/resultados
        kc cp "export-metrics:$remoto/$RUN.csv" "$PASTA_RUN/$RUN.csv"
        kc cp "export-metrics:$remoto/$RUN.json" "$PASTA_RUN/$RUN.json"
    fi
}

finalizar_registro() {
    set +e
    local valida
    valida=$([[ $INVALIDA == 0 ]] && echo true || echo false)
    meta '.validade.valida = $v | .fim_script = ($f | tonumber)' --argjson v "$valida" --arg f "$(agora)"
    local destino=$PASTA_RUN
    if [[ $INVALIDA == 1 && $PILOTO == 0 ]]; then
        destino=$PASTA_RUN/invalidas
        mkdir -p "$destino"
        local f
        for f in "$PASTA_RUN/$RUN".* "$PASTA_RUN/$RUN"-*; do
            [[ -e $f ]] && mv "$f" "$destino/"
        done
        JSON=$destino/$RUN.json
    fi
    meta '.pasta_resultados = $p' --arg p "$(realpath --relative-to="$RAIZ" "$destino")"
    if [[ $SEM_DIARIO == 0 ]]; then python3 "$PASTA_SIM/registro_execucao.py" diario "$JSON" "$DIARIO"; fi
    [[ -n ${INFRA_FIM:-} ]] && echo "$INFRA_FIM" > "$SAIDA/.infra-$CAMPANHA.json"
    TERMINOU=1
    if [[ $INVALIDA == 1 ]]; then
        log "execução $RUN INVÁLIDA: $(jq -r '.validade.motivos | join("; ")' "$JSON")"
    else
        log "execução $RUN concluída$([[ $PILOTO == 1 ]] && echo ' (piloto)'): $(realpath --relative-to="$RAIZ" "$destino")/$RUN.*"
    fi
}

# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

INICIOU=1
JOB_PREFIXO="exp-$(tr '[:upper:]' '[:lower:]' <<<"$RUN")-"

disparar() {  # disparar <cronjob>: cria o Job de disparo e devolve o nome em $JOB
    JOB="$JOB_PREFIXO$(date +%s)"
    local t
    t=$(agora)
    kc create job --from="cronjob/$1" "$JOB" >/dev/null
    meta '.jobs += [{nome: $j, cronjob: $c, criado: ($t | tonumber)}]' --arg j "$JOB" --arg c "$1" --arg t "$t"
    log "Job $JOB criado a partir de cronjob/$1"
    T_DISPARO=$t
}

# Contagem do Postgres a cada 15 s durante a execução (t_doc1 e vazão no A)
iniciar_acompanhamento() {
    # setsid: o uv, o Python e os port-forwards ficam num grupo próprio, que
    # recebe o SIGTERM no fim
    (cd "$RAIZ" && exec setsid uv run -q simulador/export_metrics.py --acompanhar --cenario "$CENARIO" \
        --modo "$MODO" --run "$RUN" --port-forward --namespace "$NAMESPACE" --context "$CONTEXTO" \
        --saida "$SAIDA" 9>&-) 2>&1 | sed -u 's/^/  [acompanhar] /' 9>&- &
    local pid=""
    for _ in $(seq 50); do
        pid=$(pgrep -o -f -- "--acompanhar --cenario $CENARIO --modo $MODO --run $RUN " || true)
        [[ -n $pid ]] && break
        sleep 0.1
    done
    if [[ -n $pid ]]; then
        ACOMP_PID=$(ps -o pgid= "$pid" | tr -d ' ')
    else
        anomalia "o acompanhamento do Postgres (export_metrics.py --acompanhar) não iniciou"
    fi
}

if [[ $CENARIO == E2 ]]; then
    # E2: janela de repouso, sem carga. No A, o agendamento de hora em hora
    # do CronJob é reativado durante a janela (cenarios.md, E2)
    INFRA_FIM=""
    if [[ $MODO == A ]]; then
        reativar_cronjob data-processing
        E2_DESSUSPENSO=1
    fi
    marca t0
    log "janela de repouso de ${JANELA_E2_S} s"
    fim_janela=$(( ${INST[t0]%.*} + JANELA_E2_S ))
    max_rep=0
    while (( $(date +%s) < fim_janela )); do
        if [[ $MODO == C ]]; then
            r=$(replicas spec.replicas); r=${r:-0}
            (( r > max_rep )) && max_rep=$r
        fi
        sleep 30
    done
    marca t_fim
    if [[ $MODO == A ]]; then
        kc patch cronjob data-processing -p '{"spec":{"suspend":true}}' >/dev/null
        E2_DESSUSPENSO=0
        hora=$(kc get jobs -o json | jq -r --argjson t0 "${INST[t0]%.*}" '[.items[] | select(.metadata.name | startswith("data-processing-"))
            | select((.metadata.creationTimestamp | fromdate) >= $t0) | .metadata.name] | join(",")')
        meta '.e2 = {jobs_de_hora_cheia: ($j | split(",") | map(select(. != "")))}' --arg j "$hora"
        [[ -n $hora ]] && log "Job(s) de hora cheia na janela: $hora"
    fi
    if [[ $MODO == C ]]; then
        meta '.e2 = {replicas_max_observadas: ($r | tonumber)}' --arg r "$max_rep"
        (( max_rep > 0 )) && anomalia "o extraction-worker teve $max_rep réplica(s) durante a janela de repouso"
    fi
    T_FIM_EXPORT=${INST[t_fim]}
else
    # ---------------------------------------------------------------- carga
    iniciar_acompanhamento
    marca t_carga_inicio
    args=(--profile burst --total "$N" --territory "$TERRITORIO" --seed "$SEED"
          --port-forward --namespace "$NAMESPACE" --context "$CONTEXTO")
    (( CORROMPIDOS > 0 )) && args+=(--corrupt "$CORROMPIDOS")
    set +e
    (cd "$RAIZ" && uv run -q simulador/load_simulator.py "${args[@]}") 2>&1 | tee "$TMP/carga.log"
    status_carga=${PIPESTATUS[0]}
    set -e
    marca t_carga_fim
    registro=$(grep -o 'registro: .*\.json' "$TMP/carga.log" | tail -1 | cut -d' ' -f2- || true)
    if [[ -n $registro && -f $registro ]]; then
        cp "$registro" "$PASTA_RUN/$RUN-carga.json"
        [[ -f ${registro%.json}.csv ]] && cp "${registro%.json}.csv" "$PASTA_RUN/$RUN-carga.csv"
        meta '.carga = $c[0]' --slurpfile c "$registro"
        CORROMPIDOS_IDS=$(jq -r '.corrompidos_ids | join(",")' "$registro")
    fi
    if [[ $status_carga -ne 0 || -z $registro ]]; then
        invalida "o simulador falhou (código $status_carga)"
        restaurar
        INFRA_FIM=$(pods_infra)
        finalizar_registro
        exit 2
    fi

    # ------------------------------------------------------------- disparo
    if [[ $MODO == A ]]; then disparar data-processing; else disparar enqueue-extraction; fi
    marca t0 "$T_DISPARO"
    if [[ $ENQUEUE_SUSPENSO == 1 ]]; then
        reativar_cronjob enqueue-extraction
        ENQUEUE_SUSPENSO=0
    fi
    JOB_PRINCIPAL=$JOB
    JOB_ATUAL=$JOB

    # --------------------------------------------- espera, com a falha do cenário
    limite_s=$(( ${INST[t0]%.*} + TIMEOUT_S ))
    falha_feita=0
    [[ $CENARIO == R1 || $CENARIO == R1a || $CENARIO == R3 ]] || falha_feita=-1  # -1: cenário sem falha
    case $CENARIO in R3) fracao=$FRACAO_FALHA_R3 ;; *) fracao=$FRACAO_FALHA_R1 ;; esac
    alvo_falha=$(awk -v n="$N" -v f="$fracao" 'BEGIN { a = int(n * f + 0.999); print (a < 1 ? 1 : a) }')
    declare -A TAG_GAZ=() TAG_SAIU=() TAG_PROC=()
    ultimo_log=0 processados=0 pendentes=$N fila=0

    pod_vitima() {
        if [[ $MODO == A ]]; then
            kc get pods -l "job-name=$JOB_ATUAL" -o json | jq -r '[.items[] | select(.status.phase == "Running")
                | select(.metadata.deletionTimestamp == null)][0].metadata.name // empty'
        else
            kc get pods -l app=extraction-worker -o json | jq -r '[.items[] | select(.metadata.deletionTimestamp == null)
                | select(([.status.containerStatuses[]? | select(.name == "worker") | .ready] | any))]
                | sort_by(.metadata.creationTimestamp)[0].metadata.name // empty'
        fi
    }

    injetar_falha() {
        case $CENARIO in
        R1|R1a)
            local vitima
            vitima=$(pod_vitima)
            [[ -n $vitima ]] || return 1
            if [[ $MODO != A ]]; then
                [[ $(rq hlen unacked) -ge 1 ]] || return 1
            fi
            local t
            t=$(agora)
            if [[ $CENARIO == R1 ]]; then
                kc delete pod "$vitima" --grace-period=0 --force --wait=false >/dev/null 2>&1 || true
            else
                kc delete pod "$vitima" --wait=false >/dev/null
                # Duração do desligamento: do delete até o pod sumir
                setsid bash -c "kubectl --context '$CONTEXTO' -n '$NAMESPACE' wait --for=delete pod/'$vitima' --timeout=900s >/dev/null 2>&1; date +%s.%3N > '$TMP/t_pod_removido'" 9>&- &
                FALHA_PID=$!
            fi
            marca t_kill "$t"
            if [[ $MODO != A ]]; then
                # Mensagens reservadas logo DEPOIS da falha: o processo morto já
                # não confirma nada, então a dele é a que fica em unacked até o
                # visibility_timeout. Uma foto tirada antes do kill pega a
                # mensagem que o worker ainda confirma em seguida (visto no
                # teste de 24/11/2026)
                sleep 3
                rq hgetall unacked > "$TMP/unacked" || true
            fi
            meta '.falha = {tipo: $tipo, pod: $p, processados_na_falha: ($pr | tonumber), pendentes_na_falha: ($pe | tonumber), fila_na_falha: ($f | tonumber)}' \
                --arg tipo "$([[ $CENARIO == R1 ]] && echo 'delete --grace-period=0 --force' || echo 'delete (SIGTERM)')" \
                --arg p "$vitima" --arg pr "$processados" --arg pe "$pendentes" --arg f "$fila"
            if [[ $MODO != A && -s $TMP/unacked ]]; then
                local tag corpo gid
                while IFS= read -r tag && IFS= read -r corpo; do
                    gid=$(jq -r '.[0].headers.argsrepr // empty' <<<"$corpo" 2>/dev/null | grep -o '[0-9]\+' | head -1 || true)
                    TAG_GAZ[$tag]=${gid:-?}
                done < "$TMP/unacked"
                meta '.falha.unacked_na_falha = ($m | to_entries | map({tag: .key, gazette_id: (.value | tonumber? // .value)}))' \
                    --argjson m "$(for k in "${!TAG_GAZ[@]}"; do printf '%s\n%s\n' "$k" "${TAG_GAZ[$k]}"; done | jq -Rn '[inputs] | [_nwise(2) | {(.[0]): .[1]}] | add // {}')"
                log "mensagens reservadas na falha: ${!TAG_GAZ[*]} (gazettes ${TAG_GAZ[*]})"
            fi
            ;;
        R3)
            # Fora do laço principal: o laço continua contando no Postgres
            setsid bash -c "
                k() { kubectl --context '$CONTEXTO' -n '$NAMESPACE' \"\$@\"; }
                date +%s.%3N > '$TMP/t_down'
                k scale sts opensearch --replicas=0 >/dev/null
                sleep $INDISPONIBILIDADE_R3_S
                date +%s.%3N > '$TMP/t_up_cmd'
                k scale sts opensearch --replicas=1 >/dev/null
                until k get pod opensearch-0 >/dev/null 2>&1; do sleep 2; done
                k wait pod/opensearch-0 --for=condition=Ready --timeout=600s >/dev/null && date +%s.%3N > '$TMP/t_ready'
            " 9>&- &
            FALHA_PID=$!
            log "OpenSearch fora por ${INDISPONIBILIDADE_R3_S} s nominais (processados: $processados)"
            meta '.falha = {tipo: "scale sts opensearch 0 → 1", processados_na_falha: ($pr | tonumber), pendentes_na_falha: ($pe | tonumber)}' \
                --arg pr "$processados" --arg pe "$pendentes"
            ;;
        esac
    }

    acompanhar_falha() {
        local nome
        for nome in t_down t_up_cmd t_ready t_pod_removido; do
            if [[ -z ${INST[$nome]:-} && -s $TMP/$nome ]]; then marca "$nome" "$(cat "$TMP/$nome")"; fi
        done
        if [[ $CENARIO == R1 && $MODO == A && -z ${INST[t_restore]:-} ]]; then
            # No A não há visibility_timeout: a recuperação é o pod novo do Job
            local novo
            novo=$(pod_vitima)
            if [[ -n $novo && $novo != "$(jq -r '.falha.pod' "$JSON")" ]]; then
                marca t_restore
                meta '.falha.pod_novo = $p' --arg p "$novo"
            fi
        fi
        local tag
        for tag in "${!TAG_GAZ[@]}"; do
            if [[ -z ${TAG_SAIU[$tag]:-} && -z $(rq zscore unacked_index "$tag" 2>/dev/null || echo x) ]]; then
                TAG_SAIU[$tag]=$(agora)
                # Já processado quando a mensagem foi devolvida: a entrega nova reprocessa (duplicado)
                TAG_PROC[$tag]=$(pg "SELECT processed FROM gazettes WHERE id = ${TAG_GAZ[$tag]//[^0-9]/0}" 2>/dev/null || echo "?")
            fi
        done
    }

    # R1 (B e C): o diário pode ficar processed=true antes de a mensagem ser
    # confirmada (worker morto entre a gravação e o ack; visto no teste de
    # 24/11/2026). A execução só termina quando toda mensagem reservada na
    # falha saiu de unacked (t_restore) e a devolvida foi consumida (unacked
    # vazio). No C, se as réplicas voltam a 0 com a órfã parada, é resultado
    # (limitação prevista em cenarios.md, R1) e a execução termina
    ORFA_AVISADA=0
    orfas_resolvidas() {
        [[ $CENARIO == R1 && $MODO != A && ${#TAG_GAZ[@]} -gt 0 ]] || return 0
        local tag faltam=0
        for tag in "${!TAG_GAZ[@]}"; do [[ -n ${TAG_SAIU[$tag]:-} ]] || faltam=$((faltam + 1)); done
        if (( faltam > 0 )); then
            if [[ $MODO == C && $(replicas spec.replicas) == 0 ]]; then
                anomalia "fila vazia e réplicas em 0 com $faltam mensagem(ns) órfã(s) ainda em unacked (antes do visibility_timeout): a órfã só volta quando um worker subir (resultado, cenarios.md R1)"
                meta '.falha.orfa_parada = true'
                return 0
            fi
            if [[ $ORFA_AVISADA == 0 ]]; then
                log "pendentes em 0; esperando a mensagem órfã sair de unacked (visibility_timeout de ${VT} s desde t_kill)"
                ORFA_AVISADA=1
            fi
            return 1
        fi
        [[ $(rq hlen unacked 2>/dev/null || echo 1) == 0 ]]
    }

    estado_job() {  # "ativo" | "ok" | "falhou"
        local j
        j=$(kc get job "$1" -o json 2>/dev/null) || { echo ativo; return; }
        jq -r 'if any(.status.conditions[]?; .type == "Complete" and .status == "True") then "ok"
               elif any(.status.conditions[]?; .type == "Failed" and .status == "True") then "falhou"
               else "ativo" end' <<<"$j"
    }

    log "esperando os pendentes chegarem a 0 (timeout ${TIMEOUT_S} s)"
    while true; do
        agora_s=$(date +%s)
        if c=$(contagem 2>/dev/null) && [[ $c == *"|"* ]]; then
            processados=${c%%|*} pendentes=${c##*|}
        fi
        if [[ $MODO != A ]]; then fila=$(rq llen extraction 2>/dev/null || echo "$fila"); fi

        # Instantes observados pelo script (os da análise vêm do Prometheus e do Postgres)
        if [[ -z ${INST[t_rep1_obs]:-} ]]; then
            if [[ $MODO == A ]]; then
                [[ -n $(pod_vitima) ]] && marca t_rep1_obs
            elif [[ $(replicas status.readyReplicas) -ge 1 ]] 2>/dev/null; then
                marca t_rep1_obs
            fi
        fi
        [[ -z ${INST[t_doc1_obs]:-} && $processados -ge 1 ]] && marca t_doc1_obs

        if [[ $falha_feita == 0 && $processados -ge $alvo_falha ]]; then
            if injetar_falha; then falha_feita=1; fi
        fi
        [[ $falha_feita == 1 ]] && acompanhar_falha

        if (( agora_s - ultimo_log >= 60 )); then
            log "processados $processados/$N, pendentes $pendentes$([[ $MODO != A ]] && echo ", fila $fila, réplicas $(r=$(replicas status.readyReplicas); echo "${r:-0}")")"
            ultimo_log=$agora_s
        fi

        if [[ $pendentes == 0 && ( $MODO == A || $fila == 0 ) && $falha_feita != 0 ]]; then
            # R1a/R3: espera também o desligamento/a volta do OpenSearch
            if [[ $CENARIO == R1a && -z ${INST[t_pod_removido]:-} ]] || [[ $CENARIO == R3 && -z ${INST[t_ready]:-} ]]; then
                :
            elif ! orfas_resolvidas; then
                :
            else
                marca t_vazio
                break
            fi
        fi
        if [[ $MODO == A ]]; then
            ej=$(estado_job "$JOB_ATUAL")
            if [[ $ej != ativo && $pendentes != 0 ]]; then
                if [[ $CENARIO == R3 && -z ${INST[t_job2]:-} && $falha_feita == 1 ]]; then
                    # cenarios.md, R3 no A: um segundo Job logo depois do primeiro
                    log "o Job terminou ($ej) com $pendentes pendente(s): criando o segundo Job"
                    meta '.falha.pendentes_depois_do_1o_job = ($p | tonumber)' --arg p "$pendentes"
                    if [[ -z ${INST[t_ready]:-} ]]; then
                        log "esperando o OpenSearch voltar antes do segundo Job"
                        esperar 900 "OpenSearch pronto" test -s "$TMP/t_ready" || true
                        acompanhar_falha
                    fi
                    disparar data-processing
                    marca t_job2 "$T_DISPARO"
                    JOB_ATUAL=$JOB
                    continue
                fi
                anomalia "o Job $JOB_ATUAL terminou ($ej) com $pendentes diário(s) pendente(s)"
                marca t_vazio
                break
            fi
        fi
        if (( agora_s >= limite_s )); then
            invalida "timeout de ${TIMEOUT_S} s estourou (processados $processados/$N, pendentes $pendentes)"
            break
        fi
        sleep 5
    done

    meta '.imagem.usadas = $u' --argjson u "$(imagens_usadas)"
    [[ $falha_feita == 0 ]] && invalida "a falha do cenário não foi injetada (processamento terminou antes de $alvo_falha processados)"

    # ------------------------------------------------- depois de t_vazio
    if [[ -n ${INST[t_vazio]:-} ]]; then
        if [[ $MODO == A ]]; then
            # As métricas qd_* do baseline só vão ao Pushgateway no fim do Job
            # (depois dos temas): exporta até lá, a análise corta em t_vazio
            log "esperando o fim do Job $JOB_ATUAL (temas e push das métricas)"
            job_fim() { [[ $(estado_job "$JOB_ATUAL") != ativo ]]; }
            if esperar "$TIMEOUT_JOB_S" "fim do Job" job_fim; then
                marca t_job_fim
                # O push chega ao Pushgateway no fim do Job; o Prometheus só o
                # vê no próximo scrape. Sem a margem, a exportação perde o resumo
                local_margem=$(( 2 * PASSO_S + 15 ))
                log "margem de ${local_margem} s para o Prometheus raspar o push"
                sleep "$local_margem"
            else
                anomalia "o Job $JOB_ATUAL não terminou em ${TIMEOUT_JOB_S} s depois de t_vazio"
            fi
        elif [[ $MODO == C ]]; then
            log "esperando as réplicas voltarem a 0"
            zero() { [[ $(replicas spec.replicas) == 0 ]]; }
            if esperar "$TIMEOUT_ZERO_S" "réplicas em 0" zero; then
                marca t_zero
            else
                anomalia "as réplicas não voltaram a 0 em ${TIMEOUT_ZERO_S} s depois de t_vazio"
            fi
        else
            # B: o worker é raspado a cada 15 s (30 s no Revoada). Sem a margem,
            # os últimos diários não entram nas séries nem no resumo do export
            local_margem=$(( 2 * PASSO_S + 15 ))
            log "margem de ${local_margem} s para o Prometheus raspar o worker"
            sleep "$local_margem"
        fi
    fi
    [[ -n $FALHA_PID ]] && acompanhar_falha
    marca t_fim

    # Resumo da falha
    if [[ ${#TAG_GAZ[@]} -gt 0 ]]; then
        acompanhar_falha
        saidas=$(for tag in "${!TAG_GAZ[@]}"; do
            printf '%s\t%s\t%s\t%s\n' "$tag" "${TAG_GAZ[$tag]}" "${TAG_SAIU[$tag]:-}" "${TAG_PROC[$tag]:-}"; done | jq -Rn \
            '[inputs | split("\t") | {tag: .[0], gazette_id: (.[1] | tonumber? // .[1]), saiu_de_unacked: (.[2] | tonumber? // null),
              ja_processado_na_saida: (if .[3] == "t" then true elif .[3] == "f" then false else null end)}]')
        ids=$(jq -r '[.[].gazette_id | numbers] | join(",")' <<<"$saidas")
        if [[ -n $ids ]]; then
            processados_ids=$(pg "SELECT id FROM gazettes WHERE id IN ($ids) AND processed" | paste -sd, -)
        fi
        meta '.falha.mensagens = $s | .falha.gazettes_processadas_no_fim = ($p | split(",") | map(select(. != "") | tonumber))' \
            --argjson s "$saidas" --arg p "${processados_ids:-}"
        # A órfã é a última a sair de unacked (≈ t_kill + visibility_timeout no R1)
        orfa=$(jq -r 'map(select(.saiu_de_unacked != null)) | max_by(.saiu_de_unacked) // empty | .saiu_de_unacked' <<<"$saidas")
        if [[ $CENARIO == R1 && -n $orfa ]]; then
            marca t_restore "$orfa"
            log "t_restore − t_kill = $(awk -v a="$orfa" -v b="${INST[t_kill]}" 'BEGIN { printf "%.0f", a - b }') s (análise: conferir com o log dos workers)"
        fi
    fi
    if [[ -n ${INST[t_down]:-} && -n ${INST[t_ready]:-} ]]; then
        meta '.falha.indisponibilidade_real_s = ($r - $d)' --argjson d "${INST[t_down]}" --argjson r "${INST[t_ready]}"
    elif [[ $CENARIO == R3 && $falha_feita == 1 ]]; then
        invalida "o OpenSearch não voltou a ficar pronto"
    fi
    if [[ -n ${INST[t_pod_removido]:-} ]]; then
        meta '.falha.desligamento_s = ($r - $k)' --argjson k "${INST[t_kill]}" --argjson r "${INST[t_pod_removido]}"
    fi

    T_FIM_EXPORT=${INST[t_fim]}
fi

# Contagem do Postgres e configurações temporárias
restaurar

# ---------------------------------------------------------------------------
# Validade e exportação
# ---------------------------------------------------------------------------

INFRA_FIM=$(pods_infra)
meta '.infra_fim = $i' --argjson i "$INFRA_FIM"
reiniciados=$(jq -r --argjson ini "$(jq '.infra_inicio' "$JSON")" --arg c "$CENARIO" 'to_entries[]
    | select($ini[.key] == null or $ini[.key].uid != .value.uid or $ini[.key].restarts != .value.restarts)
    | select(($c == "R3" and (.key | startswith("opensearch"))) | not)
    | "\(.key)\(if .value.oom then " (OOMKilled)" else "" end)"' <<<"$INFRA_FIM" | paste -sd, -)
sumidos=$(jq -r --argjson fim "$INFRA_FIM" --arg c "$CENARIO" '.infra_inicio | keys[]
    | select($fim[.] == null) | select(($c == "R3" and startswith("opensearch")) | not)' "$JSON" | paste -sd, -)
[[ -n $reiniciados ]] && invalida "pod(s) de infraestrutura reiniciado(s) ou recriado(s): $reiniciados"
[[ -n $sumidos ]] && invalida "pod(s) de infraestrutura sumiram: $sumidos"

if [[ -n $IMAGEM_DIGEST ]]; then
    outras=$(jq -r --arg d "$IMAGEM_DIGEST" '[.imagem.usadas[]? | select(.digest != $d) | .pod] | join(",")' "$JSON")
    [[ -n $outras ]] && invalida "pod(s) com outra imagem: $outras"
fi

if exportar "${INST[t0]}" "$T_FIM_EXPORT" || { log "export falhou; tentando de novo em 30 s"; sleep 30; exportar "${INST[t0]}" "$T_FIM_EXPORT"; }; then
    if ! python3 "$PASTA_SIM/registro_execucao.py" lacunas "$PASTA_RUN/$RUN.csv" "$JSON"; then
        invalida "o Prometheus ficou mais de 1 min sem raspar um alvo usado pelas medidas (ver .lacunas no .json)"
    fi
    pend_fim=$(jq -r '.export.postgres_fim.pendentes_sem_dlq // empty' "$JSON")
    dlq_fim=$(jq -r '.export.dlq.tamanho // empty' "$JSON")
    log "no fim: pendentes fora da DLQ = ${pend_fim:-?}, DLQ = ${dlq_fim:-—}"
    if [[ $CENARIO == R2 || $CENARIO == M1 ]] && [[ $MODO != A && -n $dlq_fim && $dlq_fim != "$CORROMPIDOS" ]]; then
        anomalia "DLQ com $dlq_fim item(ns), esperado $CORROMPIDOS (resultado da arquitetura)"
    fi
else
    invalida "export_metrics.py falhou duas vezes: séries não salvas"
fi

finalizar_registro
[[ $INVALIDA == 1 && $PILOTO == 0 ]] && exit 2
exit 0
