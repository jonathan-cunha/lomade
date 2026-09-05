"""
Bot de Ofertas Lomadee -> Telegram
Busca ofertas ativas na Lomadee e envia para o Telegram.
"""

import os
import json
import time
import requests

# CONFIGURACOES
LOMADEE_API_KEY = os.environ.get("LOMADEE_API_KEY")
LOMADEE_BASE_URL = os.environ.get("LOMADEE_BASE_URL", "https://api-beta.lomadee.com.br")
SOURCE_ID = os.environ.get("LOMADEE_SOURCE_ID")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME")

MAX_POSTS_POR_EXECUCAO = 5
ARQUIVO_HISTORICO = "postados.json"

HEADERS_LOMADEE = {
    "x-api-key": LOMADEE_API_KEY,
    "Content-Type": "application/json"
}

# Palavras-chave de busca abrangentes
CATEGORIAS_AMPLAS = [
    "smartphone", "tv", "notebook", "fone", "geladeira", 
    "air fryer", "smartwatch", "ferramentas", "gamer", "cafeteira"
]


def carregar_historico() -> set:
    if not os.path.exists(ARQUIVO_HISTORICO):
        return set()
    try:
        with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def salvar_historico(historico: set):
    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(sorted(historico), f, ensure_ascii=False, indent=2)


def buscar_produtos_lomadee():
    produtos = []
    ids_vistos = set()
    url = f"{LOMADEE_BASE_URL}/affiliate/products"

    for termo in CATEGORIAS_AMPLAS:
        params = {
            "page": 1,
            "limit": 30,
            "keyword": termo
        }
        try:
            resp = requests.get(url, headers=HEADERS_LOMADEE, params=params, timeout=20)
            if not resp.ok:
                print(f"[aviso] Erro HTTP {resp.status_code} para '{termo}': {resp.text}")
                continue

            data = resp.json()
            # Trata respostas em lista ou dicionario
            itens = data.get("data", []) if isinstance(data, dict) else data
            if not isinstance(itens, list):
                itens = []

            print(f"[debug] '{termo}': {len(itens)} produtos retornados")

            for item in itens:
                item_id = str(item.get("id") or item.get("productId") or "")
                if item_id and item_id not in ids_vistos:
                    ids_vistos.add(item_id)
                    produtos.append(item)
        except Exception as e:
            print(f"[aviso] erro ao buscar termo '{termo}': {e}")

    return produtos


def encurtar_url_lomadee(url_original, organization_id):
    endpoint = f"{LOMADEE_BASE_URL}/affiliate/shortener/url"
    
    org_target = SOURCE_ID or organization_id
    try:
        org_id_val = int(org_target) if str(org_target).isdigit() else org_target
    except Exception:
        org_id_val = org_target

    payload = {
        "url": url_original,
        "organizationId": org_id_val,
        "type": "Custom"
    }

    try:
        resp = requests.post(endpoint, headers=HEADERS_LOMADEE, json=payload, timeout=15)
        if resp.ok:
            data = resp.json()
            if isinstance(data, dict):
                return data.get("shortUrl") or data.get("url") or url_original
    except Exception:
        pass
    return url_original


def normalizar_preco(valor):
    if valor is None:
        return None
    try:
        val = float(valor)
        if val > 10000 and val % 1 == 0:
            val = val / 100
        return val
    except (ValueError, TypeError):
        return None


def formatar_preco(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def postar_no_telegram(oferta: dict):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    legenda = (
        f"🔥 *{oferta['titulo']}*\n\n"
        f"Por *{formatar_preco(oferta['preco'])}*\n\n"
        f"👉 [Ver oferta]({oferta['link']})"
    )

    payload = {
        "chat_id": CHANNEL_USERNAME,
        "photo": oferta["imagem"],
        "caption": legenda,
        "parse_mode": "Markdown",
    }

    resp = requests.post(url, data=payload, timeout=20)
    resp.raise_for_status()


def main():
    if not LOMADEE_API_KEY or not BOT_TOKEN or not CHANNEL_USERNAME:
        raise SystemExit("Erro: LOMADEE_API_KEY, BOT_TOKEN ou CHANNEL_USERNAME nao configurados.")

    historico = carregar_historico()
    produtos = buscar_produtos_lomadee()
    postados_agora = 0

    print(f"[debug] Total de {len(produtos)} produtos unicos obtidos da Lomadee.")

    for prod in produtos:
        if postados_agora >= MAX_POSTS_POR_EXECUCAO:
            break

        prod_id = str(prod.get("id") or prod.get("productId") or "")
        if not prod_id or prod_id in historico:
            continue

        preco = normalizar_preco(prod.get("price"))
        link_orig = prod.get("url") or prod.get("link")
        org_id = prod.get("organizationId")

        if not preco or not link_orig:
            continue

        imagens = prod.get("images") or []
        imagem_url = None
        if isinstance(imagens, list) and imagens:
            imagem_url = (imagens[0] or {}).get("url") if isinstance(imagens[0], dict) else imagens[0]
        imagem_url = imagem_url or prod.get("image") or prod.get("imageUrl")

        if not imagem_url:
            continue

        link_afiliado = encurtar_url_lomadee(link_orig, org_id)

        oferta = {
            "id": prod_id,
            "titulo": prod.get("name") or prod.get("title", "Oferta Imperdível"),
            "preco": preco,
            "imagem": imagem_url,
            "link": link_afiliado
        }

        try:
            postar_no_telegram(oferta)
            print(f"[ok] Postado: {oferta['titulo']} - {formatar_preco(oferta['preco'])}")
            historico.add(prod_id)
            postados_agora += 1
            time.sleep(2)
        except Exception as e:
            print(f"[erro] Falha ao postar '{oferta['titulo']}': {e}")

    salvar_historico(historico)
    print(f"Concluído. {postados_agora} ofertas novas postadas.")


if __name__ == "__main__":
    main()
