FROM python:3.10-slim

# 標準出力・標準エラー出力をバッファしない（ログを即時Cloud Loggingに出すため必須）
ENV PYTHONUNBUFFERED True

# アプリケーションディレクトリの設定
ENV APP_HOME /app
WORKDIR $APP_HOME

# 【重要】ライブラリのインストールを先にやる（ビルドキャッシュの有効活用）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 【重要】ソースコードのコピーはライブラリインストールの後
COPY . ./

# セキュリティ対策: rootではなく一般ユーザーを作成して切り替える
# ※Cloud Run上で予期せぬ権限昇格を防ぐ
RUN useradd -m appuser
USER appuser

# 起動コマンド
# workers 1, threads 8 はCloud Run (1 vCPU) の標準的な設定
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
