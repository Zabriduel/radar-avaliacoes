"""
Gera avaliações FICTÍCIAS de restaurantes com o Gemini e salva em CSV.

Por que gerar com LLM: preciso de textos variados e realistas para testar o agente,
sem usar avaliações reais (que teriam dados pessoais de clientes, LGPD).

Como funciona:
1. Monto uma lista de "lotes". Cada lote tem um tema e um sentimento-alvo
   (ex.: atraso + negativo), sorteados com pesos fixos.
2. Para cada lote, peço ao Gemini N avaliações em JSON, com schema definido (pydantic).
3. O Python completa o resto: id, restaurante, data e a marca "ficticio".
   Datas e restaurantes ficam no código, não no LLM, para eu ter controle da distribuição.

Uso:
    python src/gerar_dados.py --lotes 1      # teste rápido (10 avaliações)
    python src/gerar_dados.py                # completo (20 lotes x 10 = 200)
    python src/gerar_dados.py --lotes 5 --anexar   # acrescenta ao CSV existente
"""

import argparse
import csv
import os
import random
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

load_dotenv()

MODELO = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
ARQUIVO_SAIDA = Path(__file__).resolve().parent.parent / "data" / "avaliacoes_ficticias.csv"

# Seed fixa: rodar de novo sorteia os mesmos lotes, datas e restaurantes.
random.seed(42)

TEMAS = ["atraso", "pedido_errado", "qualidade", "preco", "embalagem", "atendimento"]

# Mais negativas que positivas, porque o objetivo do Radar é achar problemas.
SENTIMENTOS = {"negativo": 0.55, "neutro": 0.15, "positivo": 0.30}

# Nomes inventados. Qualquer semelhança com restaurante real é coincidência.
# O tipo de comida vai no prompt, para o texto combinar com o restaurante (sem sushi na pizzaria).
RESTAURANTES = {
    "Cantina da Nona Fictícia": "massas e comida italiana",
    "Burger Lab Demo": "hambúrgueres e batata frita",
    "Sushi Exemplo": "sushi e comida japonesa",
    "Marmitaria Teste": "marmitas e pratos feitos",
    "Pizzaria Imaginária": "pizzas",
    "Açaí Protótipo": "açaí e sobremesas",
    "Esfiharia Mock": "esfihas e comida árabe",
    "Churrasquinho Sandbox": "espetinhos e churrasco",
}

DIAS_DE_HISTORICO = 56  # 8 semanas, para o dashboard mostrar tendência no tempo


class AvaliacaoGerada(BaseModel):
    """O que o LLM precisa devolver. O resto o Python preenche."""

    texto: str = Field(description="Texto da avaliação, como um cliente escreveria no app")
    nota: int = Field(ge=1, le=5, description="Nota de 1 a 5 estrelas")


def montar_prompt(tema: str, sentimento: str, tipo_comida: str, quantidade: int) -> str:
    return f"""Você está criando dados FICTÍCIOS para testar um sistema de análise de avaliações
de um app de delivery de comida no Brasil.

Escreva {quantidade} avaliações diferentes de clientes sobre pedidos de um restaurante de {tipo_comida}.
- Tema principal: {tema.replace("_", " ")}
- Sentimento: {sentimento}
- Português do Brasil informal, como no app: algumas curtas (1 frase), outras com 3 ou 4 frases.
- Varie o prato, o tom, erros de digitação leves e gírias. Não repita estruturas.
- Algumas podem citar um segundo assunto de passagem, mas o tema principal deve ser claro.
- NÃO inclua nomes de pessoas, telefones, endereços nem nomes de restaurantes ou marcas reais.
- A nota deve ser coerente com o sentimento (negativo 1-2, neutro 3, positivo 4-5)."""


