"""
Gráficos do dashboard. Cada função recebe os dados e devolve uma figura plotly.

Decisões que valem para os três:
- A cor do texto dos eixos não é definida aqui: vem do tema do Streamlit.
- O fundo do gráfico é transparente, para aparecer o fundo da página.
- Os dados originais não mudam: os nomes bonitos só existem na hora de desenhar.
"""

import math

import pandas as pd
import plotly.graph_objects as go

# Paleta do tema (.streamlit/config.toml). Reclamação é o destaque, então usa a cor de problema.
COR_DESTAQUE = "#D9485F"  # coral: a cor de "problema" do tema
COR_NEUTRA = "#7A869A"  # cinza-azulado das barras sem destaque
COR_GRADE = "rgba(122, 134, 154, 0.25)"
COR_ZERO = "rgba(122, 134, 154, 0.10)"  # célula sem reclamação no heatmap
COR_CELULA_MIN = "#FBE3E7"  # célula com poucas reclamações: coral bem claro
TRANSPARENTE = "rgba(0, 0, 0, 0)"

ALTURA_LINHA_PX = 44  # altura de cada barra ou linha do heatmap, com o respiro
ALTURA_GRAFICO_LINHA = 320

# A fonte do tema é mais larga que a medida pelo plotly e cortava o começo dos nomes.
# Espaços antes do rótulo fazem o plotly reservar essa folga na margem.
FOLGA_ROTULO = " " * 6

ROTULOS_TEMA = {
    "atraso": "Atraso",
    "pedido_errado": "Pedido errado",
    "qualidade": "Qualidade",
    "preco": "Preço",
    "embalagem": "Embalagem",
    "atendimento": "Atendimento",
}


def _rotulo_tema(tema: str) -> str:
    """Nome legível do tema. Um tema novo no banco aparece sem underline, em vez de quebrar."""
    return ROTULOS_TEMA.get(tema, tema.replace("_", " ").capitalize())


def _reclamacoes(n: int) -> str:
    """Texto do hover, com o plural certo."""
    if n == 0:
        return "nenhuma reclamação"
    return "1 reclamação" if n == 1 else f"{n} reclamações"


def _layout_base(figura: go.Figure, altura: int) -> go.Figure:
    """O que os três gráficos têm em comum: fundo transparente, sem legenda e sem zoom."""
    figura.update_layout(
        height=altura,
        paper_bgcolor=TRANSPARENTE,
        plot_bgcolor=TRANSPARENTE,
        showlegend=False,
        dragmode=False,  # arrastar sem querer daria zoom, e aqui isso não ajuda ninguém
        margin=dict(l=0, r=28, t=16, b=0),  # à direita cabe o número da ponta da linha
    )
    figura.update_xaxes(fixedrange=True, showgrid=False, zeroline=False)
    # automargin reserva espaço para os rótulos do eixo: sem ele, a margem 0 corta os nomes.
    figura.update_yaxes(fixedrange=True, showgrid=False, zeroline=False, automargin=True)
    return figura


def fig_por_tema(negativas: pd.DataFrame) -> go.Figure:
    """Barras horizontais por tema, da maior para a menor. O maior fica em destaque."""
    figura = go.Figure()
    if negativas.empty:
        return _layout_base(figura, ALTURA_GRAFICO_LINHA)

    # Em caso de empate, a ordem alfabética evita que as barras troquem de lugar à toa.
    contagem = negativas["tema"].value_counts().rename_axis("tema").reset_index(name="negativas")
    contagem["rotulo"] = contagem["tema"].map(_rotulo_tema)
    contagem = contagem.sort_values(["negativas", "rotulo"], ascending=[False, True])

    maior = contagem["negativas"].max()
    figura.add_bar(
        x=contagem["negativas"],
        y=contagem["rotulo"],
        orientation="h",
        # Destaque só no maior (ou nos empatados): é a resposta da pergunta.
        marker_color=[COR_DESTAQUE if n == maior else COR_NEUTRA for n in contagem["negativas"]],
        marker_line_width=0,
        text=contagem["negativas"],
        textposition="outside",
        cliponaxis=False,
        customdata=[_reclamacoes(int(n)) for n in contagem["negativas"]],
        hovertemplate="%{y}: %{customdata}<extra></extra>",
    )

    figura.update_layout(bargap=0.45, barcornerradius=4)
    # Cada barra já mostra o número, então o eixo de contagem só repetiria a informação.
    # A folga de 15% no range deixa espaço para o número na ponta da maior barra.
    figura.update_xaxes(visible=False, range=[0, maior * 1.15])
    figura.update_yaxes(type="category", autorange="reversed", tickprefix=FOLGA_ROTULO, ticksuffix="  ")
    # A altura cresce com o número de temas: com um tema só, a barra não vira um bloco.
    return _layout_base(figura, ALTURA_LINHA_PX * len(contagem) + 40)


