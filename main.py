import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException  # Для таймаута загрузки
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv
import time
import re
import random  # Для рандомных ID
import sqlite3  # Для БД

load_dotenv()
# Настройки
URL = "https://lolz.live/"
MIN_LIKES = int(os.getenv('MIN_SYMPHATY'))
NUM_IDS = 5000  # Количество случайных ID для проверки (можно изменить)
MIN_ID = int(os.getenv('MIN_RANDOM_ID'))
MAX_ID = int(os.getenv('MAX_RANDOM_ID'))
OUTPUT_FILE = 'tgs.txt'  # Файл для сохранения тг
DB_FILE = 'null_accounts.db'  # БД для нулевых акков
PAGE_LOAD_TIMEOUT = 5  # Таймаут загрузки страницы в секундах
telegram_list = []

# Инициализация БД
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS null_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL
    )
''')
conn.commit()

options = uc.ChromeOptions()
options.add_argument('--no-sandbox')
# options.add_argument('--headless')  # Убери для дебага
driver = uc.Chrome(options=options, version_main=None)
wait = WebDriverWait(driver, 20)

try:
    driver.get(URL)
    time.sleep(5)
    
    logged_in = False
    try:
        login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="navigation"]/div[3]/nav/div/div[2]/a[1]')))
        print("Кнопка входа найдена!")
        login_btn.click()
        print("Клик по кнопке входа успешен.")
    except Exception as e:
        print(f"Ошибка клика по кнопке входа: {e}")
        logged_in = True
    
    if not logged_in:
        time.sleep(3)
        try:
            username = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="ctrl_pageLogin_login"]')))
            password = driver.find_element(By.XPATH, '//*[@id="ctrl_pageLogin_password"]')
            username.send_keys(os.getenv('LOLZ_LOGIN'))
            password.send_keys(os.getenv('LOLZ_PASSWORD'))
            submit_btn = driver.find_element(By.XPATH, '//*[@id="pageLogin"]/div[2]/div[2]/div[4]/input')
            submit_btn.click()
            time.sleep(3)
            print("Логин успешен!")
            logged_in = True
        except Exception as e:
            print(f"Ошибка формы логина: {e}. Продолжаем без.")
    
    print(f"Генерируем {NUM_IDS} случайных ID от {MIN_ID} до {MAX_ID}...")
    
    # Генерация случайных ID
    random_ids = [random.randint(MIN_ID, MAX_ID) for _ in range(NUM_IDS)]
    
    processed_count = 0
    for i, user_id in enumerate(random_ids, 1):
        # Проверка в БД: если нулевый — пропускаем
        cursor.execute("SELECT user_id FROM null_accounts WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            print(f"[{i}/{NUM_IDS}] ID {user_id}: Уже в БД (нулевой), пропускаем")
            continue
        
        profile_url = f"{URL}members/{user_id}/"
        print(f"[{i}/{NUM_IDS}] Проверяем ID: {user_id}")
        
        # Установка таймаута загрузки
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        
        try:
            driver.get(profile_url)
        except TimeoutException:
            print(f"ID {user_id}: Таймаут загрузки страницы ({PAGE_LOAD_TIMEOUT} сек) — останавливаем и в БД")
            # Остановить загрузку (на всякий случай)
            driver.execute_script("window.stop();")
            # В БД как нулевой
            cursor.execute("INSERT OR IGNORE INTO null_accounts (user_id) VALUES (?)", (user_id,))
            conn.commit()
            continue
        
        time.sleep(2)  # Задержка после загрузки
        
        try:
            soup_profile = BeautifulSoup(driver.page_source, 'html.parser')
            content_block = soup_profile.select_one('#content')
            if not content_block:
                print(f"ID {user_id}: Профиль не найден")
                # Добавляем в БД как нулевой
                cursor.execute("INSERT OR IGNORE INTO null_accounts (user_id) VALUES (?)", (user_id,))
                conn.commit()
                continue
            
            # Лайки
            likes_elem = soup_profile.select_one('#content > div > div > div:nth-child(3) > div:nth-child(2) > div:nth-child(1) > div:nth-child(2) > a:nth-child(1) > div:nth-child(1)')
            if not likes_elem:
                # Нет блока — в БД
                cursor.execute("INSERT OR IGNORE INTO null_accounts (user_id) VALUES (?)", (user_id,))
                conn.commit()
                continue
            
            likes_text = likes_elem.get_text(strip=True)
            likes_match = re.search(r'(\d+)', likes_text)
            if not likes_match:
                # Нет числа — в БД
                cursor.execute("INSERT OR IGNORE INTO null_accounts (user_id) VALUES (?)", (user_id,))
                conn.commit()
                continue
            
            likes = int(likes_match.group(1))
            print(f"ID {user_id}: Лайки = {likes}")
            
            # Если likes == 0 и нет TG — в БД
            has_tg = False
            if likes >= MIN_LIKES:
                # TG: основной + fallback
                tg_elem = soup_profile.select_one('#profile_short > div:nth-child(1) > div:nth-child(3) > div:nth-child(2) > a')
                if tg_elem:
                    href = tg_elem.get('href')
                    text = tg_elem.get_text(strip=True)
                    print(f"ID {user_id}: TG-элемент найден! href='{href}', text='{text}'")
                    
                    username_match = re.search(r'(t\.me|telegram\.(me|org))/([^/?\s]+)', href, re.I)
                    if username_match:
                        username = username_match.group(3).strip('/')
                        if username:
                            telegram_list.append(username)
                            print(f"ID {user_id}: Добавлен TG: @{username}")
                            has_tg = True
                
                if not has_tg:
                    # Fallback: все t.me по странице
                    all_tg_links = soup_profile.find_all('a', href=re.compile(r't\.me|telegram\.me|telegram\.org', re.I))
                    if all_tg_links:
                        for tg in all_tg_links:
                            href = tg.get('href', '')
                            username_match = re.search(r'(t\.me|telegram\.(me|org))/([^/?\s]+)', href, re.I)
                            if username_match:
                                username = username_match.group(3).strip('/')
                                if username:
                                    telegram_list.append(username)
                                    print(f"ID {user_id}: Добавлен TG (fallback): @{username}")
                                    has_tg = True
                                    break
            
            # Если likes == 0 и no TG — в БД
            if likes == 0 and not has_tg:
                cursor.execute("INSERT OR IGNORE INTO null_accounts (user_id) VALUES (?)", (user_id,))
                conn.commit()
                print(f"ID {user_id}: 0 лайков + нет TG — добавлен в БД")
            
            processed_count += 1
            
        except Exception as e:
            print(f"ID {user_id}: Ошибка: {e}")
            # Ошибка — в БД как нулевой
            cursor.execute("INSERT OR IGNORE INTO null_accounts (user_id) VALUES (?)", (user_id,))
            conn.commit()
            continue

finally:
    driver.quit()
    conn.close()

# Результаты: уникальные TG
unique_tgs = set(telegram_list)
print("\nСобранные Telegram (>=20 лайков):")
for tg in unique_tgs:
    print(f"@{tg}")
print(f"Всего: {len(unique_tgs)}")

# Сохранение в TXT (без повторов)
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    for tg in unique_tgs:
        f.write(f"@{tg}\n")
print(f"Сохранено в {OUTPUT_FILE}")

# Статистика БД
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM null_accounts")
null_count = cursor.fetchone()[0]
print(f"В БД нулевых акков: {null_count}")
conn.close()