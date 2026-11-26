#!/usr/bin/env bash
# Campanha de execuções (E-2, issue #33): chama o run_experiment.sh para cada
# execução, na ordem do protocolo (docs/avaliacao/protocolo.md, "Repetições e
# ordem"), refaz uma execução inválida na mesma posição e retoma do meio.
#
#   simulador/run_campaign.sh <K|R> [bloco ...] [opções]
#   simulador/run_campaign.sh K piloto        # E1 nos três modos, fora dos resultados
#   simulador/run_campaign.sh K               # todos os blocos depois do piloto
#   simulador/run_campaign.sh K E1 R1         # só esses blocos
#   simulador/run_campaign.sh K --listar      # plano e situação de cada execução
#
# Blocos, sempre entre cenários (nunca dentro de um), na ordem do protocolo:
#   K: piloto | E1 | R1 | robustez (R1a, R2, R3) | E2
#   R: piloto | E1 | E2 | robustez (R1a, R2, R3; "se couberem no dia")
# O M1 não entra: roda à parte, com as pessoas participantes
# (run_experiment.sh M1 <A|C> M1-<modo>-<n>). O D5 (#31) também roda à parte
# (run_experiment.sh E1 C D5... --teto N).
#
# Dentro de um cenário, os modos giram por repetição (quadrado latino):
#   k=1: A, B, C   k=2: B, C, A   k=3: C, A, B
# 3 repetições por cenário × modo, 1 no E2.
#
# Opções:
#   --listar        mostra o plano com a situação de cada posição e sai
#   --dry-run       mostra o que rodaria, sem rodar
#   --ate <run>     para depois dessa execução (ex.: --ate E1-C-1)
#   --             o resto vai para cada run_experiment.sh (ex.: -- --permitir-sujo)
#
# Situação: resultados/campanha-<K|R>.tsv, uma linha por tentativa (posição,
# execução, código de saída, início e fim). Uma posição com uma execução
# válida (código 0) é pulada, então rodar de novo retoma de onde parou.
# Inválida (código 2): refeita logo, na mesma posição, com a próxima letra
# (E1-C-2b). Mais de 3 inválidas num mesmo cenário × modo, ou uma execução que
# não rodou (código 1: checklist ou ambiente), param a campanha.

set -Eeuo pipefail

PASTA_SIM=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RAIZ=$(dirname "$PASTA_SIM")

uso() { sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }

[[ $# -ge 1 ]] || uso
CAMPANHA=$1; shift
[[ $CAMPANHA == K || $CAMPANHA == R ]] || { echo "campanha inválida: $CAMPANHA (K ou R)" >&2; exit 1; }
# shellcheck source=campanhas/K.env
source "$PASTA_SIM/campanhas/$CAMPANHA.env"

BLOCOS=() LISTAR=0 DRY=0 ATE="" REPASSE=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --listar) LISTAR=1 ;;
        --dry-run) DRY=1 ;;
        --ate) ATE=$2; shift ;;
        --) shift; REPASSE=("$@"); break ;;
        -h|--help) uso ;;
        -*) echo "opção desconhecida: $1" >&2; uso ;;
        *) BLOCOS+=("$1") ;;
    esac
    shift
done

if [[ $CAMPANHA == K ]]; then
    TODOS=(E1 R1 robustez E2)
else
    TODOS=(E1 E2 robustez)
fi
if [[ ${#BLOCOS[@]} -eq 0 ]]; then
    if [[ $LISTAR == 1 ]]; then BLOCOS=(piloto "${TODOS[@]}"); else BLOCOS=("${TODOS[@]}"); fi
fi
for b in "${BLOCOS[@]}"; do
    [[ $b == piloto || " ${TODOS[*]} " == *" $b "* ]] || { echo "bloco inválido para a campanha $CAMPANHA: $b" >&2; exit 1; }
done

ESTADO=$RAIZ/resultados/campanha-$CAMPANHA.tsv
[[ -f $ESTADO ]] || printf 'posicao\tbloco\tbase\trun\tcodigo\tinicio\tfim\n' > "$ESTADO"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

# ---------------------------------------------------------------------------
# Plano: linhas "posição bloco cenário modo base"
# ---------------------------------------------------------------------------

ordem() {  # modos da repetição k (quadrado latino)
    case $1 in 1) echo A B C ;; 2) echo B C A ;; 3) echo C A B ;; esac
}

plano() {
    local bloco cenarios c k m reps pos
    for bloco in "${BLOCOS[@]}"; do
        case $bloco in
            piloto) for m in A B C; do echo "piloto-$m piloto E1 $m E1-$m-piloto"; done; continue ;;
            robustez) cenarios=(R1a R2 R3) ;;
            *) cenarios=("$bloco") ;;
        esac
        for c in "${cenarios[@]}"; do
            reps=3; [[ $c == E2 ]] && reps=1
            for k in $(seq "$reps"); do
                for m in $(ordem "$k"); do
                    pos="$c-$m-$k"
                    echo "$pos $bloco $c $m $pos"
                done
            done
        done
    done
}

tentativas() {  # tentativas <base> <codigo>: quantas linhas da posição com o código
    awk -F'\t' -v b="$1" -v c="$2" 'NR > 1 && $3 == b && $5 == c' "$ESTADO" | wc -l
}
invalidas_celula() {  # inválidas do mesmo cenário × modo (fora o piloto)
    awk -F'\t' -v p="^$1-$2-[0-9]" 'NR > 1 && $3 ~ p && $5 == 2' "$ESTADO" | wc -l
}
letra() {  # 0 → "", 1 → b, 2 → c...
    (( $1 == 0 )) && return
    printf "\\$(printf '%03o' $((97 + $1)))"
}

