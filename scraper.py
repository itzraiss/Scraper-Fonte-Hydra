import aiohttp
import asyncio
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import re
from tqdm import tqdm
from colorama import Fore, init

init(autoreset=True)

BASE_URL = "https://repack-games.com/category/latest-updates/"
CATEGORY_BASE_URLS = [
    "https://repack-games.com/category/latest-updates/",
    "https://repack-games.com/category/action-games/",
    "https://repack-games.com/category/anime-games/",
    "https://repack-games.com/category/adventure-games/",
    "https://repack-games.com/category/building-games/",
    "https://repack-games.com/category/exploration/",
    "https://repack-games.com/category/emulator-games/",
    "https://repack-games.com/category/multiplayer-games/",
    "https://repack-games.com/category/open-world-game/",
    "https://repack-games.com/category/vr-games/",
    "https://repack-games.com/category/fighting-games/",
    "https://repack-games.com/category/adult/",
    "https://repack-games.com/category/horror-games/",
    "https://repack-games.com/category/racing-game/",
    "https://repack-games.com/category/shooting-games/",
    "https://repack-games.com/category/rpg-pc-games/",
    "https://repack-games.com/category/puzzle/",
    "https://repack-games.com/category/sport-game/",
    "https://repack-games.com/category/survival-games/",
    "https://repack-games.com/category/simulation-game/",
    "https://repack-games.com/category/strategy-games/",
    "https://repack-games.com/category/sci-fi-games/"
]   
JSON_FILENAME = "all_games_data.json"
MAX_GAMES = 90000  # Limite máximo de jogos
CONCURRENT_REQUESTS = 40  # Número máximo de requisições simultâneas

# Contadores globais
processed_games_count = 0

# --- Funções auxiliares para carregar e salvar dados ---
def load_existing_data(json_filename):
    try:
        with open(json_filename, 'r', encoding='utf-8') as json_file:
            return json.load(json_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"downloads": []}

def save_data(json_filename, data):
    with open(json_filename, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, ensure_ascii=False, indent=4)

# --- Lógica de datas ---
def parse_relative_date(date_str):
    """
    Converte strings relativas (e.g., "3 days ago") em objetos datetime.
    Retorna a data formatada como string no padrão ISO 8601 (YYYY-MM-DDTHH:MM:SS).
    """
    now = datetime.now()
    try:
        if "hour" in date_str:
            result_date = now - timedelta(hours=int(re.search(r'(\d+)', date_str).group(1)))
        elif "day" in date_str:
            result_date = now - timedelta(days=int(re.search(r'(\d+)', date_str).group(1)))
        elif "week" in date_str:
            result_date = now - timedelta(weeks=int(re.search(r'(\d+)', date_str).group(1)))
        elif "month" in date_str:
            result_date = now - timedelta(days=30 * int(re.search(r'(\d+)', date_str).group(1)))
        elif "year" in date_str:
            result_date = now - timedelta(days=365 * int(re.search(r'(\d+)', date_str).group(1)))
        else:
            print(f"{Fore.RED}Formato de data desconhecido: {date_str}")
            return now.isoformat()  # Caso desconhecido, retorna a data atual

        return result_date.isoformat()  # Converte para formato ISO 8601
    except Exception as e:
        print(f"{Fore.RED}Erro ao interpretar a data '{date_str}': {e}")
        return now.isoformat()  # Retorna a data atual como fallback

# --- Funções de logs detalhados ---
def log_game_status(status, category, page, game_title):
    if status == "NEW":
        print(f"{Fore.GREEN}[NOVO JOGO] {category} - Página {page}: {game_title}")
    elif status == "UPDATED":
        print(f"{Fore.YELLOW}[ATUALIZADO] {category} - Página {page}: {game_title}")
    elif status == "IGNORADO":
        print(f"{Fore.CYAN}[IGNORADO] {category} - Página {page}: {game_title}")
    elif status == "NO_LINKS":
        print(f"{Fore.RED}[SEM LINKS] {category} - Página {page}: {game_title}")

# --- Funções de scraping ---
async def fetch_page(session, url, semaphore):
    async with semaphore:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            timeout = aiohttp.ClientTimeout(total=10)  # Timeout total de 30 segundos
            async with session.get(url, headers=headers, timeout=timeout) as response:
                return await response.text() if response.status == 200 else None
        except Exception as e:
            print(f"{Fore.RED}Erro ao buscar página {url}: {e}")
            return None

