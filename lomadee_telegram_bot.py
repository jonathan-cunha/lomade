"""
Bot de ofertas: Lomadee API -> Telegram

Correções desta versão:
1. Agora filtra por palavras-chave (celular, suplementos, TV, etc.) antes de
   postar - antes o robo pegava QUALQUER produto do catalogo, sem filtro,
   por isso apareciam coisas sem relacao nenhuma com o canal.
2. Nao divide mais o preco por 100 automaticamente. A versao anterior
   assumia que a API manda valores "em centavos", o que gerava precos
   errados (ex: R$ 199,90 virava R$ 1,99). Agora o valor e usado como a
   API manda, e o modo de teste (DEBUG=1) mostra os valores brutos para
   você confirmar que estao corretos antes de ligar o robo de verdade.
"""

import json
import os
import sys
import time
import requests

# ============================== CONFIG ==============================

LOMADEE_API_KEY = os.environ["LOMADEE_API_KEY"]
LOMADEE_BASE_URL = os.environ.get("LOMADEE_BASE_URL", "https://api-beta.lomadee.com.br")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DEBUG = os.environ.get("DEBUG") == "1"

# Se a Lomadee realmente manda os precos em centavos (ex: 19990 = R$ 199,90),
# mude isto para "1". Deixe "0" ate confirmar o formato certo rodando com DEBUG=1.
PRECO_EM_CENTAVOS = os.environ.get("PRECO_EM_CENTAVOS", "0") == "1"

# Palavras-chave que definem o que o robo pode postar. Um produto so passa
# se o nome dele contiver pelo menos uma dessas palavras (sem acento,
# sem diferenciar maiusculas/minusculas). Ajuste essa lista a vontade.
PALAVRAS_CHAVE = [
    # Celulares e eletronicos
    "celular", "smartphone", "iphone", "galaxy", "xiaomi", "motorola",
    "fone de ouvido", "fone bluetooth", "carregador", "power bank",
    "notebook", "tablet", "smartwatch",
    # TV e video game
    "tv", "televisao", "smart tv", "video game", "playstation", "xbox",
    "nintendo", "controle de video game",
    # Suplementos e academia
    "suplemento", "whey", "creatina", "bcaa", "pre treino", "albumina",
    "barra de proteina",
    # Roupas e calcados
    "camiseta", "camisa", "calça", "vestido", "jaqueta", "tenis",
    "sapato", "sandalia", "bolsa",
    # Eletrodomesticos
    "geladeira", "fogao", "microondas", "air fryer", "liquidificador",
    "aspirador de po", "ventilador", "ar condicionado", "maquina de lavar",
    # Itens para carro
    "som automotivo", "pneu", "bateria automotiva", "acessorio para carro",
    "capa de banco", "tapete automotivo",
]

PRODUCT_SEARCH_PARAMS = {
    "limit": 100,
    "isAvailable": True,
}

POSTADOS_PATH = "postados.json"

# Respeitar o limite de 10 pedidos por minuto da API da Lomadee
PAUSA_ENTRE_PEDIDOS_API = 6.5  # segundos

# ======================================================================


def normalizar(texto: str) -> str:
    """Remove acentos e deixa em minusculas, para comparar palavras-chave."""
    substituicoes = str.maketrans("áàâãéêíóôõúüç", "aaaaeeiooouuc")
    return (texto or "").lower().translate(substituicoes)


def produto_interessa(nome_produto: str) -> bool:
    nome_normalizado = normalizar(nome_produto)
    return any(normalizar(palavra) in nome_normalizado for palavra in PALAVRAS_CHAVE)


