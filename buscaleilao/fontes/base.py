"""Infraestrutura comum às fontes (leiloeiros) de onde os lotes são coletados."""

from __future__ import annotations

import json as _json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Iterable
from urllib import robotparser
from urllib.parse import urlencode, urljoin, urlparse

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


def montar_lote(fonte: str, valores: dict, config: dict, url_base: str | None = None) -> Lote | None:
    """Aplica a configuração da fonte sobre os valores extraídos de um item:

    - "constantes": valores fixos (ex.: {"categoria": "carro"});
    - "formatos": campos montados a partir de outros, com a sintaxe de
      str.format (ex.: {"url": "https://site/lote/{_id}"}). Campos iniciados
      por "_" servem só como auxiliares e não vão para o lote;
    - "excluir": {campo: regex}; itens cujo campo casa com a regex são
      descartados (ex.: lotes já vendidos).
    """
    valores = {**config.get("constantes", {}), **valores}
    disponiveis = {k: v for k, v in valores.items() if v not in (None, "")}
    for campo, modelo in config.get("formatos", {}).items():
        try:
            valores[campo] = modelo.format(**disponiveis)
        except (KeyError, IndexError, ValueError):
            continue
    for campo, regex in config.get("excluir", {}).items():
        if re.search(regex, str(valores.get(campo) or ""), re.I):
            return None
    return lote_de_dict(fonte, valores, url_base=url_base)


class Resposta:
    """Resposta HTTP mínima (mesma interface usada de requests.Response)."""

    def __init__(self, url: str, status_code: int, text: str):
        self.url = url
        self.status_code = status_code
        self.text = text

    def json(self) -> Any:
        return _json.loads(self.text)


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

    def requisitar(self, url: str, metodo: str = "GET", renderizar: bool = False,
                   **kwargs) -> requests.Response:
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


_TITULOS_DESAFIO = re.compile(r"um momento|just a moment|attention required|verifica|checking", re.I)

_JS_FETCH = """async ([url, opcoes]) => {
    const r = await fetch(url, opcoes);
    return {url: r.url, status: r.status, text: await r.text()};
}"""


