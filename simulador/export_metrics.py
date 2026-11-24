#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg2-binary", "redis", "requests"]
# ///
"""
Exportação dos resultados de uma execução do experimento (D4, issue #30).

    python simulador/export_metrics.py --start 1764019200 --end 1764021000 \\
        --cenario E1 --modo C --run E1-C-1 --port-forward

    # durante a execução (modo A), contagem do Postgres a cada 15 s, até Ctrl+C/SIGTERM
    python simulador/export_metrics.py --acompanhar --cenario E1 --modo A --run E1-A-1 \\
        --port-forward

Roda ao fim de CADA execução (o Prometheus do Revoada guarda só 1 dia) e grava,
em resultados/<cenario>/<modo>/ (ou .../invalidas/ com --invalida):

- <run>.csv: séries do Prometheus entre --start e --end, via /api/v1/query_range,
  em formato longo: timestamp, instante, serie, rotulos, valor. As séries são as
  do dashboard do pipeline (B3) mais as que as medidas e a validade precisam
  (series(), abaixo). Com --acompanhar rodando durante a execução, o CSV também
  recebe as séries pg_processados, pg_pendentes e pg_pendentes_sem_dlq;
- <run>.json: a chave "export" (parâmetros, resumo do Prometheus no intervalo,
  contagens finais do Postgres e conteúdo da DLQ). Se o .json já existir
  (gravado pelo run_experiment.sh, #33), as outras chaves são preservadas.

Passo do query_range: 15 s na campanha K e 30 s na R (--step). Janela do rate():
4 × o passo, com mínimo de 1 min. Formato dos arquivos: docs/avaliacao/exportacao.md.

Conexões (variáveis de ambiente > --port-forward > padrões do kind):
    QD_EXPORT_PROMETHEUS_URL    http://localhost:9091 (port-forward do Prometheus do kind)
                                No Revoada, de dentro do namespace:
                                http://prometheus-k8s.monitoring.svc:9090, ou o
                                proxy do Grafana: http://grafana.monitoring.svc:3000
                                /api/datasources/proxy/uid/<uid do datasource>
    QD_EXPORT_PROMETHEUS_USER / QD_EXPORT_PROMETHEUS_PASSWORD   basic auth (Grafana)
    QD_SIM_DB_URL               o mesmo do simulador (Postgres)
    QD_EXPORT_REDIS_URL         redis://localhost:6380/0 (redis-queue; só B e C)

--port-forward abre kubectl port-forward para o Prometheus (--prometheus-svc,
padrão monitoring/monitoring-kube-prometheus-prometheus, o do kind), o
postgres-rw e o redis-queue do --namespace, e lê as credenciais do Postgres do
Secret app-secret, como o simulador. Uma conexão cuja variável já está definida
não é encaminhada. No Revoada, use o pod de simulador/k8s/export-metrics-pod.yaml.

Dependências: psycopg2-binary, redis e requests (`uv run simulador/export_metrics.py`).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import signal
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from load_simulator import SIM_URL, _segredo, conectar_db, log, port_forward

RAIZ = Path(__file__).resolve().parent.parent
RESULTADOS = RAIZ / "resultados"
DLQ = "qd:extraction:dead"
FILA = "extraction"
MODOS = ("A", "B", "C")

# Portas locais dos port-forwards (diferentes das do simulador, que pode estar
# com os dele abertos)
PORTA_PROMETHEUS = 9091
PORTA_POSTGRES = 5435
PORTA_POSTGRES_ACOMPANHAR = 5436
PORTA_REDIS = 6380
PORTA_REDIS_ACOMPANHAR = 6381


# ---------------------------------------------------------------------------
# Séries
# ---------------------------------------------------------------------------
# {NS}: namespace da aplicação; {QD}: seletor das métricas qd_* do modo (no A,
# o grupo do Pushgateway; no B e no C, os workers do namespace); {W}: janela do
# rate(). Cada série vira linhas "serie,rotulos,valor" no CSV.


def seletor_qd(modo: str, ns: str) -> str:
    if modo == "A":
        return 'job="data-processing"'
    return f'mode="queue", namespace="{ns}"'


def series(modo: str) -> dict:
    """nome → PromQL (com {NS}, {QD} e {W} a substituir)"""
    qd = {}
    for nome, metrica in (("tempo_diario", "qd_gazette_processing_seconds"),
                          ("coleta_indexado", "qd_scrape_to_index_seconds")):
        for q in (0.5, 0.95):
            if modo == "A":
                # Pushgateway: o valor é o histograma da última execução, não um contador contínuo
                expr = f"histogram_quantile({q}, sum by (le) ({metrica}_bucket{{{{QD}}}}))"
            else:
                expr = f"histogram_quantile({q}, sum by (le) (rate({metrica}_bucket{{{{QD}}}}[{{W}}])))"
            qd[f"{nome}_p{round(q * 100)}_s"] = expr

    return {
        # Aplicação (linhas 1 e 2 do dashboard)
        "processados": "sum by (status) (qd_gazettes_processed_total{{QD}})",
        "vazao_por_min": "60 * sum by (status) (rate(qd_gazettes_processed_total{{QD}}[{W}]))",
        **qd,
        "push_time_s": 'max(push_time_seconds{job="data-processing"})',
        # Fila (linha 3)
        "fila": f'sum(redis_key_size{{namespace="{{NS}}", key="{FILA}"}})',
        "dlq": f'sum(redis_key_size{{namespace="{{NS}}", key="{DLQ}"}})',
        "replicas_desejadas": 'max(kube_deployment_spec_replicas{namespace="{NS}", deployment="extraction-worker"})',
        "replicas": 'max(kube_deployment_status_replicas{namespace="{NS}", deployment="extraction-worker"})',
        "replicas_disponiveis": 'max(kube_deployment_status_replicas_available{namespace="{NS}", deployment="extraction-worker"})',
        # Recursos por pod (linha 4) e reservas (E2)
        "cpu_cores": 'sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="{NS}", container!="", image!=""}[{W}]))',
        "memoria_bytes": 'sum by (pod) (container_memory_working_set_bytes{namespace="{NS}", container!="", image!=""})',
        "request_cpu_cores": 'sum by (pod) (kube_pod_container_resource_requests{namespace="{NS}", resource="cpu"})',
        "request_memoria_bytes": 'sum by (pod) (kube_pod_container_resource_requests{namespace="{NS}", resource="memory"})',
        # Instantes (t_rep1 no A) e validade da execução
        "pod_fase": 'sum by (pod, phase) (kube_pod_status_phase{namespace="{NS}"}) > 0',
        "reinicios": 'sum by (pod, container) (kube_pod_container_status_restarts_total{namespace="{NS}"})',
        "oomkilled": 'sum by (pod, container) (kube_pod_container_status_last_terminated_reason{namespace="{NS}", reason="OOMKilled"}) > 0',
        "alvo_up": 'max by (job) (up{namespace="{NS}"} or up{job=~".*pushgateway.*"})',
    }


def montar(expr: str, ns: str, qd: str, janela: str) -> str:
    return expr.replace("{NS}", ns).replace("{QD}", qd).replace("{W}", janela)


# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------


class Prometheus:
    def __init__(self, url: str, usuario: str | None, senha: str | None):
        import requests

        self.url = url.rstrip("/")
        self.sessao = requests.Session()
        if usuario:
            self.sessao.auth = (usuario, senha or "")

    def _get(self, caminho: str, params: dict) -> list:
        resposta = self.sessao.get(f"{self.url}{caminho}", params=params, timeout=120)
        try:
            corpo = resposta.json()
        except ValueError:
            sys.exit(f"Prometheus respondeu {resposta.status_code} sem JSON em {caminho}: "
                     f"{resposta.text[:300]}")
        if corpo.get("status") != "success":
            raise RuntimeError(f"{corpo.get('errorType')}: {corpo.get('error')} ({params.get('query')})")
        return corpo["data"]["result"]

    def faixa(self, expr: str, inicio: float, fim: float, passo: int) -> list:
        return self._get("/api/v1/query_range",
                         {"query": expr, "start": inicio, "end": fim, "step": passo})

    def instante(self, expr: str, quando: float) -> list:
        return self._get("/api/v1/query", {"query": expr, "time": quando})

    def conferir(self) -> None:
        try:
            self.instante("vector(1)", time.time())
        except Exception as erro:  # noqa: BLE001 - qualquer falha aqui impede a exportação
            sys.exit(f"Prometheus inacessível em {self.url}: {erro}")


def rotulos(metrica: dict) -> str:
    return ";".join(f"{k}={v}" for k, v in sorted(metrica.items()) if k != "__name__")


def valor(texto: str) -> float | None:
    numero = float(texto)
    return None if math.isnan(numero) or math.isinf(numero) else numero


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def exportar_series(prom, modo, ns, inicio, fim, passo, janela) -> tuple[list, dict]:
    """Linhas do CSV e quantos pontos cada série gerou (None se a consulta falhou)"""
    linhas, contagem = [], {}
    qd = seletor_qd(modo, ns)
    for nome, modelo in series(modo).items():
        expr = montar(modelo, ns, qd, janela)
        try:
            resultado = prom.faixa(expr, inicio, fim, passo)
        except RuntimeError as erro:
            log(f"aviso: série {nome} falhou: {erro}")
            contagem[nome] = None
            continue
        n = 0
        for serie in resultado:
            r = rotulos(serie["metric"])
            for ts, texto in serie["values"]:
                v = valor(texto)
                if v is None:
                    continue
                linhas.append((float(ts), nome, r, v))
                n += 1
        contagem[nome] = n
    return linhas, contagem


def _agrupamento(metrica: str) -> str:
    if metrica.endswith("_bucket"):
        return " by (le)"
    if metrica == "qd_gazettes_processed_total":
        return " by (status)"
    return ""


def _delta_na_execucao(metrica: str, qd: str, duracao: int) -> str:
    """
    Quanto um contador (ou bucket) cresceu entre o início e o fim. Por série
    (cada pod é uma série), o máximo no intervalo menos o valor no início; uma
    série que nasceu durante a execução (pod novo) conta inteira. Não usa
    increase(): ele perde as primeiras observações de um pod novo, porque o
    contador só aparece no /metrics depois do 1º diário. Um contêiner que
    reinicia dentro do mesmo pod (OOMKill) zera o contador e quebra a conta.
    """
    por = _agrupamento(metrica)
    maximo = f"sum{por} (max_over_time({metrica}{{{qd}}}[{duracao}s]))"
    no_inicio = f"sum{por} ({metrica}{{{qd}}} offset {duracao}s)"
    return f"{maximo} - ({no_inicio} or {maximo} * 0)"


def resumo(prom, modo, ns, inicio, fim) -> dict:
    """Contagens e percentis da execução inteira, por consultas instantâneas em --end"""
    qd = seletor_qd(modo, ns)
    duracao = max(int(round(fim - inicio)), 1)
    saida = {"observacao": None}

    if modo == "A":
        # O Pushgateway guarda a última execução inteira; só vale se o push é desta execução
        push = prom.instante('max(push_time_seconds{job="data-processing"})', fim)
        momento = float(push[0]["value"][1]) if push else None
        saida["push_time"] = iso(momento) if momento else None
        if not momento or momento < inicio:
            saida["observacao"] = ("sem push do CronJob nesta execução (Job morto ou não "
                                   "terminou): use as contagens do Postgres")
            return saida

        def expr(metrica):
            return f"sum{_agrupamento(metrica)} ({metrica}{{{qd}}})"
    else:
        def expr(metrica):
            return _delta_na_execucao(metrica, qd, duracao)

    def consultar(e):
        return prom.instante(e, fim)

    saida["processados_por_status"] = {
        s["metric"].get("status", ""): valor(s["value"][1])
        for s in consultar(expr("qd_gazettes_processed_total"))
    }
    for nome, metrica in (("tempo_diario_s", "qd_gazette_processing_seconds"),
                          ("coleta_indexado_s", "qd_scrape_to_index_seconds")):
        buckets = {s["metric"]["le"]: valor(s["value"][1]) for s in consultar(expr(f"{metrica}_bucket"))}
        soma = consultar(expr(f"{metrica}_sum"))
        cont = consultar(expr(f"{metrica}_count"))
        h = {
            "buckets": dict(sorted(buckets.items(), key=lambda kv: float(kv[0]))),
            "soma": valor(soma[0]["value"][1]) if soma else None,
            "contagem": valor(cont[0]["value"][1]) if cont else None,
        }
        for q in (0.5, 0.95, 0.99):
            r = consultar(f"histogram_quantile({q}, {expr(f'{metrica}_bucket')})")
            h[f"p{round(q * 100)}"] = valor(r[0]["value"][1]) if r else None
        h["media"] = h["soma"] / h["contagem"] if h["soma"] is not None and h["contagem"] else None
        saida[nome] = h
    return saida


# ---------------------------------------------------------------------------
# Postgres e Redis
# ---------------------------------------------------------------------------


def ids_dlq(entradas: list) -> list:
    ids = []
    for e in entradas:
        try:
            ids.append(int(e["id"]))
        except (KeyError, TypeError, ValueError):
            pass
    return ids


def contar_postgres(conexao, dlq: list) -> dict:
    with conexao.cursor() as cur:
        cur.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE processed),
                   count(*) FILTER (WHERE NOT processed),
                   count(*) FILTER (WHERE NOT processed AND NOT (id = ANY(%s::bigint[])))
            FROM gazettes WHERE file_url LIKE %s
            """,
            (dlq, f"{SIM_URL}%"),
        )
        total, processados, pendentes, sem_dlq = cur.fetchone()
    return {"sinteticos": total, "processados": processados,
            "pendentes": pendentes, "pendentes_sem_dlq": sem_dlq}