def carregar_postados():
    if os.path.exists(POSTADOS_PATH):
        try:
            with open(POSTADOS_PATH, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def salvar_postados(postados):
    with open(POSTADOS_PATH, "w", encoding="utf-8") as f:
        json.dump(list(postados), f)


def buscar_produtos():
    url = f"{LOMADEE_BASE_URL}/affiliate/products"
    headers = {"x-api-key": LOMADEE_API_KEY}
    produtos = []
    page = 1
    # A API nao informa quantas paginas existem no total (o campo "meta"
    # vem vazio), entao continuamos pedindo paginas ate ela devolver uma
    # lista vazia, com um limite de seguranca para nao rodar para sempre
    # e para respeitar o limite de pedidos por minuto.
    MAX_PAGINAS = 15

    while page <= MAX_PAGINAS:
        params = dict(PRODUCT_SEARCH_PARAMS)
        params["page"] = page

        resp = requests.get(url, headers=headers, params=params, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        pagina = data.get("data", []) or []

        if page == 1:
            meta = data.get("meta", {}) or {}
            print(f"[debug] meta da 1a pagina recebida da API: {json.dumps(meta, ensure_ascii=False)}")

        if not pagina:
            print(f"[debug] pagina {page} veio vazia, parando a busca")
            break

        produtos.extend(pagina)
        print(f"[debug] pagina {page}: {len(pagina)} produtos")
        page += 1
        time.sleep(PAUSA_ENTRE_PEDIDOS_API)

    return produtos


def encurtar_url(url_original, organization_id, feature_id=None):
    """
    POST /affiliate/shortener/url
    Se houver erro (como domain_not_allowed ou rate-limit),
    retorna a URL original como fallback para nao travar o envio.
    """
    endpoint = f"{LOMADEE_BASE_URL}/affiliate/shortener/url"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": LOMADEE_API_KEY,
    }

    payload = {
        "url": url_original,
        "organizationId": int(organization_id) if str(organization_id).isdigit() else organization_id,
        "type": "Custom"
    }
    if feature_id:
        payload["featureId"] = feature_id

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=20)

        if not resp.ok:
            print(f"[ENCURTADOR] Falhou ({resp.status_code}) - Usando URL original de fallback.")
            return url_original

        data = resp.json()

        if isinstance(data, dict):
            if "shortUrl" in data and data["shortUrl"]:
                return data["shortUrl"]
            if "url" in data and data["url"]:
                return data["url"]
            if isinstance(data.get("type"), list) and data["type"]:
                item = data["type"][0]
                if isinstance(item, dict):
                    short_urls = item.get("shortUrls")
                    if isinstance(short_urls, list) and short_urls:
                        return short_urls[0]

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                canais = item.get("availableChannels") or []
                if isinstance(canais, list):
                    for canal in canais:
                        if not isinstance(canal, dict):
                            continue
                        short_urls = canal.get("shortUrls")
                        if isinstance(short_urls, list) and short_urls:
                            return short_urls[0]
    except Exception as e:
        print(f"[ENCURTADOR] Exceção capturada: {e} - Usando URL original.")

    return url_original


def extrair_dados_produto(produto):
    preco = produto.get("price")
    preco_original = produto.get("listPrice") or produto.get("originalPrice")

    options = produto.get("options") or []
    if isinstance(options, list):
        for option in options:
            pricing = (option or {}).get("pricing") or []
            if pricing:
                item = pricing[0] or {}
                preco = item.get("price", preco)
                preco_original = item.get("listPrice", preco_original)
                if preco is not None:
                    break

    imagens = produto.get("images") or []
    imagem = None
    if isinstance(imagens, list) and imagens:
        imagem = (imagens[0] or {}).get("url")

    link_produto = produto.get("url") or produto.get("link") or produto.get("productUrl")

    return {
        "id": produto.get("id") or produto.get("productId"),
        "organization_id": produto.get("organizationId"),
        "nome": produto.get("name") or produto.get("title", "Produto"),
        "preco": preco,
        "preco_original": preco_original,
        "url": link_produto,
        "imagem": imagem or produto.get("image") or produto.get("imageUrl"),
    }


