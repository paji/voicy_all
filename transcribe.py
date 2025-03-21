#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import glob
import time
import argparse
import logging
from pathlib import Path
import whisper
import datetime

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('transcribe')

def setup_args():
    """コマンドライン引数の設定"""
    parser = argparse.ArgumentParser(description='MP3ファイルを書き起こしてテキスト化します')
    parser.add_argument('--mp3_dir', type=str, default='mp3_downloads', 
                        help='MP3ファイルのディレクトリパス')
    parser.add_argument('--text_dir', type=str, default='mp3_text', 
                        help='書き起こしテキストの出力先ディレクトリパス')
    parser.add_argument('--limit', type=int, default=10, 
                        help='一度に処理するファイル数の上限')
    parser.add_argument('--model', type=str, default='medium', 
                        help='Whisperモデルのサイズ (tiny, base, small, medium, large)')
    return parser.parse_args()

def get_mp3_files(mp3_dir):
    """MP3ファイルの一覧を取得"""
    mp3_files = glob.glob(os.path.join(mp3_dir, '*.mp3'))
    logger.info(f"MP3ファイル数: {len(mp3_files)}")
    return mp3_files

def get_processed_files(text_dir):
    """既に処理済みのファイル一覧を取得"""
    if not os.path.exists(text_dir):
        os.makedirs(text_dir)
        return []
    
    processed_files = []
    text_files = glob.glob(os.path.join(text_dir, '*.txt'))
    
    for text_file in text_files:
        # テキストファイル名からMP3ファイル名を復元
        base_name = os.path.basename(text_file).replace('.txt', '.mp3')
        processed_files.append(base_name)
    
    logger.info(f"処理済みファイル数: {len(processed_files)}")
    return processed_files

def transcribe_audio(audio_path, model_name='medium'):
    """音声ファイルを書き起こし"""
    logger.info(f"モデル {model_name} を読み込み中...")
    model = whisper.load_model(model_name)
    
    logger.info(f"書き起こし中: {audio_path}")
    result = model.transcribe(audio_path, language="ja")
    
    return result["text"]

def main():
    args = setup_args()
    
    # ディレクトリパスの設定
    mp3_dir = args.mp3_dir
    text_dir = args.text_dir
    
    # 処理済みファイルの確認
    processed_files = get_processed_files(text_dir)
    
    # MP3ファイルの取得
    mp3_files = get_mp3_files(mp3_dir)
    
    # 未処理のファイルをフィルタリング
    files_to_process = []
    for mp3_file in mp3_files:
        base_name = os.path.basename(mp3_file)
        if base_name not in processed_files:
            files_to_process.append(mp3_file)
    
    logger.info(f"未処理ファイル数: {len(files_to_process)}")
    
    # 処理数の制限
    files_to_process = files_to_process[:args.limit]
    logger.info(f"今回処理するファイル数: {len(files_to_process)}")
    
    # 各ファイルを処理
    for mp3_file in files_to_process:
        try:
            start_time = time.time()
            base_name = os.path.basename(mp3_file)
            output_file = os.path.join(text_dir, base_name.replace('.mp3', '.txt'))
            
            logger.info(f"処理開始: {base_name}")
            
            # 書き起こし実行
            transcription = transcribe_audio(mp3_file, args.model)
            
            # 結果をファイルに保存
            with open(output_file, 'w', encoding='utf-8') as f:
                # ファイル名から日付とタイトルを抽出
                file_parts = base_name.split('_', 1)
                date_str = file_parts[0]
                try:
                    date_obj = datetime.datetime.strptime(date_str, '%Y%m%d')
                    formatted_date = date_obj.strftime('%Y年%m月%d日')
                except:
                    formatted_date = date_str
                
                title = file_parts[1].rsplit('_', 1)[0] if len(file_parts) > 1 else base_name
                
                # ヘッダー情報を追加
                f.write(f"# {title}\n")
                f.write(f"日付: {formatted_date}\n\n")
                f.write(transcription)
            
            elapsed_time = time.time() - start_time
            logger.info(f"処理完了: {base_name} (所要時間: {elapsed_time:.2f}秒)")
            
        except Exception as e:
            logger.error(f"エラー発生: {base_name} - {str(e)}")
    
    logger.info("すべての処理が完了しました")

if __name__ == "__main__":
    main()
