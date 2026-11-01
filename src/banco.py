"""
Banco SQLite do Radar. Um arquivo só (data/radar.db), sem servidor: suficiente para o demo
e fácil de trocar por Postgres ou Google Sheets depois.

Tabelas:
- avaliacoes: os textos (vindos do CSV fictício ou, depois, do n8n)
- classificacoes: a saída do agente, 1 linha por avaliação
- chamadas_llm: 1 linha por lote classificado, para medir tempo, tokens e custo
"""

import csv
import sqlite3
from pathlib import Path

PASTA_DADOS = Path(__file__).resolve().parent.parent / "data"
CAMINHO_BANCO = PASTA_DADOS / "radar.db"
CAMINHO_CSV = PASTA_DADOS / "avaliacoes_ficticias.csv"


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(CAMINHO_BANCO)
    con.row_factory = sqlite3.Row  # permite acessar colunas pelo nome: linha["texto"]
    return con


def criar_tabelas(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS avaliacoes (
            id          INTEGER PRIMARY KEY,
            data        TEXT NOT NULL,
            restaurante TEXT NOT NULL,
            nota        INTEGER,
            texto       TEXT NOT NULL,
            ficticio    INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS classificacoes (
            id_avaliacao      INTEGER PRIMARY KEY REFERENCES avaliacoes(id),
            sentimento        TEXT NOT NULL,
            tema              TEXT NOT NULL,
            gravidade         TEXT NOT NULL,
            resposta_sugerida TEXT NOT NULL,
            motivo            TEXT,
            tentativas        INTEGER NOT NULL,
            modelo            TEXT NOT NULL,
            classificado_em   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS chamadas_llm (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            momento        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            modelo         TEXT NOT NULL,
            avaliacoes     INTEGER NOT NULL,
            chamadas       INTEGER NOT NULL,
            tokens_entrada INTEGER NOT NULL,
            tokens_saida   INTEGER NOT NULL,
            segundos       REAL NOT NULL,
            falhas         INTEGER NOT NULL
        );
    """)


def importar_csv(con: sqlite3.Connection, caminho: Path = CAMINHO_CSV) -> int:
    """Copia o CSV para a tabela avaliacoes. Ids que já existem são ignorados. Devolve quantas entraram."""
    with open(caminho, encoding="utf-8-sig") as f:
        linhas = [
            (int(r["id"]), r["data"], r["restaurante"], int(r["nota"]), r["texto"])
            for r in csv.DictReader(f)
        ]
    antes = con.total_changes
    con.executemany(
        "INSERT OR IGNORE INTO avaliacoes (id, data, restaurante, nota, texto) VALUES (?, ?, ?, ?, ?)",
        linhas,
    )
    con.commit()
    return con.total_changes - antes


def avaliacoes_pendentes(con: sqlite3.Connection, limite: int) -> list[dict]:
    """Avaliações que ainda não foram classificadas. Rodar o script de novo continua de onde parou."""
    linhas = con.execute("""
        SELECT a.id, a.texto FROM avaliacoes a
        LEFT JOIN classificacoes c ON c.id_avaliacao = a.id
        WHERE c.id_avaliacao IS NULL
        ORDER BY a.id LIMIT ?
    """, (limite,)).fetchall()
    return [dict(l) for l in linhas]


def salvar_classificacao(con: sqlite3.Connection, c, tentativas: int, modelo: str) -> None:
    con.execute("""
        INSERT OR REPLACE INTO classificacoes
            (id_avaliacao, sentimento, tema, gravidade, resposta_sugerida, motivo, tentativas, modelo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (c.id, c.sentimento, c.tema, c.gravidade, c.resposta_sugerida, c.motivo, tentativas, modelo))


def registrar_chamada(con: sqlite3.Connection, modelo: str, resultado, qtd_avaliacoes: int) -> None:
    con.execute("""
        INSERT INTO chamadas_llm (modelo, avaliacoes, chamadas, tokens_entrada, tokens_saida, segundos, falhas)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (modelo, qtd_avaliacoes, resultado.chamadas, resultado.tokens_entrada,
          resultado.tokens_saida, round(resultado.segundos, 2), len(resultado.falhas)))