def formatar_mensagem(p):
    preco_atual = p.get("preco")
    preco_original = p.get("preco_original")

    if PRECO_EM_CENTAVOS:
        if isinstance(preco_atual, (int, float)):
            preco_atual = preco_atual / 100
        if isinstance(preco_original, (int, float)):
            preco_original = preco_original / 100

    linhas = [f"🔥 *{p['nome']}*"]

    if (
        isinstance(preco_original, (int, float))
        and isinstance(preco_atual, (int, float))
        and preco_original > preco_atual
    ):
        desconto_pct = round((1 - preco_atual / preco_original) * 100)
        linhas.append(
            f"~De R$ {preco_original:.2f}~ por *R$ {preco_atual:.2f}* "
            f"({desconto_pct}% OFF)"
        )
    elif isinstance(preco_atual, (int, float)):
        linhas.append(f"Por *R$ {preco_atual:.2f}*")

    linhas.append(f"👉 {p['link_afiliado']}")
    return "\n".join(linhas)


def enviar_telegram(texto, imagem_url=None):
    if imagem_url:
        endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": imagem_url,
            "caption": texto,
            "parse_mode": "Markdown",
        }
    else:
        endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": texto,
            "parse_mode": "Markdown",
        }

    resp = requests.post(endpoint, json=payload, timeout=30)
    if not resp.ok:
        motivo = resp.text
        try:
            motivo_json = resp.json()
            motivo = motivo_json.get("description") or resp.text
        except Exception:
            pass
        print(f"[TELEGRAM] Falhou ({resp.status_code}): {motivo}")
    return resp.ok


def rodar_uma_vez():
    postados = carregar_postados()
    produtos = buscar_produtos()
    print(f"[debug] {len(produtos)} produtos recebidos da Lomadee (antes do filtro)")

    relevantes = [p for p in produtos if produto_interessa(
        p.get("name") or p.get("title") or ""
    )]
    print(f"[debug] {len(relevantes)} produtos combinam com as palavras-chave configuradas")

    if DEBUG:
        for produto_bruto in relevantes[:3]:
            p = extrair_dados_produto(produto_bruto)
            print(json.dumps({
                "nome": p["nome"],
                "preco_bruto_da_api": p["preco"],
                "preco_original_bruto_da_api": p["preco_original"],
            }, indent=2, ensure_ascii=False))
        print("[debug] Modo DEBUG ativo - nada foi postado no Telegram. "
              "Confira se os valores de preco acima batem com o preco real do produto "
              "(pesquise o nome do produto no Google pra comparar).")
        return

    novos = 0
    falhas_telegram = 0
    pulados_campo_faltando = 0
    pulados_ja_postado = 0
    marcas = set()
    for produto_bruto in relevantes:
        p = extrair_dados_produto(produto_bruto)

        if not p["id"] or not p["url"] or not p["organization_id"]:
            pulados_campo_faltando += 1
            print(f"[debug] pulado por falta de campo -> id={p['id']!r} "
                  f"url={p['url']!r} organization_id={p['organization_id']!r} "
                  f"nome={p['nome']!r}")
            continue
        if p["id"] in postados:
            pulados_ja_postado += 1
            continue

        p["link_afiliado"] = encurtar_url(
            p["url"],
            p["organization_id"],
        )
        time.sleep(PAUSA_ENTRE_PEDIDOS_API)

        marcas.add(str(p["organization_id"]))
        mensagem = formatar_mensagem(p)

        if enviar_telegram(mensagem, imagem_url=p["imagem"]):
            postados.add(p["id"])
            novos += 1
            print(f"[POSTADO] {p['nome']}")
            time.sleep(2)
        else:
            falhas_telegram += 1

    salvar_postados(postados)
    print(
        f"Concluído. {novos} ofertas novas postadas de {len(marcas)} marcas. "
        f"{falhas_telegram} falharam ao enviar pro Telegram. "
        f"{pulados_campo_faltando} pulados por falta de dados. "
        f"{pulados_ja_postado} pulados por ja terem sido postados antes."
    )


if __name__ == "__main__":
    try:
        rodar_uma_vez()
    except Exception as e:
        print(f"Erro na execução: {e}")
        sys.exit(1)