def ler_dlq(url: str) -> list:
    import redis

    cliente = redis.Redis.from_url(url, decode_responses=True, socket_timeout=10)
    entradas = []
    for bruto in cliente.lrange(DLQ, 0, -1):
        try:
            entradas.append(json.loads(bruto))
        except ValueError:
            entradas.append({"bruto": bruto})
    return entradas


# ---------------------------------------------------------------------------
# Conexões
# ---------------------------------------------------------------------------


def conexoes(args, pilha: ExitStack, porta_pg: int, porta_redis: int,
             prometheus=True, redis_=True) -> dict:
    env = os.environ
    conf = {
        "prometheus": env.get("QD_EXPORT_PROMETHEUS_URL"),
        "db_url": env.get("QD_SIM_DB_URL"),
        "redis": env.get("QD_EXPORT_REDIS_URL"),
    }
    if args.port_forward:
        if not shutil.which("kubectl"):
            sys.exit("--port-forward precisa do kubectl")
        ns, ctx = args.namespace, args.context
        if prometheus and not conf["prometheus"]:
            ns_prom, svc = args.prometheus_svc.split("/", 1)
            pilha.enter_context(port_forward(svc, 9090, PORTA_PROMETHEUS, ns_prom, ctx))
            conf["prometheus"] = f"http://localhost:{PORTA_PROMETHEUS}"
        if not conf["db_url"]:
            pilha.enter_context(port_forward("postgres-rw", 5432, porta_pg, ns, ctx))
            usuario, senha = _segredo("QD_DATA_DB_USER", ns, ctx), _segredo("QD_DATA_DB_PASSWORD", ns, ctx)
            conf["db_url"] = f"postgresql://{usuario}:{senha}@localhost:{porta_pg}/queridodiario"
        if redis_ and not conf["redis"]:
            pilha.enter_context(port_forward("redis-queue", 6379, porta_redis, ns, ctx))
            conf["redis"] = f"redis://localhost:{porta_redis}/0"

    conf["prometheus"] = conf["prometheus"] or f"http://localhost:{PORTA_PROMETHEUS}"
    conf["db_url"] = conf["db_url"] or f"postgresql://admin:admin@localhost:{porta_pg}/queridodiario"
    conf["redis"] = conf["redis"] or f"redis://localhost:{porta_redis}/0"
    return conf


