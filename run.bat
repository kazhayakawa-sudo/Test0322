@echo off
chcp 65001 > nul
title スタジオスケジュール集約プログラム

echo ============================================
echo   スタジオスケジュール集約プログラム
echo ============================================
echo.

:: Python の存在確認
python --version > nul 2>&1
if errorlevel 1 (
    echo [エラー] Python が見つかりません。
    echo.
    echo Python 3.8 以上をインストールしてください:
    echo https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 初回セットアップ：必要なパッケージが入っていなければインストール
python -c "import playwright" > nul 2>&1
if errorlevel 1 (
    echo [初回セットアップ] 必要なパッケージをインストールしています...
    echo  playwright / pdfplumber / beautifulsoup4
    pip install playwright pdfplumber beautifulsoup4 -q
    if errorlevel 1 (
        echo [エラー] パッケージのインストールに失敗しました。
        pause
        exit /b 1
    )
    echo.
    echo [初回セットアップ] Chromium ブラウザをインストールしています...
    python -m playwright install chromium
    if errorlevel 1 (
        echo [エラー] Chromium のインストールに失敗しました。
        pause
        exit /b 1
    )
    echo.
)

:: スクリプトと同じフォルダに移動して実行
cd /d "%~dp0"
python schedule_aggregator.py

if errorlevel 1 (
    echo.
    echo [エラー] 実行中に問題が発生しました。
    echo 上記のメッセージを確認してください。
    pause
)
