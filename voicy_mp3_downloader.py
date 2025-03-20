import os
import re
import json
import requests
import subprocess
from datetime import datetime
from bs4 import BeautifulSoup
import traceback
import time
import shutil
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# 設定
MP3_DIR = "mp3_downloads"  # MP3保存ディレクトリ
TEMP_DIR = "temp_segments"  # 一時ファイル用ディレクトリ
DEBUG_DIR = "debug_files"  # デバッグファイル用ディレクトリ
JSON_FILE = "output/voicy_urls_only.json"  # URLリストのJSONファイル
DOWNLOAD_HISTORY_FILE = "download_history.json"  # ダウンロード履歴ファイル
MAX_DOWNLOADS_PER_RUN = 10  # 1回の実行でダウンロードする最大件数

def setup_directories():
    """必要なディレクトリを作成"""
    for directory in [MP3_DIR, TEMP_DIR, DEBUG_DIR]:
        os.makedirs(directory, exist_ok=True)
        print(f"ディレクトリを確認/作成しました: {directory}")

def load_download_history():
    """ダウンロード履歴を読み込む"""
    if os.path.exists(DOWNLOAD_HISTORY_FILE):
        try:
            with open(DOWNLOAD_HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"履歴ファイルの読み込みエラー: {e}")
            return []
    return []

def save_download_history(history):
    """ダウンロード履歴を保存する"""
    try:
        with open(DOWNLOAD_HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"履歴ファイルの保存エラー: {e}")

def load_urls_from_json():
    """JSONファイルからURLリストを読み込む"""
    try:
        with open(JSON_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"JSONファイルの読み込みエラー: {e}")
        return []

