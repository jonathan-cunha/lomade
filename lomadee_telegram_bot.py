"""
Bot de ofertas: Lomadee API -> Telegram
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

PRODUCT_SEARCH_PARAMS = {
    "limit": 100,
    "isAvailable": True,
}

POSTADOS_PATH = "postados.json"

# ======================================================================


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

    while True:
        params = dict(PRODUCT_SEARCH_PARAMS)
        params["page"] = page

        resp = requests.get(url, headers=headers, params=params, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        pagina = data.get("data", []) or []
        produtos.extend(pagina)

        meta = data.get("meta", {}) or {}
        total_pages = int(meta.get("totalPages") or page)
        if page >= total_pages or not pagina:
            break
        page += 1

    return produtos


def encurtar_url(url_original, organization_id, feature_id=None):
    """
    POST /affiliate/shortener/url
    Ajustado estritamente para as exigências do schema da Lomadee.
    """
    endpoint = f"{LOMADEE_BASE_URL}/affiliate/shortener/url"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": LOMADEE_API_KEY,
    }
    
    # Campo 'url' e 'type' com Capital Case ("Custom")
    payload = {
        "url": url_original,
        "organizationId": int(organization_id) if str(organization_id).isdigit() else organization_id,
        "type": "Custom"
    }
    if feature_id:
        payload["featureId"] = feature_id

    resp = requests.post(endpoint, headers=headers, json=payload, timeout=20)
    
    if not resp.ok:
        print(f"Erro no encurtador ({resp.status_code}): {resp.text}")
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
        print(f"Erro ao enviar pro Telegram: {resp.status_code} - {resp.text}")
    return resp.ok


def rodar_uma_vez():
    postados = carregar_postados()
    produtos = buscar_produtos()

    if DEBUG:
        print(json.dumps(produtos[:2], indent=2, ensure_ascii=False))
        return

    novos = 0
    marcas = set()
    for produto_bruto in produtos:
        p = extrair_dados_produto(produto_bruto)

        if not p["id"] or not p["url"] or not p["organization_id"]:
            continue
        if p["id"] in postados:
            continue

        p["link_afiliado"] = encurtar_url(
            p["url"],
            p["organization_id"],
        )

        marcas.add(str(p["organization_id"]))
        mensagem = formatar_mensagem(p)

        if enviar_telegram(mensagem, imagem_url=p["imagem"]):
            postados.add(p["id"])
            novos += 1
            print(f"Postado: {p['nome']}")
            time.sleep(2)

    salvar_postados(postados)
    print(f"Concluído. {novos} ofertas novas postadas de {len(marcas)} marcas.")


if __name__ == "__main__":
    try:
        rodar_uma_vez()
    except Exception as e:
        print(f"Erro na execução: {e}")
        sys.exit(1)
