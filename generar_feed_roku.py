import json
import re
import time
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://cinebel.cc"

def obtener_urls_sitemap():
    sitemap_candidates = [
        f"{BASE_URL}/wp-sitemap-posts-movies-1.xml",
        f"{BASE_URL}/movie-sitemap.xml",
        f"{BASE_URL}/sitemap-movies.xml"
    ]
    urls = []
    for sm_url in sitemap_candidates:
        try:
            res = requests.get(sm_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if res.status_code == 200 and "<urlset" in res.text:
                root = ET.fromstring(res.content)
                for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
                    if "/movies/" in elem.text and elem.text != f"{BASE_URL}/movies/":
                        urls.append(elem.text)
                if urls:
                    break
        except Exception:
            continue
    return urls

def resolver_video_rumble(context, embed_url):
    try:
        page = context.new_page()
        page.goto(embed_url, wait_until="domcontentloaded", timeout=20000)
        html = page.content()
        page.close()

        config_match = re.search(r'const\s+configId\s*=\s*["\']([a-zA-Z0-9_-]+)["\']', html)
        if not config_match:
            return None

        config_id = config_match.group(1)
        config_url = f"{BASE_URL}/get_video_config.php?id={config_id}"

        # Realizar fetch dentro del contexto del navegador para mantener cookies/referer
        page_api = context.new_page()
        res = page_api.request.get(config_url, headers={"Referer": embed_url})
        if res.status == 200:
            data = res.json()
            for source in data.get("sources", []):
                file_url = source.get("file", "")
                if file_url and "test-streams.mux.dev" not in file_url:
                    page_api.close()
                    return {
                        "url": file_url,
                        "format": "hls" if ".m3u8" in file_url else "mp4"
                    }
        page_api.close()
    except Exception as e:
        print(f"       -> Error en config: {e}")
    return None

def generar_feed(limite_peliculas=15):
    print("[-] Obteniendo lista de títulos desde el sitemap...")
    movie_links = obtener_urls_sitemap()

    if not movie_links:
        print("[!] No se encontraron URLs en los sitemaps.")
        return

    print(f"[+] Total de títulos: {len(movie_links)}. Extrayendo los primeros {limite_peliculas}...")

    peliculas_roku = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox"
        ])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()

        # Visita inicial a la raíz para superar el reto inicial
        try:
            print("[-] Pasando validación inicial en la home...")
            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            time.sleep(3)
        except Exception:
            pass

        for movie_url in movie_links[:limite_peliculas]:
            slug = movie_url.rstrip("/").split("/")[-1]
            print(f"  -> Procesando: {slug}")

            try:
                page.goto(movie_url, wait_until="domcontentloaded", timeout=25000)
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                title_tag = soup.select_one("h1, .sheader .data h1")
                title = title_tag.get_text(strip=True) if title_tag else slug

                poster_tag = soup.select_one(".poster img, .sheader .poster img")
                poster = ""
                if poster_tag:
                    poster = poster_tag.get("data-src") or poster_tag.get("src") or ""
                    if poster.startswith("//"):
                        poster = "https:" + poster

                player_item = soup.select_one("li[data-post][data-nume], div[data-post][data-nume]")
                if not player_item:
                    print("       -> No se encontró elemento player")
                    continue

                post_id = player_item.get("data-post")
                nume = player_item.get("data-nume")
                player_type = player_item.get("data-type", "movie")

                # Petición AJAX desde el contexto del navegador
                ajax_res = page.request.post(
                    f"{BASE_URL}/wp-admin/admin-ajax.php",
                    form={
                        "action": "doo_player_ajax",
                        "post": post_id,
                        "nume": nume,
                        "type": player_type
                    },
                    headers={"Referer": movie_url}
                )

                if ajax_res.status == 200:
                    embed_html = ajax_res.json().get("embed_url", "")
                    src_match = re.search(r'src=["\']([^"\']+)["\']', embed_html)
                    iframe_url = src_match.group(1) if src_match else embed_html

                    if iframe_url.startswith("//"):
                        iframe_url = "https:" + iframe_url

                    stream_info = resolver_video_rumble(context, iframe_url)
                    if stream_info:
                        print(f"     [OK] Enlace extraído ({stream_info['format'].upper()})")
                        peliculas_roku.append({
                            "id": slug,
                            "title": title,
                            "hdPosterUrl": poster,
                            "description": "",
                            "url": stream_info["url"],
                            "streamFormat": stream_info["format"]
                        })
                    else:
                        print("     [x] No se pudo resolver URL de Rumble")
                else:
                    print(f"       -> Falló admin-ajax.php (Status: {ajax_res.status})")

            except Exception as e:
                print(f"       -> Error procesando película: {e}")

            time.sleep(1)

        browser.close()

    with open("feed_roku.json", "w", encoding="utf-8") as f:
        json.dump(peliculas_roku, f, ensure_ascii=False, indent=2)

    print(f"\n[+] Proceso finalizado. {len(peliculas_roku)} películas guardadas en 'feed_roku.json'.")

if __name__ == "__main__":
    generar_feed(limite_peliculas=15)