def get_episode_info(url):
    """Voicyエピソードページから情報を取得"""
    print(f"::group::エピソード情報取得: {url}")
    try:
        # Chromeのオプション設定
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        # WebDriverの初期化
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # ページにアクセス
        print(f"ページにアクセス中: {url}")
        driver.get(url)
        
        # ページが完全に読み込まれるまで待機
        print("ページの読み込みを待機中...")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.title")))
        
        # エピソードID
        episode_id = url.split("/")[-1]
        print(f"エピソードID: {episode_id}")
        
        # タイトル取得
        title_element = driver.find_element(By.CSS_SELECTOR, "h1.title")
        title = title_element.text.strip()
        print(f"タイトル: {title}")
        
        # 日付取得
        date_element = driver.find_element(By.CSS_SELECTOR, "p.date")
        date_text = date_element.text.strip()
        print(f"日付テキスト: {date_text}")
        
        # 日付フォーマット変換（例: 2023年2月1日 → 202302）
        date_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_text)
        if date_match:
            year, month, day = date_match.groups()
            formatted_date = f"{year}{month.zfill(2)}"
        else:
            formatted_date = datetime.now().strftime("%Y%m")
        print(f"フォーマット済み日付: {formatted_date}")
        
        # 有料放送かどうかを確認
        is_premium = False
        try:
            premium_elements = driver.find_elements(By.CSS_SELECTOR, ".premium-episode")
            if premium_elements:
                is_premium = True
            print(f"有料放送: {'はい' if is_premium else 'いいえ'}")
        except Exception as e:
            print(f"有料放送判定エラー: {e}")
        
        # ページソースを保存（デバッグ用）
        page_source = driver.page_source
        debug_file = os.path.join(DEBUG_DIR, f"page_source_{episode_id}.html")
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(page_source)
        print(f"ページソースを保存しました: {debug_file}")
        
        # MP3 URLを取得（複数の方法を試す）
        mp3_url = None
        
        # 方法1: オーディオプレーヤーのソースを探す
        print("方法1: オーディオプレーヤーのソースを探しています...")
        try:
            audio_elements = driver.find_elements(By.TAG_NAME, "audio")
            if audio_elements:
                mp3_url = audio_elements[0].get_attribute("src")
                print(f"方法1でMP3 URLを取得: {mp3_url}")
        except Exception as e:
            print(f"方法1でのMP3 URL取得エラー: {e}")
        
        # 方法2: ページソースから直接探す
        if not mp3_url:
            print("方法2: ページソースからMP3 URLを探しています...")
            try:
                soup = BeautifulSoup(page_source, "html.parser")
                audio_tags = soup.find_all("audio")
                for audio in audio_tags:
                    if audio.has_attr("src"):
                        mp3_url = audio["src"]
                        print(f"方法2でMP3 URLを取得: {mp3_url}")
                        break
            except Exception as e:
                print(f"方法2でのMP3 URL取得エラー: {e}")
        
        # 方法3: JavaScriptを実行してMP3 URLを取得
        if not mp3_url:
            print("方法3: JavaScriptを実行してMP3 URLを探しています...")
            try:
                js_result = driver.execute_script("""
                    var audioElements = document.getElementsByTagName('audio');
                    if (audioElements.length > 0) {
                        return audioElements[0].src;
                    }
                    return null;
                """)
                if js_result:
                    mp3_url = js_result
                    print(f"方法3でMP3 URLを取得: {mp3_url}")
            except Exception as e:
                print(f"方法3でのMP3 URL取得エラー: {e}")
        
        # 方法4: ネットワークリクエストを監視してMP3 URLを取得
        if not mp3_url:
            print("方法4: ページ内のすべてのリンクからMP3 URLを探しています...")
            try:
                all_links = []
                link_elements = driver.find_elements(By.TAG_NAME, "a")
                for link in link_elements:
                    href = link.get_attribute("href")
                    if href and (".mp3" in href or "audio" in href):
                        all_links.append(href)
                        print(f"潜在的なMP3リンクを発見: {href}")
                
                # スクリプトタグ内のURLも探す
                script_elements = driver.find_elements(By.TAG_NAME, "script")
                for script in script_elements:
                    script_content = script.get_attribute("innerHTML")
                    if script_content:
                        mp3_matches = re.findall(r'(https?://[^\s"\']+\.mp3)', script_content)
                        for match in mp3_matches:
                            all_links.append(match)
                            print(f"スクリプト内でMP3 URLを発見: {match}")
                
                if all_links:
                    mp3_url = all_links[0]  # 最初のリンクを使用
                    print(f"方法4でMP3 URLを取得: {mp3_url}")
            except Exception as e:
                print(f"方法4でのMP3 URL取得エラー: {e}")
        
        # 最終確認
        if not mp3_url:
            print("警告: MP3 URLを取得できませんでした")
            
            # デバッグ情報を保存
            debug_info = {
                "url": url,
                "episode_id": episode_id,
                "title": title,
                "date": formatted_date,
                "is_premium": is_premium,
                "error": "MP3 URLを取得できませんでした"
            }
            debug_file = os.path.join(DEBUG_DIR, f"debug_info_{episode_id}.json")
            with open(debug_file, "w", encoding="utf-8") as f:
                json.dump(debug_info, f, indent=2, ensure_ascii=False)
            print(f"デバッグ情報を保存しました: {debug_file}")
        
        driver.quit()
        
        # 結果を返す
        result = {
            "id": episode_id,
            "title": title,
            "date": formatted_date,
            "mp3_url": mp3_url,
            "is_premium": is_premium,
            "url": url
        }
        print(f"エピソード情報: {result}")
        print(f"::endgroup::")
        return result
    except Exception as e:
        print(f"エピソード情報取得エラー: {e}")
        traceback.print_exc()
        print(f"::endgroup::")
        return None

