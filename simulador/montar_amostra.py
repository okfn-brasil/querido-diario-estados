#!/usr/bin/env python3
"""
Monta a amostra de PDFs reais usada pelo simulador de carga (D1, issue #27)

    python3 simulador/montar_amostra.py montar   # sorteia, baixa e gera o manifest.csv
    python3 simulador/montar_amostra.py baixar   # baixa de novo o que falta, a partir do manifest.csv
    python3 simulador/montar_amostra.py resumo   # distribuição da amostra, em Markdown

Os PDFs ficam em simulador/amostras/, fora do git (.gitignore). O manifest.csv
é versionado: traz a URL e o SHA-256 de cada arquivo, então `baixar` refaz a
mesma amostra em outra máquina e confere byte a byte.

Composição (ver docs/avaliacao/amostra.md):
- es_estado/a4: as 5 edições do reconhecimento do portal do DIO-ES (A4);
- es_estado/a6: todas as edições de 01/09 a 09/10/2026, o período da coleta
  real do ES no cluster local (A6) e da validação funcional (C7);
- es_estado/historico: uma edição por ano, de 2004 a 2025;
- municipal: 10 edições de 2025-2026 de cada município cujo portal usa a mesma
  plataforma do DIO-ES (DIONET) e tem raspador no querido-diario.

Os sorteios usam random.Random(SEMENTE), então `montar` sempre escolhe as
mesmas datas. O que pode mudar entre execuções é o portal: uma edição
republicada ou um portal fora do ar. Por isso o manifest.csv, e não o sorteio,
é a referência da amostra.

Só usa a biblioteca padrão e o poppler-utils (pdfinfo, pdftotext).
"""

import argparse
import csv
import hashlib
import json
import random
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "amostras"
MANIFESTO = PASTA / "manifest.csv"
SEMENTE = 2026
USER_AGENT = "Mozilla/5.0 (compatible; amostra-simulador-tcc)"
PAUSA = 0.5  # segundos entre requisições ao mesmo portal

COLUNAS = [
    "arquivo",
    "fonte",
    "grupo",
    "territory_id",
    "territorio",
    "data",
    "edicao_id",
    "numero",
    "extra",
    "tamanho_bytes",
    "paginas",
    "caracteres_texto",
    "produtor",
    "sha256",
    "url",
]

ES_ESTADO = {
    "fonte": "es_estado",
    "territory_id": "3299999",
    "territorio": "Espírito Santo (estado)",
    "base_url": "https://ioes.dio.es.gov.br",
    "subtheme": "",
}

# Portais DIONET com raspador no querido-diario (gazette/spiders/base/dionet.py)
MUNICIPAIS = [
    {
        "fonte": "es_serra",
        "territory_id": "3205002",
        "territorio": "Serra (ES)",
        "base_url": "https://ioes.dio.es.gov.br",
        "subtheme": "?subtheme=diariodaserra",
    },
    {
        "fonte": "rj_rio_de_janeiro",
        "territory_id": "3304557",
        "territorio": "Rio de Janeiro (RJ)",
        "base_url": "https://doweb.rio.rj.gov.br",
        "subtheme": "",
    },
    {
        "fonte": "sp_sao_jose_dos_campos",
        "territory_id": "3549904",
        "territorio": "São José dos Campos (SP)",
        "base_url": "https://diariodomunicipio.sjc.sp.gov.br",
        "subtheme": "",
    },
    {
        "fonte": "ms_corumba",
        "territory_id": "5003207",
        "territorio": "Corumbá (MS)",
        "base_url": "https://do.corumba.ms.gov.br",
        "subtheme": "",
    },
    {
        "fonte": "ro_jaru",
        "territory_id": "1100114",
        "territorio": "Jaru (RO)",
        "base_url": "https://doe.jaru.ro.gov.br",
        "subtheme": "",
    },
]

# Edições do reconhecimento do portal (A4), já descritas em docs/coleta/dio-es.md
A4_EDICOES = {
    "2003-03-17": 347,
    "2014-01-02": 1849,
    "2022-01-03": 6530,
    "2026-10-08": 11538,
    "2026-10-09": 11542,
}
A6_INICIO, A6_FIM = date(2026, 9, 1), date(2026, 10, 9)
HISTORICO_ANOS = range(2004, 2026)
MUNICIPAIS_POR_FONTE = 10
MUNICIPAIS_INICIO, MUNICIPAIS_FIM = date(2025, 1, 1), date(2026, 10, 31)


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for tentativa in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as resposta:
                return resposta.read()
        except Exception as erro:  # rede instável ou portal lento
            if tentativa == 3:
                raise
            espera = 2 ** (tentativa + 1)
            print(f"  erro em {url}: {erro!r}; nova tentativa em {espera}s", file=sys.stderr)
            time.sleep(espera)