async def fetch_game_details(session, game_url, semaphore):
    """
    Busca detalhes do jogo, incluindo título, tamanho, links de download e data de upload.
    """
    page_content = await fetch_page(session, game_url, semaphore)
    if not page_content:
        return None, None, {}, None

    soup = BeautifulSoup(page_content, 'html.parser')

    # Captura o título do jogo
    title = soup.find('h1', class_='entry-title').get_text(strip=True) if soup.find('h1', class_='entry-title') else "Título desconhecido"

    # Captura o tamanho do jogo
    # Captura o tamanho do jogo
    size = "Undefined"
    size_patterns = [
        r"(\d+(\.\d+)?)\s*(GB|MB)\s+available space",  # Exemplo: 25 GB available space
        r"Storage:\s*(\d+(\.\d+)?)\s*(GB|MB)"          # Exemplo: Storage: 25 GB
    ]
    for pattern in size_patterns:
        match = re.search(pattern, page_content, re.IGNORECASE)
        if match:
            size_value = match.group(1)
            size_unit = match.group(3).upper()  # GB ou MB
            size = f"{size_value} {size_unit}"
            break

    # Captura a data relativa do upload
    date_element = soup.select_one('.time-article.updated a')
    if date_element and date_element.text.strip():
        relative_date_str = date_element.text.strip()  # Exemplo: "3 days ago"
        upload_date = parse_relative_date(relative_date_str)
    else:
        upload_date = None  # Caso não seja encontrado

    # Captura os links de download
    download_links = {}
    for tag in soup.find_all('a', href=True):
        href = tag['href']
        if "1fichier.com" in href:
            download_links["1fichier"] = href
        elif "qiwi.gg" in href:
            download_links["qiwi"] = href
        elif "gofile.io" in href:
            download_links["gofile"] = href

    return title, size, download_links, upload_date

async def process_page(session, page_url, semaphore, existing_data, category, page_num):
    global processed_games_count
    page_content = await fetch_page(session, page_url, semaphore)
    if not page_content:
        return

    soup = BeautifulSoup(page_content, 'html.parser')
    articles = soup.find_all('div', class_='articles-content')

    tasks = [
        fetch_game_details(session, li.find('a')['href'], semaphore)
        for article in articles
        for li in article.find_all('li') if li.find('a', href=True)
    ]
    games = await asyncio.gather(*tasks, return_exceptions=True)
    for game in games:
        if isinstance(game, Exception):
            print(f"{Fore.RED}Erro ao processar jogo: {game}")
            continue

        title, size, links, upload_date = game
        if not links:
            log_game_status("NO_LINKS", category, page_num, title)
            continue

        existing_game = next((g for g in existing_data["downloads"] if g["title"] == title), None)
        if existing_game:
            if is_newer_upload_date(existing_game["uploadDate"], upload_date):
                update_existing_game(existing_game, title, links, size, upload_date)
                log_game_status("UPDATED", category, page_num, title)
            else:
                log_game_status("IGNORADO", category, page_num, title)
        else:
            existing_data["downloads"].append({
                "title": title,
                "uris": links,
                "fileSize": size,
                "uploadDate": upload_date
            })
            log_game_status("NEW", category, page_num, title)
            processed_games_count += 1
            if processed_games_count >= MAX_GAMES:
                print(f"{Fore.MAGENTA}Limite de {MAX_GAMES} jogos atingido. Encerrando scraping.")
                return True
    return False

async def process_category(session, category_url, semaphore, existing_data):
    page_num = 1
    while processed_games_count < MAX_GAMES:
        page_url = f"{category_url}/page/{page_num}"
        stop = await process_page(session, page_url, semaphore, existing_data, category_url, page_num)
        if stop:
            break
        page_num += 1

# Funções de gerenciamento de upload e JSON
def is_newer_upload_date(existing_date, new_date):
    if existing_date is None:
        return True
    if isinstance(new_date, str):
        new_date = datetime.fromisoformat(new_date)
    if isinstance(existing_date, str):
        existing_date = datetime.fromisoformat(existing_date)
    return new_date > existing_date

def update_existing_game(existing_game, new_title, new_links, new_size, new_upload_date):
    if is_newer_upload_date(existing_game["uploadDate"], new_upload_date):
        existing_game["title"] = new_title
        existing_game["uris"] = merge_links(existing_game["uris"], new_links)
        existing_game["fileSize"] = new_size
        existing_game["uploadDate"] = new_upload_date

def merge_links(existing_links, new_links):
    merged_links = existing_links.copy()
    for source, link in new_links.items():
        if source not in merged_links:
            merged_links[source] = link
    return merged_links

async def scrape_games():
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    existing_data = load_existing_data(JSON_FILENAME)

    async with aiohttp.ClientSession() as session:
        tasks = [process_category(session, url, semaphore, existing_data) for url in CATEGORY_BASE_URLS]
        await asyncio.gather(*tasks)

    save_data(JSON_FILENAME, existing_data)
    print(f"Total de jogos processados: {len(existing_data['downloads'])}")

if __name__ == "__main__":
    asyncio.run(scrape_games())