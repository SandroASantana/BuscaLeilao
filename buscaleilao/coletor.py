"""Executa as fontes configuradas, normaliza os lotes e grava no banco."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .banco import Banco
from .fontes import Fonte
from .normalizacao import normalizar_lote

log = logging.getLogger(__name__)


@dataclass
class ResultadoColeta:
    fonte: str
    lotes: int = 0
    erro: str | None = None


@dataclass
class RelatorioColeta:
    resultados: list[ResultadoColeta] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(r.lotes for r in self.resultados)


def coletar(banco: Banco, fontes: list[Fonte]) -> RelatorioColeta:
    """Coleta cada fonte isoladamente: a falha de um site não impede os demais."""
    relatorio = RelatorioColeta()
    for fonte in fontes:
        resultado = ResultadoColeta(fonte.id)
        try:
            lotes = [normalizar_lote(l) for l in fonte.coletar()]
            for lote in lotes:
                lote.leilao = lote.leilao or fonte.nome
            # Só desativa lotes ausentes se a coleta trouxe algo; uma página
            # vazia costuma indicar erro/mudança no site, não fim dos lotes.
            resultado.lotes = banco.salvar(lotes, fonte=fonte.id, desativar_ausentes=bool(lotes))
        except Exception as e:  # noqa: BLE001 - registrar e seguir para a próxima fonte
            log.exception("erro coletando %s", fonte.id)
            resultado.erro = f"{type(e).__name__}: {e}"
        relatorio.resultados.append(resultado)
    return relatorio
