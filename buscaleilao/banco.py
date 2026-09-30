"""Armazenamento dos lotes em SQLite e consultas de busca."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .modelos import Lote
from .normalizacao import chave, normalizar_categoria, normalizar_marca, normalizar_monta

CAMINHO_PADRAO = Path("buscaleilao.db")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS lotes (
    fonte TEXT NOT NULL,
    id_externo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    leilao TEXT,
    url TEXT,
    categoria TEXT,
    marca TEXT,
    modelo TEXT,
    versao TEXT,
    ano_fabricacao INTEGER,
    ano_modelo INTEGER,
    monta TEXT,
    condicao TEXT,
    combustivel TEXT,
    cor TEXT,
    km INTEGER,
    cidade TEXT,
    uf TEXT,
    lance_inicial REAL,
    lance_atual REAL,
    valor_fipe REAL,
    data_leilao TEXT,
    imagem_url TEXT,
    descricao TEXT,
    coletado_em TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    busca TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (fonte, id_externo)
);
CREATE INDEX IF NOT EXISTS ix_lotes_categoria ON lotes (categoria);
CREATE INDEX IF NOT EXISTS ix_lotes_marca ON lotes (marca);
CREATE INDEX IF NOT EXISTS ix_lotes_monta ON lotes (monta);
CREATE INDEX IF NOT EXISTS ix_lotes_leilao ON lotes (fonte, leilao);
CREATE INDEX IF NOT EXISTS ix_lotes_data ON lotes (data_leilao);
"""

_CAMPOS = Lote.campos()

# Colunas que podem ser usadas para ordenar resultados.
ORDENACOES = {
    "data": "data_leilao IS NULL, data_leilao",
    "lance": "COALESCE(lance_atual, lance_inicial) IS NULL, COALESCE(lance_atual, lance_inicial)",
    "lance_desc": "COALESCE(lance_atual, lance_inicial) DESC",
    "ano": "ano_modelo DESC",
    "km": "km IS NULL, km",
    "marca": "marca, modelo",
}

# Dimensões para as quais geramos contagens (facetas) na busca.
FACETAS = ("fonte", "leilao", "categoria", "marca", "monta", "condicao", "uf", "combustivel")


@dataclass
class Filtros:
    texto: str | None = None
    categoria: list[str] | None = None
    marca: list[str] | None = None
    modelo: str | None = None
    monta: list[str] | None = None
    condicao: list[str] | None = None
    fonte: list[str] | None = None
    leilao: list[str] | None = None
    uf: list[str] | None = None
    cidade: str | None = None
    combustivel: list[str] | None = None
    ano_min: int | None = None
    ano_max: int | None = None
    km_max: int | None = None
    lance_min: float | None = None
    lance_max: float | None = None
    data_de: datetime | None = None
    data_ate: datetime | None = None
    apenas_futuros: bool = False
    incluir_inativos: bool = False

    def sql(self) -> tuple[str, list]:
        cond: list[str] = []
        args: list = []

        def em(coluna: str, valores: list[str] | None, normalizar=None):
            if not valores:
                return
            vals = [normalizar(v) if normalizar else v for v in valores]
            vals = [v for v in vals if v]
            if vals:
                cond.append(f"{coluna} IN ({','.join('?' * len(vals))})")
                args.extend(vals)

        if not self.incluir_inativos:
            cond.append("ativo = 1")
        if self.texto:
            for palavra in chave(self.texto).split():
                cond.append("busca LIKE ?")
                args.append(f"%{palavra}%")
        em("categoria", self.categoria, normalizar_categoria)
        em("marca", self.marca, normalizar_marca)
        em("monta", self.monta, lambda m: "sem_monta" if chave(m) in ("sem", "sem monta", "sem_monta") else normalizar_monta(m))
        em("condicao", self.condicao)
        em("fonte", self.fonte)
        em("leilao", self.leilao)
        em("uf", [u.upper() for u in self.uf] if self.uf else None)
        em("combustivel", [chave(c) for c in self.combustivel] if self.combustivel else None)
        if self.modelo:
            cond.append("modelo LIKE ?")
            args.append(f"%{self.modelo.upper()}%")
        if self.cidade:
            cond.append("busca LIKE ?")
            args.append(f"%{chave(self.cidade)}%")
        if self.ano_min is not None:
            cond.append("ano_modelo >= ?")
            args.append(self.ano_min)
        if self.ano_max is not None:
            cond.append("ano_modelo <= ?")
            args.append(self.ano_max)
        if self.km_max is not None:
            cond.append("km <= ?")
            args.append(self.km_max)
        if self.lance_min is not None:
            cond.append("COALESCE(lance_atual, lance_inicial) >= ?")
            args.append(self.lance_min)
        if self.lance_max is not None:
            cond.append("COALESCE(lance_atual, lance_inicial) <= ?")
            args.append(self.lance_max)
        if self.data_de is not None:
            cond.append("data_leilao >= ?")
            args.append(self.data_de.isoformat())
        if self.data_ate is not None:
            cond.append("data_leilao <= ?")
            args.append(self.data_ate.isoformat())
        if self.apenas_futuros:
            cond.append("(data_leilao IS NULL OR data_leilao >= ?)")
            args.append(datetime.now().replace(microsecond=0).isoformat())

        return (" WHERE " + " AND ".join(cond)) if cond else "", args


