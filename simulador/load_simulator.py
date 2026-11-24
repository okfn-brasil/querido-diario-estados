#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3", "psycopg2-binary", "requests"]
# ///
"""
Simulador de carga (D2, issue #28): insere diários sintéticos, porém realistas,
como se a coleta tivesse acabado de rodar.

    python simulador/load_simulator.py --profile burst --total 500 --territory 3299999
    python simulador/load_simulator.py --profile peak-day --total 5600 --duration 8h
    python simulador/load_simulator.py --profile constant --total 120 --duration 1h
    python simulador/load_simulator.py --profile burst --total 300 --corrupt 10 --seed 1
    python simulador/load_simulator.py --cleanup

Para cada diário sintético:
1. sorteia um PDF da amostra do D1 (simulador/amostras/) e anexa um comentário
   único no final (b"\\n%qd-sim-<uuid>\\n"). O PDF continua válido e o checksum
   (MD5, como no FilesPipeline do Scrapy) fica único, o que é necessário por
   causa de UNIQUE(territory_id, date, file_checksum) e porque o OpenSearch usa
   o checksum como ID do documento;
2. sobe o PDF para o storage S3 (Garage no kind) em <territory>/<data>/<checksum>.pdf;
3. INSERT INTO gazettes (..., processed=false, scraped_at=now(), file_url='sim://<uuid>').

Perfis (instante de cada inserção, contado a partir do início):
- constant: taxa fixa, total/duração (duração padrão: 1 h);
- burst: todo o volume em 5 min, como os estados publicando à meia-noite;
- peak-day: 60% do volume nas primeiras 2 h e o resto distribuído até o fim
  da duração (padrão: 8 h). Ajustável com --peak-fraction e --peak-window.
Os instantes são determinísticos (espaçamento uniforme dentro de cada trecho);
a --seed fixa a sequência de PDFs sorteados e as posições dos corrompidos, então
a repetição k usa a mesma carga nos três modos do experimento.

--corrupt K troca K diários, entre 25% e 75% da inserção, por um arquivo com
cabeçalho %PDF-1.7 seguido de bytes aleatórios, do tamanho do PDF sorteado
(cenário R2, docs/avaliacao/cenarios.md). Os ids ficam no .json da execução.

--cleanup apaga os diários sintéticos (file_url LIKE 'sim://%'): os documentos
no OpenSearch (_delete_by_query pelos checksums, inclusive excertos temáticos
via source_file_checksum), os objetos no storage (PDF e .txt extraído) e, por
último, as linhas do Postgres. Roda antes de cada execução do experimento.

Cada execução grava simulador/execucoes/<início>_<perfil>.csv (uma linha por
diário) e .json (parâmetros, instantes de início/fim e ids corrompidos).

Conexões (variáveis de ambiente; os padrões são os do overlay dev no kind, com
os port-forwards abertos por --port-forward):
    QD_SIM_DB_URL               postgresql://admin:admin@localhost:5434/queridodiario
    QD_SIM_S3_ENDPOINT          http://localhost:3910
    QD_SIM_S3_ACCESS_KEY / QD_SIM_S3_SECRET_KEY / QD_SIM_S3_BUCKET / QD_SIM_S3_REGION
    QD_SIM_OPENSEARCH_URL       http://localhost:9210
    QD_SIM_OPENSEARCH_USER / QD_SIM_OPENSEARCH_PASSWORD / QD_SIM_OPENSEARCH_INDEX

--port-forward abre kubectl port-forward para postgres-rw, garage e opensearch
no --namespace (e --context) indicado e lê as credenciais do Secret app-secret.
Um serviço cuja variável de endpoint já está definida não é encaminhado, o que
permite, no Revoada, apontar o S3 direto para o Ceph.

Dependências: boto3, psycopg2-binary e requests. Com o uv, basta
`uv run simulador/load_simulator.py ...` (metadados PEP 723 no topo).
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

PASTA = Path(__file__).resolve().parent
AMOSTRAS = PASTA / "amostras"
MANIFESTO = AMOSTRAS / "manifest.csv"
EXECUCOES = PASTA / "execucoes"

TERRITORIO_PADRAO = "3299999"  # Espírito Santo (estado), ADR-0006
SIM_URL = "sim://"
MARCA = b"\n%qd-sim-{uuid}\n"

PERFIS = ("constant", "burst", "peak-day")
DURACAO_PADRAO = {"constant": "1h", "burst": "5m", "peak-day": "8h"}

# Port-forwards: serviço, porta remota, porta local, variável que dispensa o forward
FORWARDS = {
    "postgres": ("postgres-rw", 5432, 5434, "QD_SIM_DB_URL"),
    "s3": ("garage", 3900, 3910, "QD_SIM_S3_ENDPOINT"),
    "opensearch": ("opensearch", 9200, 9210, "QD_SIM_OPENSEARCH_URL"),
}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_duracao(texto: str) -> float:
    """'8h', '5m', '90s', '1h30m' ou '300' (segundos) → segundos"""
    texto = texto.strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", texto):
        return float(texto)
    partes = re.findall(r"(\d+(?:\.\d+)?)([hms])", texto)
    if not partes or "".join(n + u for n, u in partes) != texto:
        raise argparse.ArgumentTypeError(f"duração inválida: {texto!r} (ex.: 8h, 5m, 90s)")
    return sum(float(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in partes)


# ---------------------------------------------------------------------------
# Perfis de carga
# ---------------------------------------------------------------------------


def agenda(perfil: str, total: int, duracao: float, peak_fraction=0.6, peak_window=7200.0) -> list:
    """Instante (s desde o início) de cada uma das `total` inserções"""
    if total <= 0:
        return []

    def uniforme(n, inicio, fim):
        # n pontos em [inicio, fim), espaçados igualmente; o primeiro em `inicio`
        passo = (fim - inicio) / n if n else 0
        return [inicio + i * passo for i in range(n)]

    if perfil in ("constant", "burst"):
        return uniforme(total, 0.0, duracao)
    if perfil == "peak-day":
        janela = min(peak_window, duracao)
        n_pico = round(total * peak_fraction) if janela < duracao else total
        return uniforme(n_pico, 0.0, janela) + uniforme(total - n_pico, janela, duracao)
    raise ValueError(f"perfil desconhecido: {perfil}")


# ---------------------------------------------------------------------------
# Amostra
# ---------------------------------------------------------------------------


@dataclass
class Amostra:
    arquivo: Path
    territory_id: str
    data: str
    numero: str
    extra: bool
    power: str


def _data_do_nome(nome: str) -> str:
    achado = re.search(r"(\d{4}-\d{2}-\d{2})", nome)
    return achado.group(1) if achado else date.today().isoformat()


def carregar_amostra(territorio: str | None) -> list:
    """
    Lê o manifest.csv do D1. Aceita tanto a versão com territory_id/data quanto
    só a coluna `arquivo`; sem manifesto, usa todos os PDFs da pasta. Arquivos
    listados mas ainda não baixados são ignorados.
    """
    if MANIFESTO.exists():
        with open(MANIFESTO, newline="") as f:
            linhas = list(csv.DictReader(f))
    else:
        linhas = [{"arquivo": p.name} for p in sorted(AMOSTRAS.glob("*.pdf"))]

    amostra, faltando = [], 0
    for linha in linhas:
        caminho = AMOSTRAS / linha["arquivo"]
        if not caminho.exists():
            faltando += 1
            continue
        amostra.append(
            Amostra(
                arquivo=caminho,
                territory_id=territorio or linha.get("territory_id") or TERRITORIO_PADRAO,
                data=linha.get("data") or _data_do_nome(linha["arquivo"]),
                numero=(linha.get("numero") or "").strip(),
                extra=(linha.get("extra") or "").lower() == "true",
                power="executive",
            )
        )
    if faltando:
        log(f"aviso: {faltando} arquivo(s) do manifesto não estão em {AMOSTRAS} "
            "(rode `python3 simulador/montar_amostra.py baixar`)")
    if not amostra:
        sys.exit(f"nenhum PDF da amostra encontrado em {AMOSTRAS}")
    return amostra


def pdf_sintetico(original: bytes, marca_uuid: str) -> bytes:
    """O PDF original com um comentário no final: continua válido, checksum único"""
    return original + MARCA.replace(b"{uuid}", marca_uuid.encode())


def pdf_corrompido(tamanho: int) -> bytes:
    """Cabeçalho PDF válido + bytes aleatórios, sem objetos nem xref (R2)"""
    cabecalho = b"%PDF-1.7\n"
    return cabecalho + os.urandom(max(tamanho - len(cabecalho), 1024))


# ---------------------------------------------------------------------------
# Conexões
# ---------------------------------------------------------------------------


def _porta_livre(porta: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", porta)) != 0


@contextmanager
def port_forward(servico, remota, local, namespace, contexto):
    if not _porta_livre(local):
        sys.exit(f"porta local {local} ocupada (port-forward antigo para {servico}?)")
    cmd = ["kubectl", "port-forward", f"svc/{servico}", f"{local}:{remota}", "-n", namespace]
    if contexto:
        cmd += ["--context", contexto]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            if proc.poll() is not None:
                sys.exit(f"port-forward para svc/{servico} falhou: {proc.stderr.read().decode().strip()}")
            if not _porta_livre(local):
                break
            time.sleep(0.2)
        else:
            sys.exit(f"port-forward para svc/{servico} não abriu a porta {local}")
        log(f"port-forward svc/{servico} → localhost:{local}")
        yield
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _segredo(chave, namespace, contexto) -> str | None:
    cmd = ["kubectl", "get", "secret", "app-secret", "-n", namespace,
           "-o", f"jsonpath={{.data.{chave}}}"]
    if contexto:
        cmd += ["--context", contexto]
    saida = subprocess.run(cmd, capture_output=True, text=True)
    if saida.returncode != 0 or not saida.stdout:
        return None
    return base64.b64decode(saida.stdout).decode()


def preparar_conexoes(args, pilha: ExitStack) -> dict:
    """Configuração final das conexões: env > Secret (com --port-forward) > padrões do kind"""
    env = os.environ
    conf = {
        "db_url": env.get("QD_SIM_DB_URL"),
        "s3_endpoint": env.get("QD_SIM_S3_ENDPOINT"),
        "s3_key": env.get("QD_SIM_S3_ACCESS_KEY"),
        "s3_secret": env.get("QD_SIM_S3_SECRET_KEY"),
        "s3_bucket": env.get("QD_SIM_S3_BUCKET"),
        "s3_region": env.get("QD_SIM_S3_REGION", "us-east-1"),
        "os_url": env.get("QD_SIM_OPENSEARCH_URL"),
        "os_user": env.get("QD_SIM_OPENSEARCH_USER"),
        "os_password": env.get("QD_SIM_OPENSEARCH_PASSWORD"),
        "os_index": env.get("QD_SIM_OPENSEARCH_INDEX", "queridodiario"),
    }

    if args.port_forward:
        if not shutil.which("kubectl"):
            sys.exit("--port-forward precisa do kubectl")
        ns, ctx = args.namespace, args.context

        def s(chave):
            return _segredo(chave, ns, ctx)

        for nome, (servico, remota, local, var) in FORWARDS.items():
            if env.get(var):
                continue
            pilha.enter_context(port_forward(servico, remota, local, ns, ctx))
            if nome == "postgres":
                conf["db_url"] = (f"postgresql://{s('QD_DATA_DB_USER')}:{s('QD_DATA_DB_PASSWORD')}"
                                  f"@localhost:{local}/queridodiario")
            elif nome == "s3":
                conf["s3_endpoint"] = f"http://localhost:{local}"
            else:
                conf["os_url"] = f"http://localhost:{local}"
        conf["s3_key"] = conf["s3_key"] or s("STORAGE_ACCESS_KEY")
        conf["s3_secret"] = conf["s3_secret"] or s("STORAGE_ACCESS_SECRET")
        conf["s3_bucket"] = conf["s3_bucket"] or s("STORAGE_BUCKET")
        conf["os_user"] = conf["os_user"] or s("QUERIDO_DIARIO_OPENSEARCH_USER")
        conf["os_password"] = conf["os_password"] or s("QUERIDO_DIARIO_OPENSEARCH_PASSWORD")

    # Padrões do overlay dev (k8s/overlays/dev/patch-secret-dev.yaml no deployment)
    padroes = {
        "db_url": "postgresql://admin:admin@localhost:5434/queridodiario",
        "s3_endpoint": "http://localhost:3910",
        "s3_key": "GKdeadbeef000000000000dead",
        "s3_secret": "c0ffee000000000000000000000000000000000000000000000000000000cafe",
        "s3_bucket": "queridodiariobucket",
        "os_url": "http://localhost:9210",
        "os_user": "admin",
        "os_password": "admin",
    }
    for chave, valor in padroes.items():
        conf[chave] = conf[chave] or valor
    return conf


def cliente_s3(conf):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=conf["s3_endpoint"],
        aws_access_key_id=conf["s3_key"],
        aws_secret_access_key=conf["s3_secret"],
        region_name=conf["s3_region"],
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5},
                      max_pool_connections=32),
    )


def conectar_db(conf):
    import psycopg2

    conexao = psycopg2.connect(conf["db_url"])
    conexao.autocommit = True
    return conexao


def sessao_opensearch(conf):
    import requests

    sessao = requests.Session()
    sessao.auth = (conf["os_user"], conf["os_password"])
    sessao.verify = os.environ.get("QD_SIM_OPENSEARCH_CA", False) or False
    sessao.headers["Content-Type"] = "application/json"
    return sessao


# ---------------------------------------------------------------------------
# Inserção
# ---------------------------------------------------------------------------

INSERT = """
INSERT INTO gazettes
    (source_text, date, edition_number, is_extra_edition, power, file_checksum,
     file_path, file_url, scraped_at, created_at, territory_id, processed)
VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, now(), now(), %s, false)
RETURNING id, scraped_at
"""


class Simulador:
    def __init__(self, conf, amostra, args):
        self.conf = conf
        self.amostra = amostra
        self.args = args
        self.s3 = cliente_s3(conf)
        self.local = threading.local()
        self.lock = threading.Lock()
        self.cache = {}  # bytes dos PDFs já lidos (a amostra cabe em memória)

    def _db(self):
        if not hasattr(self.local, "conexao"):
            self.local.conexao = conectar_db(self.conf)
        return self.local.conexao

    def _bytes(self, caminho: Path) -> bytes:
        with self.lock:
            if caminho not in self.cache:
                self.cache[caminho] = caminho.read_bytes()
            return self.cache[caminho]

    def inserir(self, item: dict) -> dict:
        amostra: Amostra = item["amostra"]
        marca = str(uuid.uuid4())
        original = self._bytes(amostra.arquivo)
        if item["corrompido"]:
            conteudo = pdf_corrompido(len(original))
        else:
            conteudo = pdf_sintetico(original, marca)
        checksum = hashlib.md5(conteudo).hexdigest()
        caminho = f"{amostra.territory_id}/{amostra.data}/{checksum}.pdf"

        t_inicio = time.time()
        self.s3.put_object(Bucket=self.conf["s3_bucket"], Key=caminho, Body=conteudo,
                           ContentType="application/pdf")
        try:
            with self._db().cursor() as cur:
                cur.execute(INSERT, (amostra.data, amostra.numero or None, amostra.extra,
                                     amostra.power, checksum, caminho, f"{SIM_URL}{marca}",
                                     amostra.territory_id))
                gazette_id, scraped_at = cur.fetchone()
        except Exception:
            # sem a linha, o objeto ficaria órfão e o --cleanup não o encontraria
            self.s3.delete_object(Bucket=self.conf["s3_bucket"], Key=caminho)
            raise
        return {
            "seq": item["seq"],
            "id": gazette_id,
            "agendado_s": round(item["t"], 3),
            "inserido_em": scraped_at.isoformat(),
            "atraso_s": round(t_inicio - item["t_absoluto"], 3),
            "duracao_s": round(time.time() - t_inicio, 3),
            "territory_id": amostra.territory_id,
            "data": amostra.data,
            "origem": amostra.arquivo.name,
            "tamanho_bytes": len(conteudo),
            "file_checksum": checksum,
            "file_path": caminho,
            "file_url": f"{SIM_URL}{marca}",
            "corrompido": str(item["corrompido"]).lower(),
        }


def planejar(args, amostra) -> list:
    rng = random.Random(args.seed)
    instantes = agenda(args.profile, args.total, args.duration, args.peak_fraction, args.peak_window)
    escolhas = [rng.choice(amostra) for _ in range(args.total)]
    corrompidos = set()
    if args.corrupt:
        inicio, fim = int(args.total * 0.25), int(args.total * 0.75)
        if args.corrupt > fim - inicio:
            sys.exit(f"--corrupt {args.corrupt} não cabe entre 25% e 75% de {args.total} diários")
        corrompidos = set(rng.sample(range(inicio, fim), args.corrupt))
    return [
        {"seq": i, "t": t, "amostra": a, "corrompido": i in corrompidos}
        for i, (t, a) in enumerate(zip(instantes, escolhas))
    ]


def resumo_agenda(plano, duracao) -> None:
    """Histograma da agenda (para conferir o perfil sem tocar no cluster)"""
    baldes = 12
    largura = duracao / baldes
    contagem = [0] * baldes
    for item in plano:
        contagem[min(int(item["t"] // largura), baldes - 1)] += 1
    maior = max(contagem) or 1
    for i, n in enumerate(contagem):
        ini = i * largura
        print(f"  {ini / 60:7.1f} min  {n:6d}  {'#' * round(40 * n / maior)}")
    tamanho = sum(item["amostra"].arquivo.stat().st_size for item in plano)
    print(f"  total: {len(plano)} diários, {tamanho / 1e9:.2f} GB, "
          f"{sum(i['corrompido'] for i in plano)} corrompido(s)")


def simular(args) -> None:
    amostra = carregar_amostra(args.territory)
    plano = planejar(args, amostra)
    log(f"perfil {args.profile}: {args.total} diários em {args.duration / 60:.1f} min, "
        f"seed {args.seed}, {len(amostra)} PDFs na amostra")
    if args.dry_run:
        resumo_agenda(plano, args.duration)
        return

    with ExitStack() as pilha:
        conf = preparar_conexoes(args, pilha)
        sim = Simulador(conf, amostra, args)

        EXECUCOES.mkdir(exist_ok=True)
        inicio = datetime.now(timezone.utc)
        base = EXECUCOES / f"{inicio.strftime('%Y%m%dT%H%M%SZ')}_{args.profile}"
        resultados, erros = [], []
        t0 = time.time()

        def tarefa(item):
            try:
                return sim.inserir(item)
            except Exception as erro:
                erros.append((item["seq"], repr(erro)))
                log(f"erro no diário {item['seq']}: {erro!r}")
                return None

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futuros = []
            for item in plano:
                item["t_absoluto"] = t0 + item["t"]
                espera = item["t_absoluto"] - time.time()
                if espera > 0:
                    time.sleep(espera)
                futuros.append(pool.submit(tarefa, item))
                if (item["seq"] + 1) % max(args.total // 20, 1) == 0:
                    feitos = sum(f.done() for f in futuros)
                    log(f"agendados {item['seq'] + 1}/{args.total}, concluídos {feitos}")
            for futuro in futuros:
                if (r := futuro.result()) is not None:
                    resultados.append(r)

        fim = datetime.now(timezone.utc)
        resultados.sort(key=lambda r: r["seq"])
        if resultados:
            with open(base.with_suffix(".csv"), "w", newline="") as f:
                escritor = csv.DictWriter(f, fieldnames=list(resultados[0]), lineterminator="\n")
                escritor.writeheader()
                escritor.writerows(resultados)
        atrasos = sorted(r["atraso_s"] for r in resultados) or [0]
        resumo = {
            "perfil": args.profile,
            "total_pedido": args.total,
            "inseridos": len(resultados),
            "erros": len(erros),
            "duracao_planejada_s": args.duration,
            "seed": args.seed,
            "territory": args.territory,
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            "duracao_real_s": round((fim - inicio).total_seconds(), 1),
            "atraso_max_s": atrasos[-1],
            "atraso_p95_s": atrasos[int(0.95 * (len(atrasos) - 1))],
            "bytes_enviados": sum(r["tamanho_bytes"] for r in resultados),
            "corrompidos_ids": [r["id"] for r in resultados if r["corrompido"] == "true"],
            "ids_min_max": [resultados[0]["id"], resultados[-1]["id"]] if resultados else [],
            "erros_detalhe": erros[:50],
            "amostra": str(MANIFESTO.relative_to(PASTA.parent)) if MANIFESTO.exists() else None,
        }
        base.with_suffix(".json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False) + "\n")

        log(f"fim: {len(resultados)} inseridos, {len(erros)} erro(s), "
            f"{resumo['duracao_real_s']} s, atraso máx. {resumo['atraso_max_s']} s")
        if resumo["corrompidos_ids"]:
            log(f"corrompidos: {resumo['corrompidos_ids']}")
        log(f"registro: {base.with_suffix('.json')}")
        if atrasos[-1] > 30:
            log("aviso: a inserção ficou mais de 30 s atrás da agenda; aumente --workers "
                "ou reduza o volume")
        if erros:
            sys.exit(1)


# ---------------------------------------------------------------------------
# Limpeza
# ---------------------------------------------------------------------------


def _lotes(itens, tamanho):
    for i in range(0, len(itens), tamanho):
        yield itens[i:i + tamanho]


def limpar(args) -> None:
    with ExitStack() as pilha:
        conf = preparar_conexoes(args, pilha)
        conexao = conectar_db(conf)
        with conexao.cursor() as cur:
            cur.execute("SELECT id, file_checksum, file_path FROM gazettes WHERE file_url LIKE %s",
                        (f"{SIM_URL}%",))
            linhas = cur.fetchall()
        log(f"{len(linhas)} diário(s) sintético(s) no Postgres")
        if not linhas:
            return
        checksums = [l[1] for l in linhas]

        # 1. OpenSearch: diários (_id = checksum) e excertos temáticos (source_file_checksum)
        sessao = sessao_opensearch(conf)
        removidos = 0
        for lote in _lotes(checksums, 1000):
            consulta = {"query": {"bool": {"should": [
                {"ids": {"values": lote}},
                {"terms": {"source_file_checksum": lote}},
            ]}}}
            resposta = sessao.post(
                f"{conf['os_url']}/*/_delete_by_query",
                params={"conflicts": "proceed", "refresh": "true",
                        "ignore_unavailable": "true", "allow_no_indices": "true"},
                data=json.dumps(consulta), timeout=600,
            )
            resposta.raise_for_status()
            removidos += resposta.json().get("deleted", 0)
        log(f"OpenSearch: {removidos} documento(s) removido(s)")

        # 2. Storage: PDF e o .txt que a extração grava ao lado
        s3 = cliente_s3(conf)
        chaves = []
        for _, _, caminho in linhas:
            chaves += [caminho, str(Path(caminho).with_suffix(".txt"))]
        apagados = 0
        for lote in _lotes(chaves, 1000):
            resposta = s3.delete_objects(
                Bucket=conf["s3_bucket"],
                Delete={"Objects": [{"Key": k} for k in lote], "Quiet": True},
            )
            falhas = resposta.get("Errors", [])
            if falhas:
                sys.exit(f"storage: {len(falhas)} falha(s) ao apagar, ex.: {falhas[0]}")
            apagados += len(lote)
        log(f"storage: {apagados} chave(s) apagada(s) (PDF + .txt)")

        # 3. Postgres por último: se algo acima falhar, o --cleanup pode rodar de novo
        with conexao.cursor() as cur:
            cur.execute("DELETE FROM gazettes WHERE file_url LIKE %s", (f"{SIM_URL}%",))
            log(f"Postgres: {cur.rowcount} linha(s) apagada(s)")
        conexao.close()


# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Detalhes no docstring do arquivo e em docs/avaliacao/cenarios.md.",
    )
    acao = parser.add_mutually_exclusive_group(required=True)
    acao.add_argument("--profile", choices=PERFIS, help="perfil de inserção ao longo do tempo")
    acao.add_argument("--cleanup", action="store_true", help="apaga todos os diários sintéticos")
    parser.add_argument("--total", type=int, help="número de diários sintéticos")
    parser.add_argument("--duration", type=parse_duracao,
                        help="duração da inserção (padrão: constant 1h, burst 5m, peak-day 8h)")
    parser.add_argument("--territory", help="territory_id de todos os diários "
                        "(padrão: o do manifesto, ou 3299999)")
    parser.add_argument("--seed", type=int, default=1, help="semente dos sorteios (padrão: 1)")
    parser.add_argument("--corrupt", type=int, default=0,
                        help="diários corrompidos entre 25%% e 75%% da inserção (R2)")
    parser.add_argument("--peak-fraction", type=float, default=0.6,
                        help="peak-day: fração do volume na janela de pico (padrão: 0.6)")
    parser.add_argument("--peak-window", type=parse_duracao, default=7200.0,
                        help="peak-day: duração da janela de pico (padrão: 2h)")
    parser.add_argument("--workers", type=int, default=4,
                        help="uploads/inserções simultâneos (padrão: 4)")
    parser.add_argument("--dry-run", action="store_true",
                        help="só mostra a agenda, sem tocar no cluster")
    parser.add_argument("--port-forward", action="store_true",
                        help="abre port-forwards para Postgres, Garage e OpenSearch")
    parser.add_argument("--namespace", default="querido-diario",
                        help="namespace dos serviços (padrão: querido-diario)")
    parser.add_argument("--context", help="contexto do kubectl (ex.: revoada-testes)")
    args = parser.parse_args()

    if args.cleanup:
        limpar(args)
        return
    if not args.total or args.total <= 0:
        parser.error("--total é obrigatório (e positivo) com --profile")
    if args.duration is None:
        args.duration = parse_duracao(DURACAO_PADRAO[args.profile])
    if args.duration <= 0:
        parser.error("--duration precisa ser positiva")
    if not 0 < args.peak_fraction <= 1:
        parser.error("--peak-fraction precisa estar em (0, 1]")
    simular(args)


if __name__ == "__main__":
    main()