# ---------------------------------------------------------------------------
# Ações
# ---------------------------------------------------------------------------


def pasta_saida(args) -> Path:
    pasta = Path(args.saida) / args.cenario / args.modo
    if args.invalida:
        pasta = pasta / "invalidas"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def acompanhar(args) -> None:
    """Grava a contagem do Postgres a cada --intervalo s em <run>-postgres.csv até SIGTERM/SIGINT"""
    destino = pasta_saida(args) / f"{args.run}-postgres.csv"
    parar = []
    signal.signal(signal.SIGTERM, lambda *_: parar.append(1))
    signal.signal(signal.SIGINT, lambda *_: parar.append(1))

    with ExitStack() as pilha:
        conf = conexoes(args, pilha, PORTA_POSTGRES_ACOMPANHAR, PORTA_REDIS_ACOMPANHAR,
                        prometheus=False, redis_=args.modo != "A")
        conexao = conectar_db(conf)
        novo = not destino.exists()
        with open(destino, "a", newline="") as f:
            escritor = csv.writer(f)
            if novo:
                escritor.writerow(["timestamp", "instante", "sinteticos", "processados",
                                   "pendentes", "pendentes_sem_dlq"])
            log(f"acompanhando o Postgres a cada {args.intervalo:g} s em {destino}")
            while not parar:
                agora = time.time()
                dlq = []
                if args.modo != "A":
                    try:
                        dlq = ids_dlq(ler_dlq(conf["redis"]))
                    except Exception as erro:  # noqa: BLE001
                        log(f"aviso: DLQ inacessível: {erro}")
                c = contar_postgres(conexao, dlq)
                escritor.writerow([round(agora, 3), iso(agora), c["sinteticos"], c["processados"],
                                   c["pendentes"], c["pendentes_sem_dlq"]])
                f.flush()
                while not parar and time.time() - agora < args.intervalo:
                    time.sleep(0.2)
        conexao.close()
    log("acompanhamento encerrado")


