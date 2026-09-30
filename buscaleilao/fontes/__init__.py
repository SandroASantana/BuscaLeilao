"""Registro dos tipos de fonte e carregamento da configuração."""

from __future__ import annotations

import json
from pathlib import Path

from .api_json import FonteApiJson
from .arquivo import FonteArquivo
from .base import ClienteHttp, ClienteNavegador, Fonte, lote_de_dict, montar_lote
from .html import FonteHtml

TIPOS: dict[str, type[Fonte]] = {
    FonteArquivo.tipo: FonteArquivo,
    FonteHtml.tipo: FonteHtml,
    FonteApiJson.tipo: FonteApiJson,
}

CONFIG_PADRAO = Path("config/fontes.json")


def registrar(classe: type[Fonte]) -> type[Fonte]:
    """Decorador para registrar um raspador escrito em Python para um site
    específico (quando a configuração genérica não é suficiente)."""
    TIPOS[classe.tipo] = classe
    return classe


def criar_fonte(config: dict) -> Fonte:
    config = dict(config)
    tipo = config.pop("tipo")
    if tipo not in TIPOS:
        raise ValueError(f"tipo de fonte desconhecido: {tipo!r} (disponíveis: {', '.join(TIPOS)})")
    return TIPOS[tipo](**config)


def carregar_fontes(caminho: str | Path = CONFIG_PADRAO) -> list[Fonte]:
    caminho = Path(caminho)
    configs = json.loads(caminho.read_text(encoding="utf-8"))
    if isinstance(configs, dict):
        configs = configs.get("fontes", [])
    return [criar_fonte(c) for c in configs if c.get("ativo", True)]


__all__ = [
    "ClienteHttp", "ClienteNavegador", "Fonte", "FonteApiJson", "FonteArquivo", "FonteHtml", "TIPOS",
    "carregar_fontes", "criar_fonte", "lote_de_dict", "montar_lote", "registrar",
]
