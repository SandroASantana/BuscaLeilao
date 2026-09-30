"""API HTTP (FastAPI) e página de busca."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..banco import CAMINHO_PADRAO, ORDENACOES, Banco, Filtros
from ..modelos import CATEGORIAS, CONDICOES, MONTAS

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _filtros(
    q: str | None = None,
    categoria: list[str] | None = Query(None),
    marca: list[str] | None = Query(None),
    modelo: str | None = None,
    monta: list[str] | None = Query(None),
    condicao: list[str] | None = Query(None),
    fonte: list[str] | None = Query(None),
    leilao: list[str] | None = Query(None),
    uf: list[str] | None = Query(None),
    cidade: str | None = None,
    combustivel: list[str] | None = Query(None),
    ano_min: int | None = None,
    ano_max: int | None = None,
    km_max: int | None = None,
    lance_min: float | None = None,
    lance_max: float | None = None,
    data_de: datetime | None = None,
    data_ate: datetime | None = None,
    futuros: bool = False,
) -> Filtros:
    return Filtros(
        texto=q, categoria=categoria, marca=marca, modelo=modelo, monta=monta,
        condicao=condicao, fonte=fonte, leilao=leilao, uf=uf, cidade=cidade,
        combustivel=combustivel, ano_min=ano_min, ano_max=ano_max, km_max=km_max,
        lance_min=lance_min, lance_max=lance_max, data_de=data_de, data_ate=data_ate,
        apenas_futuros=futuros,
    )


def criar_app(caminho_banco: str | Path = CAMINHO_PADRAO) -> FastAPI:
    app = FastAPI(title="BuscaLeilão", description="Busca unificada em leilões de veículos")
    banco = Banco(caminho_banco)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def pagina(request: Request):
        return TEMPLATES.TemplateResponse(request, "index.html", {"ordenacoes": list(ORDENACOES)})

    @app.get("/api/lotes", summary="Busca lotes com filtros")
    def lotes(filtros: Filtros = Depends(_filtros), ordem: str = "data",
              limite: int = Query(30, ge=1, le=500), pagina: int = Query(1, ge=1)):
        return banco.buscar(filtros, ordem=ordem, limite=limite, pagina=pagina)

    @app.get("/api/facetas", summary="Contagens por categoria, marca, monta, leilão...")
    def facetas(filtros: Filtros = Depends(_filtros)):
        return banco.facetas(filtros)

    @app.get("/api/leiloes", summary="O que tem disponível em cada leilão")
    def leiloes(filtros: Filtros = Depends(_filtros)):
        return banco.resumo_leiloes(filtros)

    @app.get("/api/lotes/{fonte}/{id_externo:path}", summary="Detalhe de um lote")
    def lote(fonte: str, id_externo: str):
        encontrado = banco.obter(fonte, id_externo)
        if not encontrado:
            raise HTTPException(404, "lote não encontrado")
        return encontrado

    @app.get("/api/valores", summary="Valores aceitos nos filtros")
    def valores():
        return {"categorias": CATEGORIAS, "montas": MONTAS, "condicoes": CONDICOES,
                "ordenacoes": list(ORDENACOES)}

    return app
