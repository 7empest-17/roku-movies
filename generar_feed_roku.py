import json
import re
import time
from bs4 import BeautifulSoup
from curl_cffi import requests

BASE_URL = "https://cinebel.cc"
AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"

# Sesión con impersonación de Edge/Chrome para superar Cloudflare
session = requests.Session(impersonate="edge101")
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Referer": BASE_URL,
    "Accept-Language": "es-419,es;q=0.9,es-ES;q=0.8,en;q=0.7"
})

def resolver_video_rumble(embed_url):
    try:
        res = session.get(embed_url, headers={"Referer": BASE_URL})
        if res.status_code != 200:
            return None

        html = res.text
        config_match = re.search(r'const\s+configId\s*=\s*["\']([a-zA-Z0-9_-]+)["\']', html)
        if not config_match:
            return None

        config_id = config_match.group(1)
        config_url = f"{BASE_URL}/get_video_config.php?id={config_id}"

        cfg_res = session.get(config_url, headers={
            "Referer": embed_url,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest"
        })

        if cfg_res.status_code == 200:
            data = cfg_res.json()
            for source in data.get("sources", []):
                file_url = source.get("file", "")
                if file_url and "test-streams.mux.dev" not in file_url:
                    return {
                        "url": file_url,
                        "format": "hls" if ".m3u8" in file_url else "mp4"
                    }
    except Exception as e:
        print(f"    [!] Error en config: {e}")
    return None

def extraer_stream_pelicula(movie_url):
    try:
        res = session.get(movie_url)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        player_item = soup.select_one("li[data-post][data-nume], div[data-post][data-nume]")
        if not player_item:
            return None

        post_id = player_item.get("data-post")
        nume = player_item.get("data-nume")
        player_type = player_item.get("data-type", "movie")

        payload = {
            "action": "doo_player_ajax",
            "post": post_id,
            "nume": nume,
            "type": player_type
        }

        ajax_res = session.post(AJAX_URL, data=payload, headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": movie_url,
            "X-Requested-With": "XMLHttpRequest"
        })

        if ajax_res.status_code == 200:
            embed_html = ajax_res.json().get("embed_url", "")
            src_match = re.search(r'src=["\']([^"\']+)["\']', embed_html)
            iframe_url = src_match.group(1) if src_match else embed_html

            if iframe_url.startswith("//"):
                iframe_url = "https:" + iframe_url

            return resolver_video_rumble(iframe_url)
    except Exception as e:
        print(f"    [!] Error en ajax: {e}")
    return None

def generar_feed(max_paginas=2):
    peliculas_roku = []

    for page in range(1, max_paginas + 1):
        catalog_url = f"{BASE_URL}/movies/" if page == 1 else f"{BASE_URL}/movies/page/{page}/"
        print(f"\n[-] Escaneando catálogo página {page}: {catalog_url}")

        res = session.get(catalog_url)
        if res.status_code != 200:
            print(f"[!] Error al cargar catálogo ({res.status_code})")
            break

        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("article.item.movies, .item.movies")

        for item in items:
            link_tag = item.select_one("a")
            img_tag = item.select_one("img")
            title_tag = item.select_one(".data h3, .title a, a")

            if not link_tag:
                continue

            movie_url = link_tag.get("href", "")
            title = title_tag.get_text(strip=True) if title_tag else "Sin título"
            poster = img_tag.get("data-src") or img_tag.get("src") or "" if img_tag else ""
            if poster.startswith("//"):
                poster = "https:" + poster

            print(f"  -> Extrayendo: {title}")
            stream_info = extraer_stream_pelicula(movie_url)

            if stream_info:
                print(f"     [OK] Video directo encontrado ({stream_info['format'].upper()})")
                peliculas_roku.append({
                    "id": movie_url.rstrip("/").split("/")[-1],
                    "title": title,
                    "hdPosterUrl": poster,
                    "description": "",
                    "url": stream_info["url"],
                    "streamFormat": stream_info["format"]
                })
            else:
                print("     [x] No se pudo obtener stream")

            time.sleep(1)

    with open("feed_roku.json", "w", encoding="utf-8") as f:
        json.dump(peliculas_roku, f, ensure_ascii=False, indent=2)

    print(f"\n[+] Proceso completado. {len(peliculas_roku)} películas guardadas en 'feed_roku.json'.")

if __name__ == "__main__":
    # Ajusta max_paginas según la cantidad de películas que desees extraer
    generar_feed(max_paginas=1)