"""Cold start de cada réplica do extraction-worker numa execução do modo C.

Lê do Prometheus, por pod, os instantes do kube-state-metrics (criação,
agendamento, início do contêiner `worker`, Ready) e o fim do primeiro diário,
que é a série `qd_gazettes_processed_created`: o contador tem rótulos, e o
prometheus_client só cria a série filha no primeiro `.labels()`, chamado no
fim do processamento do diário (`monitoring/metrics.py` do data-processing).

O Tika é native sidecar com `startupProbe` (ADR-0010), então o contêiner
`worker` só inicia depois de a JVM do Tika responder: "criado → worker"
inclui agendamento, criação dos contêineres e a JVM do Tika (com a
granularidade de 5 s da probe); "worker → 1º diário" inclui a inicialização
do worker e o processamento do próprio diário.

Roda onde o Prometheus é alcançável (no Revoada, dentro do pod
export-metrics). O Prometheus do Revoada guarda só 1 dia.

Uso:
    python3 cold_start.py <run.json> [<run.json> ...] > cold-start.csv
    (os .json das execuções, para tirar t0 e t_fim e o teto)
"""

import csv
import json
import os
import sys
import urllib.parse
import urllib.request

PROMETHEUS = os.environ.get(
    "PROMETHEUS_URL", "http://prometheus-k8s.monitoring.svc:9090"
)
NAMESPACE = os.environ.get("NAMESPACE", "querido-diario-tcc")
SELETOR = f'{{namespace="{NAMESPACE}",pod=~"extraction-worker.*"}}'

CAMPOS = [
    "execucao", "teto", "ordem", "pod", "t0", "criado", "agendado",
    "worker_iniciado", "pronto", "primeiro_diario_fim",
    "t0_ate_criado_s", "criado_ate_worker_s", "worker_ate_1o_diario_s",
    "cold_start_s", "t0_ate_1o_diario_s",
]


def consulta(expr, instante):
    url = f"{PROMETHEUS}/api/v1/query?" + urllib.parse.urlencode(
        {"query": expr, "time": instante}
    )
    with urllib.request.urlopen(url, timeout=60) as resposta:
        return json.load(resposta)["data"]["result"]


def por_pod(metrica, instante, janela, agregacao="last_over_time", filtro=None):
    valores = {}
    for serie in consulta(f"{agregacao}({metrica}{SELETOR}[{janela}])", instante):
        rotulos = serie["metric"]
        if filtro and not filtro(rotulos):
            continue
        valores[rotulos["pod"]] = float(serie["value"][1])
    return valores


def linhas_da_execucao(caminho):
    with open(caminho) as arquivo:
        execucao = json.load(arquivo)
    t0 = execucao["instantes"]["t0"]
    t_fim = execucao["instantes"]["t_fim"]
    instante = t_fim + 60
    janela = f"{int(instante - t0 + 120)}s"

    criado = por_pod("kube_pod_created", instante, janela)
    agendado = por_pod("kube_pod_status_scheduled_time", instante, janela)
    worker = por_pod(
        "kube_pod_container_state_started", instante, janela,
        filtro=lambda r: r.get("container") == "worker",
    )
    pronto = por_pod("kube_pod_status_ready_time", instante, janela)
    primeiro = por_pod(
        "qd_gazettes_processed_created", instante, janela,
        agregacao="min_over_time",
    )

    pods = sorted(
        (p for p, t in criado.items() if t0 - 60 <= t <= t_fim),
        key=lambda p: criado[p],
    )
    for ordem, pod in enumerate(pods, start=1):
        c, w, f = criado[pod], worker.get(pod), primeiro.get(pod)
        yield {
            "execucao": execucao["run"],
            "teto": execucao["parametros"]["teto"],
            "ordem": ordem,
            "pod": pod,
            "t0": f"{t0:.3f}",
            "criado": f"{c:.0f}",
            "agendado": f"{agendado[pod]:.0f}" if pod in agendado else "",
            "worker_iniciado": f"{w:.0f}" if w else "",
            "pronto": f"{pronto[pod]:.0f}" if pod in pronto else "",
            "primeiro_diario_fim": f"{f:.3f}" if f else "",
            "t0_ate_criado_s": f"{c - t0:.1f}",
            "criado_ate_worker_s": f"{w - c:.0f}" if w else "",
            "worker_ate_1o_diario_s": f"{f - w:.1f}" if f and w else "",
            "cold_start_s": f"{f - c:.1f}" if f else "",
            "t0_ate_1o_diario_s": f"{f - t0:.1f}" if f else "",
        }


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    saida = csv.DictWriter(sys.stdout, fieldnames=CAMPOS)
    saida.writeheader()
    for caminho in sys.argv[1:]:
        saida.writerows(linhas_da_execucao(caminho))


if __name__ == "__main__":
    main()
