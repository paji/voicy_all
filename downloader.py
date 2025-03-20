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
OUTPUT_DIR = "output"  # 出力ディレクトリ
JSON_FILE = os.path.join(OUTPUT_DIR, "voicy_urls_only.json")  # URLリストのJSONファイル
DOWNLOAD_HISTORY_FILE = "download_history.json"  # ダウンロード履歴ファイル
MAX_DOWNLOADS_PER_RUN = 10  # 1回の実行でダウンロードする最大件数
DEBUG_MODE = True  # デバッグモード

def setup_directories():
    """必要なディレクトリを作成"""
    for directory in [MP3_DIR, TEMP_DIR, DEBUG_DIR, OUTPUT_DIR]:
        os.makedirs(directory, exist_ok=True)
        print(f"ディレクトリを確認/作成しました: {directory}")

def create_sample_json():
    """サンプルのJSONファイルを作成（テスト用）"""
    if not os.path.exists(JSON_FILE):
        print(f"サンプルのJSONファイルを作成します: {JSON_FILE}")
        sample_urls = [
            "https://voicy.jp/channel/1234/567890",
            "https://voicy.jp/channel/1234/567891"
        ]
        try:
            with open(JSON_FILE, "w") as f:
                json.dump(sample_urls, f, indent=2)
            print(f"サンプルのJSONファイルを作成しました")
        except Exception as e:
            print(f"サンプルのJSONファイル作成エラー: {e}")

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
        if not os.path.exists(JSON_FILE):
            print(f"JSONファイルが存在しません: {JSON_FILE}")
            create_sample_json()
            
        with open(JSON_FILE, "r") as f:
            urls = json.load(f)
            print(f"JSONファイルから{len(urls)}件のURLを読み込みました: {JSON_FILE}")
            return urls
    except Exception as e:
        print(f"JSONファイルの読み込みエラー: {e}")
        traceback.print_exc()
        return []

def ensure_ffmpeg_installed():
    """FFmpegがインストールされていることを確認し、なければインストールを試みる"""
    try:
        # FFmpegがインストールされているか確認
        result = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
        if result.stdout.strip():
            print("FFmpegはすでにインストールされています")
            return True
        
        print("FFmpegがインストールされていません。インストールを試みます...")
        
        # FFmpegをインストール
        install_cmd = ["sudo", "apt-get", "update", "-y"]
        subprocess.run(install_cmd, check=True)
        
        install_cmd = ["sudo", "apt-get", "install", "-y", "ffmpeg"]
        subprocess.run(install_cmd, check=True)
        
        # インストール確認
        result = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
        if result.stdout.strip():
            print("FFmpegのインストールに成功しました")
            return True
        else:
            print("FFmpegのインストールに失敗しました")
            return False
    except Exception as e:
        print(f"FFmpegインストールエラー: {e}")
        traceback.print_exc()
        return False

def save_debug_info(driver, episode_id, suffix=""):
    """デバッグ情報を保存"""
    if not DEBUG_MODE:
        return
    
    try:
        # ページソースを保存
        page_source = driver.page_source
        debug_file = os.path.join(DEBUG_DIR, f"page_source_{episode_id}{suffix}.html")
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(page_source)
        print(f"ページソースを保存しました: {debug_file}")
        
        # スクリーンショットを保存
        screenshot_file = os.path.join(DEBUG_DIR, f"screenshot_{episode_id}{suffix}.png")
        driver.save_screenshot(screenshot_file)
        print(f"スクリーンショットを保存しました: {screenshot_file}")
        
        # コンソールログを保存
        logs = driver.get_log('browser')
        log_file = os.path.join(DEBUG_DIR, f"console_log_{episode_id}{suffix}.txt")
        with open(log_file, "w", encoding="utf-8") as f:
            for log in logs:
                f.write(f"{log['level']}: {log['message']}\n")
        print(f"コンソールログを保存しました: {log_file}")
    except Exception as e:
        print(f"デバッグ情報保存エラー: {e}")

