#!/usr/bin/env python3
"""
Apoio ao run_experiment.sh (E-2, issue #33). Só biblioteca padrão.

    python3 simulador/registro_execucao.py lacunas <run>.csv <run>.json
    python3 simulador/registro_execucao.py diario <run>.json resultados/diario-de-bordo.md

lacunas: confere, no CSV exportado pelo export_metrics.py, o critério de
validade "o Prometheus ficou mais de 1 min sem raspar algum alvo usado pelas
medidas" (docs/avaliacao/protocolo.md, "Validade de uma execução"). Olha:
- `alvo_up` dos alvos que existem a execução inteira no modo (Pushgateway em
  todos; redis-queue no B e no C): ponto com valor 0 ou buraco maior que
  60 s + o passo;
- as séries do kube-state-metrics (`request_memoria_bytes`) e do cAdvisor
  (`memoria_bytes`) somadas por instante: buraco maior que 60 s + o passo.
Grava o resultado em "lacunas" no .json e sai com 1 se houver alguma.

diario: acrescenta a entrada da execução ao fim do diário de bordo, no formato
do modelo que está no próprio arquivo, a partir do .json da execução.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LIMITE_S = 60


def _iso(ts) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat(timespec="seconds")


def _hora_local(ts) -> str:
    return datetime.fromtimestamp(float(ts)).astimezone().strftime("%Y-%m-%d %H:%M")


def lacunas(caminho_csv: Path, caminho_json: Path) -> int:
    meta = json.loads(caminho_json.read_text())
    modo = meta["modo"]
    passo = float(meta["parametros"]["passo_s"])
    inicio = float(meta["export_janela"]["inicio"])
    fim = float(meta["export_janela"]["fim"])
    tolerancia = LIMITE_S + passo

    # O alvo do extraction-worker é por pod e some legitimamente (escala a 0 no
    # C, pod morto no R1/R1a): não entra. As métricas dele são contadores
    # acumulados, que um buraco curto não distorce
    alvos_exigidos = ["pushgateway"]
    if modo in ("B", "C"):
        alvos_exigidos.append("redis-queue")

    up = defaultdict(list)          # job → [(ts, valor)]
    instantes = defaultdict(set)    # série → {ts}
    with open(caminho_csv, newline="") as f:
        for linha in csv.DictReader(f):
            serie = linha["serie"]
            ts = float(linha["timestamp"])
            if serie == "alvo_up":
                rotulos = dict(p.split("=", 1) for p in linha["rotulos"].split(";") if "=" in p)
                up[rotulos.get("job", "")].append((ts, float(linha["valor"])))
            elif serie in ("request_memoria_bytes", "memoria_bytes"):
                instantes[serie].add(ts)

    problemas = []

    def buracos(nome, pontos):
        pontos = sorted(pontos)
        if not pontos:
            problemas.append(f"{nome}: nenhum ponto entre t0 e o fim")
            return
        anteriores = [inicio] + pontos
        for antes, depois in zip(anteriores, pontos + [fim]):
            if depois - antes > tolerancia:
                problemas.append(f"{nome}: {depois - antes:.0f} s sem pontos "
                                 f"({_iso(antes)} → {_iso(depois)})")

    for alvo in alvos_exigidos:
        jobs = [j for j in up if alvo in j]
        if not jobs:
            problemas.append(f"up do alvo {alvo}: série ausente")
            continue
        for job in jobs:
            pontos = up[job]
            zeros = [ts for ts, v in pontos if v == 0]
            if zeros:
                problemas.append(f"up{{job={job}}} = 0 em {len(zeros)} ponto(s), "
                                 f"a partir de {_iso(zeros[0])}")
            buracos(f"up{{job={job}}}", [ts for ts, _ in pontos])
    for serie in ("request_memoria_bytes", "memoria_bytes"):
        buracos(serie, list(instantes[serie]))

    meta["lacunas"] = {"tolerancia_s": tolerancia, "alvos": alvos_exigidos, "problemas": problemas}
    caminho_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    for p in problemas:
        print(f"lacuna: {p}")
    return 1 if problemas else 0


def _commit(meta, repo) -> str:
    c = (meta.get("commits") or {}).get(repo) or {}
    if not c.get("sha"):
        return "?"
    texto = f"`{c['sha'][:7]}`"
    if c.get("branch"):
        texto += f" ({c['branch']})"
    if c.get("sujo"):
        texto += " **com mudanças locais**"
    return texto


def diario(caminho_json: Path, caminho_diario: Path) -> int:
    meta = json.loads(caminho_json.read_text())
    p = meta["parametros"]
    inst = meta.get("instantes", {})
    val = meta.get("validade", {})
    exp = meta.get("export") or {}
    pg = exp.get("postgres_fim") or {}
    dlq = exp.get("dlq")

    if meta.get("piloto"):
        tipo = "piloto"
    elif val.get("valida"):
        tipo = "válida"
    else:
        tipo = "inválida"

    parametros = [f"N = {p.get('n', '—')}", f"*seed* = {p.get('seed', '—')}"]
    if meta["modo"] != "A":
        parametros.append(f"teto = {p.get('teto')}")
    if p.get("corrompidos"):
        parametros.append(f"corrompidos = {p['corrompidos']}")
    if p.get("visibility_timeout"):
        parametros.append(f"`QUEUE_VISIBILITY_TIMEOUT` = {p['visibility_timeout']} s")
    if meta["cenario"] == "R3":
        parametros.append(f"indisponibilidade nominal = {p.get('indisponibilidade_s')} s")
    if meta["cenario"] == "E2":
        parametros.append(f"janela = {p.get('janela_s')} s")
    parametros.append(f"timeout = {p.get('timeout_s')} s")

    ordem = ["t_carga_inicio", "t_carga_fim", "t0", "t_kill", "t_pod_removido", "t_down",
             "t_up_cmd", "t_ready", "t_restore", "t_reproc", "t_job2", "t_vazio", "t_zero",
             "t_job_fim", "t_fim"]
    instantes = "; ".join(f"{k} = {_iso(inst[k])}" for k in ordem if inst.get(k))

    duracao = "—"
    if inst.get("t0") and inst.get("t_vazio"):
        duracao = f"{(inst['t_vazio'] - inst['t0']) / 60:.1f} min até t_vazio"
    if meta["cenario"] == "E2" and inst.get("t0") and inst.get("t_fim"):
        duracao = f"{(inst['t_fim'] - inst['t0']) / 60:.1f} min de janela"
    resultado = [f"pendentes no fim = {pg.get('pendentes', '—')} "
                 f"({pg.get('pendentes_sem_dlq', '—')} fora da DLQ)",
                 f"na DLQ = {dlq['tamanho'] if dlq else '—'}",
                 f"duração = {duracao}"]
    falha = meta.get("falha") or {}
    if falha.get("indisponibilidade_real_s") is not None:
        resultado.append(f"indisponibilidade real = {falha['indisponibilidade_real_s']:.0f} s")
    if falha.get("desligamento_s") is not None:
        resultado.append(f"desligamento = {falha['desligamento_s']:.0f} s")

    imagens = sorted({i.get("digest") or "?" for i in (meta.get("imagem") or {}).get("usadas", [])})
    imagem = ", ".join(f"`{d}`" for d in imagens) or "—"

    anomalias = val.get("anomalias") or []
    motivos = val.get("motivos") or []
    if tipo == "inválida":
        validade = "inválida: " + "; ".join(motivos)
    else:
        validade = ("válida pelos critérios automáticos do `run_experiment.sh`; "
                    "conferir as anomalias e a interferência externa")
        if tipo == "piloto":
            validade = "piloto, fora dos resultados" + (f" (critérios: {'; '.join(motivos)})" if motivos else "")

    pasta = meta.get("pasta_resultados", "resultados")
    entrada = f"""
### {meta['run']} · {_hora_local(meta['inicio_script'])}

- **Campanha:** {meta['campanha']}
- **Tipo:** {tipo}
- **Commits:** data-processing {_commit(meta, 'data_processing')} · deployment {_commit(meta, 'deployment')} · estados {_commit(meta, 'estados')}
- **Imagem:** {imagem}
- **Parâmetros:** {', '.join(parametros)}
- **Instantes (UTC):** {instantes or '—'}
- **Resultado rápido:** {'; '.join(resultado)}
- **Arquivos:** `{pasta}/{meta['run']}.{{csv,json,log}}`
- **Anomalias:** {'; '.join(anomalias) if anomalias else 'nenhuma detectada pelo script'}
- **Validade:** {validade}
"""
    with open(caminho_diario, "a") as f:
        f.write(entrada)
    print(f"entrada {meta['run']} acrescentada a {caminho_diario}")
    return 0


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] not in ("lacunas", "diario"):
        print(__doc__, file=sys.stderr)
        return 2
    acao, a, b = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if acao == "lacunas":
        return lacunas(a, b)
    return diario(a, b)


if __name__ == "__main__":
    sys.exit(main())
