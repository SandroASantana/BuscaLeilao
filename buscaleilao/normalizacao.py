"""Normalização dos dados brutos coletados.

Cada leiloeiro escreve os dados de um jeito ("VW", "VOLKSWAGEN", "Volks";
"Média Monta", "MEDIA MONTA"; "R$ 12.500,00"...). Estas funções transformam
tudo em valores canônicos para que a busca funcione igual em todas as fontes.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from .modelos import Lote


def sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def chave(texto: str | None) -> str:
    """Forma comparável de um texto: minúsculo, sem acento, espaços simples."""
    if not texto:
        return ""
    return re.sub(r"\s+", " ", sem_acento(texto).lower()).strip()


# --------------------------------------------------------------------------
# Montadoras
# --------------------------------------------------------------------------

# nome canônico -> apelidos (já em forma de chave())
MARCAS: dict[str, tuple[str, ...]] = {
    "Audi": ("audi",),
    "BMW": ("bmw",),
    "BYD": ("byd",),
    "Caoa Chery": ("caoa chery", "chery"),
    "Chevrolet": ("chevrolet", "gm", "chev", "gm chevrolet"),
    "Citroën": ("citroen",),
    "Dafra": ("dafra",),
    "Fiat": ("fiat",),
    "Ford": ("ford",),
    "Honda": ("honda",),
    "Hyundai": ("hyundai", "hyundai caoa"),
    "Iveco": ("iveco",),
    "JAC": ("jac",),
    "Jeep": ("jeep",),
    "Kawasaki": ("kawasaki",),
    "Kia": ("kia", "kia motors"),
    "Land Rover": ("land rover", "landrover", "lr"),
    "Mercedes-Benz": ("mercedes-benz", "mercedes benz", "mercedes", "mb", "m.benz", "m benz"),
    "Mitsubishi": ("mitsubishi", "mmc"),
    "Nissan": ("nissan",),
    "Peugeot": ("peugeot",),
    "Renault": ("renault",),
    "Scania": ("scania",),
    "Shineray": ("shineray",),
    "Suzuki": ("suzuki",),
    "Toyota": ("toyota",),
    "Volkswagen": ("volkswagen", "vw", "volks", "vw/volkswagen", "vw caminhoes", "volkswagen caminhoes"),
    "Volvo": ("volvo",),
    "Yamaha": ("yamaha",),
}

_APELIDO_PARA_MARCA = {apelido: nome for nome, apelidos in MARCAS.items() for apelido in apelidos}

# Marcas que só fabricam motos (no mercado brasileiro).
MARCAS_MOTO = {"Dafra", "Kawasaki", "Shineray", "Yamaha"}
MARCAS_CAMINHAO = {"Scania", "Iveco"}

# Modelos que ajudam a desambiguar a categoria quando a marca faz de tudo.
# Só modelos de marcas que também fazem carros (Honda, Suzuki, BMW...); as
# marcas exclusivas de moto já estão em MARCAS_MOTO. Evita palavras comuns do
# português ("fazer") que gerariam falsos positivos na descrição.
MODELOS_MOTO = (
    "cg", "cb", "cg 160", "cg 150", "cb 300", "cb 500", "biz", "pop 100", "pop 110", "titan",
    "fan 150", "fan 160", "bros", "xre", "pcx", "nxr", "cbr", "hornet", "sahara", "twister",
    "intruder", "burgman", "gsx", "gs 500", "g 310", "f 800", "r 1200 gs", "r 1250 gs",
)
MODELOS_CAMINHAO = (
    "accelo", "atego", "axor", "actros", "cargo", "constellation", "delivery", "worker",
    "tector", "stralis", "daily", "fh", "vm", "r 440", "r440", "g 420", "p 310",
    "l 1113", "1113", "1620", "24.250", "24250", "8.150", "8150",
)
MODELOS_UTILITARIO = (
    "strada", "saveiro", "montana", "toro", "hilux", "s10", "ranger", "amarok", "l200",
    "frontier", "fiorino", "kangoo", "doblo", "ducato", "master", "sprinter", "boxer",
    "jumper", "hr", "bongo", "oroch", "maverick", "rampage", "expert", "partner", "trafic",
)
MODELOS_ONIBUS = ("onibus", "micro-onibus", "microonibus", "marcopolo", "caio", "busscar", "volare")
PALAVRAS_MAQUINA = (
    "trator", "retroescavadeira", "escavadeira", "pa carregadeira", "empilhadeira",
    "motoniveladora", "rolo compactador", "colheitadeira",
)


def normalizar_marca(texto: str | None) -> str | None:
    """Converte uma marca escrita de qualquer forma no nome canônico.

    Retorna o texto original (com capitalização) se a marca não for conhecida.
    """
    k = chave(texto)
    if not k:
        return None
    if k in _APELIDO_PARA_MARCA:
        return _APELIDO_PARA_MARCA[k]
    return texto.strip().title()


def encontrar_marca(texto: str | None) -> str | None:
    """Procura uma montadora conhecida em qualquer lugar de um texto livre."""
    k = chave(texto)
    if not k:
        return None
    # Testa os apelidos mais longos primeiro ("mercedes benz" antes de "mb").
    for apelido in sorted(_APELIDO_PARA_MARCA, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(apelido)}(?![a-z0-9])", k):
            return _APELIDO_PARA_MARCA[apelido]
    return None


# --------------------------------------------------------------------------
# Categoria, monta e condição
# --------------------------------------------------------------------------

_CATEGORIA_ALIASES = {
    "carro": "carro", "carros": "carro", "automovel": "carro", "automoveis": "carro",
    "passeio": "carro", "veiculo leve": "carro", "leves": "carro", "leve": "carro",
    "moto": "moto", "motos": "moto", "motocicleta": "moto", "motocicletas": "moto",
    "motoneta": "moto", "ciclomotor": "moto",
    "caminhao": "caminhao", "caminhoes": "caminhao", "pesado": "caminhao", "pesados": "caminhao",
    "cavalo mecanico": "caminhao", "carreta": "caminhao",
    "utilitario": "utilitario", "utilitarios": "utilitario", "pickup": "utilitario",
    "pick-up": "utilitario", "picape": "utilitario", "van": "utilitario", "furgao": "utilitario",
    "onibus": "onibus", "micro-onibus": "onibus", "microonibus": "onibus",
    "maquina": "maquina", "maquinas": "maquina", "trator": "maquina", "implemento": "maquina",
    "outros": "outros", "diversos": "outros",
}


def _contem_palavra(texto: str, palavras) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", texto) for p in palavras)


def normalizar_categoria(texto: str | None) -> str | None:
    k = chave(texto)
    if not k:
        return None
    if k in _CATEGORIA_ALIASES:
        return _CATEGORIA_ALIASES[k]
    for alias, categoria in _CATEGORIA_ALIASES.items():
        if _contem_palavra(k, [alias]):
            return categoria
    return None


def inferir_categoria(texto: str | None, marca: str | None = None) -> str | None:
    """Deduz a categoria a partir do título/descrição e da marca."""
    k = chave(texto)
    if _contem_palavra(k, PALAVRAS_MAQUINA):
        return "maquina"
    if _contem_palavra(k, MODELOS_ONIBUS):
        return "onibus"
    if marca in MARCAS_MOTO or _contem_palavra(k, MODELOS_MOTO) or _contem_palavra(k, ("moto", "motocicleta")):
        return "moto"
    if marca in MARCAS_CAMINHAO or _contem_palavra(k, MODELOS_CAMINHAO) or _contem_palavra(k, ("caminhao", "cavalo mecanico")):
        return "caminhao"
    if _contem_palavra(k, MODELOS_UTILITARIO) or _contem_palavra(k, ("pickup", "picape", "van", "furgao")):
        return "utilitario"
    if marca:
        return "carro"
    return None


def normalizar_monta(texto: str | None) -> str | None:
    """Extrai a classificação de monta ("pequena", "media", "grande", "sem_monta")."""
    k = chave(texto)
    if not k:
        return None
    if k in {"pequena", "media", "grande"}:
        return k
    if re.search(r"\bsem monta\b|\bmonta:? ?(nao|nenhuma)\b", k):
        return "sem_monta"
    m = re.search(r"\b(pequena|media|grande)\s+monta\b|\bmonta:?\s*(pequena|media|grande)\b", k)
    if m:
        return m.group(1) or m.group(2)
    return None


_CONDICOES_PALAVRAS = (
    ("sucata", ("sucata", "baixa definitiva", "fim de vida util")),
    ("recuperado_financiamento", ("recuperado de financiamento", "recuperado financiamento",
                                  "retomado", "busca e apreensao", "financiamento")),
    ("roubo_furto", ("roubo", "furto", "recuperado de roubo")),
    ("sinistro", ("sinistro", "sinistrado", "colisao", "enchente", "alagamento", "incendio")),
    ("apreendido", ("apreendido", "patio detran", "removido", "detran")),
    ("frota", ("frota", "renovacao de frota", "locadora")),
    ("particular", ("particular",)),
)


def normalizar_condicao(texto: str | None) -> str | None:
    k = chave(texto)
    if not k:
        return None
    for condicao, palavras in _CONDICOES_PALAVRAS:
        if _contem_palavra(k, palavras):
            return condicao
    return None


# --------------------------------------------------------------------------
# Números, anos, datas
# --------------------------------------------------------------------------

def parse_dinheiro(valor) -> float | None:
    """Aceita 'R$ 12.345,67', '12345.67', 12345 ... e devolve float."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = re.sub(r"[^\d,.\-]", "", str(valor))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s:  # formato brasileiro: ponto é milhar, vírgula é decimal
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.search(r"\.\d{3}$", s):  # 12.345 ou 1.234.567
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_inteiro(valor) -> int | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    s = re.sub(r"[^\d]", "", str(valor))
    return int(s) if s else None


