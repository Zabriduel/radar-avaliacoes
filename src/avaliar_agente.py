"""
Mede o acerto do agente comparando com rótulos feitos à mão.

Passo 1: python src/avaliar_agente.py sortear
    Cria data/rotulos_manuais.csv com 30 avaliações SEM a resposta do agente,
    para o rótulo humano não ser influenciado por ela.
Passo 2: preencher as colunas *_humano no Excel e salvar como CSV.
Passo 3: python src/avaliar_agente.py calcular
    Mostra o % de acerto e lista as divergências.

A amostra é estratificada: 5 avaliações de cada tema dado pelo agente, senão temas raros
como preço quase não apareceriam. Por isso o resultado vale como um retrato de 30 casos,
não como uma medida estatística precisa de toda a base.
"""

import argparse
import csv
import random
import sys
import unicodedata
from pathlib import Path

import banco

ARQUIVO_ROTULOS = banco.PASTA_DADOS / "rotulos_manuais.csv"
POR_TEMA = 5
SEPARADOR = ";"  # o Excel em português abre ";" já separado em colunas

VALORES_VALIDOS = {
    "tema": {"atraso", "pedido_errado", "qualidade", "preco", "embalagem", "atendimento"},
    "sentimento": {"negativo", "neutro", "positivo"},
    "gravidade": {"baixa", "media", "alta"},
}


def normalizar(valor: str) -> str:
    """Aceita 'Preço', 'média' ou 'pedido errado' e deixa no formato do banco."""
    sem_acento = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode()
    return sem_acento.strip().lower().replace(" ", "_")


def sortear(caminho: Path) -> None:
    if caminho.exists():
        sys.exit(f"{caminho} já existe. Não vou sobrescrever os seus rótulos.")

    con = banco.conectar()
    linhas = con.execute("""
        SELECT a.id, a.nota, a.texto, c.tema FROM avaliacoes a
        JOIN classificacoes c ON c.id_avaliacao = a.id
        ORDER BY a.id
    """).fetchall()

    sorteio = random.Random(2026)  # seed fixa: a amostra pode ser reproduzida
    amostra = []
    for tema in sorted(VALORES_VALIDOS["tema"]):
        do_tema = [l for l in linhas if l["tema"] == tema]
        amostra += sorteio.sample(do_tema, POR_TEMA)
    sorteio.shuffle(amostra)  # a ordem não pode entregar o tema

    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.writer(f, delimiter=SEPARADOR)
        escritor.writerow(["id", "nota", "texto", "tema_humano", "sentimento_humano", "gravidade_humano"])
        for l in amostra:
            escritor.writerow([l["id"], l["nota"], l["texto"], "", "", ""])
    print(f"{len(amostra)} avaliações salvas em {caminho}")


def ler_rotulos(caminho: Path) -> list[dict]:
    """O Excel pode salvar em UTF-8 ou no padrão do Windows, então aceito os dois."""
    try:
        conteudo = caminho.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        conteudo = caminho.read_text(encoding="cp1252")
    return list(csv.DictReader(conteudo.splitlines(), delimiter=SEPARADOR))


def calcular(caminho: Path) -> None:
    rotulos = ler_rotulos(caminho)

    problemas = []
    for r in rotulos:
        for campo, validos in VALORES_VALIDOS.items():
            r[campo] = normalizar(r[f"{campo}_humano"] or "")
            if r[campo] not in validos:
                problemas.append(f"id {r['id']}: {campo} = '{r[campo]}'")
    if problemas:
        sys.exit("Corrija estes rótulos vazios ou inválidos:\n" + "\n".join(problemas))

    con = banco.conectar()
    agente = {
        l["id_avaliacao"]: l
        for l in con.execute("SELECT id_avaliacao, tema, sentimento, gravidade FROM classificacoes")
    }

    print(f"Amostra: {len(rotulos)} avaliações rotuladas à mão\n")
    for campo in VALORES_VALIDOS:
        acertos = sum(r[campo] == agente[int(r["id"])][campo] for r in rotulos)
        print(f"{campo:<11} {acertos}/{len(rotulos)} = {acertos / len(rotulos):.0%}")

    print("\nDivergências (humano x agente):")
    for r in rotulos:
        a = agente[int(r["id"])]
        difs = [f"{c}: {r[c]} x {a[c]}" for c in VALORES_VALIDOS if r[c] != a[c]]
        if difs:
            print(f"- id {r['id']} | {' | '.join(difs)}\n  {r['texto'][:110]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compara o agente com rótulos manuais")
    parser.add_argument("acao", choices=["sortear", "calcular"])
    parser.add_argument("--arquivo", type=Path, default=ARQUIVO_ROTULOS)
    args = parser.parse_args()
    if args.acao == "sortear":
        sortear(args.arquivo)
    else:
        calcular(args.arquivo)
