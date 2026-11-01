"""
Agente classificador do Radar de Avaliações.

Para cada avaliação, devolve: sentimento, tema, gravidade, uma resposta sugerida ao cliente
e o motivo da classificação.

Decisões principais:
- Classifico em LOTES (várias avaliações por chamada). O plano gratuito do Gemini tem limite
  diário de requisições, e 1 chamada por avaliação estouraria esse limite.
- O schema JSON (response_schema) garante o FORMATO. As regras de NEGÓCIO (ex.: avaliação
  positiva não pode ter gravidade alta; a resposta não pode prometer reembolso) quem garante
  é a validação com pydantic, aqui no Python.
- Se alguma classificação for rejeitada, mando de novo SÓ as que falharam, junto com o erro,
  para o modelo corrigir. Até 2 novas tentativas (3 no total).
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field, ValidationError, model_validator

load_dotenv()

MODELO = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
MAX_TENTATIVAS = 3  # 1 tentativa normal + 2 de correção

# Palavras que indicam promessa de compensação. Quem decide isso é o restaurante, não a IA.
PROMESSA_COMPENSACAO = re.compile(r"reembols|estorn|cupom|cupons|desconto|dinheiro de volta|ressarc", re.IGNORECASE)


class Classificacao(BaseModel):
    """Uma avaliação classificada. Os Literal viram 'enum' no schema enviado ao Gemini."""

    id: int
    sentimento: Literal["negativo", "neutro", "positivo"]
    tema: Literal["atraso", "pedido_errado", "qualidade", "preco", "embalagem", "atendimento"]
    gravidade: Literal["baixa", "media", "alta"]
    resposta_sugerida: str = Field(description="Resposta ao cliente em nome do restaurante, até 3 frases")
    motivo: str = Field(description="Uma frase curta explicando a classificação")

    @model_validator(mode="after")
    def regras_de_negocio(self):
        if self.sentimento == "positivo" and self.gravidade != "baixa":
            raise ValueError("avaliação positiva deve ter gravidade 'baixa'")
        if PROMESSA_COMPENSACAO.search(self.resposta_sugerida):
            raise ValueError(
                "a resposta_sugerida não pode prometer reembolso, cupom ou desconto: "
                "compensação é decisão do restaurante"
            )
        if not 20 <= len(self.resposta_sugerida) <= 400:
            raise ValueError("a resposta_sugerida deve ter entre 20 e 400 caracteres")
        return self


@dataclass
class ResultadoLote:
    classificacoes: dict[int, Classificacao] = field(default_factory=dict)
    tentativas: dict[int, int] = field(default_factory=dict)  # id -> em qual tentativa passou
    falhas: dict[int, str] = field(default_factory=dict)      # id -> último erro
    chamadas: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    segundos: float = 0.0


INSTRUCOES = """Você é um analista de experiência do cliente de um app de delivery de comida no Brasil.
Classifique cada avaliação abaixo.

TEMA (escolha o principal, ou seja, o que mais incomodou ou mais agradou o cliente):
- atraso: demora na entrega ou no preparo
- pedido_errado: item trocado, faltando ou diferente do que foi pedido
- qualidade: sabor, temperatura, ponto, frescor ou higiene da comida
- preco: valor, custo-benefício ou taxas
- embalagem: vazamento, embalagem amassada, lacre ou cuidado com a embalagem
- atendimento: comunicação e educação do restaurante, do suporte ou do entregador

GRAVIDADE:
- alta: risco à saúde (comida estragada, corpo estranho, mal-estar, alergia), pedido não entregue ou desrespeito grave
- media: problema real que estragou a experiência
- baixa: incômodo leve, comentário neutro ou elogio

RESPOSTA_SUGERIDA: em nome do restaurante, cordial, até 3 frases, citando o ponto específico da avaliação.
NÃO prometa reembolso, cupom ou desconto (quem decide compensação é o restaurante) e não invente fatos.

MOTIVO: uma frase curta explicando por que escolheu o tema e a gravidade.

