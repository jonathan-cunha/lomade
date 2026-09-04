"""
Bot de ofertas: Lomadee API -> Telegram (Multilojas e Todos os Produtos)
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
    """
    Busca produtos de todas as lojas parceiras navegando pelas páginas da API da Lomadee.
    """
    url = f"{LOMADEE_BASE_URL}/affiliate/products"
    headers = {"x-api-key": LOMADEE_API_KEY}
    produtos = []
    page = 1
    max_pages = 10  # Ajuste o limite de páginas por execução se quiser mais ofertas

    while page <= max_pages:
        params = {
            "page": page,
            "limit": 100,
            "isAvailable": True,
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=45)
            if not resp.ok:
                print(f"[API LOMADEE] Erro ao buscar página {page}: {resp.status_code}")
                break

            data = resp.json()
            pagina = data.get("data", []) or []
            produtos.extend(pagina)

            meta = data.get("meta", {}) or {}
            total_pages = int(meta.get("totalPages") or page)

            if page >= total_pages or not pagina:
                break
            page += 1
        except Exception as e:
            print(f"[API LOMADEE] Exceção ao buscar produtos: {e}")
            break

    return produtos


def encurtar_url(url_original, organization_id):
    """
    Tenta encurtar e gerar o link de afiliado. Caso ocorra erro, usa a URL original.
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

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        if resp.ok:
            data = resp.json()
            if isinstance(data, dict):
                if data.get("shortUrl"):
                    return data["shortUrl"]
                if data.get("url"):
                    return data["url"]
    except Exception:
        pass

    return url_original


def normalizar_preco(valor):
    """
    Trata valores inteiros ou decimais vindos da API (ajusta se vier em centavos).
    """
    if valor is None:
        return None
    try:
        val = float(valor)
        # Se o valor for muito alto (ex: 159900 para R$ 1.599,00), converte de centavos para reais
        if val > 10000 and val % 1 == 0:
            val = val / 100
        return val
    except (ValueError, TypeError):
        return None


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
        "preco": normalizar_preco(preco),
        "preco_original": normalizar_preco(preco_original),
        "url": link_produto,
        "imagem": imagem or produto.get("image") or produto.get("imageUrl"),
    }


def formatar_mensagem(p):
    preco_atual = p.get("preco")
    preco_original = p.get("preco_original")

    linhas = [f"🔥 *{p['nome']}*"]

    if preco_original and preco_atual and preco_original > preco_atual:
        desconto_pct = round((1 - preco_atual / preco_original) * 100)
        linhas.append(
            f"~De R$ {preco_original:.2f}~ por *R$ {preco_atual:.2f}* "
            f"({desconto_pct}% OFF)"
        )
    elif preco_atual:
        linhas.append(f"Por *R$ {preco_atual:.2f}*")

    linhas.append(f"\n👉 {p['link_afiliado']}")
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
        print(f"[TELEGRAM] Erro ao enviar ({resp.status_code}): {resp.text}")
    return resp.ok


def rodar_uma_vez():
    postados = carregar_postados()
    produtos = buscar_produtos()

    if DEBUG:
        print(json.dumps(produtos[:2], indent=2, ensure_ascii=False))
        return

    novos = 0
    falhas_telegram = 0
    marcas = set()

    for produto_bruto in produtos:
        p = extrair_dados_produto(produto_bruto)

        # Validações essenciais
        if not p["id"] or not p["url"] or not p["organization_id"] or not p["preco"]:
            continue
        if p["id"] in postados:
            continue

        p["link_afiliado"] = encurtar_url(p["url"], p["organization_id"])
        marcas.add(str(p["organization_id"]))
        mensagem = formatar_mensagem(p)

        if enviar_telegram(mensagem, imagem_url=p["imagem"]):
            postados.add(p["id"])
            novos += 1
            print(f"[POSTADO] {p['nome']} - R$ {p['preco']:.2f}")
            time.sleep(2)
        else:
            falhas_telegram += 1

    salvar_postados(postados)
    print(
        f"Concluído. {novos} ofertas novas postadas de {len(marcas)} lojas/marcas diferentes. "
        f"{falhas_telegram} falhas."
    )


if __name__ == "__main__":
    try:
        rodar_uma_vez()
    except Exception as e:
        print(f"Erro na execução: {e}")
        sys.exit(1)
