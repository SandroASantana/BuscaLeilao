"""Teste rápido das fontes configuradas, para rodar no computador do usuário.

Coleta só as primeiras páginas de cada leiloeiro, grava os lotes no banco e
gera um .zip com um resumo (quantos lotes, quais campos vieram preenchidos,
erros) e as primeiras respostas brutas de cada site. Esse arquivo permite
ajustar a configuração de uma fonte que não funcionou sem acesso ao site.
"""

from __future__ import annotations

import json
import traceback
import zipfile
from collections import Counter
from pathlib import Path

from .banco import Banco
from .fontes import Fonte
from .modelos import Lote
from .normalizacao import normalizar_lote

_CAMPOS_RESUMO = ("marca", "modelo", "ano_modelo", "categoria", "monta", "condicao", "cidade",
                  "uf", "lance_atual", "lance_inicial", "data_leilao", "url", "imagem_url")
_MAX_RESPOSTA = 300_000


class Gravador:
    """Envolve o cliente HTTP de uma fonte e guarda as primeiras respostas."""

    def __init__(self, cliente, limite: int = 3):
        self.cliente = cliente
        self.limite = limite
        self.registros: list[dict] = []

    def requisitar(self, url, metodo="GET", **kwargs):
        registro = {"url": url, "metodo": metodo,
                    "enviado": {k: v for k, v in kwargs.items() if k in ("json", "data")}}
        try:
            resp = self.cliente.requisitar(url, metodo, **kwargs)
        except Exception as e:
            registro["erro"] = f"{type(e).__name__}: {e}"
            self.registros.append(registro)
            raise
        if len(self.registros) < self.limite:
            registro.update(status=getattr(resp, "status_code", None), resposta=resp.text[:_MAX_RESPOSTA])
            self.registros.append(registro)
        return resp

    def fechar(self):
        if hasattr(self.cliente, "fechar"):
            self.cliente.fechar()


def _resumo_lotes(lotes: list[Lote]) -> list[str]:
    if not lotes:
        return ["  nenhum lote extraído"]
    linhas = ["  campos preenchidos:"]
    for campo in _CAMPOS_RESUMO:
        n = sum(1 for l in lotes if getattr(l, campo) not in (None, ""))
        linhas.append(f"    {campo:<14} {n}/{len(lotes)}")
    for campo in ("categoria", "monta", "condicao"):
        contagem = Counter(getattr(l, campo) for l in lotes).most_common(6)
        linhas.append(f"  {campo}: " + ", ".join(f"{k}={v}" for k, v in contagem))
    linhas.append("  exemplos:")
    for l in lotes[:3]:
        linhas.append(f"    {l.titulo} | {l.marca} {l.modelo} {l.ano_modelo} | {l.categoria} | "
                      f"monta={l.monta} | {l.cidade}/{l.uf} | lance={l.lance_atual or l.lance_inicial} | "
                      f"{l.data_leilao} | {l.url}")
    return linhas


def testar(banco: Banco, fontes: list[Fonte], destino: Path, max_paginas: int = 2,
           log=print) -> Path:
    resumo: list[str] = []
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for fonte in fontes:
            log(f"[{fonte.id}] testando...")
            gravador = None
            if hasattr(fonte, "cliente"):
                gravador = fonte.cliente = Gravador(fonte.cliente)
            lotes: list[Lote] = []
            erro = None
            try:
                for lote in fonte.coletar(max_paginas=max_paginas):
                    lote = normalizar_lote(lote)
                    lote.leilao = lote.leilao or fonte.nome
                    lotes.append(lote)
            except Exception as e:  # noqa: BLE001 - relatar e seguir
                erro = f"{type(e).__name__}: {e}"
                z.writestr(f"{fonte.id}/erro.txt", traceback.format_exc())
            finally:
                fonte.fechar()
            if lotes:
                banco.salvar(lotes)
            situacao = f"ERRO {erro}" if erro else "ok"
            log(f"  {len(lotes)} lote(s) - {situacao}")
            resumo += [f"== {fonte.id}: {len(lotes)} lote(s) - {situacao}", *_resumo_lotes(lotes), ""]
            if gravador:
                for i, r in enumerate(gravador.registros):
                    z.writestr(f"{fonte.id}/resposta_{i}.json", json.dumps(r, ensure_ascii=False, indent=1))
        z.writestr("resumo.txt", "\n".join(resumo))
    return destino