def edicoes_do_dia(portal: dict, dia: date) -> list:
    """Edições publicadas no dia, pela mesma API que o BaseDionetSpider usa"""
    url = (
        f"{portal['base_url']}/apifront/portal/edicoes/edicoes_from_data/"
        f"{dia.isoformat()}.json{portal['subtheme']}"
    )
    dados = json.loads(_get(url))
    time.sleep(PAUSA)
    if dados.get("erro"):
        return []
    return dados.get("itens") or []


def _linha(portal: dict, grupo: str, dia: date, item: dict) -> dict:
    # O portal do Rio devolve números como string
    edicao_id = int(item["id"])
    extra = int(item["suplemento"]) == 1
    numero = int(item["numero"] or 0) or ""
    sufixo = "_extra" if extra else ""
    return {
        "arquivo": f"{portal['fonte']}_{dia.isoformat()}_{edicao_id}{sufixo}.pdf",
        "fonte": portal["fonte"],
        "grupo": grupo,
        "territory_id": portal["territory_id"],
        "territorio": portal["territorio"],
        "data": dia.isoformat(),
        "edicao_id": edicao_id,
        "numero": numero,
        "extra": str(extra).lower(),
        "url": f"{portal['base_url']}/portal/edicoes/download/{edicao_id}",
    }


def sortear_um(portal, grupo, rng, inicio, fim, ja_escolhidas, max_dias=15):
    """
    Sorteia um dia no intervalo e, se não houver edição nele, avança dia a dia
    (fins de semana e feriados). Entre as edições do dia, sorteia uma.
    """
    for _ in range(20):
        dia = inicio + timedelta(days=rng.randrange((fim - inicio).days + 1))
        for _ in range(max_dias):
            if dia > fim:
                break
            itens = [
                i for i in edicoes_do_dia(portal, dia) if int(i["id"]) not in ja_escolhidas
            ]
            if itens:
                return _linha(portal, grupo, dia, rng.choice(itens))
            dia += timedelta(days=1)
    raise RuntimeError(f"{portal['fonte']}: nenhuma edição encontrada em {inicio}..{fim}")


def selecionar() -> list:
    rng = random.Random(SEMENTE)
    linhas = []

    print("es_estado/a4")
    for dia_iso, edicao_id in A4_EDICOES.items():
        dia = date.fromisoformat(dia_iso)
        item = next(i for i in edicoes_do_dia(ES_ESTADO, dia) if int(i["id"]) == edicao_id)
        linhas.append(_linha(ES_ESTADO, "a4", dia, item))

    print("es_estado/a6")
    dia = A6_INICIO
    while dia <= A6_FIM:
        for item in edicoes_do_dia(ES_ESTADO, dia):
            linhas.append(_linha(ES_ESTADO, "a6", dia, item))
        dia += timedelta(days=1)

    escolhidas = {int(l["edicao_id"]) for l in linhas}

    print("es_estado/historico")
    for ano in HISTORICO_ANOS:
        linha = sortear_um(
            ES_ESTADO, "historico", rng, date(ano, 1, 1), date(ano, 12, 31), escolhidas
        )
        escolhidas.add(int(linha["edicao_id"]))
        linhas.append(linha)

    for portal in MUNICIPAIS:
        print(f"municipal/{portal['fonte']}")
        ids = set()
        while len(ids) < MUNICIPAIS_POR_FONTE:
            linha = sortear_um(
                portal, "municipal", rng, MUNICIPAIS_INICIO, MUNICIPAIS_FIM, ids
            )
            ids.add(int(linha["edicao_id"]))
            linhas.append(linha)

    # O A6 pode repetir uma edição do A4 (08 e 09/10/2026): fica a do A4
    vistas, unicas = set(), []
    for linha in linhas:
        chave = (linha["fonte"], linha["edicao_id"])
        if chave not in vistas:
            vistas.add(chave)
            unicas.append(linha)
    return unicas


def baixar_pdf(linha: dict) -> Path:
    caminho = PASTA / linha["arquivo"]
    if not caminho.exists():
        print(f"  baixando {linha['arquivo']}")
        conteudo = _get(linha["url"])
        if not conteudo.startswith(b"%PDF"):
            raise RuntimeError(f"{linha['url']} não devolveu um PDF")
        caminho.write_bytes(conteudo)
        time.sleep(PAUSA)
    return caminho


