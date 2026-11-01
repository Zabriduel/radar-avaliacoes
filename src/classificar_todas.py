"""
Classifica todas as avaliações pendentes no banco, em lotes, e mostra um resumo com as métricas.

Uso:
    python src/classificar_todas.py --limite 20      # teste
    python src/classificar_todas.py                  # tudo o que estiver pendente

Pode interromper e rodar de novo: ele continua de onde parou.
"""

import argparse
import time

from google import genai

import banco
from agente import MODELO, classificar_lote


def main():
    parser = argparse.ArgumentParser(description="Classifica avaliações pendentes com o agente")
    parser.add_argument("--limite", type=int, default=1000, help="máximo de avaliações nesta execução")
    parser.add_argument("--tamanho-lote", type=int, default=10, help="avaliações por chamada ao LLM")
    parser.add_argument("--pausa", type=float, default=5, help="segundos entre lotes (limite por minuto)")
    args = parser.parse_args()

    con = banco.conectar()
    banco.criar_tabelas(con)
    novas = banco.importar_csv(con)
    if novas:
        print(f"{novas} avaliações importadas do CSV")

    pendentes = banco.avaliacoes_pendentes(con, args.limite)
    print(f"{len(pendentes)} avaliações para classificar com {MODELO}, em lotes de {args.tamanho_lote}\n")

    cliente = genai.Client()
    inicio = time.perf_counter()
    total_ok, total_falhas, chamadas, tok_in, tok_out = 0, 0, 0, 0, 0
    com_correcao = 0

    for i in range(0, len(pendentes), args.tamanho_lote):
        lote = pendentes[i:i + args.tamanho_lote]
        print(f"Lote {i // args.tamanho_lote + 1}: ids {lote[0]['id']} a {lote[-1]['id']}")
        r = classificar_lote(cliente, lote)

        for id_ok, classif in r.classificacoes.items():
            banco.salvar_classificacao(con, classif, r.tentativas[id_ok], MODELO)
        banco.registrar_chamada(con, MODELO, r, len(lote))
        con.commit()  # salva a cada lote: se cair no meio, não perde o que já foi feito

        total_ok += len(r.classificacoes)
        total_falhas += len(r.falhas)
        com_correcao += sum(1 for t in r.tentativas.values() if t > 1)
        chamadas += r.chamadas
        tok_in += r.tokens_entrada
        tok_out += r.tokens_saida
        for id_falha, erro in r.falhas.items():
            print(f"    ✗ id {id_falha} falhou de vez: {erro}")

        time.sleep(args.pausa)

    duracao = time.perf_counter() - inicio
    print("\n===== RESUMO =====")
    print(f"Classificadas: {total_ok}   Falhas: {total_falhas}")
    print(f"Corrigidas na 2ª ou 3ª tentativa: {com_correcao}")
    print(f"Chamadas ao LLM: {chamadas}   Tokens: {tok_in} entrada + {tok_out} saída")
    print(f"Tempo total: {duracao:.0f} s (inclui pausas de {args.pausa:.0f} s entre lotes)")
    if total_ok:
        print(f"Tokens por avaliação: {(tok_in + tok_out) / total_ok:.0f}")


if __name__ == "__main__":
    main()