if [[ $LISTAR == 1 ]]; then
    printf '%-14s %-9s %-14s %s\n' POSIÇÃO BLOCO SITUAÇÃO TENTATIVAS
    while read -r pos bloco c m base; do
        situacao=pendente
        [[ $(tentativas "$base" 0) -gt 0 ]] && situacao=feita
        runs=$(awk -F'\t' -v b="$base" 'NR > 1 && $3 == b { printf "%s(%s) ", $4, $5 }' "$ESTADO")
        printf '%-14s %-9s %-14s %s\n' "$pos" "$bloco" "$situacao" "$runs"
    done < <(plano)
    exit 0
fi

# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

mapfile -t PLANO < <(plano)
total=${#PLANO[@]}
feitas=0
for linha in "${PLANO[@]}"; do
    read -r _ _ _ _ base <<<"$linha"
    [[ $(tentativas "$base" 0) -gt 0 ]] && feitas=$((feitas + 1))
done
log "campanha $CAMPANHA, blocos: ${BLOCOS[*]}; $feitas de $total execuções já feitas (orçamento da campanha inteira: ${ORCAMENTO_H} h)"
primeira=$(awk -F'\t' 'NR == 2 { print $6 }' "$ESTADO")
[[ -n $primeira ]] && log "primeira execução da campanha em $primeira"

inicio_sessao=$(date +%s)
duracoes=()
for linha in "${PLANO[@]}"; do
    read -r pos bloco cenario modo base <<<"$linha"
    if [[ $(tentativas "$base" 0) -gt 0 ]]; then
        continue
    fi
    tentativas_sessao=0
    while true; do
        inval=$(tentativas "$base" 2)
        # O piloto não entra na conta das 3 inválidas por célula, mas também não
        # pode repetir sem fim: para depois de 3 inválidas seguidas nesta sessão
        if [[ $bloco == piloto ]] && (( tentativas_sessao >= 3 )); then
            log "PARADA: 3 tentativas inválidas seguidas de $base nesta sessão; investigar antes de continuar"
            exit 1
        fi
        tentativas_sessao=$((tentativas_sessao + 1))
        if [[ $bloco != piloto && $(invalidas_celula "$cenario" "$modo") -gt 3 ]]; then
            log "PARADA: mais de 3 execuções inválidas em $cenario × $modo; investigar antes de continuar (protocolo, 'Validade')"
            exit 1
        fi
        run="$base$(letra "$inval")"
        args=("$cenario" "$modo" "$run" --campanha "$CAMPANHA")
        [[ $bloco == piloto ]] && args+=(--piloto)
        args+=("${REPASSE[@]}")
        restantes=$(( total - feitas ))
        log "── $run ($((feitas + 1))/$total, bloco $bloco)"
        if [[ $DRY == 1 ]]; then
            echo "  simulador/run_experiment.sh ${args[*]}"
            feitas=$((feitas + 1))
            break
        fi
        t_ini=$(date +%s)
        set +e
        "$PASTA_SIM/run_experiment.sh" "${args[@]}"
        codigo=$?
        set -e
        t_fim=$(date +%s)
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$pos" "$bloco" "$base" "$run" "$codigo" \
            "$(date -d "@$t_ini" '+%F %T')" "$(date -d "@$t_fim" '+%F %T')" >> "$ESTADO"
        duracoes+=($((t_fim - t_ini)))
        case $codigo in
            0)
                feitas=$((feitas + 1))
                soma=0; for d in "${duracoes[@]}"; do soma=$((soma + d)); done
                media=$((soma / ${#duracoes[@]}))
                decorrido=$(( t_fim - inicio_sessao ))
                log "$run ok em $(( (t_fim - t_ini) / 60 )) min; nesta sessão: $(( decorrido / 60 )) min, " \
                    "restam $((restantes - 1)) execução(ões) (~$(( media * (restantes - 1) / 60 )) min pela média desta sessão)"
                if [[ -n $primeira ]]; then
                    desde=$(( t_fim - $(date -d "$primeira" +%s) ))
                    awk -v d="$desde" -v l="$LIMITE_H" 'BEGIN { exit !(d > l * 3600) }' && \
                        log "aviso: $(( desde / 3600 )) h desde a primeira execução da campanha (limite do protocolo: ${LIMITE_H} h); se a campanha foi dividida em blocos, registrar em 'Desvios do protocolo'"
                fi
                break
                ;;
            2)
                log "$run inválida: refazendo na mesma posição"
                ;;
            *)
                log "PARADA: $run não rodou (código $codigo: checklist ou ambiente). Veja resultados/<campanha>/nao-executadas/ e rode de novo para retomar"
                exit 1
                ;;
        esac
    done
    [[ -z $primeira ]] && primeira=$(awk -F'\t' 'NR == 2 { print $6 }' "$ESTADO")
    if [[ -n $ATE && $base == "$ATE"* ]]; then
        log "parando depois de $ATE (--ate)"
        exit 0
    fi
done
log "blocos ${BLOCOS[*]} concluídos: $feitas de $total execuções"
[[ " ${BLOCOS[*]} " == *" piloto "* ]] && log "depois do piloto: fixar IMAGEM_DIGEST, TIMEOUT_S e N em simulador/campanhas/$CAMPANHA.env e no protocolo"
exit 0
