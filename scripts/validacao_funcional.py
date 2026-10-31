#!/usr/bin/env python3
"""Validação funcional da fila de extração (C7): baseline (CronJob) × fila.

Coleta, para os diários de um território, o resultado de cada item do
checklist de docs/validacao-funcional.md e salva em JSON. Rodando uma vez em
cada modo, com os mesmos diários, `comparar` mostra se os dois entregam o
mesmo resultado funcional.

Uso (cluster kind local, com o modo a validar já processado; o passo a passo
completo está em docs/validacao-funcional.md):
    python3 scripts/validacao_funcional.py zerar   # antes de processar cada modo
    python3 scripts/validacao_funcional.py coletar --modo baseline \
        --saida resultados/validacao-funcional/baseline.json
    python3 scripts/validacao_funcional.py comparar \
        resultados/validacao-funcional/baseline.json \
        resultados/validacao-funcional/fila.json

Só usa a biblioteca padrão. O item 1 lê o Postgres do cluster com kubectl.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "http://api.queridodiario.local"
TERRITORIO = "3299999"  # Governo do Estado do Espírito Santo (ADR-0006)
TEMAS = ["Tecnologias na Educação", "Políticas Ambientais"]
# Índices dos excertos de cada tema (themes_config.json do data-processing)
INDICES_TEMAS = ["educacao", "ambiental"]

# Itens 2 e 3: OpenSearch "simple query string" (sem operador, o padrão entre
# termos é OU). Cada consulta tem uma descrição para o documento.
CONSULTAS = [
    ("decreto", "item 2: termo simples"),
    ('"secretaria de estado"', "frase entre aspas"),
    ("+decreto +nomear", "+ obrigatório (E)"),
    # Com o padrão OU, "a -b" vira "a OU (não b)" e não exclui nada
    ("decreto -portaria", "- exclusão, como um usuário escreveria"),
    ("decreto +-portaria", "- exclusão que funciona com o padrão OU"),
    ("decreto | portaria", "| OU"),
    ("exoner*", "* prefixo"),
    ('"secretaria educação"~3', "~N proximidade em frase"),
    ("govenador~1", "~N aproximação em termo (erro de digitação)"),
    # A aproximação não passa pelo stemmer: o índice guarda "exoner"
    ("exonaração~1", "~N aproximação em palavra reduzida pelo stemmer"),
    ("(decreto | portaria) +educação", "( ) agrupamento"),
    ("nomeação", "acento: com acento"),
    ("nomeacao", "acento: sem acento"),
]


def get_json(caminho: str, **params) -> dict:
    url = f"{API}{caminho}?{urllib.parse.urlencode(params, doseq=True)}"
    with urllib.request.urlopen(url, timeout=60) as resposta:
        return json.load(resposta)


def kubectl_exec(pod: str, container: str, *comando: str) -> str:
    return subprocess.run(
        ["kubectl", "exec", "-n", "querido-diario", pod, "-c", container, "--", *comando],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def psql(sql: str) -> str:
    return kubectl_exec(
        "postgres-1", "postgres", "psql", "-U", "postgres", "-d", "queridodiario", "-tAc", sql
    )


def diarios_processados() -> dict:
    saida = psql(
        "select count(*), coalesce(sum(processed::int), 0) from gazettes "
        f"where territory_id='{TERRITORIO}'"
    )
    total, processados = (int(x) for x in saida.split("|"))
    return {"total": total, "processados": processados}


def zerar() -> None:
    """Volta o território ao estado "coletado, não processado" no cluster local:
    processed=false no Postgres e, no OpenSearch, sem os documentos do
    território e sem os excertos temáticos deles"""
    print(psql(f"update gazettes set processed=false where territory_id='{TERRITORIO}'"))
    indices = {"queridodiario": "territory_id"}
    indices.update({indice: "source_territory_id" for indice in INDICES_TEMAS})
    for indice, campo in indices.items():
        corpo = json.dumps({"query": {"term": {campo: TERRITORIO}}})
        saida = kubectl_exec(
            "opensearch-0", "opensearch", "curl", "-s", "-XPOST",
            "-H", "Content-Type: application/json",
            f"http://localhost:9200/{indice}/_delete_by_query?refresh=true", "-d", corpo,
        )
        print(f"{indice}: {json.loads(saida).get('deleted')} apagados")


def busca(querystring: str) -> dict:
    resposta = get_json(
        "/gazettes",
        territory_ids=TERRITORIO,
        querystring=querystring,
        size=100,
        number_of_excerpts=1,
        excerpt_size=200,
    )
    return {
        "total": resposta["total_gazettes"],
        # O diário é identificado pela URL do PDF (território/data/checksum)
        "diarios": sorted(g["url"].rsplit("/", 3)[-2] + "/" + g["url"].rsplit("/", 1)[-1]
                          for g in resposta["gazettes"]),
    }


def excertos(tema: str) -> dict:
    resposta = get_json(
        f"/gazettes/by_theme/{urllib.parse.quote(tema)}",
        territory_ids=TERRITORIO,
        size=100,
    )
    return {
        "total": resposta["total_excerpts"],
        "excertos": sorted(e["date"] + " | " + e["excerpt"][:80] for e in resposta["excerpts"]),
    }


def pdf_abre() -> dict:
    resposta = get_json("/gazettes", territory_ids=TERRITORIO, size=1)
    url = resposta["gazettes"][0]["url"]
    with urllib.request.urlopen(url, timeout=60) as pdf:
        inicio = pdf.read(5)
        return {
            "url": url,
            "status": pdf.status,
            "content_type": pdf.headers.get("Content-Type"),
            "comeca_com_pdf": inicio == b"%PDF-",
        }


def coletar(modo: str, saida: str) -> None:
    resultado = {
        "modo": modo,
        "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "territorio": TERRITORIO,
        "item1_processados": diarios_processados(),
        "item2_3_buscas": {q: {"descricao": d, **busca(q)} for q, d in CONSULTAS},
        "item4_excertos": {t: excertos(t) for t in TEMAS},
        "item5_pdf": pdf_abre(),
    }
    with open(saida, "w", encoding="utf-8") as arquivo:
        json.dump(resultado, arquivo, ensure_ascii=False, indent=2)
    p = resultado["item1_processados"]
    print(f"[{modo}] processados {p['processados']}/{p['total']}")
    for q, r in resultado["item2_3_buscas"].items():
        print(f"[{modo}] {r['total']:>3} diários  {q}")
    for t, r in resultado["item4_excertos"].items():
        print(f"[{modo}] {r['total']:>3} excertos  {t}")
    print(f"[{modo}] PDF: {resultado['item5_pdf']}")
    print(f"Salvo em {saida}")


def comparar(arquivo_a: str, arquivo_b: str) -> int:
    with open(arquivo_a, encoding="utf-8") as f:
        a = json.load(f)
    with open(arquivo_b, encoding="utf-8") as f:
        b = json.load(f)
    diferencas = 0

    def checa(nome: str, va, vb) -> None:
        nonlocal diferencas
        igual = va == vb
        diferencas += not igual
        print(f"{'igual    ' if igual else 'DIFERENTE'}  {nome}")

    checa("item 1: diários processados", a["item1_processados"], b["item1_processados"])
    for q in a["item2_3_buscas"]:
        checa(f"busca {q}", a["item2_3_buscas"][q]["diarios"], b["item2_3_buscas"].get(q, {}).get("diarios"))
    for t in a["item4_excertos"]:
        checa(f"excertos {t}", a["item4_excertos"][t]["excertos"], b["item4_excertos"].get(t, {}).get("excertos"))
    pa, pb = a["item5_pdf"], b["item5_pdf"]
    checa("item 5: PDF abre", (pa["status"], pa["comeca_com_pdf"]), (pb["status"], pb["comeca_com_pdf"]))
    print(f"\n{a['modo']} × {b['modo']}: {diferencas} diferença(s)")
    return 1 if diferencas else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="comando", required=True)
    p_coletar = sub.add_parser("coletar", help="salva o resultado do modo atual em JSON")
    p_coletar.add_argument("--modo", required=True, choices=["baseline", "fila"])
    p_coletar.add_argument("--saida", required=True)
    p_comparar = sub.add_parser("comparar", help="compara dois JSONs de coletar")
    p_comparar.add_argument("a")
    p_comparar.add_argument("b")
    sub.add_parser("zerar", help="volta o território a 'não processado' no cluster local")
    args = parser.parse_args()
    if args.comando == "zerar":
        zerar()
        return 0
    if args.comando == "coletar":
        coletar(args.modo, args.saida)
        return 0
    return comparar(args.a, args.b)


if __name__ == "__main__":
    sys.exit(main())