def descrever_pdf(caminho: Path) -> dict:
    info = subprocess.run(
        ["pdfinfo", str(caminho)], capture_output=True, text=True, errors="replace"
    ).stdout
    campos = dict(
        (chave.strip(), valor.strip())
        for chave, _, valor in (l.partition(":") for l in info.splitlines())
    )
    texto = subprocess.run(["pdftotext", "-q", str(caminho), "-"], capture_output=True).stdout
    return {
        "tamanho_bytes": caminho.stat().st_size,
        "paginas": int(campos.get("Pages", 0)),
        "caracteres_texto": len(texto.decode("utf-8", "replace")),
        "produtor": campos.get("Producer", ""),
        "sha256": hashlib.sha256(caminho.read_bytes()).hexdigest(),
    }


def ler_manifesto() -> list:
    with open(MANIFESTO, newline="") as arquivo:
        return list(csv.DictReader(arquivo))


def escrever_manifesto(linhas: list) -> None:
    ordem = {"a4": 0, "a6": 1, "historico": 2, "municipal": 3}
    linhas.sort(key=lambda l: (ordem[l["grupo"]], l["fonte"], l["data"], int(l["edicao_id"])))
    with open(MANIFESTO, "w", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=COLUNAS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(linhas)


def montar(_args) -> None:
    PASTA.mkdir(exist_ok=True)
    linhas = selecionar()
    print(f"{len(linhas)} edições selecionadas")
    for linha in linhas:
        linha.update(descrever_pdf(baixar_pdf(linha)))
    escrever_manifesto(linhas)
    print(f"manifesto gravado em {MANIFESTO}")


def baixar(_args) -> None:
    PASTA.mkdir(exist_ok=True)
    divergentes = 0
    for linha in ler_manifesto():
        caminho = baixar_pdf(linha)
        sha = hashlib.sha256(caminho.read_bytes()).hexdigest()
        if sha != linha["sha256"]:
            divergentes += 1
            print(f"  SHA-256 diferente: {linha['arquivo']}", file=sys.stderr)
    if divergentes:
        sys.exit(f"{divergentes} arquivo(s) diferente(s) do manifesto")
    print("amostra completa e conferida")


def _quartis(valores):
    q1, mediana, q3 = statistics.quantiles(valores, n=4, method="inclusive")
    return min(valores), q1, mediana, q3, max(valores)


def resumo(_args) -> None:
    linhas = ler_manifesto()
    grupos = {}
    for linha in linhas:
        rotulo = "ES estadual" if linha["fonte"] == "es_estado" else "Municipal"
        grupos.setdefault(rotulo, []).append(linha)
    grupos["Total"] = linhas

    def mb(b):
        return f"{b / 1e6:.1f}".replace(".", ",")

    def inteiro(n):
        return f"{round(n):,}".replace(",", ".")

    print("| Grupo | Arquivos | Tamanho (MB): mín · Q1 · mediana · Q3 · máx | Total (MB) "
          "| Páginas: mín · Q1 · mediana · Q3 · máx | Caracteres/página (mediana) |")
    print("|---|---|---|---|---|---|")
    for rotulo, itens in grupos.items():
        tamanhos = [int(l["tamanho_bytes"]) for l in itens]
        paginas = [int(l["paginas"]) for l in itens]
        densidade = [int(l["caracteres_texto"]) / max(int(l["paginas"]), 1) for l in itens]
        print(
            f"| {rotulo} | {len(itens)} | {' · '.join(mb(v) for v in _quartis(tamanhos))} "
            f"| {mb(sum(tamanhos))} | {' · '.join(inteiro(v) for v in _quartis(paginas))} "
            f"| {inteiro(statistics.median(densidade))} |"
        )

    print()
    print("| Fonte | Grupo | Arquivos | Páginas (total) | Tamanho (MB, total) | Sem texto extraível* |")
    print("|---|---|---|---|---|---|")
    chaves = sorted({(l["fonte"], l["grupo"]) for l in linhas}, key=lambda c: (c[0] != "es_estado", c))
    for fonte, grupo in chaves:
        itens = [l for l in linhas if l["fonte"] == fonte and l["grupo"] == grupo]
        sem_texto = sum(
            1 for l in itens if int(l["caracteres_texto"]) / max(int(l["paginas"]), 1) < 100
        )
        print(
            f"| `{fonte}` | {grupo} | {len(itens)} | {inteiro(sum(int(l['paginas']) for l in itens))} "
            f"| {mb(sum(int(l['tamanho_bytes']) for l in itens))} | {sem_texto} |"
        )
    print()
    print("\\* menos de 100 caracteres por página no `pdftotext`: provavelmente digitalizado (precisaria de OCR).")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("montar", help="sorteia as edições, baixa os PDFs e gera o manifest.csv").set_defaults(func=montar)
    sub.add_parser("baixar", help="baixa o que falta a partir do manifest.csv e confere o SHA-256").set_defaults(func=baixar)
    sub.add_parser("resumo", help="distribuição da amostra em Markdown").set_defaults(func=resumo)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