def extract_audio_urls_from_javascript(page_source):
    """JavaScriptからオーディオURLを抽出"""
    audio_urls = []
    
    # パターン1: 一般的なMP3 URL
    mp3_matches = re.findall(r'(https?://[^\s"\']+\.mp3)', page_source)
    if mp3_matches:
        audio_urls.extend(mp3_matches)
        print(f"JavaScriptから{len(mp3_matches)}個のMP3 URLを抽出しました")
    
    # パターン2: m3u8 URL
    m3u8_matches = re.findall(r'(https?://[^\s"\']+\.m3u8)', page_source)
    if m3u8_matches:
        audio_urls.extend(m3u8_matches)
        print(f"JavaScriptから{len(m3u8_matches)}個のm3u8 URLを抽出しました")
    
    # パターン3: JSON内のURLパターン
    json_url_matches = re.findall(r'"url"\s*:\s*"(https?://[^"]+)"', page_source)
    if json_url_matches:
        for url in json_url_matches:
            if '.mp3' in url or '.m3u8' in url:
                audio_urls.append(url)
        print(f"JSON内から{len(json_url_matches)}個のURLを抽出しました")
    
    # パターン4: data-src属性
    data_src_matches = re.findall(r'data-src="(https?://[^"]+)"', page_source)
    if data_src_matches:
        for url in data_src_matches:
            if '.mp3' in url or '.m3u8' in url:
                audio_urls.append(url)
        print(f"data-src属性から{len(data_src_matches)}個のURLを抽出しました")
    
    # 重複を削除
    audio_urls = list(set(audio_urls))
    
    return audio_urls

