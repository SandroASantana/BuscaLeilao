"""Infraestrutura comum às fontes (leiloeiros) de onde os lotes são coletados."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Iterable
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests

from ..modelos import Lote
from ..normalizacao import parse_data, parse_dinheiro, parse_inteiro

log = logging.getLogger(__name__)

USER_AGENT = "BuscaLeilao/0.1 (+agregador de lotes de leiloes de veiculos)"

_CAMPOS_DINHEIRO = {"lance_inicial", "lance_atual", "valor_fipe"}
_CAMPOS_INTEIRO = {"ano_fabricacao", "ano_modelo", "km"}
_CAMPOS_TEXTO = set(Lote.campos()) - _CAMPOS_DINHEIRO - _CAMPOS_INTEIRO - {"data_leilao", "coletado_em"}


def lote_de_dict(fonte: str, dados: dict, url_base: str | None = None) -> Lote | None:
    """Monta um Lote a partir de um dicionário de valores brutos (texto ou números)."""
    valores: dict = {}
    for campo, bruto in dados.items():
        if bruto is None or (isinstance(bruto, str) and not bruto.strip()):
            continue
        if campo in _CAMPOS_DINHEIRO:
            valores[campo] = parse_dinheiro(bruto)
        elif campo in _CAMPOS_INTEIRO:
            valores[campo] = parse_inteiro(bruto)
        elif campo == "data_leilao":
            valores[campo] = parse_data(bruto)
        elif campo in _CAMPOS_TEXTO:
            valores[campo] = " ".join(str(bruto).split())
    if url_base:
        for campo in ("url", "imagem_url"):
            if valores.get(campo):
                valores[campo] = urljoin(url_base, valores[campo])
    valores.setdefault("id_externo", valores.get("url"))
    if not valores.get("titulo") or not valores.get("id_externo"):
        return None
    valores.pop("fonte", None)
    return Lote(fonte=fonte, **valores)


class ClienteHttp:
    """requests.Session com User-Agent identificável, intervalo mínimo entre
    requisições, novas tentativas e respeito ao robots.txt."""

    def __init__(self, intervalo: float = 1.5, tentativas: int = 3, respeitar_robots: bool = True,
                 cabecalhos: dict | None = None, timeout: float = 30):
        self.sessao = requests.Session()
        self.sessao.headers["User-Agent"] = USER_AGENT
        self.sessao.headers.update(cabecalhos or {})
        self.intervalo = intervalo
        self.tentativas = tentativas
        self.respeitar_robots = respeitar_robots
        self.timeout = timeout
        self._ultima = 0.0
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}

    def _permitido(self, url: str) -> bool:
        if not self.respeitar_robots:
            return True
        p = urlparse(url)
        raiz = f"{p.scheme}://{p.netloc}"
        if raiz not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.sessao.get(raiz + "/robots.txt", timeout=self.timeout)
                rp.parse(r.text.splitlines() if r.ok else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[raiz] = rp
        return self._robots[raiz].can_fetch(USER_AGENT, url)

    def requisitar(self, url: str, metodo: str = "GET", **kwargs) -> requests.Response:
        if not self._permitido(url):
            raise PermissionError(f"robots.txt não permite acessar {url}")
        kwargs.setdefault("timeout", self.timeout)
        for tentativa in range(1, self.tentativas + 1):
            espera = self.intervalo - (time.monotonic() - self._ultima)
            if espera > 0:
                time.sleep(espera)
            self._ultima = time.monotonic()
            try:
                resp = self.sessao.request(metodo, url, **kwargs)
                if resp.status_code < 500 and resp.status_code != 429:
                    resp.raise_for_status()
                    return resp
                log.warning("%s respondeu %s (tentativa %d)", url, resp.status_code, tentativa)
            except requests.ConnectionError as e:
                log.warning("falha ao acessar %s: %s (tentativa %d)", url, e, tentativa)
            time.sleep(2 ** tentativa)
        raise RuntimeError(f"não foi possível acessar {url} após {self.tentativas} tentativas")


class Fonte(ABC):
    """Um leiloeiro/site de onde os lotes são coletados."""

    tipo: str = ""

    def __init__(self, id: str, nome: str | None = None, **config):
        self.id = id
        self.nome = nome or id
        self.config = config

    @abstractmethod
    def coletar(self) -> Iterable[Lote]:
        """Devolve os lotes disponíveis na fonte (ainda não normalizados)."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id}>"