def series_postgres(caminho: Path, inicio: float, fim: float) -> list:
    if not caminho.exists():
        return []
    linhas = []
    with open(caminho, newline="") as f:
        for linha in csv.DictReader(f):
            ts = float(linha["timestamp"])
            if inicio <= ts <= fim:
                for col in ("processados", "pendentes", "pendentes_sem_dlq"):
                    linhas.append((ts, f"pg_{col}", "", float(linha[col])))
    return linhas


def numero_csv(v: float):
    return int(v) if v == int(v) else repr(v)


def exportar(args) -> None:
    inicio, fim = args.start, args.end
    passo = args.step
    janela = f"{max(4 * passo, 60)}s"
    pasta = pasta_saida(args)
    log(f"{args.run}: {iso(inicio)} → {iso(fim)} ({fim - inicio:.0f} s), passo {passo} s, "
        f"rate[{janela}], namespace {args.namespace}")

    with ExitStack() as pilha:
        conf = conexoes(args, pilha, PORTA_POSTGRES, PORTA_REDIS, redis_=args.modo != "A")
        prom = Prometheus(conf["prometheus"], os.environ.get("QD_EXPORT_PROMETHEUS_USER"),
                          os.environ.get("QD_EXPORT_PROMETHEUS_PASSWORD"))
        prom.conferir()

        linhas, contagem = exportar_series(prom, args.modo, args.namespace, inicio, fim, passo, janela)
        linhas += series_postgres(pasta / f"{args.run}-postgres.csv", inicio, fim)
        linhas.sort(key=lambda l: (l[1], l[2], l[0]))
        res = resumo(prom, args.modo, args.namespace, inicio, fim)

        dlq = None
        if args.modo != "A":
            try:
                dlq = ler_dlq(conf["redis"])
            except Exception as erro:  # noqa: BLE001
                log(f"aviso: DLQ inacessível ({conf['redis']}): {erro}")

        postgres = None
        if not args.sem_postgres:
            try:
                conexao = conectar_db(conf)
                postgres = contar_postgres(conexao, ids_dlq(dlq or []))
                conexao.close()
            except Exception as erro:  # noqa: BLE001
                log(f"aviso: Postgres inacessível: {erro}")

    csv_saida = pasta / f"{args.run}.csv"
    with open(csv_saida, "w", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["timestamp", "instante", "serie", "rotulos", "valor"])
        for ts, nome, r, v in linhas:
            escritor.writerow([numero_csv(round(ts, 3)), iso(ts), nome, r, numero_csv(v)])

    json_saida = pasta / f"{args.run}.json"
    meta = json.loads(json_saida.read_text()) if json_saida.exists() else {}
    meta["export"] = {
        "gerado_em": iso(time.time()),
        "run": args.run, "cenario": args.cenario, "modo": args.modo,
        "namespace": args.namespace, "contexto": args.context,
        "inicio": iso(inicio), "fim": iso(fim), "inicio_ts": inicio, "fim_ts": fim,
        "passo_s": passo, "janela_rate": janela,
        "prometheus": conf["prometheus"],
        "linhas_por_serie": contagem,
        "series_vazias": sorted(n for n, c in contagem.items() if not c),
        "prometheus_resumo": res,
        "postgres_fim": postgres,
        "dlq": {"tamanho": len(dlq), "ids": ids_dlq(dlq), "entradas": dlq} if dlq is not None else None,
    }
    json_saida.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")

    log(f"{len(linhas)} linha(s) em {csv_saida}")
    log(f"resumo em {json_saida.name}; séries vazias: {', '.join(meta['export']['series_vazias']) or 'nenhuma'}")
    if postgres:
        log(f"Postgres: {postgres}")
    if dlq is not None:
        log(f"DLQ: {len(dlq)} item(ns)")