def get_episode_info(url):
    """Voicyエピソードページから情報を取得"""
    print(f"::group::エピソード情報取得: {url}")
    driver = None
    
    try:
        # Chromeのオプション設定
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        chrome_options.add_experimental_option('w3c', False)  # ログ取得のため
        
        # WebDriverの初期化
        print("WebDriverを初期化中...")
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception as e:
            print(f"WebDriver初期化エラー: {e}")
            traceback.print_exc()
            return None
        
        # エピソードID
        episode_id = url.split("/")[-1]
        print(f"エピソードID: {episode_id}")
        
        # ページにアクセス
        print(f"ページにアクセス中: {url}")
        try:
            driver.get(url)
        except Exception as e:
            print(f"ページアクセスエラー: {e}")
            traceback.print_exc()
            save_debug_info(driver, episode_id, "_access_error")
            return None
        
        # ページが完全に読み込まれるまで待機
        print("ページの読み込みを待機中...")
        try:
            # タイトル要素が表示されるまで待機
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1, h2, .title, .episode-title"))
            )
            
            # JavaScriptが完全に実行されるまで少し待機
            time.sleep(5)
        except Exception as e:
            print(f"ページ読み込み待機エラー: {e}")
            traceback.print_exc()
            save_debug_info(driver, episode_id, "_load_error")
            
            # エラーでも続行を試みる
            print("エラーが発生しましたが、処理を続行します...")
        
        # デバッグ情報を保存
        save_debug_info(driver, episode_id)
        
        # タイトル取得
        title = "未知のタイトル"
        try:
            # 複数のセレクタを試す
            for selector in ["h1.title", "h2.title", ".episode-title", "h1", "h2"]:
                title_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if title_elements:
                    title = title_elements[0].text.strip()
                    print(f"タイトル: {title}")
                    break
        except Exception as e:
            print(f"タイトル取得エラー: {e}")
            title = f"未知のタイトル_{episode_id}"
        
        # 日付取得
        formatted_date = datetime.now().strftime("%Y%m")
        try:
            # 複数のセレクタを試す
            date_text = ""
            for selector in ["p.date", ".date", ".episode-date", ".published-date"]:
                date_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if date_elements:
                    date_text = date_elements[0].text.strip()
                    print(f"日付テキスト: {date_text}")
                    break
            
            # 日付フォーマット変換（例: 2023年2月1日 → 202302）
            if date_text:
                date_match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_text)
                if date_match:
                    year, month, day = date_match.groups()
                    formatted_date = f"{year}{month.zfill(2)}"
                    print(f"フォーマット済み日付: {formatted_date}")
        except Exception as e:
            print(f"日付取得エラー: {e}")
        
        # 有料放送かどうかを確認
        is_premium = False
        try:
            premium_elements = driver.find_elements(By.CSS_SELECTOR, ".premium-episode, .premium, .paid-content")
            if premium_elements:
                is_premium = True
            print(f"有料放送: {'はい' if is_premium else 'いいえ'}")
        except Exception as e:
            print(f"有料放送判定エラー: {e}")
        
        # ページソースを取得
        page_source = driver.page_source
        
        # オーディオURLを取得するための複数の方法を試す
        audio_urls = []
        
        # 方法1: オーディオプレーヤーのソースを探す
        print("方法1: オーディオプレーヤーのソースを探しています...")
        try:
            audio_elements = driver.find_elements(By.TAG_NAME, "audio")
            for audio in audio_elements:
                audio_url = audio.get_attribute("src")
                if audio_url:
                    audio_urls.append(audio_url)
                    print(f"方法1でオーディオURLを取得: {audio_url}")
        except Exception as e:
            print(f"方法1でのオーディオURL取得エラー: {e}")
        
        # 方法2: ページソースから直接探す
        if not audio_urls:
            print("方法2: ページソースからオーディオURLを探しています...")
            try:
                soup = BeautifulSoup(page_source, "html.parser")
                audio_tags = soup.find_all("audio")
                for audio in audio_tags:
                    if audio.has_attr("src"):
                        audio_urls.append(audio["src"])
                        print(f"方法2でオーディオURLを取得: {audio['src']}")
                    
                    # source タグも確認
                    source_tags = audio.find_all("source")
                    for source in source_tags:
                        if source.has_attr("src"):
                            audio_urls.append(source["src"])
                            print(f"方法2でsourceタグからオーディオURLを取得: {source['src']}")
            except Exception as e:
                print(f"方法2でのオーディオURL取得エラー: {e}")
        
        # 方法3: JavaScriptを実行してオーディオURLを取得
        if not audio_urls:
            print("方法3: JavaScriptを実行してオーディオURLを探しています...")
            try:
                # audioタグのsrc属性を取得
                js_result = driver.execute_script("""
                    var audioElements = document.getElementsByTagName('audio');
                    var urls = [];
                    for (var i = 0; i < audioElements.length; i++) {
                        if (audioElements[i].src) {
                            urls.push(audioElements[i].src);
                        }
                        // sourceタグも確認
                        var sources = audioElements[i].getElementsByTagName('source');
                        for (var j = 0; j < sources.length; j++) {
                            if (sources[j].src) {
                                urls.push(sources[j].src);
                            }
                        }
                    }
                    return urls;
                """)
                
                if js_result:
                    audio_urls.extend(js_result)
                    print(f"方法3でオーディオURLを取得: {js_result}")
            except Exception as e:
                print(f"方法3でのオーディオURL取得エラー: {e}")
        
        # 方法4: ネットワークリクエストを監視してオーディオURLを取得
        if not audio_urls:
            print("方法4: ページ内のすべてのリンクからオーディオURLを探しています...")
            try:
                all_links = []
                link_elements = driver.find_elements(By.TAG_NAME, "a")
                for link in link_elements:
                    href = link.get_attribute("href")
                    if href and ('.mp3' in href or '.m3u8' in href or 'audio' in href):
                        all_links.append(href)
                        print(f"潜在的なオーディオリンクを発見: {href}")
                
                if all_links:
                    audio_urls.extend(all_links)
                    print(f"方法4でオーディオURLを取得: {all_links}")
            except Exception as e:
                print(f"方法4でのオーディオURL取得エラー: {e}")
        
        # 方法5: JavaScriptからオーディオURLを抽出
        if not audio_urls:
            print("方法5: JavaScriptからオーディオURLを抽出しています...")
            js_audio_urls = extract_audio_urls_from_javascript(page_source)
            if js_audio_urls:
                audio_urls.extend(js_audio_urls)
                print(f"方法5でオーディオURLを取得: {js_audio_urls}")
        
        # 方法6: ページを再読み込みして再試行
        if not audio_urls:
            print("方法6: ページを再読み込みして再試行しています...")
            try:
                driver.refresh()
                time.sleep(5)  # ページが読み込まれるまで待機
                
                # 再度デバッグ情報を保存
                save_debug_info(driver, episode_id, "_refresh")
                
                # 再度オーディオURLを探す
                audio_elements = driver.find_elements(By.TAG_NAME, "audio")
                for audio in audio_elements:
                    audio_url = audio.get_attribute("src")
                    if audio_url:
                        audio_urls.append(audio_url)
                        print(f"方法6でオーディオURLを取得: {audio_url}")
                
                # JavaScriptからも再度抽出
                if not audio_urls:
                    js_audio_urls = extract_audio_urls_from_javascript(driver.page_source)
                    if js_audio_urls:
                        audio_urls.extend(js_audio_urls)
                        print(f"方法6でJavaScriptからオーディオURLを取得: {js_audio_urls}")
            except Exception as e:
                print(f"方法6でのオーディオURL取得エラー: {e}")
        
        # 重複を削除
        audio_urls = list(set(audio_urls))
        
        # URLの種類を判別
        mp3_urls = []
        m3u8_urls = []
        
        for url in audio_urls:
            if '.mp3' in url:
                mp3_urls.append(url)
            elif '.m3u8' in url:
                m3u8_urls.append(url)
        
        # m3u8プレイリストを処理
        if m3u8_urls:
            print(f"{len(m3u8_urls)}個のm3u8 URLを処理します")
            for m3u8_url in m3u8_urls:
                try:
                    print(f"m3u8 URLを処理中: {m3u8_url}")
                    m3u8_response = requests.get(m3u8_url, timeout=30)
                    
                    if m3u8_response.status_code == 200:
                        m3u8_content = m3u8_response.text
                        
                        # デバッグ用にm3u8コンテンツを保存
                        m3u8_debug_file = os.path.join(DEBUG_DIR, f"m3u8_content_{episode_id}.txt")
                        with open(m3u8_debug_file, "w", encoding="utf-8") as f:
                            f.write(m3u8_content)
                        print(f"m3u8コンテンツを保存しました: {m3u8_debug_file}")
                        
                        # m3u8からセグメントURLを抽出
                        segment_urls = []
                        for line in m3u8_content.splitlines():
                            if line and not line.startswith('#'):
                                # 相対URLを絶対URLに変換
                                if line.startswith('http'):
                                    segment_url = line
                                else:
                                    base_url = '/'.join(m3u8_url.split('/')[:-1]) + '/'
                                    segment_url = base_url + line
                                segment_urls.append(segment_url)
                        
                        if segment_urls:
                            print(f"m3u8から{len(segment_urls)}個のセグメントURLを抽出しました")
                            # セグメント情報を返す
                            return {
                                "id": episode_id,
                                "title": title,
                                "date": formatted_date,
                                "is_premium": is_premium,
                                "url": url,
                                "type": "m3u8",
                                "segment_urls": segment_urls
                            }
                except Exception as e:
                    print(f"m3u8プレイリスト処理エラー: {e}")
                    traceback.print_exc()
        
        # MP3 URLが見つかった場合
        if mp3_urls:
            print(f"{len(mp3_urls)}個のMP3 URLを取得しました")
            return {
                "id": episode_id,
                "title": title,
                "date": formatted_date,
                "is_premium": is_premium,
                "url": url,
                "type": "mp3",
                "mp3_urls": mp3_urls
            }
        
        # オーディオURLが見つからなかった場合
        print(f"オーディオURLが見つかりませんでした")
        return None
    except Exception as e:
        print(f"エピソード情報取得エラー: {e}")
        traceback.print_exc()
        if driver:
            save_debug_info(driver, episode_id if 'episode_id' in locals() else "unknown", "_error")
        return None
    finally:
        try:
            if driver:
                driver.quit()
        except:
            pass
        print(f"::endgroup::")

