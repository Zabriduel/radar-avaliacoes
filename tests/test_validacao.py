"""
Testes da validação do agente. Não chamam a API: testam só as regras que o Python aplica
sobre a resposta do modelo.

Rodar: python -m pytest
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agente import validar_resposta  # noqa: E402

RESPOSTA_OK = "Poxa, sentimos muito pelo atraso no seu pedido. Vamos rever nosso tempo de preparo."


def item(**mudancas):
    """Uma classificação válida, com os campos que o teste quiser trocar."""
    base = {
        "id": 1,
        "sentimento": "negativo",
        "tema": "atraso",
        "gravidade": "media",
        "resposta_sugerida": RESPOSTA_OK,
        "motivo": "Cliente reclama da demora.",
    }
    return base | mudancas


def validar(*itens, ids=None):
    ids = ids or {i["id"] for i in itens}
    return validar_resposta(json.dumps(list(itens)), ids)


def test_classificacao_valida_passa():
    validas, erros = validar(item())
    assert 1 in validas and not erros


def test_positiva_com_gravidade_alta_e_rejeitada():
    _, erros = validar(item(sentimento="positivo", gravidade="alta"))
    assert "gravidade 'baixa'" in erros[1]


def test_resposta_prometendo_reembolso_e_rejeitada():
    _, erros = validar(item(resposta_sugerida="Sentimos muito! Vamos fazer o reembolso do seu pedido hoje."))
    assert "reembolso" in erros[1]


def test_tema_fora_da_lista_e_rejeitado():
    _, erros = validar(item(tema="higiene"))
    assert 1 in erros


def test_avaliacao_que_nao_veio_na_resposta_vira_erro():
    validas, erros = validar(item(id=1), ids={1, 2})
    assert 1 in validas
    assert erros[2] == "esta avaliação não veio na resposta"


def test_id_inventado_e_ignorado():
    validas, erros = validar(item(id=99), ids={1})
    assert 99 not in validas and 99 not in erros
    assert 1 in erros


def test_json_quebrado_marca_todas_como_erro():
    validas, erros = validar_resposta('[{"id": 1, "sentimento": ', {1, 2})
    assert not validas
    assert set(erros) == {1, 2}