def _texto_busca(lote: Lote) -> str:
    partes = [lote.titulo, lote.marca, lote.modelo, lote.versao, lote.categoria, lote.cor,
              lote.cidade, lote.uf, lote.leilao, lote.descricao, lote.combustivel]
    return chave(" ".join(p for p in partes if p))


def _linha_para_lote(linha: sqlite3.Row) -> dict:
    d = {k: linha[k] for k in _CAMPOS}
    d["ativo"] = bool(linha["ativo"])
    return d


class Banco:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO):
        self.caminho = str(caminho)
        with self._conexao() as con:
            con.executescript(_ESQUEMA)

    @contextmanager
    def _conexao(self):
        con = sqlite3.connect(self.caminho)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------------ escrita

    def salvar(self, lotes: list[Lote], fonte: str | None = None, desativar_ausentes: bool = False) -> int:
        """Insere/atualiza lotes. Com `desativar_ausentes`, os lotes da `fonte`
        que não vieram nesta coleta são marcados como inativos (já leiloados ou
        retirados)."""
        colunas = _CAMPOS + ["ativo", "busca"]
        marcadores = ",".join("?" * len(colunas))
        atualizacoes = ",".join(f"{c}=excluded.{c}" for c in colunas if c not in ("fonte", "id_externo"))
        sql = (
            f"INSERT INTO lotes ({','.join(colunas)}) VALUES ({marcadores}) "
            f"ON CONFLICT(fonte, id_externo) DO UPDATE SET {atualizacoes}"
        )
        with self._conexao() as con:
            for lote in lotes:
                d = lote.para_dict()
                con.execute(sql, [d[c] for c in _CAMPOS] + [1, _texto_busca(lote)])
            if desativar_ausentes and fonte:
                ids = [l.id_externo for l in lotes if l.fonte == fonte]
                con.execute("CREATE TEMP TABLE IF NOT EXISTS _vistos (id TEXT PRIMARY KEY)")
                con.execute("DELETE FROM _vistos")
                con.executemany("INSERT OR IGNORE INTO _vistos VALUES (?)", [(i,) for i in ids])
                con.execute(
                    "UPDATE lotes SET ativo = 0 WHERE fonte = ? AND id_externo NOT IN (SELECT id FROM _vistos)",
                    (fonte,),
                )
        return len(lotes)

    # ------------------------------------------------------------------ leitura

    def buscar(self, filtros: Filtros | None = None, ordem: str = "data",
               limite: int = 50, pagina: int = 1) -> dict:
        filtros = filtros or Filtros()
        where, args = filtros.sql()
        ordem_sql = ORDENACOES.get(ordem, ORDENACOES["data"])
        limite = max(1, min(limite, 500))
        deslocamento = (max(pagina, 1) - 1) * limite
        with self._conexao() as con:
            total = con.execute(f"SELECT COUNT(*) FROM lotes{where}", args).fetchone()[0]
            linhas = con.execute(
                f"SELECT * FROM lotes{where} ORDER BY {ordem_sql} LIMIT ? OFFSET ?",
                args + [limite, deslocamento],
            ).fetchall()
        return {
            "total": total,
            "pagina": max(pagina, 1),
            "por_pagina": limite,
            "lotes": [_linha_para_lote(l) for l in linhas],
        }

    def facetas(self, filtros: Filtros | None = None) -> dict[str, list[dict]]:
        """Contagem de lotes por categoria, marca, monta, leilão etc. dentro do
        resultado filtrado — é o que alimenta os filtros laterais da interface.

        Cada faceta ignora o próprio filtro, para que seja possível marcar mais
        de um valor na mesma dimensão (ex.: "carro" e "moto")."""
        filtros = filtros or Filtros()
        where, args = filtros.sql()
        resultado = {}
        with self._conexao() as con:
            for coluna in FACETAS:
                where_c, args_c = replace(filtros, **{coluna: None}).sql()
                linhas = con.execute(
                    f"SELECT {coluna} AS valor, COUNT(*) AS n FROM lotes{where_c} "
                    f"GROUP BY {coluna} ORDER BY n DESC, valor",
                    args_c,
                ).fetchall()
                resultado[coluna] = [{"valor": l["valor"], "total": l["n"]} for l in linhas]
            linha = con.execute(
                f"SELECT MIN(ano_modelo), MAX(ano_modelo), "
                f"MIN(COALESCE(lance_atual, lance_inicial)), MAX(COALESCE(lance_atual, lance_inicial)) "
                f"FROM lotes{where}",
                args,
            ).fetchone()
        resultado["faixas"] = {
            "ano_min": linha[0], "ano_max": linha[1], "lance_min": linha[2], "lance_max": linha[3],
        }
        return resultado

    def resumo_leiloes(self, filtros: Filtros | None = None) -> list[dict]:
        """O que tem em cada leilão: total de lotes e distribuição por categoria,
        monta e principais marcas."""
        where, args = (filtros or Filtros()).sql()
        with self._conexao() as con:
            leiloes = con.execute(
                f"SELECT fonte, leilao, COUNT(*) AS total, MIN(data_leilao) AS data_inicio, "
                f"MAX(data_leilao) AS data_fim, "
                f"MIN(COALESCE(lance_atual, lance_inicial)) AS menor_lance "
                f"FROM lotes{where} GROUP BY fonte, leilao ORDER BY data_inicio IS NULL, data_inicio",
                args,
            ).fetchall()
            resumo = []
            for l in leiloes:
                cond_leilao = (where + " AND " if where else " WHERE ") + "fonte = ? AND leilao IS ?"
                args_leilao = args + [l["fonte"], l["leilao"]]
                item = dict(l)
                for coluna, limite in (("categoria", 10), ("monta", 10), ("marca", 8)):
                    linhas = con.execute(
                        f"SELECT {coluna} AS valor, COUNT(*) AS n FROM lotes{cond_leilao} "
                        f"GROUP BY {coluna} ORDER BY n DESC LIMIT {limite}",
                        args_leilao,
                    ).fetchall()
                    item[coluna] = {(x["valor"] or "não informado"): x["n"] for x in linhas}
                resumo.append(item)
        return resumo

    def obter(self, fonte: str, id_externo: str) -> dict | None:
        with self._conexao() as con:
            linha = con.execute(
                "SELECT * FROM lotes WHERE fonte = ? AND id_externo = ?", (fonte, id_externo)
            ).fetchone()
        return _linha_para_lote(linha) if linha else None