def download_mp3_segments(episode_info, mp3_urls):
    """MP3セグメントをダウンロード"""
    episode_id = episode_info["id"]
    title = episode_info["title"]
    date = episode_info["date"]
    is_premium = episode_info.get("is_premium", False)
    
    print(f"::group::エピソード {episode_id} のMP3ダウンロード")
    print(f"タイトル: {title}")
    print(f"日付: {date}")
    print(f"MP3 URL数: {len(mp3_urls)}")
    print(f"有料放送: {'はい' if is_premium else 'いいえ'}")
    
    # ファイル名を作成（特殊文字を置換）
    safe_title = re.sub(r"[\\/*?:\"<>|]", "_", title)
    
    # セグメントをダウンロード
    segment_files = []
    
    for i, mp3_url in enumerate(mp3_urls):
        segment_filename = f"segment_{episode_id}_{i+1}.mp3"
        segment_path = os.path.join(TEMP_DIR, segment_filename)
        
        print(f"セグメント {i+1}/{len(mp3_urls)} をダウンロード中: {mp3_url}")
        
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
        success = False
        
        for retry in range(max_retries):
            try:
                response = requests.get(mp3_url, headers=headers, stream=True, timeout=30)
                
                if response.status_code == 200:
                    with open(segment_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    # ファイルサイズを確認
                    file_size = os.path.getsize(segment_path)
                    print(f"ダウンロード完了: {segment_path} (サイズ: {file_size / (1024 * 1024):.2f}MB)")
                    
                    if file_size > 0:
                        segment_files.append(segment_path)
                        success = True
                        break
                    else:
                        print(f"ダウンロードしたファイルのサイズが0です")
                        os.remove(segment_path)
                        if retry < max_retries - 1:
                            print(f"リトライ中... ({retry + 1}/{max_retries})")
                            time.sleep(2)  # 少し待機してから再試行
                else:
                    print(f"セグメントダウンロードエラー: ステータスコード {response.status_code}")
                    if retry < max_retries - 1:
                        print(f"リトライ中... ({retry + 1}/{max_retries})")
                        time.sleep(2)  # 少し待機してから再試行
            except Exception as e:
                print(f"リクエスト中のエラー: {e}")
                traceback.print_exc()
                if retry < max_retries - 1:
                    print(f"リトライ中... ({retry + 1}/{max_retries})")
                    time.sleep(2)  # 少し待機してから再試行
    
    print(f"ダウンロードしたセグメント数: {len(segment_files)}/{len(mp3_urls)}")
    
    if not segment_files:
        print(f"セグメントをダウンロードできませんでした")
        print(f"::endgroup::")
        return None
    
    # セグメントを結合
    print(f"セグメントを結合しています...")
    
    # 最終的なMP3ファイル名
    filename = f"{date}_{safe_title}_{episode_id}.mp3"
    mp3_path = os.path.join(MP3_DIR, filename)
    
    # セグメントを結合
    merged_file = merge_mp3_files(segment_files, mp3_path)
    
    # 一時ファイルを削除
    for segment_file in segment_files:
        try:
            os.remove(segment_file)
        except Exception as e:
            print(f"一時ファイル削除エラー: {e}")
    
    print(f"::endgroup::")
    return merged_file

def download_m3u8_segments(episode_info, segment_urls):
    """m3u8プレイリストからセグメントをダウンロード"""
    episode_id = episode_info["id"]
    title = episode_info["title"]
    date = episode_info["date"]
    is_premium = episode_info.get("is_premium", False)
    
    print(f"::group::エピソード {episode_id} のm3u8セグメントダウンロード")
    print(f"タイトル: {title}")
    print(f"日付: {date}")
    print(f"セグメント数: {len(segment_urls)}")
    print(f"有料放送: {'はい' if is_premium else 'いいえ'}")
    
    # ファイル名を作成（特殊文字を置換）
    safe_title = re.sub(r"[\\/*?:\"<>|]", "_", title)
    
    # セグメントをダウンロード
    segment_files = []
    
    for i, segment_url in enumerate(segment_urls):
        segment_filename = f"segment_{episode_id}_{i+1}.ts"
        segment_path = os.path.join(TEMP_DIR, segment_filename)
        
        print(f"セグメント {i+1}/{len(segment_urls)} をダウンロード中: {segment_url}")
        
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
        success = False
        
        for retry in range(max_retries):
            try:
                response = requests.get(segment_url, headers=headers, stream=True, timeout=30)
                
                if response.status_code == 200:
                    with open(segment_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    # ファイルサイズを確認
                    file_size = os.path.getsize(segment_path)
                    print(f"ダウンロード完了: {segment_path} (サイズ: {file_size / (1024 * 1024):.2f}MB)")
                    
                    if file_size > 0:
                        segment_files.append(segment_path)
                        success = True
                        break
                    else:
                        print(f"ダウンロードしたファイルのサイズが0です")
                        os.remove(segment_path)
                        if retry < max_retries - 1:
                            print(f"リトライ中... ({retry + 1}/{max_retries})")
                            time.sleep(2)  # 少し待機してから再試行
                else:
                    print(f"セグメントダウンロードエラー: ステータスコード {response.status_code}")
                    if retry < max_retries - 1:
                        print(f"リトライ中... ({retry + 1}/{max_retries})")
                        time.sleep(2)  # 少し待機してから再試行
            except Exception as e:
                print(f"リクエスト中のエラー: {e}")
                traceback.print_exc()
                if retry < max_retries - 1:
                    print(f"リトライ中... ({retry + 1}/{max_retries})")
                    time.sleep(2)  # 少し待機してから再試行
    
    print(f"ダウンロードしたセグメント数: {len(segment_files)}/{len(segment_urls)}")
    
    if not segment_files:
        print(f"セグメントをダウンロードできませんでした")
        print(f"::endgroup::")
        return None
    
    # セグメントを結合
    print(f"セグメントを結合しています...")
    
    # 最終的なMP3ファイル名
    filename = f"{date}_{safe_title}_{episode_id}.mp3"
    mp3_path = os.path.join(MP3_DIR, filename)
    
    # セグメントを結合してMP3に変換
    merged_file = merge_ts_files_to_mp3(segment_files, mp3_path)
    
    # 一時ファイルを削除
    for segment_file in segment_files:
        try:
            os.remove(segment_file)
        except Exception as e:
            print(f"一時ファイル削除エラー: {e}")
    
    print(f"::endgroup::")
    return merged_file

def merge_mp3_files(segment_files, output_file):
    """MP3ファイルを結合する"""
    print(f"MP3ファイルを結合しています: {len(segment_files)}個のファイル → {output_file}")
    
    # FFmpegがインストールされているか確認
    ffmpeg_available = ensure_ffmpeg_installed()
    
    if ffmpeg_available:
        try:
            # FFmpegを使用してMP3ファイルを結合
            # 入力ファイルリストを作成
            input_list_file = os.path.join(TEMP_DIR, "input_list.txt")
            with open(input_list_file, "w", encoding="utf-8") as f:
                for segment_file in segment_files:
                    # パスをエスケープして絶対パスに変換
                    abs_path = os.path.abspath(segment_file)
                    # バックスラッシュをエスケープ
                    escaped_path = abs_path.replace('\\', '\\\\')
                    f.write(f"file '{escaped_path}'\n")
            
            # FFmpegコマンドを実行
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", input_list_file,
                "-c", "copy",
                "-y",  # 既存ファイルを上書き
                output_file
            ]
            
            print(f"FFmpegコマンド: {' '.join(ffmpeg_cmd)}")
            
            process = subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # 入力リストファイルを削除
            os.remove(input_list_file)
            
            if process.returncode == 0:
                print(f"MP3ファイルの結合に成功しました: {output_file}")
                return output_file
            else:
                print(f"MP3ファイルの結合に失敗しました")
                print(f"FFmpeg出力: {process.stderr}")
                
                # 代替方法: バイナリ結合
                print(f"代替方法でMP3ファイルを結合しています...")
                with open(output_file, "wb") as outfile:
                    for segment_file in segment_files:
                        with open(segment_file, "rb") as infile:
                            shutil.copyfileobj(infile, outfile, 1024*1024)  # 1MBずつコピー
                
                # ファイルサイズを確認
                file_size = os.path.getsize(output_file)
                if file_size > 0:
                    print(f"代替方法でMP3ファイルの結合に成功しました: {output_file} (サイズ: {file_size / (1024 * 1024):.2f}MB)")
                    return output_file
                else:
                    print(f"代替方法でもMP3ファイルの結合に失敗しました")
                    return None
        except Exception as e:
            print(f"MP3ファイル結合エラー: {e}")
            traceback.print_exc()
    
    # FFmpegが利用できない場合や例外が発生した場合は代替方法を試す
    try:
        print(f"代替方法でMP3ファイルを結合しています...")
        with open(output_file, "wb") as outfile:
            for segment_file in segment_files:
                with open(segment_file, "rb") as infile:
                    shutil.copyfileobj(infile, outfile, 1024*1024)  # 1MBずつコピー
        
        # ファイルサイズを確認
        file_size = os.path.getsize(output_file)
        if file_size > 0:
            print(f"代替方法でMP3ファイルの結合に成功しました: {output_file} (サイズ: {file_size / (1024 * 1024):.2f}MB)")
            return output_file
    except Exception as e2:
        print(f"代替方法でのMP3ファイル結合エラー: {e2}")
        traceback.print_exc()
    
    return None

def merge_ts_files_to_mp3(segment_files, output_file):
    """TSファイルを結合してMP3に変換する"""
    print(f"TSファイルを結合してMP3に変換しています: {len(segment_files)}個のファイル → {output_file}")
    
    # FFmpegがインストールされているか確認
    ffmpeg_available = ensure_ffmpeg_installed()
    
    if ffmpeg_available:
        try:
            # FFmpegを使用してTSファイルを結合してMP3に変換
            # 入力ファイルリストを作成
            input_list_file = os.path.join(TEMP_DIR, "input_list.txt")
            with open(input_list_file, "w", encoding="utf-8") as f:
                for segment_file in segment_files:
                    # パスをエスケープして絶対パスに変換
                    abs_path = os.path.abspath(segment_file)
                    # バックスラッシュをエスケープ
                    escaped_path = abs_path.replace('\\', '\\\\')
                    f.write(f"file '{escaped_path}'\n")
            
            # FFmpegコマンドを実行
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", input_list_file,
                "-c:a", "libmp3lame",
                "-q:a", "2",
                "-y",  # 既存ファイルを上書き
                output_file
            ]
            
            print(f"FFmpegコマンド: {' '.join(ffmpeg_cmd)}")
            
            process = subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # 入力リストファイルを削除
            os.remove(input_list_file)
            
            if process.returncode == 0:
                print(f"TSファイルの結合とMP3変換に成功しました: {output_file}")
                return output_file
            else:
                print(f"TSファイルの結合とMP3変換に失敗しました")
                print(f"FFmpeg出力: {process.stderr}")
                
                # 代替方法: 直接連結してみる
                try:
                    print(f"代替方法でTSファイルを結合しています...")
                    # まず一時的なTSファイルに結合
                    temp_ts_file = os.path.join(TEMP_DIR, "temp_combined.ts")
                    with open(temp_ts_file, "wb") as outfile:
                        for segment_file in segment_files:
                            with open(segment_file, "rb") as infile:
                                shutil.copyfileobj(infile, outfile, 1024*1024)  # 1MBずつコピー
                    
                    # 結合したTSファイルをMP3に変換
                    ffmpeg_cmd2 = [
                        "ffmpeg",
                        "-i", temp_ts_file,
                        "-c:a", "libmp3lame",
                        "-q:a", "2",
                        "-y",
                        output_file
                    ]
                    
                    print(f"代替FFmpegコマンド: {' '.join(ffmpeg_cmd2)}")
                    
                    process2 = subprocess.run(
                        ffmpeg_cmd2,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    
                    # 一時ファイルを削除
                    os.remove(temp_ts_file)
                    
                    if process2.returncode == 0:
                        print(f"代替方法でTSファイルの結合とMP3変換に成功しました: {output_file}")
                        return output_file
                    else:
                        print(f"代替方法でもTSファイルの結合とMP3変換に失敗しました")
                        print(f"FFmpeg出力: {process2.stderr}")
                        return None
                except Exception as e:
                    print(f"代替方法でのTS結合エラー: {e}")
                    traceback.print_exc()
                    return None
        except Exception as e:
            print(f"TS→MP3変換エラー: {e}")
            traceback.print_exc()
    
    # FFmpegが利用できない場合や例外が発生した場合
    print(f"FFmpegが利用できないため、TSファイルをMP3に変換できません")
    return None

def process_episode(url, download_history):
    """エピソードを処理"""
    print(f"::group::エピソード処理: {url}")
    
    # 既にダウンロード済みかチェック
    if url in download_history:
        print(f"このエピソードは既にダウンロード済みです: {url}")
        print(f"::endgroup::")
        return None
    
    # エピソード情報を取得
    episode_info = get_episode_info(url)
    
    if not episode_info:
        print(f"エピソード情報を取得できませんでした: {url}")
        print(f"::endgroup::")
        return None
    
    # エピソードタイプに応じて処理
    if episode_info["type"] == "mp3":
        # MP3ファイルをダウンロード
        mp3_file = download_mp3_segments(episode_info, episode_info["mp3_urls"])
        if mp3_file:
            print(f"MP3ファイルのダウンロードに成功しました: {mp3_file}")
            download_history.append(url)
            return mp3_file
    elif episode_info["type"] == "m3u8":
        # m3u8セグメントをダウンロード
        mp3_file = download_m3u8_segments(episode_info, episode_info["segment_urls"])
        if mp3_file:
            print(f"m3u8セグメントのダウンロードと変換に成功しました: {mp3_file}")
            download_history.append(url)
            return mp3_file
    
    print(f"エピソードの処理に失敗しました: {url}")
    print(f"::endgroup::")
    return None

def main():
    """メイン処理"""
    print("Voicy MP3ダウンローダーを開始します")
    
    # 必要なディレクトリを作成
    setup_directories()
    
    # FFmpegがインストールされているか確認
    ensure_ffmpeg_installed()
    
    # ダウンロード履歴を読み込む
    download_history = load_download_history()
    print(f"ダウンロード履歴: {len(download_history)}件")
    
    # URLリストを読み込む
    urls = load_urls_from_json()
    print(f"URLリスト: {len(urls)}件")
    
    # URLリストが空の場合、サンプルURLを使用
    if not urls:
        print("URLリストが空です。サンプルURLを使用します。")
        urls = [
            "https://voicy.jp/channel/1234/567890",
            "https://voicy.jp/channel/1234/567891"
        ]
    
    # 未ダウンロードのURLをフィルタリング
    urls_to_process = [url for url in urls if url not in download_history]
    print(f"未ダウンロードのURL: {len(urls_to_process)}件")
    
    if not urls_to_process:
        print("処理するURLがありません。すべてのURLが既にダウンロード済みです。")
        return
    
    # 最大ダウンロード数を制限
    if len(urls_to_process) > MAX_DOWNLOADS_PER_RUN:
        print(f"ダウンロード数を{MAX_DOWNLOADS_PER_RUN}件に制限します")
        urls_to_process = urls_to_process[:MAX_DOWNLOADS_PER_RUN]
    
    # 各URLを処理
    successful_downloads = 0
    
    for url in urls_to_process:
        print(f"\n--- URL {urls_to_process.index(url) + 1}/{len(urls_to_process)} 処理中 ---")
        result = process_episode(url, download_history)
        if result:
            successful_downloads += 1
    
    # ダウンロード履歴を保存
    save_download_history(download_history)
    
    print(f"\n処理完了: {successful_downloads}/{len(urls_to_process)}件のダウンロードに成功しました")

if __name__ == "__main__":
    main()
