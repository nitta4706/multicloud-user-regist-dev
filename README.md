# マルチクラウド利用者申請Web アプリ
   マルチクラウドデータ基盤において、利用者が自身の情報を登録し、その内容を管理者側で確認し運用を行って行く上での登録及び申請のWEBアプリケーション
- [マルチクラウド利用者申請Web アプリ](#マルチクラウド利用者申請web-アプリ)
- [1. フォルダ構成](#1-フォルダ構成)
  - [1.1 全体構成](#11-全体構成)
- [2. ローカル開発環境構築手順](#2-ローカル開発環境構築手順)
  - [2.1 リポジトリのクローン](#21-リポジトリのクローン)
  - [2.2 必要なモジュールのインストール](#22-必要なモジュールのインストール)
  - [2.3 ユーザアカウントに対して、サービスアカウントトークン作成者ロールを付与](#23-ユーザアカウントに対してサービスアカウントトークン作成者ロールを付与)
  - [2.4 サービス アカウントの権限借用を使用して、ローカル デフォルト認証情報(ADC) ファイルを作成](#24-サービス-アカウントの権限借用を使用してローカル-デフォルト認証情報adc-ファイルを作成)
  - [2.5 .envファイルの書き換え](#25-envファイルの書き換え)
  - [2.6 Webサーバの起動](#26-webサーバの起動)
- [3. 開発環境へのデプロイ](#3-開発環境へのデプロイ)
- [4. 本番環境へのデプロイ](#4-本番環境へのデプロイ)
- [5. ソースコードを修正時の対応](#5-ソースコードを修正時の対応)
  - [5.1 Backlogに課題を起票](#51-backlogに課題を起票)
  - [5.2 プルリク用ブランチの作成](#52-プルリク用ブランチの作成)
  - [5.3 管理者にプルリクエストの提出](#53-管理者にプルリクエストの提出)

 # 1. フォルダ構成
 ## 1.1 全体構成
 ```
 ./MCG_MULTICLOUD_USER_REGIST_DEV
         ┣ .github/
         ┃　  └ workflows/
         ┃         └app_deploy_dev.yaml
         ┃
         ┣ static/
         ┃　  └ github_logo.png(GitHubのロゴ)
         ┃
         ┣ templates/
         ┃    └ add.html(利用者側の登録時に使用するフォーム(No.1))
         ┃    └ add2.html(利用者側の登録時に使用するフォーム(No.2))
         ┃    └ base_user_list.html(フッター/ヘッダー(管理者画面一覧で使用))
         ┃    └ base.html(フッター/ヘッダー)
         ┃    └ confirm.html(入力確認画面)
         ┃    └ edit_confirm.html(編集確認画面(管理者登録時に使用))
         ┃    └ first_img.html(初期画面)
         ┃    └ manage_regist_error.html(管理者登録エラー画面)
         ┃    └ regist_complete.html(登録編集確認画面)
         ┃    └ regist_error.html(エラー発生時画面)
         ┃    └ regist.html(正常入力完了画面(一般利用者側用))
         ┃    └ users_delete.html(削除内容確認画面)
         ┃    └ users_edit.html(管理者側が入力すべき項目を表示)
         ┃    └ users_list.html(利用者が登録した内容を一覧で表示)
         ┣ utils/
         ┃    └ utils.py(入力時のバリデーション等を記載)
         ┣ Dockerfile(デプロイ時に使用)
         ┣ main.py(主要動作)
         ┣ .env_example(必要な環境変数を記載)
         ┣ requirements.txt
         ┣ README.md
 ```

# 2. ローカル開発環境構築手順

## 2.1 リポジトリのクローン
ローカル環境にて以下のコマンドを実行
```
git clone git@github.com:mec-mcg/mcg-multicloud_user_regist.git
```
## 2.2 必要なモジュールのインストール

```
cd mcg-multicloud_user_regist && pip install requirements.txt
```

## 2.3 ユーザアカウントに対して、サービスアカウントトークン作成者ロールを付与

- 以下のコマンドを実行

```
gcloud iam service-accounts add-iam-policy-binding \
    mcg-ope-admin-dev@mcg-ope-admin-dev.iam.gserviceaccount.com \
    --member='{ユーザアカウントのメールアドレス}' \
    --role=roles/iam.serviceAccountTokenCreator
```
## 2.4 サービス アカウントの権限借用を使用して、ローカル デフォルト認証情報(ADC) ファイルを作成

- 以下のコマンドを実行

```
gcloud auth application-default login \ --impersonate-service-account mcg-ope-admin-dev@mcg-ope-admin-dev.iam.gserviceaccount.com
```

## 2.5 .envファイルの書き換え

.envファイルが空になっているので、以下の値に書き換える

```
PROJECT_NAME={BigQueryのリソースがあるプロジェクト名}
DATASET_ID={BigQueryの利用者申請用データセットID}
TABLE_ID={BigQueryの利用者申請の登録用テーブル名ID}
PROJECT_NUMBER={BigQuery及びSecretManagerのリソースがあるプロジェクト番号}
COMPANY_LIST_TABLE={BigQueryの会社名及び会社IDがデータとして保存されているテーブル名ID}
FLASK_SECRET_KEY={任意の英文字(半角)で8文字以上}
```

## 2.6 Webサーバの起動
mcg_multicloud_user_registのフォルダに移動し、以下のコマンドを実行

```
python3 main.py
```

# 3. 開発環境へのデプロイ

developブランチへプルリク→マージを実施する。  
対象プロジェクト:**mcg-ope-admin-dev**  
Cloud Runデプロイ先:**multiclouduserregistdev**

# 4. 本番環境へのデプロイ

mainブランチへプルリク→マージを実施する。  
対象プロジェクト:**mcg-ope-admin**  
Cloud Runデプロイ先:**multiclouduserregist**

# 5. ソースコードを修正時の対応

## 5.1 Backlogに課題を起票
- backlogにて修正したソースコードについて、起票を行う。  
尚、Backlog課題Noについては、管理者との要相談

## 5.2 プルリク用ブランチの作成
- 以下の形式でブランチを作成  

```
mec-mcg/mcg-multicloud_user_regist/FEATURE/[(任意)backlog課題No]
```
## 5.3 管理者にプルリクエストの提出
- 4.2 で作成したブランチでコードの修正を行い、ローカルで動作確認後にpull request を実施。  