def download_episode(episode_info):
    """エピソード情報からMP3をダウンロード"""
    if not episode_info or not episode_info.get("mp3_url"):
        print(f"ダウンロード可能なMP3 URLがありません")
        return None
    
    episode_id = episode_info["id"]
    title = episode_info["title"]
    date = episode_info["date"]
    mp3_url = episode_info["mp3_url"]
    is_premium = episode_info.get("is_premium", False)
    
    print(f"::group::エピソード {episode_id} のダウンロード")
    print(f"タイトル: {title}")
    print(f"日付: {date}")
    print(f"MP3 URL: {mp3_url}")
    print(f"有料放送: {'はい' if is_premium else 'いいえ'}")
    
    # ファイル名を作成（特殊文字を置換）
    safe_title = re.sub(r"[\\/*?:\"<>|]", "_", title)
    
    # ファイル名の形式: 年月_タイトル_ID.mp3（有料/無料で区別しない）
    filename = f"{date}_{safe_title}_{episode_id}.mp3"
    mp3_path = os.path.join(MP3_DIR, filename)
    
    try:
        # MP3をダウンロード
        print(f"MP3ダウンロード中: {mp3_url}")
        
        # リクエストヘッダーを設定（Refererを含める）
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": episode_info["url"],
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive"
        }
        
        # ダウンロード試行（最大3回）
        max_retries = 3
        for retry in range(max_retries):
            try:
                response = requests.get(mp3_url, headers=headers, stream=True, timeout=30)
                
                # レスポンスヘッダーを表示（デバッグ用）
                print(f"レスポンスステータス: {response.status_code}")
                print(f"レスポンスヘッダー: {dict(response.headers)}")
                
                if response.status_code == 200:
                    with open(mp3_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    # ファイルサイズを確認
                    file_size = os.path.getsize(mp3_path)
                    print(f"ダウンロード完了: {mp3_path} (サイズ: {file_size / (1024 * 1024):.2f}MB)")
                    
                    if file_size > 0:
                        print(f"エピソード {episode_id} のダウンロードに成功しました: {mp3_path}")
                        print(f"::endgroup::")
                        return mp3_path
                    else:
                        print(f"ダウンロードしたファイルのサイズが0です")
                        os.remove(mp3_path)
                        if retry < max_retries - 1:
                            print(f"リトライ中... ({retry + 1}/{max_retries})")
                            time.sleep(2)  # 少し待機してから再試行
                        else:
                            print(f"最大リトライ回数に達しました")
                            print(f"::endgroup::")
                            return None
                else:
                    print(f"MP3ダウンロードエラー: ステータスコード {response.status_code}")
                    if retry < max_retries - 1:
                        print(f"リトライ中... ({retry + 1}/{max_retries})")
                        time.sleep(2)  # 少し待機してから再試行
                    else:
                        print(f"最大リトライ回数に達しました")
                        print(f"::endgroup::")
                        return None
            except Exception as e:
                print(f"リクエスト中のエラー: {e}")
                if retry < max_retries - 1:
                    print(f"リトライ中... ({retry + 1}/{max_retries})")
                    time.sleep(2)  # 少し待機してから再試行
                else:
                    print(f"最大リトライ回数に達しました")
                    print(f"::endgroup::")
                    return None
        
        print(f"::endgroup::")
        return None
    except Exception as e:
        print(f"MP3ダウンロードエラー: {e}")
        traceback.print_exc()
        print(f"::endgroup::")
        return None

def main():
    """メイン処理"""
    print("Voicy MP3ダウンローダーを開始します")
    
    # 必要なディレクトリを作成
    setup_directories()
    
    # ダウンロード履歴を読み込む
    download_history = load_download_history()
    downloaded_ids = set(item["id"] for item in download_history)
    
    # URLリストを読み込む
    urls = load_urls_from_json()
    if not urls:
        print("URLリストが空です。処理を終了します。")
        return
    
    print(f"URLリストから{len(urls)}件のエピソードを読み込みました")
    
    # 未ダウンロードのURLをフィルタリング
    undownloaded_urls = []
    for url in urls:
        episode_id = url.split("/")[-1]
        if episode_id not in downloaded_ids:
            undownloaded_urls.append(url)
    
    print(f"未ダウンロードのエピソード: {len(undownloaded_urls)}件")
    
    # 最大ダウンロード数を制限
    urls_to_process = undownloaded_urls[:MAX_DOWNLOADS_PER_RUN]
    print(f"今回ダウンロードするエピソード: {len(urls_to_process)}件")
    
    # 各エピソードをダウンロード
    downloaded_files = []
    new_history_items = []
    
    for url in urls_to_process:
        episode_info = get_episode_info(url)
        if episode_info:
            mp3_file = download_episode(episode_info)
            if mp3_file:
                downloaded_files.append(mp3_file)
                new_history_items.append({
                    "id": episode_info["id"],
                    "title": episode_info["title"],
                    "date": episode_info["date"],
                    "file": os.path.basename(mp3_file),
                    "downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
    
    # 履歴を更新
    if new_history_items:
        download_history.extend(new_history_items)
        save_download_history(download_history)
    
    # ダウンロード結果を表示
    print("\n=== ダウンロード結果 ===")
    for i, item in enumerate(new_history_items, 1):
        print(f"{i}. ID: {item['id']}")
        print(f"   タイトル: {item['title']}")
        print(f"   ファイル: {item['file']}")
        print(f"   ダウンロード日時: {item['downloaded_at']}\n")
    
    print(f"今回のダウンロード: {len(new_history_items)}個のMP3ファイル")
    print(f"合計ダウンロード済み: {len(download_history)}個のMP3ファイル")
    print("Voicy MP3ダウンローダーを終了します")

if __name__ == "__main__":
    main()
