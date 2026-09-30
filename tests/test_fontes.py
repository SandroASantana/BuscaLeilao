import json
from pathlib import Path

from buscaleilao.banco import Banco, Filtros
from buscaleilao.coletor import coletar
from buscaleilao.fontes import Fonte, FonteApiJson, FonteHtml, carregar_fontes, criar_fonte
from buscaleilao.fontes.api_json import pegar
from buscaleilao.normalizacao import normalizar_lote

FIXTURES = Path(__file__).parent / "fixtures"
RAIZ = Path(__file__).parent.parent


class RespostaFalsa:
    def __init__(self, texto="", dados=None):
        self.text = texto
        self._dados = dados

    def json(self):
        return self._dados


class ClienteFalso:
    """Substitui o acesso à rede: devolve respostas pré-definidas por página."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.urls = []

    def requisitar(self, url, metodo="GET", **kwargs):
        self.urls.append((metodo, url, kwargs))
        return self.respostas.pop(0) if self.respostas else RespostaFalsa("", {"itens": []})


CONFIG_HTML = {
    "id": "html1",
    "url": "https://leiloeiro.test/veiculos?p={pagina}",
    "paginas": 3,
    "seletores": {
        "item": "div.lote", "id_externo": "@data-id", "titulo": ".lote-titulo", "url": "a@href",
        "lance_atual": ".lote-lance", "data_leilao": ".lote-data", "cidade": ".lote-local",
        "monta": ".lote-monta", "imagem_url": "img@src",
    },
    "constantes": {"leilao": "Leilão Teste"},
}


def test_fonte_html_extrai_e_para_na_pagina_vazia():
    html = (FIXTURES / "listagem.html").read_text()
    cliente = ClienteFalso([RespostaFalsa(html), RespostaFalsa("<html></html>")])
    fonte = FonteHtml(cliente=cliente, **CONFIG_HTML)
    lotes = [normalizar_lote(l) for l in fonte.coletar()]

    assert len(cliente.urls) == 2  # parou ao encontrar a página 2 vazia
    assert [l.id_externo for l in lotes] == ["A1", "A2"]
    gol, cg = lotes
    assert gol.url == "https://leiloeiro.test/lote/A1"
    assert gol.imagem_url == "https://leiloeiro.test/fotos/a1.jpg"
    assert (gol.marca, gol.ano_modelo, gol.monta, gol.lance_atual) == ("Volkswagen", 2019, "pequena", 21300.0)
    assert (gol.cidade, gol.uf, gol.leilao) == ("Sorocaba", "SP", "Leilão Teste")
    assert gol.data_leilao.isoformat() == "2026-10-15T14:00:00"
    assert (cg.marca, cg.categoria, cg.imagem_url) == ("Honda", "moto", None)


def test_fonte_html_nao_repete_lotes_de_paginas_repetidas():
    html = (FIXTURES / "listagem.html").read_text()
    # alguns sites devolvem a última página para qualquer número acima do máximo
    cliente = ClienteFalso([RespostaFalsa(html), RespostaFalsa(html), RespostaFalsa(html)])
    lotes = list(FonteHtml(cliente=cliente, **CONFIG_HTML).coletar())
    assert len(lotes) == 2
    assert len(cliente.urls) == 2


def test_pegar_caminho():
    dados = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert pegar(dados, "a.b.1.c") == 2
    assert pegar(dados, "a.x.c") is None
    assert pegar(dados, "a.b.5.c") is None


def test_fonte_api_json():
    pagina1 = {"dados": {"itens": [
        {"id": 10, "descricao": "Caminhão Scania R 450 2019/2020",
         "veiculo": {"marca": "SCANIA", "anoModelo": 2020, "tipo": "Caminhões", "monta": "MEDIA"},
         "lanceAtual": 250000.5, "leilao": {"titulo": "Pesados #3", "data": "2026-11-02T10:00:00Z"},
         "fotos": [{"url": "https://cdn.test/10.jpg"}]},
        {"id": 11, "descricao": "Moto Honda Biz 125 2022",
         "veiculo": {"marca": "honda", "anoModelo": "2022"}, "lanceAtual": "R$ 6.100,00",
         "leilao": {"titulo": "Pesados #3"}, "fotos": []},
    ]}}
    config = {
        "id": "api1", "url": "https://api.test/lotes?page={pagina}", "paginas": 5,
        "caminho_lista": "dados.itens",
        "campos": {"id_externo": "id", "titulo": "descricao", "marca": "veiculo.marca",
                   "ano_modelo": "veiculo.anoModelo", "categoria": "veiculo.tipo",
                   "monta": "veiculo.monta", "lance_atual": "lanceAtual",
                   "leilao": "leilao.titulo", "data_leilao": "leilao.data", "imagem_url": "fotos.0.url"},
        "url_lote": "https://www.test/lote/{id_externo}",
    }
    cliente = ClienteFalso([RespostaFalsa(dados=pagina1)])
    lotes = [normalizar_lote(l) for l in FonteApiJson(cliente=cliente, **config).coletar()]
    scania, biz = lotes
    assert (scania.id_externo, scania.marca, scania.categoria, scania.monta) == ("10", "Scania", "caminhao", "media")
    assert scania.url == "https://www.test/lote/10"
    assert scania.lance_atual == 250000.5
    assert scania.imagem_url == "https://cdn.test/10.jpg"
    assert (biz.marca, biz.categoria, biz.ano_modelo, biz.lance_atual) == ("Honda", "moto", 2022, 6100.0)


def test_corpo_post_com_pagina():
    config = {"id": "api2", "url": "https://api.test/busca", "metodo": "POST", "paginas": 2,
              "corpo": {"page": "{pagina}", "filtro": "veiculos-{pagina}"},
              "caminho_lista": "itens", "campos": {"id_externo": "id", "titulo": "t"}}
    cliente = ClienteFalso([RespostaFalsa(dados={"itens": [{"id": 1, "t": "FIAT/UNO 2010"}]})])
    list(FonteApiJson(cliente=cliente, **config).coletar())
    assert cliente.urls[0][2]["json"] == {"page": 1, "filtro": "veiculos-1"}
    assert cliente.urls[1][2]["json"] == {"page": 2, "filtro": "veiculos-2"}


class FonteQuebrada(Fonte):
    tipo = "quebrada"

    def coletar(self):
        raise RuntimeError("site fora do ar")


def test_coletor_isola_falhas(tmp_path, monkeypatch):
    monkeypatch.chdir(RAIZ)
    banco = Banco(tmp_path / "t.db")
    demo = criar_fonte({"id": "demo", "tipo": "arquivo", "nome": "Demo", "caminho": "dados/exemplo_lotes.json"})
    relatorio = coletar(banco, [FonteQuebrada("ruim"), demo])
    assert relatorio.resultados[0].erro == "RuntimeError: site fora do ar"
    assert relatorio.resultados[1].lotes == 60
    assert banco.buscar(Filtros(fonte=["demo"]))["total"] == 60


def test_config_padrao_carrega(monkeypatch):
    monkeypatch.chdir(RAIZ)
    fontes = carregar_fontes()
    assert [f.id for f in fontes] == ["demo"]  # os modelos vêm desativados
    todos = json.loads((RAIZ / "config/fontes.json").read_text())["fontes"]
    for config in todos:  # os modelos também precisam ser válidos
        criar_fonte({k: v for k, v in config.items() if k != "ativo"})
