import os
import re
import json
import time
import requests
import subprocess
import traceback
import shutil
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Voicyチャンネル情報
CHANNEL_ID = "2834"  # パジ郎チャンネル
CHANNEL_URL = f"https://voicy.jp/channel/{CHANNEL_ID}"  # チャンネルトップページ

# ディレクトリ設定
MP3_DIR = "mp3_downloads"
TEMP_DIR = "temp_segments"
DEBUG_DIR = "debug_files"

# エピソード情報ファイル
EPISODES_FILE = "episodes.json"

def setup_directories():
    """必要なディレクトリを作成"""
    for directory in [MP3_DIR, TEMP_DIR, DEBUG_DIR]:
        os.makedirs(directory, exist_ok=True)
        print(f"ディレクトリを確認/作成しました: {directory}")

def setup_driver():
    """Seleniumドライバーのセットアップ"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # ヘッドレスモードで実行
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(30)
    return driver

def get_audio_url(driver, episode_id):
    """エピソードページから音声URLを取得"""
    episode_url = f"{CHANNEL_URL}/{episode_id}"
    print(f"::group::音声URL取得: {episode_url}")
    
    try:
        driver.get(episode_url)
        
        # ページが完全に読み込まれるまで待機
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "audio"))
            )
        except TimeoutException:
            print("ページの読み込みタイムアウト")
            print(f"::endgroup::")
            return None
        
        # JavaScriptを実行して音声URLを取得
        audio_url = driver.execute_script("""
            var audioElement = document.querySelector('audio');
            if (audioElement && audioElement.src) {
                return audioElement.src;
            }
            
            // audioタグがない場合はページ内のJavaScriptから探す
            var scripts = document.querySelectorAll('script');
            for (var i = 0; i < scripts.length; i++) {
                var content = scripts[i].textContent;
                if (content) {
                    // m3u8またはmp3のURLを探す
                    var m3u8Match = content.match(/"(https?:[^"]+\\.m3u8[^"]*)"/);
                    if (m3u8Match) return m3u8Match[1];
                    
                    var mp3Match = content.match(/"(https?:[^"]+\\.mp3[^"]*)"/);
                    if (mp3Match) return mp3Match[1];
                }
            }
            return null;
        """)
        
        if audio_url:
            print(f"音声URLを取得しました: {audio_url}")
            print(f"::endgroup::")
            return audio_url
        else:
            print("音声URLが見つかりませんでした")
            
            # デバッグ情報を保存
            debug_file = f"{DEBUG_DIR}/page_source_{episode_id}.html"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
            print(f"ページソースを保存しました: {debug_file}")
            
            print(f"::endgroup::")
            return None
    
    except Exception as e:
        print(f"音声URL取得中にエラーが発生しました: {str(e)}")
        traceback.print_exc()
        print(f"::endgroup::")
        return None

def download_m3u8_to_mp3(m3u8_url, mp3_path, episode_id):
    """m3u8からMP3をダウンロード"""
    print(f"::group::MP3ダウンロード")
    print(f"オーディオURLからMP3をダウンロード中: {m3u8_url}")
    print(f"出力先: {mp3_path}")
    
    try:
        # URLの拡張子を確認
        is_m3u8 = '.m3u8' in m3u8_url.lower()
        is_mp3 = '.mp3' in m3u8_url.lower()
        
        # MP3の場合は直接ダウンロード
        if is_mp3:
            print(f"MP3ファイルを直接ダウンロードします")
            try:
                response = requests.get(m3u8_url, timeout=30)
                if response.status_code == 200:
                    with open(mp3_path, 'wb') as f:
                        f.write(response.content)
                    
                    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                        file_size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
                        print(f"MP3ファイルのダウンロードに成功しました: {mp3_path} (サイズ: {file_size_mb:.2f}MB)")
                        print(f"::endgroup::")
                        return mp3_path
                    else:
                        print(f"MP3ファイルが正常にダウンロードされませんでした")
                else:
                    print(f"MP3ファイルのダウンロードに失敗しました: ステータスコード {response.status_code}")
            except Exception as e:
                print(f"MP3ファイルのダウンロード中にエラーが発生しました: {str(e)}")
        
        # m3u8ファイルの場合
        if is_m3u8:
            # m3u8ファイルの内容を取得
            response = requests.get(m3u8_url, timeout=30)
            if response.status_code != 200:
                print(f"m3u8ファイルの取得に失敗しました: ステータスコード {response.status_code}")
                print(f"::endgroup::")
                return None
            
            m3u8_content = response.text
            
            # m3u8ファイルをデバッグ用に保存
            m3u8_debug_path = f"{DEBUG_DIR}/playlist_{episode_id}.m3u8"
            with open(m3u8_debug_path, 'w') as f:
                f.write(m3u8_content)
            print(f"m3u8ファイルを保存しました: {m3u8_debug_path}")
            
            # セグメントURLを抽出
            segment_urls = []
            base_url = '/'.join(m3u8_url.split('/')[:-1]) + '/'
            
            for line in m3u8_content.splitlines():
                if not line.startswith('#') and line.strip():
                    if line.startswith('http'):
                        segment_urls.append(line)
                    else:
                        segment_urls.append(base_url + line)
            
            print(f"セグメント数: {len(segment_urls)}")
            if not segment_urls:
                print(f"セグメントURLが見つかりませんでした")
                print(f"::endgroup::")
                return None
            
            # セグメントをダウンロード - AACファイルとして保存（JSファイルの実装に合わせる）
            segment_files = []
            for i, url in enumerate(segment_urls):
                segment_path = f"{TEMP_DIR}/segment_{i:03d}.aac"  # .ts から .aac に変更
                try:
                    segment_response = requests.get(url, timeout=30)
                    if segment_response.status_code == 200:
                        with open(segment_path, 'wb') as f:
                            f.write(segment_response.content)
                        segment_files.append(segment_path)
                    else:
                        print(f"セグメント {i} のダウンロードに失敗: ステータスコード {segment_response.status_code}")
                except Exception as e:
                    print(f"セグメント {i} のダウンロード中にエラー: {str(e)}")
            
            print(f"ダウンロードしたセグメント数: {len(segment_files)}")
            
            if not segment_files:
                print(f"セグメントのダウンロードに失敗しました")
                print(f"::endgroup::")
                return None
                
            # JSファイルの実装に合わせて、直接バイナリ結合する方法を最初に試す
            print("方法0: 直接バイナリ結合（JSファイルの実装に合わせる）")
            try:
                with open(mp3_path, 'wb') as outfile:
                    for segment in segment_files:
                        if os.path.exists(segment):
                            with open(segment, 'rb') as infile:
                                shutil.copyfileobj(infile, outfile)
                
                if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                    file_size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
                    print(f"バイナリ結合によるMP3ファイルの作成に成功しました: {mp3_path} (サイズ: {file_size_mb:.2f}MB)")
                    
                    # 一時ファイルを削除
                    for segment in segment_files:
                        if os.path.exists(segment):
                            os.remove(segment)
                    
                    print(f"::endgroup::")
                    return mp3_path
                else:
                    print(f"バイナリ結合によるMP3ファイルの作成に失敗しました")
            except Exception as e:
                print(f"バイナリ結合中にエラーが発生しました: {str(e)}")
        
        # 以下は元の実装をフォールバックとして残す
        
        # 方法1: 直接FFmpegを使用してURLからMP3に変換
        print("方法1: 直接FFmpegを使用してURLからMP3に変換")
        try:
            cmd1 = [
                'ffmpeg',
                '-i', m3u8_url,
                '-c:a', 'libmp3lame',
                '-q:a', '2',
                '-y',
                mp3_path
            ]
            print(f"FFmpegコマンド（方法1）を実行: {' '.join(cmd1)}")
            result1 = subprocess.run(cmd1, capture_output=True, text=True)
            
            if result1.returncode == 0:
                print(f"MP3ファイルの作成に成功しました: {mp3_path}")
                if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                    file_size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
                    print(f"MP3ファイル: {mp3_path} (サイズ: {file_size_mb:.2f}MB)")
                    
                    # 一時ファイルを削除
                    if is_m3u8:
                        for segment in segment_files:
                            if os.path.exists(segment):
                                os.remove(segment)
                    
                    print(f"::endgroup::")
                    return mp3_path
                else:
                    print(f"MP3ファイルが正常に作成されませんでした")
            else:
                print(f"FFmpegエラー（方法1）: {result1.stderr}")
        except Exception as e:
            print(f"方法1でのMP3変換中にエラーが発生しました: {str(e)}")
        
        # m3u8の場合のみ以下の方法を試行
        if is_m3u8:
            # 方法2: セグメントファイルを結合してからMP3に変換
            print("方法2: セグメントファイルを結合してからMP3に変換")
            try:
                # セグメントリストファイルを作成
                segments_list = f"{TEMP_DIR}/segments.txt"
                with open(segments_list, 'w') as f:
                    for segment in segment_files:
                        segment_escaped = segment.replace('\\', '\\\\').replace("'", "\\'")
                        f.write(f"file '{segment_escaped}'\n")
                
                # FFmpegでセグメントファイルを結合
                combined_file = f"{TEMP_DIR}/combined.aac"
                cmd2 = [
                    'ffmpeg',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', segments_list,
                    '-c', 'copy',
                    '-y',
                    combined_file
                ]
                print(f"FFmpegコマンド（方法2-1）を実行: {' '.join(cmd2)}")
                result2 = subprocess.run(cmd2, capture_output=True, text=True)
                
                if result2.returncode == 0 and os.path.exists(combined_file) and os.path.getsize(combined_file) > 0:
                    # 結合したファイルをMP3に変換
                    cmd3 = [
                        'ffmpeg',
                        '-i', combined_file,
                        '-c:a', 'libmp3lame',
                        '-q:a', '2',
                        '-y',
                        mp3_path
                    ]
                    print(f"FFmpegコマンド（方法2-2）を実行: {' '.join(cmd3)}")
                    result3 = subprocess.run(cmd3, capture_output=True, text=True)
                    
                    if result3.returncode == 0:
                        print(f"MP3ファイルの作成に成功しました: {mp3_path}")
                        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                            file_size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
                            print(f"MP3ファイル: {mp3_path} (サイズ: {file_size_mb:.2f}MB)")
                            
                            # 一時ファイルを削除
                            for segment in segment_files:
                                if os.path.exists(segment):
                                    os.remove(segment)
                            if os.path.exists(segments_list):
                                os.remove(segments_list)
                            if os.path.exists(combined_file):
                                os.remove(combined_file)
                            
                            print(f"::endgroup::")
                            return mp3_path
                        else:
                            print(f"MP3ファイルが正常に作成されませんでした")
                    else:
                        print(f"FFmpegエラー（方法2-2）: {result3.stderr}")
                else:
                    print(f"FFmpegエラー（方法2-1）: {result2.stderr}")
            except Exception as e:
                print(f"方法2でのMP3変換中にエラーが発生しました: {str(e)}")
        
        print(f"すべての方法でMP3変換に失敗しました")
        print(f"::endgroup::")
        return None
    
    except Exception as e:
        print(f"MP3ダウンロード中に予期しないエラーが発生しました: {str(e)}")
        traceback.print_exc()
        print(f"::endgroup::")
        return None

def process_episodes(episodes, start_index=0, max_episodes=None):
    """エピソードリストを処理してMP3をダウンロード"""
    if max_episodes is None:
        max_episodes = len(episodes)
    
    end_index = min(start_index + max_episodes, len(episodes))
    episodes_to_process = episodes[start_index:end_index]
    
    print(f"処理するエピソード数: {len(episodes_to_process)}")
    
    driver = setup_driver()
    try:
        for i, episode in enumerate(episodes_to_process):
            episode_id = episode["id"]
            title = episode["title"]
            date_str = episode.get("date", "")
            
            # ファイル名を作成（日付_タイトル_ID.mp3）
            # ファイル名に使えない文字を置換
            safe_title = re.sub(r'[\\/*?:"<>|]', '_', title)
            safe_date = re.sub(r'[\\/*?:"<>|]', '_', date_str)
            
            if safe_date:
                mp3_filename = f"{safe_date}_{safe_title}_{episode_id}.mp3"
            else:
                mp3_filename = f"{safe_title}_{episode_id}.mp3"
            
            mp3_path = os.path.join(MP3_DIR, mp3_filename)
            
            # すでにダウンロード済みの場合はスキップ
            if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                print(f"[{i+1}/{len(episodes_to_process)}] すでにダウンロード済み: {mp3_path}")
                continue
            
            print(f"[{i+1}/{len(episodes_to_process)}] 処理中: {title} (ID: {episode_id})")
            
            # 音声URLを取得
            audio_url = get_audio_url(driver, episode_id)
            if not audio_url:
                print(f"音声URLの取得に失敗しました: {episode_id}")
                continue
            
            # MP3をダウンロード
            result = download_m3u8_to_mp3(audio_url, mp3_path, episode_id)
            if result:
                print(f"MP3のダウンロードに成功しました: {mp3_path}")
            else:
                print(f"MP3のダウンロードに失敗しました: {episode_id}")
    
    finally:
        driver.quit()

def main():
    """メイン処理"""
    start_time = datetime.now()
    print(f"処理開始: {start_time}")
    
    # ディレクトリを準備
    setup_directories()
    
    # エピソード情報を読み込む
    if not os.path.exists(EPISODES_FILE):
        print(f"エピソード情報ファイルが見つかりません: {EPISODES_FILE}")
        return
    
    with open(EPISODES_FILE, 'r', encoding='utf-8') as f:
        episodes = json.load(f)
    
    print(f"読み込んだエピソード数: {len(episodes)}")
    
    # エピソードを処理
    process_episodes(episodes)
    
    end_time = datetime.now()
    print(f"処理終了: {end_time}")
    print(f"処理時間: {end_time - start_time}")

if __name__ == "__main__":
    main()