def gerar_lote(cliente: genai.Client, tema: str, sentimento: str, restaurante: str, quantidade: int) -> list[AvaliacaoGerada]:
    """Chama o Gemini pedindo JSON no formato list[AvaliacaoGerada]. Tenta até 3 vezes se a API falhar."""
    for tentativa in range(1, 4):
        try:
            resposta = cliente.models.generate_content(
                model=MODELO,
                contents=montar_prompt(tema, sentimento, RESTAURANTES[restaurante], quantidade),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=list[AvaliacaoGerada],
                    temperature=1.0,  # mais variedade nos textos
                ),
            )
            itens = resposta.parsed  # o SDK já converte o JSON para objetos pydantic
            if itens:
                return itens
            print(f"  resposta vazia (tentativa {tentativa})")
        except errors.ClientError as erro:
            # 429 = limite de requisições: vale esperar e tentar de novo.
            # Outros 4xx (chave inválida, modelo inexistente...) não melhoram com nova tentativa.
            if erro.code != 429:
                raise SystemExit(f"Erro {erro.code} na API, sem nova tentativa: {erro.message}")
            print(f"  limite de requisições (tentativa {tentativa}), aguardando...")
        except Exception as erro:
            print(f"  erro na API (tentativa {tentativa}): {erro}")
        time.sleep(10 * tentativa)  # espera mais a cada falha (limite do plano gratuito)
    return []


def sortear_lotes(qtd_lotes: int) -> list[tuple[str, str, str]]:
    """Cada lote = (tema, sentimento, restaurante). Todas as avaliações do lote são do mesmo restaurante."""
    nomes = list(SENTIMENTOS)
    pesos = list(SENTIMENTOS.values())
    return [
        (random.choice(TEMAS), random.choices(nomes, pesos)[0], random.choice(list(RESTAURANTES)))
        for _ in range(qtd_lotes)
    ]


def main():
    parser = argparse.ArgumentParser(description="Gera avaliações fictícias com o Gemini")
    parser.add_argument("--lotes", type=int, default=20, help="quantidade de chamadas ao LLM")
    parser.add_argument("--por-lote", type=int, default=10, help="avaliações por chamada")
    parser.add_argument("--anexar", action="store_true", help="mantém o CSV atual e acrescenta as novas")
    args = parser.parse_args()

    cliente = genai.Client()  # lê GEMINI_API_KEY do ambiente (.env)
    hoje = date.today()
    linhas = []

    if args.anexar and ARQUIVO_SAIDA.exists():
        with open(ARQUIVO_SAIDA, encoding="utf-8-sig") as f:
            linhas = list(csv.DictReader(f))
        # Seed diferente da original, senão os lotes sorteados seriam os mesmos de antes.
        random.seed(len(linhas))
        print(f"Anexando ao CSV existente ({len(linhas)} avaliações)")

    for i, (tema, sentimento, restaurante) in enumerate(sortear_lotes(args.lotes), start=1):
        print(f"Lote {i}/{args.lotes}: {tema} / {sentimento} / {restaurante}")
        for item in gerar_lote(cliente, tema, sentimento, restaurante, args.por_lote):
            linhas.append({
                "id": len(linhas) + 1,
                "data": (hoje - timedelta(days=random.randint(0, DIAS_DE_HISTORICO - 1))).isoformat(),
                "restaurante": restaurante,
                "nota": item.nota,
                "texto": item.texto.strip(),
                # O que eu PEDI ao LLM. Serve de referência, mas não é rótulo garantido:
                # a avaliação de qualidade do agente usa 30 rótulos feitos à mão.
                "tema_pedido": tema,
                "sentimento_pedido": sentimento,
                "ficticio": True,
            })
        time.sleep(6)  # respeita o limite de requisições por minuto do plano gratuito

    if not linhas:
        print("Nenhuma avaliação gerada. Confira a chave e o modelo no .env.")
        return

    ARQUIVO_SAIDA.parent.mkdir(exist_ok=True)
    # utf-8-sig para o Excel abrir os acentos certo
    with open(ARQUIVO_SAIDA, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=linhas[0].keys())
        escritor.writeheader()
        escritor.writerows(linhas)

    print(f"\n{len(linhas)} avaliações fictícias salvas em {ARQUIVO_SAIDA}")


if __name__ == "__main__":
    main()
