# 📡 Radar de Avaliações

Um restaurante recebe muitas avaliações e não consegue ler todas, então a reclamação que se repete passa batido. Construí este agente para ler as avaliações, dizer do que estão reclamando, se está piorando e o que responder primeiro.

> ⚠️ **Todos os dados são fictícios**, gerados por LLM. Nenhuma avaliação, cliente ou restaurante é real.

## O que ele faz

- **Classifica cada avaliação:** sentimento, tema, gravidade, motivo e uma sugestão de resposta ao cliente.
- **Mostra o que importa num dashboard:** o que mais gera reclamação, a evolução por semana, restaurante por tema e a fila "Responder primeiro".
- **Responde perguntas sobre os dados**, como "quais os 3 maiores problemas da última semana?".

## Como funciona

```
CSV fictício ──► Agente (Gemini + validação) ──► SQLite ──► Dashboard em Streamlit
                       │                                          │
           rejeitou? reenvia só o item,                  pergunta em português:
           junto com o erro (até 3 tentativas)           o Python calcula, o LLM explica
```

Decisões que tomei:

- **Lotes de 10 avaliações por chamada.** No plano gratuito, um dos modelos que testei tinha limite de 20 requisições por dia. Com uma chamada por avaliação, nem daria para rodar.
- **Duas camadas de validação.** O schema garante o formato. O pydantic garante as regras que o schema não expressa, como não prometer reembolso, cupom ou desconto na resposta, porque isso é decisão do restaurante.
- **Nova tentativa só quando faz sentido.** Limite por minuto e servidor fora esperam e tentam de novo. Cota diária acabada e modelo inexistente param na hora.
- **O LLM não gera SQL.** Em "Pergunte aos dados", o Python monta um resumo e o modelo só lê. Um bug real mostrou por que isso importa: no começo, ele contava os itens no olho e respondeu "pedido errado: 4" quando o banco tinha 2. Passei a enviar a tabela de semana por tema já calculada e conferi as respostas com o banco.

## Resultados

**Execução nas 200 avaliações, com `gemini-3.1-flash-lite`:**

| Métrica | Valor |
|---|---|
| Classificadas | 200 de 200, sem falhas |
| Chamadas ao LLM | 20 |
| Tokens | 14.368 de entrada + 22.841 de saída (cerca de 186 por avaliação) |
| Tempo de API | 145 s |
| Volume para 1.000 avaliações | cerca de 186 mil tokens (projeção) |
| Custo | zero no plano gratuito, respeitando os limites dele |

Nenhuma avaliação precisou de correção nessa execução. Quem cobre a lógica de reenvio são os testes da validação.

**Comparação com 30 rótulos feitos à mão por mim (5 por tema, sem ver a resposta do agente):**

| Campo | Acerto |
|---|---|
| Tema | 24/30 (80%) |
| Sentimento | 20/30 (67%) |
| Gravidade | 20/30 (67%) |

É um retrato pequeno, de uma amostra escolhida por tema, e não uma medida precisa de toda a base. Mesmo assim, as divergências mostram onde melhorar:

- **Sentimento:** nas 10 divergências, eu marquei neutro e o agente escolheu um lado. Ele tem dificuldade com avaliações mistas, como "atrasou, mas estava ótimo".
- **Gravidade:** em 9 das 10 divergências, o agente deu uma gravidade menor que a minha. Reclamações de preço caíram várias vezes em "baixa".
- **Tema:** boa parte das divergências é de avaliações com dois assuntos, em que é preciso decidir qual pesou mais.

## Limites e riscos

- Os dados são sintéticos. Avaliações reais seriam mais bagunçadas e teriam dados pessoais (LGPD).
- O modelo pode errar ou alucinar, então a resposta sugerida é só um rascunho e precisa de revisão humana.
- Antes de produção, eu ajustaria os critérios de sentimento e gravidade e mediria de novo com uma amostra maior.

## Como construí

Comecei o dashboard no **Cursor** (filtros e indicadores) e terminei no **Claude Code**, usando agentes separados para layout e gráficos. O agente, a validação e os dados também foram feitos com o Claude Code. Revisei o resultado, testei no navegador e comparei os números com o banco, e foi assim que os erros acima apareceram.

## Stack

Python · API Gemini (`google-genai`) · pydantic · SQLite · Streamlit · pandas · Plotly · pytest

## Como rodar

```bash
git clone https://github.com/zabriduel/radar-avaliacoes.git
cd radar-avaliacoes
python -m venv .venv
.venv\Scripts\activate          # no Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

Copie o `.env.example` para `.env` e coloque a sua chave do [Google AI Studio](https://aistudio.google.com/apikey). Ela só é necessária para "Pergunte aos dados" e para classificar de novo, porque o banco com as 200 avaliações já vem no repositório.

```bash
streamlit run app.py
python -m pytest -q
python src/classificar_todas.py
python src/avaliar_agente.py calcular
```

## Próximos passos

- Fluxo no n8n: receber uma avaliação nova e avisar no Telegram quando a gravidade for alta.
- Ajustar os critérios a partir das divergências e medir de novo.