Devolva uma classificação para CADA avaliação, com o mesmo id."""


def montar_prompt(avaliacoes: list[dict], erros_anteriores: dict[int, str]) -> str:
    linhas = [INSTRUCOES, "", "AVALIAÇÕES:"]
    linhas += [f"[id {a['id']}] {a['texto']}" for a in avaliacoes]
    if erros_anteriores:
        linhas += ["", "ATENÇÃO: na tentativa anterior, estas classificações foram rejeitadas pela validação. Corrija:"]
        linhas += [f"- id {i}: {erro}" for i, erro in erros_anteriores.items()]
    return "\n".join(linhas)


def validar_resposta(texto_json: str, ids_esperados: set[int]) -> tuple[dict[int, Classificacao], dict[int, str]]:
    """
    Confere a resposta do modelo, item por item.
    Devolve (classificações válidas, erros por id). Função pura: dá para testar sem chamar a API.
    """
    try:
        itens = json.loads(texto_json)
    except json.JSONDecodeError as erro:
        return {}, {i: f"a resposta não era um JSON válido ({erro.msg})" for i in ids_esperados}

    validas, erros = {}, {}
    for item in itens if isinstance(itens, list) else []:
        id_item = item.get("id") if isinstance(item, dict) else None
        if id_item not in ids_esperados:
            continue  # id inventado ou repetido: ignoro
        try:
            validas[id_item] = Classificacao.model_validate(item)
        except ValidationError as erro:
            erros[id_item] = "; ".join(e["msg"] for e in erro.errors())

    for faltando in ids_esperados - validas.keys() - erros.keys():
        erros[faltando] = "esta avaliação não veio na resposta"
    return validas, erros


def chamar_gemini(cliente: genai.Client, prompt: str) -> types.GenerateContentResponse:
    """Chamada com nova tentativa só para erro de infraestrutura (limite por minuto, servidor fora)."""
    for tentativa in range(1, 5):
        try:
            return cliente.models.generate_content(
                model=MODELO,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=list[Classificacao],
                    temperature=0.2,  # baixa: quero classificação consistente, não criativa
                ),
            )
        except errors.ClientError as erro:
            if erro.code != 429:
                raise  # chave inválida, modelo inexistente...: não adianta repetir
            if "per day" in str(erro):
                raise  # cota diária acabou: esperar segundos não resolve
            print(f"    limite por minuto, aguardando ({tentativa})...")
        except Exception as erro:  # 503, conexão caída
            print(f"    erro de servidor ({tentativa}): {str(erro)[:80]}")
        time.sleep(15 * tentativa)
    raise RuntimeError("a API não respondeu depois de 4 tentativas")


def classificar_lote(cliente: genai.Client, avaliacoes: list[dict]) -> ResultadoLote:
    """Classifica uma lista de {'id', 'texto'}. Reenvia só o que falhou na validação."""
    resultado = ResultadoLote()
    pendentes = list(avaliacoes)
    erros: dict[int, str] = {}

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        inicio = time.perf_counter()
        resposta = chamar_gemini(cliente, montar_prompt(pendentes, erros))
        resultado.segundos += time.perf_counter() - inicio
        resultado.chamadas += 1
        uso = resposta.usage_metadata
        if uso:
            resultado.tokens_entrada += uso.prompt_token_count or 0
            resultado.tokens_saida += (uso.candidates_token_count or 0) + (uso.thoughts_token_count or 0)

        validas, erros = validar_resposta(resposta.text or "", {a["id"] for a in pendentes})
        for id_ok, classif in validas.items():
            resultado.classificacoes[id_ok] = classif
            resultado.tentativas[id_ok] = tentativa

        if not erros:
            break
        print(f"    tentativa {tentativa}: {len(erros)} rejeitada(s), reenviando com o erro")
        pendentes = [a for a in pendentes if a["id"] in erros]

    resultado.falhas = erros
    return resultado


if __name__ == "__main__":
    # Teste rápido: python src/agente.py
    exemplo = [
        {"id": 1, "texto": "Pizza chegou fria e com 1h de atraso, e o motoboy ainda foi grosso."},
        {"id": 2, "texto": "Achei um fio de cabelo no hambúrguer, nojento."},
        {"id": 3, "texto": "Açaí perfeito, bem servido e chegou rápido!"},
    ]
    r = classificar_lote(genai.Client(), exemplo)
    for i, c in r.classificacoes.items():
        print(f"[{i}] {c.sentimento} | {c.tema} | {c.gravidade} | {c.resposta_sugerida}")
    print(f"chamadas={r.chamadas} tokens={r.tokens_entrada}+{r.tokens_saida} falhas={r.falhas}")
