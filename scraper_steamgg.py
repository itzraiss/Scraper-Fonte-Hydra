import aiohttp
import asyncio
from bs4 import BeautifulSoup
import json
from datetime import datetime
import re
import time
from colorama import Fore, init

init(autoreset=True)

BASE_URL = "https://steamgg.net"
JSON_FILENAME = "hydra_source_full.json"
CONCURRENT_REQUESTS = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

# Padrões para identificar links relevantes
VALID_LINK_PATTERNS = [
    r"magnet:\?xt=urn:btih:",  # Links magnet
    r"(https?://.*?\.(zip|rar|7z))",  # Arquivos compactados
    r"(https?://.*?1fichier\.com)",  # 1fichier
    r"(https?://.*?mega\.nz)",  # Mega.nz
    r"(https?://.*?gofile\.io)",  # Gofile
    r"(https?://.*?datanodes\.to\/download)",  # Páginas de redirecionamento como Datanodes
]

def normalize_title(title):
    """Remove informações adicionais do título."""
    REGEX_TITLE = r"(?:\(.*?\)|\s*(Free Download|v\d+(\.\d+)*[a-zA-Z0-9\-]*|Build \d+|P2P|GOG|Repack|Edition.*|FLT|TENOKE)\s*)"
    return re.sub(REGEX_TITLE, "", title).strip()

async def fetch_page(session, url):
    """Faz a requisição de uma página."""
    try:
        async with session.get(url, headers=HEADERS) as response:
            if response.status == 200:
                return await response.text()
            print(f"{Fore.RED}Erro ao acessar {url}: {response.status}")
            return None
    except Exception as e:
        print(f"{Fore.RED}Erro ao buscar {url}: {str(e)}")
        return None

async def fetch_redirect_page(session, redirect_url):
    """Resolve links de páginas intermediárias de download (como datanodes)."""
    print(f"{Fore.CYAN}Seguindo redirecionamento para: {redirect_url}{Fore.RESET}")
    try:
        async with session.get(redirect_url, headers=HEADERS) as response:
            if response.status == 200:
                page_content = await response.text()
                soup = BeautifulSoup(page_content, 'html.parser')

                # Procurar o link de redirecionamento final (esperar 5 segundos ou usar uma abordagem de tempo)
                time.sleep(5)  # Simula a espera de 5 segundos antes de clicar em "Continue"

                # Buscar links de download
                download_links = [a['href'] for a in soup.select("a[href]") if re.search(r"(https?://.*?\.(zip|rar|7z))", a['href'])]
                return download_links
            else:
                print(f"{Fore.RED}Erro ao acessar página de redirecionamento: {redirect_url} ({response.status}){Fore.RESET}")
                return []
    except Exception as e:
        print(f"{Fore.RED}Erro ao seguir redirecionamento {redirect_url}: {str(e)}{Fore.RESET}")
        return []

def filter_links(links):
    """Filtra apenas os links relevantes."""
    filtered_links = []
    for link in links:
        for pattern in VALID_LINK_PATTERNS:
            if re.search(pattern, link):
                filtered_links.append(link)
                break
    return filtered_links

async def get_game_details(session, game_url):
    """Coleta detalhes de um jogo específico."""
    print(f"{Fore.CYAN}Coletando detalhes do jogo: {game_url}{Fore.RESET}")
    page_content = await fetch_page(session, game_url)
    if not page_content:
        return None

    soup = BeautifulSoup(page_content, 'html.parser')

    # Nome do jogo
    title_element = soup.select_one("div.blog-content-title h2")
    title = title_element.get_text(strip=True) if title_element else "Título Desconhecido"
    title = normalize_title(title)

    # Coleta todos os links
    all_links = [a['href'] for a in soup.select("a[href]") if a['href'].startswith("http")]
    download_links = filter_links(all_links)

    # Se algum link for uma página de redirecionamento, seguimos para pegar o link direto
    redirect_links = [link for link in download_links if "datanodes.to/download" in link]
    for redirect_link in redirect_links:
        direct_links = await fetch_redirect_page(session, redirect_link)
        download_links.extend(direct_links)

    # Tamanho do arquivo (se disponível)
    size_match = re.search(r"(\d+(\.\d+)?)\s*(GB|MB)", page_content, re.IGNORECASE)
    file_size = f"{size_match.group(1)} {size_match.group(3)}" if size_match else "Desconhecido"

    # Data de upload
    upload_date = datetime.now().isoformat()

    if download_links:
        return {
            "title": title,
            "uris": download_links,
            "fileSize": file_size,
            "uploadDate": upload_date
        }
    return None

async def scrape_games(game_links):
    """Coleta os dados de todos os jogos."""
    async with aiohttp.ClientSession() as session:
        all_data = {"name": "Hydra Source", "downloads": []}
        tasks = [get_game_details(session, game_url) for game_url in game_links]
        games = await asyncio.gather(*tasks)

        for game in games:
            if game:
                all_data["downloads"].append(game)
                print(f"{Fore.GREEN}[JOGO ADICIONADO] {game['title']}{Fore.RESET}")
            else:
                print(f"{Fore.RED}[SEM LINKS] Jogo ignorado.{Fore.RESET}")

        with open(JSON_FILENAME, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
        print(f"{Fore.GREEN}Dados salvos em {JSON_FILENAME}.{Fore.RESET}")

def load_game_links(file_path):
    """Carrega os links de jogos de um arquivo HTML."""
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
    return [a["href"] for a in soup.select("a[href^='https://steamgg.net/']")]

def main():
    game_links = load_game_links("text.html")  # Substitua pelo caminho correto
    print(f"{Fore.CYAN}Total de jogos encontrados: {len(game_links)}{Fore.RESET}")
    asyncio.run(scrape_games(game_links))

if __name__ == "__main__":
    main()
