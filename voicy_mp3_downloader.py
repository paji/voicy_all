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
        mp3_urls = []
        
        # 方法1: オーディオプレーヤーのソースを探す
        print("方法1: オーディオプレーヤーのソースを探しています...")
        try:
            audio_elements = driver.find_elements(By.TAG_NAME, "audio")
            for audio in audio_elements:
                mp3_url = audio.get_attribute("src")
                if mp3_url:
                    mp3_urls.append(mp3_url)
                    print(f"方法1でMP3 URLを取得: {mp3_url}")
        except Exception as e:
            print(f"方法1でのMP3 URL取得エラー: {e}")
        
        # 方法2: ページソースから直接探す
        if not mp3_urls:
            print("方法2: ページソースからMP3 URLを探しています...")
            try:
                soup = BeautifulSoup(page_source, "html.parser")
                audio_tags = soup.find_all("audio")
                for audio in audio_tags:
                    if audio.has_attr("src"):
                        mp3_urls.append(audio["src"])
                        print(f"方法2でMP3 URLを取得: {audio['src']}")
            except Exception as e:
                print(f"方法2でのMP3 URL取得エラー: {e}")
        
        # 方法3: JavaScriptを実行してMP3 URLを取得
        if not mp3_urls:
            print("方法3: JavaScriptを実行してMP3 URLを探しています...")
            try:
                js_result = driver.execute_script("""
                    var audioElements = document.getElementsByTagName('audio');
                    var urls = [];
                    for (var i = 0; i < audioElements.length; i++) {
                        if (audioElements[i].src) {
                            urls.push(audioElements[i].src);
                        }
                    }
                    return urls;
                """)
                if js_result:
                    mp3_urls.extend(js_result)
                    print(f"方法3でMP3 URLを取得: {js_result}")
            except Exception as e:
                print(f"方法3でのMP3 URL取得エラー: {e}")
        
        # 方法4: ネットワークリクエストを監視してMP3 URLを取得
        if not mp3_urls:
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
                    mp3_urls.extend(all_links)
                    print(f"方法4でMP3 URLを取得: {all_links}")
            except Exception as e:
                print(f"方法4でのMP3 URL取得エラー: {e}")
        
        # 方法5: m3u8プレイリストを探す
        print("方法5: m3u8プレイリストを探しています...")
        try:
            m3u8_matches = re.findall(r'(https?://[^\s"\']+\.m3u8)', page_source)
            if m3u8_matches:
                print(f"m3u8プレイリストを発見: {m3u8_matches}")
                for m3u8_url in m3u8_matches:
                    print(f"m3u8 URL: {m3u8_url}")
                    # m3u8プレイリストを取得
                    try:
                        m3u8_response = requests.get(m3u8_url)
                        if m3u8_response.status_code == 200:
                            m3u8_content = m3u8_response.text
                            # m3u8からセグメントURLを抽出
                            segment_urls = []
                            for line in m3u8_content.splitlines():
                                if line and not line.startswith('#') and (line.endswith('.ts') or line.endswith('.aac') or line.endswith('.mp3')):
                                    # 相対URLを絶対URLに変換
                                    if not line.startswith('http'):
                                        base_url = m3u8_url.rsplit('/', 1)[0]
                                        segment_url = f"{base_url}/{line}"
                                    else:
                                        segment_url = line
                                    segment_urls.append(segment_url)
                            
                            if segment_urls:
                                print(f"m3u8から{len(segment_urls)}個のセグメントURLを抽出しました")
                                # セグメントURLをmp3_urlsに追加せず、別途保存
                                debug_file = os.path.join(DEBUG_DIR, f"segments_{episode_id}.json")
                                with open(debug_file, "w", encoding="utf-8") as f:
                                    json.dump(segment_urls, f, indent=2)
                                print(f"セグメントURLを保存しました: {debug_file}")
                    except Exception as e:
                        print(f"m3u8プレイリスト処理エラー: {e}")
        except Exception as e:
            print(f"m3u8 URL検索エラー: {e}")
        
        # 最終確認
        if not mp3_urls:
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
            "mp3_urls": mp3_urls,  # 複数のURLを返すように変更
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

def download_segments(episode_info):
    """エピソード情報からMP3セグメントをダウンロード"""
    if not episode_info or not episode_info.get("mp3_urls") or len(episode_info["mp3_urls"]) == 0:
        print(f"ダウンロード可能なMP3 URLがありません")
        
        # m3u8セグメントを確認
        episode_id = episode_info["id"]
        segments_file = os.path.join(DEBUG_DIR, f"segments_{episode_id}.json")
        if os.path.exists(segments_file):
            try:
                with open(segments_file, "r") as f:
                    segment_urls = json.load(f)
                if segment_urls:
                    print(f"m3u8セグメントファイルが見つかりました。セグメントをダウンロードします。")
                    return download_m3u8_segments(episode_info, segment_urls)
            except Exception as e:
                print(f"m3u8セグメントファイル読み込みエラー: {e}")
        
        return None
    
    episode_id = episode_info["id"]
    title = episode_info["title"]
    date = episode_info["date"]
    mp3_urls = episode_info["mp3_urls"]
    is_premium = episode_info.get("is_premium", False)
    
    print(f"::group::エピソード {episode_id} のセグメントダウンロード")
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
                
                # レスポンスヘッダーを表示（デバッグ用）
                print(f"レスポンスステータス: {response.status_code}")
                print(f"レスポンスヘッダー: {dict(response.headers)}")
                
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
    
    try:
        # FFmpegを使用してMP3ファイルを結合
        # 入力ファイルリストを作成
        input_list_file = os.path.join(TEMP_DIR, "input_list.txt")
        with open(input_list_file, "w") as f:
            for segment_file in segment_files:
                f.write(f"file '{os.path.abspath(segment_file)}'\n")
        
        # FFmpegコマンドを実行
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", input_list_file,
            "-c", "copy",
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
                        outfile.write(infile.read())
            
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
        return None

def merge_ts_files_to_mp3(segment_files, output_file):
    """TSファイルを結合してMP3に変換する"""
    print(f"TSファイルを結合してMP3に変換しています: {len(segment_files)}個のファイル → {output_file}")
    
    try:
        # FFmpegを使用してTSファイルを結合してMP3に変換
        # 入力ファイルリストを作成
        input_list_file = os.path.join(TEMP_DIR, "input_list.txt")
        with open(input_list_file, "w") as f:
            for segment_file in segment_files:
                f.write(f"file '{os.path.abspath(segment_file)}'\n")
        
        # FFmpegコマンドを実行
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", input_list_file,
            "-c:a", "libmp3lame",
            "-q:a", "2",
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
            return None
    except Exception as e:
        print(f"TSファイル結合エラー: {e}")
        traceback.print_exc()
        return None

def main():
    """メイン処理"""
    print("Voicy MP3ダウンローダーを開始します")
    
    # 必要なディレクトリを作成
    setup_directories()
    
    # FFmpegが利用可能か確認
    try:
        process = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if process.returncode == 0:
            print("FFmpegが利用可能です")
        else:
            print("警告: FFmpegが見つかりません。MP3の結合機能が制限されます。")
    except Exception as e:
        print(f"FFmpeg確認エラー: {e}")
        print("警告: FFmpegが見つかりません。MP3の結合機能が制限されます。")
    
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
            mp3_file = download_segments(episode_info)
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
