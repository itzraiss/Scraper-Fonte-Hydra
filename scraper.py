import aiohttp
import asyncio
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import re
from tqdm import tqdm
from colorama import Fore, init

# Inicialização do Colorama
init(autoreset=True)

# Configurações gerais
BASE_URL = "https://repack-games.com/category/latest-updates/"
CATEGORY_BASE_URLS = [
    "https://repack-games.com/category/latest-updates/",
    "https://repack-games.com/category/action-games/",
    "https://repack-games.com/category/anime-games/",
    "https://repack-games.com/category/adventure-games/",
    "https://repack-games.com/category/building-games/",
    "https://repack-games.com/category/exploration/",
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
MAX_GAMES = 200
CONCURRENT_REQUESTS = 100
MAX_PAGES_CONCURRENT = 80

processed_games_count = 0

# Constante para a regex
REGEX_TITULO = r"(?:\(.*?\)|\s*(Free Download|v\d+(\.\d+)*[a-zA-Z0-9\-]*|Build \d+|P2P|GOG|Repack|Edition.*|FLT|TENOKE)\s*)"

def normalizar_titulo(titulo):
    """Remove informações irrelevantes do título do jogo."""
    titulo_normalizado = re.sub(REGEX_TITULO, "", titulo)
    return titulo_normalizado.strip()

def load_existing_data(json_filename):
    try:
        with open(json_filename, 'r', encoding='utf-8') as json_file:
            return json.load(json_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"name": "Shisuy's source [repack-games]", "downloads": []}

def save_data(json_filename, data):
    with open(json_filename, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, ensure_ascii=False, indent=4)

def parse_relative_date(date_str):
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
            return now.isoformat()

        return result_date.isoformat()
    except Exception:
        return now.isoformat()

def log_game_status(status, category, page, game_title):
    global processed_games_count
    if status == "NEW":
        processed_games_count += 1
        print(f"{Fore.GREEN}[NEW GAME] {category} - Page {page}: {game_title} - Games Processed: {processed_games_count}")
    elif status == "UPDATED":
        print(f"{Fore.YELLOW}[UPDATED] {category} - Page {page}: {game_title}")
    elif status == "IGNORED":
        print(f"{Fore.CYAN}[IGNORED] {category} - Page {page}: {game_title}")
    elif status == "NO_LINKS":
        print(f"{Fore.RED}[NO LINKS] {category} - Page {page}: {game_title}")

async def fetch_page(session, url, semaphore):
    async with semaphore:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            timeout = aiohttp.ClientTimeout(total=50)
            async with session.get(url, headers=headers, timeout=timeout) as response:
                return await response.text() if response.status == 200 else None
        except Exception:
            return None

async def fetch_game_details(session, game_url, semaphore):
    page_content = await fetch_page(session, game_url, semaphore)
    if not page_content:
        return None, None, [], None

    soup = BeautifulSoup(page_content, 'html.parser')

    title = soup.find('h1', class_='entry-title').get_text(strip=True) if soup.find('h1', class_='entry-title') else "Unknown Title"

    size = "Undefined"
    size_patterns = [
        r"(\d+(\.\d+)?)\s*(GB|MB)\s+available space",
        r"Storage:\s*(\d+(\.\d+)?)\s*(GB|MB)"
    ]
    for pattern in size_patterns:
        match = re.search(pattern, page_content, re.IGNORECASE)
        if match:
            size_value = match.group(1)
            size_unit = match.group(3).upper()
            size = f"{size_value} {size_unit}"
            break

    date_element = soup.select_one('.time-article.updated a')
    if date_element and date_element.text.strip():
        relative_date_str = date_element.text.strip()
        upload_date = parse_relative_date(relative_date_str)
    else:
        upload_date = None

    download_links = []
    for tag in soup.find_all('a', href=True):
        href = tag['href']
        if "1fichier.com" in href or "qiwi.gg" in href or "gofile.io" in href:
            download_links.append(href)

    return title, size, download_links, upload_date

async def fetch_last_page_num(session, category_url, semaphore):
    page_content = await fetch_page(session, category_url, semaphore)
    if not page_content:
        return 1

    soup = BeautifulSoup(page_content, 'html.parser')
    last_page_tag = soup.find('a', class_='last', string='Last »')
    if last_page_tag:
        match = re.search(r'page/(\d+)', last_page_tag['href'])
        if match:
            return int(match.group(1))
    return 1

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
            continue

        title, size, links, upload_date = game
        if not links:
            log_game_status("NO_LINKS", category, page_num, title)
            continue

        title_normalized = normalizar_titulo(title)
        existing_game = next((g for g in existing_data["downloads"] if normalizar_titulo(g["title"]) == title_normalized), None)
        if existing_game:
            if upload_date and upload_date > existing_game.get("uploadDate", ""):
                existing_game.update({
                    "title": title,
                    "uris": list(set(existing_game["uris"] + links)),
                    "fileSize": size,
                    "uploadDate": upload_date
                })
                log_game_status("UPDATED", category, page_num, title)
            else:
                log_game_status("IGNORED", category, page_num, title)
        else:
            existing_data["downloads"].append({
                "title": title,
                "uris": links,
                "fileSize": size,
                "uploadDate": upload_date
            })
            log_game_status("NEW", category, page_num, title)
            processed_games_count += 1

async def process_category(session, category_url, semaphore, existing_data):
    last_page_num = await fetch_last_page_num(session, category_url, semaphore)

    tasks = []
    for page_num in range(1, last_page_num + 1):
        if processed_games_count >= MAX_GAMES:
            break
        page_url = f"{category_url}/page/{page_num}"
        tasks.append(process_page(session, page_url, semaphore, existing_data, category_url, page_num))

    for i in range(0, len(tasks), MAX_PAGES_CONCURRENT):
        await asyncio.gather(*tasks[i:i + MAX_PAGES_CONCURRENT])

async def scrape_games():
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    existing_data = load_existing_data(JSON_FILENAME)

    async with aiohttp.ClientSession() as session:
        tasks = [process_category(session, url, semaphore, existing_data) for url in CATEGORY_BASE_URLS]
        await asyncio.gather(*tasks)

    save_data(JSON_FILENAME, existing_data)
    print(f"Total games processed: {processed_games_count}")

if __name__ == "__main__":
    asyncio.run(scrape_games())
