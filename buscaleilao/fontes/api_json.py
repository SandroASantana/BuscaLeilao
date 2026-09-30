"""Fonte genérica para sites que carregam os lotes via API JSON.

Muitos sites de leilão modernos montam a página no navegador a partir de uma
API (veja a aba "Rede/Network" do DevTools). Consumir essa API é bem mais
estável do que raspar o HTML. Exemplo de configuração:

    {
      "id": "leiloeiro_y",
      "tipo": "json",
      "url": "https://api.leiloeiroy.com.br/lotes?page={pagina}&size=100",
      "paginas": 20,
      "caminho_lista": "data.content",
      "campos": {
        "id_externo": "id",
        "titulo": "descricao",
        "marca": "veiculo.marca",
        "modelo": "veiculo.modelo",
        "ano_modelo": "veiculo.anoModelo",
        "monta": "veiculo.tipoMonta",
        "lance_atual": "valorLanceAtual",
        "data_leilao": "leilao.dataInicio",
        "leilao": "leilao.nome",
        "imagem_url": "fotos.0.url"
      },
      "url_lote": "https://www.leiloeiroy.com.br/lote/{id_externo}"
    }

Caminhos usam ponto para navegar em objetos e números para índices de lista.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from ..modelos import Lote
from .base import ClienteHttp, Fonte, lote_de_dict

log = logging.getLogger(__name__)


def pegar(dados: Any, caminho: str | None) -> Any:
    if not caminho:
        return dados
    atual = dados
    for parte in caminho.split("."):
        if isinstance(atual, list) and parte.isdigit():
            idx = int(parte)
            atual = atual[idx] if idx < len(atual) else None
        elif isinstance(atual, dict):
            atual = atual.get(parte)
        else:
            return None
        if atual is None:
            return None
    return atual


def _com_pagina(valor: Any, pagina: int) -> Any:
    """Substitui "{pagina}" no corpo da requisição (o valor exato vira número)."""
    if valor == "{pagina}":
        return pagina
    if isinstance(valor, str):
        return valor.replace("{pagina}", str(pagina))
    if isinstance(valor, dict):
        return {k: _com_pagina(v, pagina) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_com_pagina(v, pagina) for v in valor]
    return valor


class FonteApiJson(Fonte):
    tipo = "json"

    def __init__(self, id: str, nome: str | None = None, cliente: ClienteHttp | None = None, **config):
        super().__init__(id, nome, **config)
        self.cliente = cliente or ClienteHttp(
            intervalo=config.get("intervalo", 1.0),
            respeitar_robots=config.get("respeitar_robots", True),
            cabecalhos=config.get("cabecalhos"),
        )

    def extrair_resposta(self, dados: Any) -> list[Lote]:
        itens = pegar(dados, self.config.get("caminho_lista")) or []
        campos: dict = self.config["campos"]
        constantes = self.config.get("constantes", {})
        url_lote = self.config.get("url_lote")
        lotes = []
        for item in itens:
            valores = {campo: pegar(item, caminho) for campo, caminho in campos.items()}
            valores = {k: (str(v) if isinstance(v, (dict, list)) else v) for k, v in valores.items()}
            if url_lote and not valores.get("url") and valores.get("id_externo") is not None:
                valores["url"] = url_lote.format(**{k: v for k, v in valores.items() if v is not None})
            if valores.get("id_externo") is not None:
                valores["id_externo"] = str(valores["id_externo"])
            lote = lote_de_dict(self.id, {**constantes, **valores}, url_base=self.config.get("url_base"))
            if lote:
                lotes.append(lote)
        return lotes

    def coletar(self) -> Iterable[Lote]:
        url = self.config["url"]
        metodo = self.config.get("metodo", "GET").upper()
        paginas = self.config.get("paginas", 1)
        vistos: set[str] = set()
        for pagina in range(1, paginas + 1):
            kwargs = {}
            if "corpo" in self.config:
                kwargs["json"] = _com_pagina(self.config["corpo"], pagina)
            resp = self.cliente.requisitar(url.format(pagina=pagina), metodo, **kwargs)
            lotes = [l for l in self.extrair_resposta(resp.json()) if l.id_externo not in vistos]
            log.info("%s: página %d -> %d lotes", self.id, pagina, len(lotes))
            if not lotes:
                break
            for lote in lotes:
                vistos.add(lote.id_externo)
                yield lote
            if "{pagina}" not in url and "corpo" not in self.config:
                break