_RE_ANOS = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*/\s*((?:19|20)\d{2})(?!\d)")
_RE_ANO = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def extrair_anos(texto: str | None) -> tuple[int | None, int | None]:
    """'GOL 1.0 2015/2016' -> (2015, 2016); '... 2018' -> (2018, 2018)."""
    if not texto:
        return None, None
    m = _RE_ANOS.search(texto)
    if m:
        return int(m.group(1)), int(m.group(2))
    anos = [int(a) for a in _RE_ANO.findall(texto) if 1950 <= int(a) <= datetime.now().year + 1]
    if anos:
        return anos[0], anos[0]
    return None, None


_FORMATOS_DATA = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y às %H:%M",
    "%d/%m/%Y as %H:%M",
    "%d/%m/%Y - %H:%M",
    "%d/%m/%Y %Hh%M",
    "%d/%m/%Y",
)


def parse_data(valor) -> datetime | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, (int, float)):  # timestamp (s ou ms)
        return datetime.fromtimestamp(valor / 1000 if valor > 1e11 else valor)
    s = re.sub(r"\s+", " ", str(valor)).strip()
    s = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", s)  # ignora fuso
    s = re.sub(r"\.\d+$", "", s)  # ignora frações de segundo
    for fmt in _FORMATOS_DATA:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    m = re.search(r"(\d{2}/\d{2}/\d{4})(?:\D+(\d{1,2})[:h](\d{2}))?", s)
    if m:
        data = datetime.strptime(m.group(1), "%d/%m/%Y")
        if m.group(2):
            data = data.replace(hour=int(m.group(2)), minute=int(m.group(3)))
        return data
    return None


UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


def separar_cidade_uf(texto: str | None) -> tuple[str | None, str | None]:
    """'Campinas/SP', 'Campinas - SP', 'Campinas, SP' -> ('Campinas', 'SP')."""
    if not texto:
        return None, None
    m = re.match(r"^\s*(.+?)\s*[/\-,]\s*([A-Za-z]{2})\s*$", texto)
    if m and m.group(2).upper() in UFS:
        return m.group(1).strip().title(), m.group(2).upper()
    if texto.strip().upper() in UFS:
        return None, texto.strip().upper()
    return texto.strip().title(), None


# --------------------------------------------------------------------------
# Normalização de um lote completo
# --------------------------------------------------------------------------

def _separar_marca_modelo(titulo: str) -> tuple[str | None, str | None]:
    """Formato comum em leilões: 'VW/GOL 1.0 MI 2015/2016' ou 'FIAT - UNO WAY'."""
    m = re.match(r"^\s*([A-Za-z.\- ]{2,20}?)\s*[/\-]\s*([A-Za-z0-9].*)$", titulo)
    if m:
        marca = encontrar_marca(m.group(1))
        if marca:
            modelo = _RE_ANOS.sub("", m.group(2))
            return marca, modelo.strip(" -/") or None
    return encontrar_marca(titulo), None


def normalizar_lote(lote: Lote) -> Lote:
    """Preenche/padroniza os campos de um lote a partir do que estiver disponível."""
    texto_todo = " ".join(filter(None, [lote.titulo, lote.descricao, lote.modelo, lote.versao]))

    if lote.marca:
        lote.marca = normalizar_marca(lote.marca)
    marca_titulo, modelo_titulo = _separar_marca_modelo(lote.titulo or "")
    lote.marca = lote.marca or marca_titulo or encontrar_marca(texto_todo)
    if not lote.modelo and modelo_titulo:
        lote.modelo = modelo_titulo
    if lote.modelo:
        lote.modelo = lote.modelo.strip().upper()

    if not lote.ano_fabricacao and not lote.ano_modelo:
        lote.ano_fabricacao, lote.ano_modelo = extrair_anos(texto_todo)
    lote.ano_fabricacao = lote.ano_fabricacao or lote.ano_modelo
    lote.ano_modelo = lote.ano_modelo or lote.ano_fabricacao

    categoria = normalizar_categoria(lote.categoria) if lote.categoria else None
    lote.categoria = categoria or inferir_categoria(texto_todo, lote.marca)

    lote.monta = normalizar_monta(lote.monta) or normalizar_monta(texto_todo)
    lote.condicao = normalizar_condicao(lote.condicao) or normalizar_condicao(texto_todo)
    if lote.monta is None and lote.condicao == "sucata":
        lote.monta = "grande"

    if lote.cidade and not lote.uf:
        lote.cidade, lote.uf = separar_cidade_uf(lote.cidade)
    if lote.uf:
        lote.uf = lote.uf.strip().upper()[:2]

    if lote.combustivel:
        lote.combustivel = chave(lote.combustivel)
    return lote
