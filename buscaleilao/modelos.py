"""Modelo de dados de um lote de leilão de veículo, comum a todas as fontes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

# Valores canônicos usados na normalização e nos filtros de busca.
CATEGORIAS = ("carro", "moto", "caminhao", "utilitario", "onibus", "maquina", "outros")

# "Monta" é a classificação de dano usada em leilões de sinistrados.
MONTAS = ("sem_monta", "pequena", "media", "grande")

CONDICOES = (
    "recuperado_financiamento",
    "sinistro",
    "roubo_furto",
    "frota",
    "particular",
    "apreendido",
    "sucata",
)


@dataclass
class Lote:
    fonte: str
    id_externo: str
    titulo: str
    leilao: str | None = None
    url: str | None = None
    categoria: str | None = None
    marca: str | None = None
    modelo: str | None = None
    versao: str | None = None
    ano_fabricacao: int | None = None
    ano_modelo: int | None = None
    monta: str | None = None
    condicao: str | None = None
    combustivel: str | None = None
    cor: str | None = None
    km: int | None = None
    cidade: str | None = None
    uf: str | None = None
    lance_inicial: float | None = None
    lance_atual: float | None = None
    valor_fipe: float | None = None
    data_leilao: datetime | None = None
    imagem_url: str | None = None
    descricao: str | None = None
    coletado_em: datetime = field(default_factory=lambda: datetime.now().replace(microsecond=0))

    @classmethod
    def campos(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    def para_dict(self) -> dict:
        d = asdict(self)
        for chave in ("data_leilao", "coletado_em"):
            if d[chave] is not None:
                d[chave] = d[chave].isoformat()
        return d