def instante_arg(texto: str) -> float:
    """Timestamp Unix ('1764019200') ou ISO 8601 (sem fuso = horário local)"""
    try:
        return float(texto)
    except ValueError:
        pass
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"instante inválido: {texto!r} (timestamp Unix ou ISO 8601)")
    return momento.astimezone().timestamp()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Detalhes no docstring do arquivo e em docs/avaliacao/exportacao.md.",
    )
    parser.add_argument("--start", type=instante_arg, help="início da execução (t0)")
    parser.add_argument("--end", type=instante_arg, help="fim da execução (t_vazio, ou t_zero no C)")
    parser.add_argument("--cenario", required=True, help="E1, E2, R1, R1a, R2, R3...")
    parser.add_argument("--modo", required=True, choices=MODOS)
    parser.add_argument("--run", required=True, help="identificador, ex.: E1-C-2 (ou E1-C-2b)")
    parser.add_argument("--step", type=int, default=15,
                        help="passo do query_range em s (padrão 15; 30 na campanha R)")
    parser.add_argument("--namespace", default="querido-diario",
                        help="namespace da aplicação (padrão querido-diario; no Revoada, querido-diario-tcc)")
    parser.add_argument("--context", help="contexto do kubectl (ex.: revoada-testes)")
    parser.add_argument("--port-forward", action="store_true",
                        help="abre port-forwards para o Prometheus, o Postgres e o redis-queue")
    parser.add_argument("--prometheus-svc", default="monitoring/monitoring-kube-prometheus-prometheus",
                        help="<namespace>/<serviço> do Prometheus para o --port-forward")
    parser.add_argument("--saida", default=str(RESULTADOS), help="pasta raiz (padrão: resultados/)")
    parser.add_argument("--invalida", action="store_true", help="grava em .../<modo>/invalidas/")
    parser.add_argument("--sem-postgres", action="store_true", help="não consulta o Postgres no fim")
    parser.add_argument("--acompanhar", action="store_true",
                        help="em vez de exportar, grava a contagem do Postgres periodicamente")
    parser.add_argument("--intervalo", type=float, default=15, help="--acompanhar: intervalo em s")
    args = parser.parse_args()

    if args.acompanhar:
        acompanhar(args)
        return
    if args.start is None or args.end is None:
        parser.error("--start e --end são obrigatórios (exceto com --acompanhar)")
    if args.end <= args.start:
        parser.error("--end precisa ser depois de --start")
    if args.step <= 0:
        parser.error("--step precisa ser positivo")
    exportar(args)


if __name__ == "__main__":
    main()
