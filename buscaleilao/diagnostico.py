"""Diagnóstico de sites de leiloeiros, para rodar no computador do usuário.

Abre cada site num navegador de verdade (Edge/Chrome via Playwright), navega
até as páginas de veículos e grava como o site entrega a lista de lotes: o
HTML da página e as respostas JSON das APIs que a página chama por trás. O
resultado vai para um .zip que serve de base para escrever a configuração de
cada fonte em config/fontes.json.

Nada de login ou cookie do usuário é usado: o navegador abre com perfil novo.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Leiloeiros de veículos conhecidos; o usuário pode passar outras URLs.
SITES_PADRAO = {
    "copart": "https://www.copart.com.br/",
    "sodre_santoro": "https://www.sodresantoro.com.br/",
    "vip_leiloes": "https://www.vipleiloes.com.br/",
    "superbid": "https://www.superbid.net/",
    "mega_leiloes": "https://www.megaleiloes.com.br/",
    "freitas": "https://www.freitasleiloeiro.com.br/",
    "palacio_leiloes": "https://www.palaciodosleiloes.com.br/",
}

# Respostas destes domínios são rastreadores/anúncios, não dados de lotes.
_IGNORAR = re.compile(
    r"google|doubleclick|facebook|hotjar|clarity\.ms|tiktok|linkedin|twitter|criteo|"
    r"taboola|outbrain|newrelic|nr-data|sentry|segment|mixpanel|amplitude|onesignal|"
    r"zendesk|intercom|hubspot|rdstation|cloudflareinsights|youtube|gstatic|recaptcha|"
    r"jivosite|tawk|crisp|smartlook|yandex|bing\.com|pinterest",
    re.I,
)
_PALAVRAS_LINK = re.compile(
    r"veicul|carro|moto|automove|caminh|utilit|leil|lote|pesquis|busca|categori|search|lots?\b",
    re.I,
)
_MAX_CORPO = 60_000
_MAX_HTML = 1_500_000
_MAX_RESPOSTAS = 40


@dataclass
class RespostaJson:
    url: str
    metodo: str
    status: int
    corpo_requisicao: str | None
    corpo: str


@dataclass
class Pagina:
    url: str
    titulo: str = ""
    html: str = ""
    erro: str | None = None


@dataclass
class ResultadoSite:
    nome: str
    url: str
    paginas: list[Pagina] = field(default_factory=list)
    respostas: list[RespostaJson] = field(default_factory=list)


def _dominio_base(url: str) -> str:
    partes = urlparse(url).hostname or ""
    partes = partes.split(".")
    # leiloeiro.com.br -> leiloeiro.com.br ; www.superbid.net -> superbid.net
    n = 3 if len(partes) >= 3 and partes[-2] in {"com", "net", "org", "gov"} and len(partes[-1]) == 2 else 2
    return ".".join(partes[-n:])


def escolher_links(url_base: str, links: list[tuple[str, str]], limite: int = 3) -> list[str]:
    """Das âncoras da página inicial, escolhe as que parecem levar a listagens
    de veículos no mesmo site."""
    dominio = _dominio_base(url_base)
    pontuados: dict[str, int] = {}
    for href, texto in links:
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absoluto = urljoin(url_base, href).split("#")[0]
        if _dominio_base(absoluto) != dominio or absoluto.rstrip("/") == url_base.rstrip("/"):
            continue
        alvo = f"{urlparse(absoluto).path} {urlparse(absoluto).query} {texto}"
        pontos = len(_PALAVRAS_LINK.findall(alvo))
        if re.search(r"veicul|carro|automove", alvo, re.I):
            pontos += 3
        if re.search(r"login|cadastr|conta|ajuda|contato|blog|noticia|imovei|imóve|faq|politica|termo", alvo, re.I):
            pontos -= 5
        if pontos > 0:
            pontuados[absoluto] = max(pontos, pontuados.get(absoluto, 0))
    ordenados = sorted(pontuados, key=lambda u: (-pontuados[u], len(u)))
    escolhidos, caminhos = [], set()
    for u in ordenados:
        caminho = urlparse(u).path.rstrip("/")
        if caminho in caminhos:
            continue
        caminhos.add(caminho)
        escolhidos.append(u)
        if len(escolhidos) >= limite:
            break
    return escolhidos


def _abrir_navegador(pw, oculto: bool, executavel: str | None):
    opcoes = {"headless": oculto}
    if executavel:
        return pw.chromium.launch(executable_path=executavel, **opcoes)
    # Edge vem em todo Windows; assim não é preciso baixar outro navegador.
    for canal in ("msedge", "chrome"):
        try:
            return pw.chromium.launch(channel=canal, **opcoes)
        except Exception:  # noqa: BLE001 - tenta o próximo
            continue
    return pw.chromium.launch(**opcoes)


def diagnosticar_site(contexto, nome: str, url: str, paginas_extras: int = 3,
                      espera_ms: int = 4000, log=print) -> ResultadoSite:
    resultado = ResultadoSite(nome, url)
    pagina = contexto.new_page()

    def ao_responder(resp):
        if len(resultado.respostas) >= _MAX_RESPOSTAS or _IGNORAR.search(resp.url):
            return
        tipo = resp.headers.get("content-type", "")
        if "json" not in tipo:
            return
        try:
            corpo = resp.text()
        except Exception:  # noqa: BLE001 - resposta sem corpo (redirect etc.)
            return
        if len(corpo) < 30:
            return
        req = resp.request
        try:
            enviado = req.post_data
        except Exception:  # noqa: BLE001 - corpo binário
            enviado = None
        resultado.respostas.append(RespostaJson(
            url=resp.url, metodo=req.method, status=resp.status,
            corpo_requisicao=enviado[:5000] if enviado else None,
            corpo=corpo[:_MAX_CORPO],
        ))

    pagina.on("response", ao_responder)

    def visitar(alvo: str) -> Pagina:
        p = Pagina(alvo)
        try:
            pagina.goto(alvo, wait_until="domcontentloaded", timeout=45_000)
            pagina.wait_for_timeout(espera_ms)
            for _ in range(4):  # rola a página para carregar lotes preguiçosos
                pagina.mouse.wheel(0, 2500)
                pagina.wait_for_timeout(700)
            p.url = pagina.url
            p.titulo = pagina.title()
            p.html = pagina.content()[:_MAX_HTML]
        except Exception as e:  # noqa: BLE001 - registrar e seguir
            p.erro = f"{type(e).__name__}: {e}"[:500]
        resultado.paginas.append(p)
        return p

    log(f"  abrindo {url}")
    inicial = visitar(url)
    if not inicial.erro:
        try:
            links = pagina.eval_on_selector_all(
                "a[href]", "els => els.map(e => [e.getAttribute('href'), (e.innerText || '').slice(0, 80)])")
        except Exception:  # noqa: BLE001
            links = []
        for extra in escolher_links(pagina.url, links, paginas_extras):
            log(f"  abrindo {extra}")
            visitar(extra)
    pagina.close()
    return resultado


def _nome_arquivo(i: int, url: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "_", urlparse(url).netloc + urlparse(url).path).strip("_")
    return f"{i:02d}_{base[:80]}"


def _resumo(resultado: ResultadoSite) -> str:
    linhas = [f"Site: {resultado.nome} ({resultado.url})", "", "Páginas visitadas:"]
    for p in resultado.paginas:
        estado = f"ERRO {p.erro}" if p.erro else f"{len(p.html):,} bytes - {p.titulo!r}"
        linhas.append(f"  {p.url}  [{estado}]")
    linhas += ["", f"Respostas JSON capturadas: {len(resultado.respostas)}"]
    for r in resultado.respostas:
        linhas.append(f"  {r.metodo} {r.status} {len(r.corpo):>7,}b  {r.url[:200]}")
    return "\n".join(linhas) + "\n"


def salvar_zip(resultados: list[ResultadoSite], destino: Path) -> Path:
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for res in resultados:
            z.writestr(f"{res.nome}/resumo.txt", _resumo(res))
            for i, p in enumerate(res.paginas):
                if p.html:
                    z.writestr(f"{res.nome}/paginas/{_nome_arquivo(i, p.url)}.html", p.html)
            for i, r in enumerate(res.respostas):
                z.writestr(f"{res.nome}/api/{_nome_arquivo(i, r.url)}.json", json.dumps({
                    "url": r.url, "metodo": r.metodo, "status": r.status,
                    "corpo_requisicao": r.corpo_requisicao, "corpo": r.corpo,
                }, ensure_ascii=False, indent=1))
    return destino


def executar(sites: dict[str, str], destino: Path, oculto: bool = False,
             executavel: str | None = None, espera_ms: int = 4000, log=print) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "O diagnóstico precisa do Playwright. Instale com:\n"
            "    pip install playwright\n"
            "Ele usa o Edge ou o Chrome que já estão no computador."
        ) from None

    resultados = []
    with sync_playwright() as pw:
        navegador = _abrir_navegador(pw, oculto, executavel)
        for nome, url in sites.items():
            log(f"[{nome}]")
            contexto = navegador.new_context(locale="pt-BR", viewport={"width": 1366, "height": 900})
            try:
                res = diagnosticar_site(contexto, nome, url, espera_ms=espera_ms, log=log)
            finally:
                contexto.close()
            log(f"  {len(res.paginas)} página(s), {len(res.respostas)} resposta(s) de API")
            resultados.append(res)
        navegador.close()
    return salvar_zip(resultados, destino)


def sites_de_argumentos(args: list[str]) -> dict[str, str]:
    """Aceita nomes da lista padrão (copart, superbid...) ou URLs."""
    if not args:
        return dict(SITES_PADRAO)
    sites = {}
    for a in args:
        if a in SITES_PADRAO:
            sites[a] = SITES_PADRAO[a]
        elif a.startswith(("http://", "https://")):
            nome = re.sub(r"[^a-z0-9]+", "_", (urlparse(a).hostname or a).lower().removeprefix("www.")).strip("_")
            sites[nome] = a
        else:
            raise SystemExit(f"'{a}' não é uma URL nem um site conhecido ({', '.join(SITES_PADRAO)})")
    return sites
