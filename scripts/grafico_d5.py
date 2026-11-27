"""Gráfico do D5 (#31): vazão, CPU do OpenSearch e cold start por teto de réplicas.

Lê as execuções do D5 em resultados/R/D5/E1/C/ (o .json de cada teto, a
série cpu_cores do .csv e o cold-start.csv gerado por simulador/cold_start.py)
e grava resultados/R/D5/vazao-teto.png e .svg.

Uso: python3 scripts/grafico_d5.py
"""

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PASTA = Path(__file__).resolve().parent.parent / "resultados" / "R" / "D5"
DADOS = PASTA / "E1" / "C"
TETOS = (2, 4, 6, 8)
ESCOLHIDO = 6
N = 500

# paleta de referência (série 1 e tintas de texto), tema claro para impressão
AZUL = "#257de0"
TEXTO = "#191919"
TEXTO_2 = "#666666"
GRADE = "#e6e6e6"


def vazao(teto):
    instantes = json.loads((DADOS / f"E1-C-D5t{teto}-1.json").read_text())["instantes"]
    return N / (instantes["t_vazio"] - instantes["t0"])


def cpu_opensearch(teto):
    with open(DADOS / f"E1-C-D5t{teto}-1.csv") as arquivo:
        return max(
            float(linha["valor"])
            for linha in csv.DictReader(arquivo)
            if linha["serie"] == "cpu_cores" and linha["rotulos"] == "pod=opensearch-0"
        )


def cold_start():
    with open(DADOS / "cold-start.csv") as arquivo:
        return list(csv.DictReader(arquivo))


def estilo(eixo, titulo, rotulo_y):
    eixo.set_title(titulo, loc="left", fontsize=11, color=TEXTO, pad=10)
    eixo.set_ylabel(rotulo_y, color=TEXTO_2, fontsize=9)
    eixo.set_xlabel("teto de réplicas (maxReplicaCount)", color=TEXTO_2, fontsize=9)
    eixo.set_xticks(TETOS)
    eixo.set_xlim(1, 9)
    eixo.grid(axis="y", color=GRADE, linewidth=0.8)
    eixo.set_axisbelow(True)
    for lado in ("top", "right"):
        eixo.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        eixo.spines[lado].set_color(GRADE)
    eixo.tick_params(colors=TEXTO_2, labelsize=9, length=0)
    eixo.axvline(ESCOLHIDO, color=TEXTO_2, linewidth=0.8, linestyle=":", zorder=0)


def main():
    v = [vazao(t) for t in TETOS]
    cpu = [cpu_opensearch(t) for t in TETOS]
    pods = cold_start()

    fig, (a, b, c) = plt.subplots(1, 3, figsize=(13, 4.2), constrained_layout=True)
    fig.patch.set_facecolor("white")

    # (a) vazão medida × crescimento linear a partir do teto 2
    estilo(a, "(a) Vazão até esvaziar a fila", "diários/s (N = 500)")
    ideal = [v[0] * t / TETOS[0] for t in TETOS]
    a.plot(TETOS, ideal, color=TEXTO_2, linewidth=1.2, linestyle="--")
    a.annotate("linear a partir do teto 2", (5, v[0] * 5 / TETOS[0]), xytext=(3.0, 4.3),
               textcoords="data", ha="center", fontsize=8, color=TEXTO_2,
               arrowprops=dict(arrowstyle="-", color=TEXTO_2, linewidth=0.8))
    a.plot(TETOS, v, color=AZUL, linewidth=2, marker="o", markersize=7,
           markeredgecolor="white", markeredgewidth=2)
    for t, y in zip(TETOS, v):
        a.annotate(f"{y:.2f}".replace(".", ","), (t, y), xytext=(0, -16),
                   textcoords="offset points", ha="center", fontsize=8, color=TEXTO)
    a.set_ylim(0, max(ideal) * 1.1)

    # (b) CPU máxima do OpenSearch
    estilo(b, "(b) CPU máxima do OpenSearch", "núcleos (passo de 30 s)")
    b.plot(TETOS, cpu, color=AZUL, linewidth=2, marker="o", markersize=7,
           markeredgecolor="white", markeredgewidth=2)
    for t, y in zip(TETOS, cpu):
        b.annotate(f"{y:.1f}".replace(".", ","), (t, y), xytext=(-8, 6),
                   textcoords="offset points", ha="right", fontsize=8, color=TEXTO)
    b.set_ylim(0, max(cpu) * 1.2)

    # (c) quando cada réplica conclui o 1º diário, desde t0
    estilo(c, "(c) Réplica produtiva: t0 → 1º diário", "segundos desde t0")
    for p in pods:
        c.plot(int(p["teto"]), float(p["t0_ate_1o_diario_s"]), "o", color=AZUL,
               markersize=8, alpha=0.55, markeredgecolor="white", markeredgewidth=1)
    for t in TETOS:
        ultimos = [float(p["t0_ate_1o_diario_s"]) for p in pods if int(p["teto"]) == t]
        c.annotate(f"{len(ultimos)} réplicas", (t, max(ultimos)), xytext=(0, 9),
                   textcoords="offset points", ha="center", fontsize=8, color=TEXTO_2)
    c.set_ylim(0, 52)

    b.annotate(f"teto escolhido ({ESCOLHIDO})", (ESCOLHIDO, b.get_ylim()[1]),
               xytext=(4, -12), textcoords="offset points", fontsize=8, color=TEXTO_2)

    for formato in ("png", "svg"):
        fig.savefig(PASTA / f"vazao-teto.{formato}", dpi=200)
    print(PASTA / "vazao-teto.png")


if __name__ == "__main__":
    main()