def fig_por_semana(por_semana: pd.DataFrame) -> go.Figure:
    """Linha por semana. O trecho até a semana mais recente é tracejado: ela pode estar incompleta."""
    figura = go.Figure()
    if por_semana.empty:
        return _layout_base(figura, ALTURA_GRAFICO_LINHA)

    dados = por_semana.sort_values("semana")
    semanas = dados["semana"].tolist()
    valores = [int(v) for v in dados["negativas"]]
    ultima = len(semanas) - 1

    # Duas linhas: uma sólida até a penúltima semana e uma tracejada no último trecho.
    # Com uma semana só, não há o que ligar: o gráfico mostra apenas o ponto.
    estilo_linha = dict(color=COR_DESTAQUE, width=2)
    if ultima >= 2:
        figura.add_scatter(
            x=semanas[:ultima], y=valores[:ultima], mode="lines",
            line=estilo_linha, hoverinfo="skip",
        )
    if ultima >= 1:
        figura.add_scatter(
            x=semanas[-2:], y=valores[-2:], mode="lines",
            line={**estilo_linha, "dash": "dot"}, hoverinfo="skip",
        )

    # Os pontos ficam num traço próprio. Assim cada semana tem um hover só.
    # O último ponto é vazado, e só ele traz o número: rótulo em todos viraria ruído.
    hover = [f"Semana de {s:%d/%m/%Y}<br>{_reclamacoes(v)}" for s, v in zip(semanas, valores)]
    hover[-1] += "<br>Semana mais recente: pode estar incompleta"
    figura.add_scatter(
        x=semanas,
        y=valores,
        mode="markers+text",
        marker=dict(
            size=9,
            color=[COR_DESTAQUE] * ultima + [TRANSPARENTE],
            line=dict(color=COR_DESTAQUE, width=2),
        ),
        text=[""] * ultima + [str(valores[-1])],
        textposition="middle right",  # à direita, para não ficar em cima do tracejado
        cliponaxis=False,
        customdata=hover,
        hovertemplate="%{customdata}<extra></extra>",
    )

    # Eixo de contagem: sempre a partir de zero e de inteiro em inteiro (ou de 2 em 2, 5 em 5...).
    # Sem isso, com poucos dados o plotly desenha 0,5 e 1,5.
    maior = max(max(valores), 1)
    figura.update_yaxes(
        title_text="Reclamações por semana",
        range=[0, maior * 1.2],
        tick0=0,
        dtick=max(1, math.ceil(maior / 5)),
        tickformat="d",
        showgrid=True,
        gridcolor=COR_GRADE,
    )

    # Datas escritas por nós: no máximo uns 6 rótulos, e nunca uma hora no eixo de uma semana só.
    passo = max(1, math.ceil(len(semanas) / 6))
    marcas = semanas[::passo]
    figura.update_xaxes(tickvals=marcas, ticktext=[f"{s:%d/%m}" for s in marcas])

    figura = _layout_base(figura, ALTURA_GRAFICO_LINHA)
    figura.update_layout(hovermode="closest", hoverdistance=50)
    return figura


def fig_heatmap(negativas: pd.DataFrame) -> go.Figure:
    """Restaurante x tema. Os maiores totais ficam em cima e à esquerda; zero fica sem número."""
    figura = go.Figure()
    if negativas.empty:
        return _layout_base(figura, ALTURA_GRAFICO_LINHA)

    # .map() faz uma cópia da coluna: o DataFrame recebido continua com os nomes do banco.
    cruzamento = pd.crosstab(negativas["restaurante"], negativas["tema"].map(_rotulo_tema))

    # Ordem por total, com desempate alfabético: os focos de problema ficam agrupados no canto.
    ordem_linhas = cruzamento.sum(axis=1).reset_index(name="t").sort_values(
        ["t", "restaurante"], ascending=[False, True])["restaurante"]
    ordem_colunas = cruzamento.sum(axis=0).reset_index(name="t").sort_values(
        ["t", "tema"], ascending=[False, True])["tema"]
    cruzamento = cruzamento.loc[ordem_linhas, ordem_colunas]

    temas = cruzamento.columns.tolist()
    restaurantes = cruzamento.index.tolist()
    maior = int(cruzamento.to_numpy().max())

    # Escala de um tom só, do coral bem claro ao coral do tema.
    # Abaixo de 0,5 é o zero, em cinza quase invisível: como as contagens são inteiras,
    # nenhum valor real cai nessa faixa além do próprio zero.
    limite_zero = 0.5 / maior
    escala = [
        [0, COR_ZERO],
        [limite_zero, COR_ZERO],
        [limite_zero, COR_CELULA_MIN],
        [1, COR_DESTAQUE],
    ]

    valores = cruzamento.to_numpy()
    figura.add_heatmap(
        z=valores,
        x=temas,
        y=restaurantes,
        zmin=0,
        zmax=maior,
        colorscale=escala,
        showscale=False,  # o número está na célula, então a régua de cores sobraria
        xgap=2,  # o espaço entre as células separa melhor que uma borda
        ygap=2,
        text=[[str(n) if n > 0 else "" for n in linha] for linha in valores],  # zero sem número
        texttemplate="%{text}",
        textfont=dict(size=13),  # sem cor fixa: o plotly usa claro no fundo escuro e vice-versa
        customdata=[[_reclamacoes(int(n)) for n in linha] for linha in valores],
        hovertemplate="%{y}<br>%{x}: %{customdata}<extra></extra>",
    )

    # automargin reserva o espaço do nome inteiro do restaurante, sem cortar.
    figura.update_xaxes(type="category", side="top", tickangle=0, automargin=True)
    figura.update_yaxes(type="category", autorange="reversed", automargin=True, tickprefix=FOLGA_ROTULO, ticksuffix="  ")
    return _layout_base(figura, ALTURA_LINHA_PX * len(restaurantes) + 50)