class ClienteNavegador:
    """Faz as requisições de dentro de um navegador de verdade (Edge/Chrome via
    Playwright), para sites protegidos contra robôs (Cloudflare, Imperva...).

    Abre a página inicial do site uma vez (passando pela verificação, se
    houver) e depois chama as URLs com fetch() dentro da página, usando os
    mesmos cookies. Com `renderizar=True` a URL é aberta como página, e o HTML
    devolvido já tem o conteúdo montado por JavaScript.
    """

    def __init__(self, url_inicial: str, intervalo: float = 1.5, respeitar_robots: bool = True,
                 oculto: bool = False, executavel: str | None = None, espera_desafio: float = 45,
                 timeout: float = 60):
        self.url_inicial = url_inicial
        self.intervalo = intervalo
        self.respeitar_robots = respeitar_robots
        self.oculto = oculto
        self.executavel = executavel
        self.espera_desafio = espera_desafio
        self.timeout = timeout
        self._pw = self._navegador = self._pagina = None
        self._ultima = 0.0
        self._robots: dict[str, robotparser.RobotFileParser] = {}

    def _iniciar(self):
        if self._pagina is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("esta fonte usa o navegador; instale com: pip install playwright") from None
        from ..diagnostico import abrir_navegador

        self._pw = sync_playwright().start()
        self._navegador = abrir_navegador(self._pw, self.oculto, self.executavel)
        contexto = self._navegador.new_context(locale="pt-BR", viewport={"width": 1366, "height": 900})
        self._pagina = contexto.new_page()
        self._abrir(self.url_inicial)

    def _abrir(self, url: str) -> None:
        self._pagina.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
        limite = time.monotonic() + self.espera_desafio
        while _TITULOS_DESAFIO.search(self._pagina.title() or "") and time.monotonic() < limite:
            self._pagina.wait_for_timeout(1000)
        self._pagina.wait_for_timeout(1500)

    def _buscar(self, url: str, opcoes: dict) -> Resposta:
        r = self._pagina.evaluate(_JS_FETCH, [url, opcoes])
        return Resposta(r["url"], r["status"], r["text"])

    def _permitido(self, url: str) -> bool:
        if not self.respeitar_robots:
            return True
        p = urlparse(url)
        raiz = f"{p.scheme}://{p.netloc}"
        if raiz not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self._buscar(raiz + "/robots.txt", {"method": "GET"})
                texto = r.text if r.status_code == 200 and "<html" not in r.text[:500].lower() else ""
            except Exception:  # noqa: BLE001 - sem robots.txt acessível
                texto = ""
            rp.parse(texto.splitlines())
            self._robots[raiz] = rp
        return self._robots[raiz].can_fetch(USER_AGENT, url)

    def requisitar(self, url: str, metodo: str = "GET", renderizar: bool = False,
                   json: Any = None, data: Any = None, headers: dict | None = None,
                   **_ignorado) -> Resposta:
        self._iniciar()
        if not self._permitido(url):
            raise PermissionError(f"robots.txt não permite acessar {url}")
        espera = self.intervalo - (time.monotonic() - self._ultima)
        if espera > 0:
            time.sleep(espera)
        self._ultima = time.monotonic()
        if renderizar:
            self._abrir(url)
            for _ in range(3):  # rola para carregar itens preguiçosos
                self._pagina.mouse.wheel(0, 3000)
                self._pagina.wait_for_timeout(600)
            return Resposta(self._pagina.url, 200, self._pagina.content())
        cabecalhos = {"Accept": "application/json, text/plain, */*", **(headers or {})}
        opcoes: dict = {"method": metodo, "headers": cabecalhos, "credentials": "include"}
        if json is not None:
            opcoes["body"] = _json.dumps(json)
            cabecalhos["Content-Type"] = "application/json"
        elif data is not None:
            opcoes["body"] = data if isinstance(data, str) else urlencode(data)
            cabecalhos["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        resp = self._buscar(url, opcoes)
        if resp.status_code >= 400:
            raise RuntimeError(f"{url} respondeu {resp.status_code}")
        return resp

    def fechar(self) -> None:
        if self._navegador is not None:
            self._navegador.close()
        if self._pw is not None:
            self._pw.stop()
        self._pw = self._navegador = self._pagina = None


def criar_cliente(config: dict):
    """ClienteHttp simples ou, com "navegador": true, ClienteNavegador."""
    if config.get("navegador"):
        p = urlparse(config["url"])
        return ClienteNavegador(
            url_inicial=config.get("url_inicial") or f"{p.scheme}://{p.netloc}/",
            intervalo=config.get("intervalo", 1.5),
            respeitar_robots=config.get("respeitar_robots", True),
            oculto=config.get("oculto", False),
        )
    return ClienteHttp(
        intervalo=config.get("intervalo", 1.5),
        respeitar_robots=config.get("respeitar_robots", True),
        cabecalhos=config.get("cabecalhos"),
    )


class Fonte(ABC):
    """Um leiloeiro/site de onde os lotes são coletados."""

    tipo: str = ""

    def __init__(self, id: str, nome: str | None = None, **config):
        self.id = id
        self.nome = nome or id
        self.config = config

    @abstractmethod
    def coletar(self, max_paginas: int | None = None) -> Iterable[Lote]:
        """Devolve os lotes disponíveis na fonte (ainda não normalizados).
        `max_paginas` limita a coleta às primeiras páginas (testes rápidos)."""

    def fechar(self) -> None:
        """Libera recursos (ex.: fecha o navegador)."""
        cliente = getattr(self, "cliente", None)
        if hasattr(cliente, "fechar"):
            cliente.fechar()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id}>"
