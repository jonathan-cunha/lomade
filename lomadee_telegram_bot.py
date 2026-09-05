"""
Bot de Ofertas Lomadee -> Telegram
Extrai preços de dentro das estruturas 'pricing' e 'options' da API v2.
"""

import os
import json
import time
import random
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

    paginas_sorteadas = random.sample(range(1, 100), 10)
    for pagina in paginas_sorteadas:
        params = {"page": pagina, "limit": 100}
        if SOURCE_ID:
            params["sourceId"] = SOURCE_ID
            params["siteId"] = SOURCE_ID

        try:
            resp = requests.get(url, headers=HEADERS_LOMADEE, params=params, timeout=20)
            if resp.ok:
                data = resp.json()
                itens = data.get("data", []) if isinstance(data, dict) else data
                if isinstance(itens, list):
                    print(f"[debug] Pagina {pagina}: {len(itens)} produtos retornados.")
                    for item in itens:
                        item_id = str(item.get("id") or item.get("productId") or "")
                        if item_id and item_id not in ids_vistos:
                            ids_vistos.add(item_id)
                            produtos.append(item)
        except Exception as e:
            print(f"[aviso] Erro ao buscar pagina {pagina}: {e}")

    random.shuffle(produtos)
    return produtos


def extrair_preco(prod: dict):
    """Extrai o preço das listas 'pricing' ou 'options' ou do nivel raiz."""
    candidatos = []

    # 1. Busca em 'pricing' (estrutura padrao observada no log)
    pricing = prod.get("pricing")
    if isinstance(pricing, list) and pricing:
        for p in pricing:
            if isinstance(p, dict):
                candidatos.extend([p.get("price"), p.get("listPrice")])

    # 2. Busca dentro de 'options'
    options = prod.get("options")
    if isinstance(options, list) and options:
        for opt in options:
            if isinstance(opt, dict):
                opt_pricing = opt.get("pricing")
                if isinstance(opt_pricing, list):
                    for p in opt_pricing:
                        if isinstance(p, dict):
                            candidatos.extend([p.get("price"), p.get("listPrice")])

    # 3. Busca no nivel raiz
    candidatos.extend([
        prod.get("price"),
        prod.get("priceTo"),
        prod.get("priceCurrent"),
        prod.get("salePrice")
    ])

    for c in candidatos:
        if c is not None:
            try:
                val = float(c)
                if val > 0:
                    if val > 50000 and val % 1 == 0:
                        val = val / 100.0
                    return val
            except (ValueError, TypeError):
                continue
    return None


def extrair_link(prod: dict):
    """Extrai a URL original do produto ou link de afiliado."""
    candidatos = [
        prod.get("url"),
        prod.get("link"),
        prod.get("affiliateLink"),
        prod.get("productUrl"),
        prod.get("shortUrl")
    ]

    for c in candidatos:
        if c and isinstance(c, str) and c.startswith("http"):
            return c
    return None


def extrair_imagem(prod: dict):
    """Extrai a URL da imagem do produto."""
    candidatos = []

    # Busca em 'images' da raiz
    images = prod.get("images")
    if isinstance(images, list) and images:
        for img in images:
            if isinstance(img, dict):
                candidatos.append(img.get("url") or img.get("link"))
            elif isinstance(img, str):
                candidatos.append(img)

    # Busca em 'options'
    options = prod.get("options")
    if isinstance(options, list) and options:
        for opt in options:
            if isinstance(opt, dict):
                opt_imgs = opt.get("images")
                if isinstance(opt_imgs, list):
                    for img in opt_imgs:
                        if isinstance(img, dict):
                            candidatos.append(img.get("url"))
                        elif isinstance(img, str):
                            candidatos.append(img)

    # Busca no nivel raiz
    candidatos.extend([
        prod.get("image"),
        prod.get("imageUrl"),
        prod.get("thumbnail")
    ])

    for c in candidatos:
        if c and isinstance(c, str) and c.startswith("http"):
            return c
    return None


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
    ignorados_historico = 0
    ignorados_indisponiveis = 0
    ignorados_sem_preco = 0
    ignorados_sem_imagem = 0

    print(f"[debug] Total de {len(produtos)} produtos unicos obtidos.")

    for prod in produtos:
        if postados_agora >= MAX_POSTS_POR_EXECUCAO:
            break

        prod_id = str(prod.get("id") or prod.get("productId") or "")
        if not prod_id or prod_id in historico:
            ignorados_historico += 1
            continue

        # Filtra produtos indisponiveis
        if prod.get("available") is False:
            ignorados_indisponiveis += 1
            continue

        preco = extrair_preco(prod)
        link_orig = extrair_link(prod)
        org_id = prod.get("organizationId")

        if not preco or not link_orig:
            ignorados_sem_preco += 1
            continue

        imagem_url = extrair_imagem(prod)
        if not imagem_url:
            ignorados_sem_imagem += 1
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
    print("Resumo da execucao:")
    print(f" - Novas postagens: {postados_agora}")
    print(f" - Ignorados por historico: {ignorados_historico}")
    print(f" - Ignorados por estar indisponivel: {ignorados_indisponiveis}")
    print(f" - Ignorados por falta de preco/link: {ignorados_sem_preco}")
    print(f" - Ignorados por falta de imagem: {ignorados_sem_imagem}")


if __name__ == "__main__":
    main()
