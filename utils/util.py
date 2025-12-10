import os
import sys
import re
import logging
from typing import List, Dict, Any, Optional

import google.auth
from google.cloud import bigquery
from google.cloud import logging as cloud_logging
from google.cloud import resourcemanager_v3

# ==========================================
# 1. 環境変数と定数の設定
# ==========================================
LOG_LEVEL = 20

# 変数名は一切変更しません
project            = os.getenv("PROJECT_ID")
project_number     = os.getenv("PROJECT_NUMBER")
secret_id          = os.getenv("SECRET_ID") # ADC利用のため本来不要ですが、互換性のため維持
dataset            = os.getenv("DATASET_ID")
table              = os.getenv("TABLE_ID")
company_list_table = os.getenv("COMPANY_LIST_TABLE")

# 必須環境変数のチェック (Fail Fast)
required_vars = [project, dataset, table]
if not all(required_vars):
    # ロガー設定前なので標準エラー出力に出して終了
    print(f"CRITICAL: 必須環境変数が設定されていません。", file=sys.stderr)
    sys.exit(1)

# ==========================================
# 2. 認証情報の取得 (ADCへの移行)
# ==========================================
# Secret Manager経由の鍵取得は廃止し、ADCを使用します。
# Cloud Runでは自動的にSA権限が適用されます。
# 変数 credentials, credentials_info は互換性維持のために定義します。
credentials = None
credentials_info = None

try:
    # google.auth.default() は環境(Cloud Run/Local)に応じて最適な認証を探します
    credentials, project_id = google.auth.default()
except Exception as e:
    print(f"CRITICAL: 認証情報の取得に失敗しました: {e}", file=sys.stderr)
    sys.exit(1)

# ==========================================
# 3. ロガー & クライアント初期化
# ==========================================
# Cloud Logging クライアント
logging_client = cloud_logging.Client(credentials=credentials, project=project)
logging_client.setup_logging(log_level=LOG_LEVEL)

# 標準ロガーの取得
logger = logging.getLogger()

# BigQueryクライアント
bigquery_client = bigquery.Client(credentials=credentials, project=project)

# Resource Manager クライアント (v3) - Lazy Loading推奨だが、要件に従いここで初期化する場合
# プロジェクト一覧取得などで使用
rm_client = resourcemanager_v3.ProjectsClient(credentials=credentials)


class Utils:

    @classmethod
    def validate(cls, data: Dict[str, Any]) -> List[str]:
        """一般ユーザー登録のバリデーション"""
        errMsg = []
        noInput = 'が正しく入力されていません。'

        # ヘルパー関数で視認性を向上
        def is_invalid_str(val, max_len=100):
            return not val or len(str(val)) > max_len

        if is_invalid_str(data.get('username')):
            errMsg.append('氏名' + noInput)

        email = data.get('email', '')
        if not re.match(r'[\w\-.-]+@[\w\-._]+\.[A-Za-z]+', email) or len(email) > 100:
            errMsg.append('メールアドレス' + noInput)

        tel = data.get('tel_number', '')
        if not re.match(r'^[0-9\-]+$', tel) or len(tel) > 100:
            errMsg.append('電話番号' + noInput)

        if not data.get('regist_date'):
            errMsg.append('引き渡し希望日' + noInput)

        if is_invalid_str(data.get('belonging_department')):
            errMsg.append('所属部署名' + noInput)

        if not data.get('company_id'):
            errMsg.append('社名' + noInput)

        return errMsg

    @classmethod
    def validate2(cls, data: Dict[str, Any]) -> List[str]:
        """プロジェクト情報のバリデーション"""
        errMsg = []
        noInput = 'が正しく入力されていません。'

        if not data.get('project_name'):
            errMsg.append('プロジェクト名' + noInput)
        if not data.get('system_name'):
            errMsg.append('システム名' + noInput)
        if not data.get('type'):
            errMsg.append('利用用途' + noInput)

        return errMsg

    @classmethod
    def admin_valitation(cls, data: Dict[str, Any]) -> List[str]:
        """管理者用バリデーション"""
        errMsg = []
        noInput = 'が正しく入力されていません。'

        # 正規表現パターンの定義
        PATTERNS = {
            'alpha_num': r'^[a-z0-9]+$',
            'alpha_num_hyphen': r'^[a-z0-9\-]+$',
            'email': r'[\w\-._]+@[\w\-._]+\.[A-Za-z]+',
            'cidr': r'^(((?!10\.0\.0\.0/31$)\d+\.\d+\.\d+\.\d+/\d+)(?:,|$))+$', # カンマ区切り対応
            'vpc_cidr': r'^(?!10\.0\.0\.0/31$)\d+\.\d+\.\d+\.\d+/28$',
            'domain': r'^(?![-.])[a-z0-9]([a-z0-9.-]*[a-z0-9])?(\.[a-z]{2,})+$'
        }

        # 項目ごとのチェック定義 (フィールド名, パターン, エラーメッセージ)
        checks = [
            ('manage_company_name', 'alpha_num', '会社名は半角英数文字(英小文字)のみです。'),
            ('project_name_gcp', 'alpha_num', 'プロジェクト名は半角英数文字(英小文字)のみです。'),
            ('organization_name', 'alpha_num', '組織名は半角英数文字(英小文字)のみです。'),
            ('group_name', 'alpha_num_hyphen', 'Googleグループ名(管理者用)は半角英数文字(英小文字),-(半角ハイフン)のみです。'),
            ('user_group_name', 'alpha_num_hyphen', 'Googleグループ名(利用者用)は半角英数文字(英小文字),-(半角ハイフン)のみです。'),
            ('group_email', 'email', 'Googleグループのemail(管理者用)' + noInput),
            ('user_group_email', 'email', 'Googleグループのemail(利用者用)' + noInput),
        ]

        # 定型チェック実行
        for field, pattern_key, msg in checks:
            val = data.get(field, '')
            if not re.search(PATTERNS[pattern_key], val):
                errMsg.append(msg)

        # 文字数チェック
        for field, label in [('manage_company_name', '会社名'), ('project_name_gcp', 'プロジェクト名'), ('organization_name', '組織名')]:
            if len(data.get(field, '')) > 8:
                errMsg.append(f'{label}が8文字を超えています!!')

        # 必須チェック
        if not data.get('env'):
            errMsg.append('環境' + noInput)
        if not data.get('use_purpose'):
            errMsg.append('利用用途' + noInput)

        # 条件付きチェック (use_purpose に依存するもの)
        use_purpose = data.get('use_purpose')

        # サブネット情報 (wp, static以外)
        if use_purpose not in ['wp', 'static']:
            subnet = data.get('subnet_info', '')
            if not re.search(r'^(?!10\.0\.0\.0/31$)\d+\.\d+\.\d+\.\d+/\d+$', subnet):
                 errMsg.append('利用IP範囲は半角数字及び.(ドット)/(スラッシュ)のみです。')

        # クライアントCIDR (api, secure)
        if use_purpose in ['api', 'secure']:
            client_cidr = data.get('client_cidr', '').replace(' ', '')
            if client_cidr and not re.search(PATTERNS['cidr'], client_cidr):
                errMsg.append('アクセス元IP制限は半角数字及び.(ドット)/(スラッシュ),(カンマ)のみです。')

        # VPCコネクタ (secure)
        if use_purpose == 'secure':
            conn_cidr = data.get('connector_cidr', '')
            if conn_cidr and conn_cidr != 'None' and not re.search(PATTERNS['vpc_cidr'], conn_cidr):
                errMsg.append('VPCコネクター利用IP範囲が適切な形式になっていません。(空欄又は*.*.*.*/28など)。')

        # ドメイン (static, wp)
        if use_purpose in ['static', 'wp']:
            domain = data.get('domain_name', '')
            if not re.search(PATTERNS['domain'], domain):
                 errMsg.append('無効なドメイン名です。')

        return errMsg

    @classmethod
    def get_company_list(cls) -> List[Dict[str, Any]]:
        """会社一覧を取得"""
        query = f'SELECT company_id, company_name FROM `{project}.{dataset}.{company_list_table}`'
        try:
            query_job = bigquery_client.query(query)
            # リスト内包表記で高速化
            return [{"company_id": row.company_id, "company_name": row.company_name} for row in query_job]
        except Exception as e:
            logger.error(f"Failed to get company list: {e}")
            return []

    @classmethod
    def get_users_list(cls) -> List[Dict[str, Any]]:
        """申請者リスト取得"""
        query = f"""
            SELECT id, name, desired_delivery_date, tel, email, belonging_department,
                   project_name, type, project_id_gcp, UPDATE_FLG
            FROM `{project}.{dataset}.{table}`
            ORDER BY id DESC
        """
        try:
            query_job = bigquery_client.query(query)
            return [dict(row.items()) for row in query_job]
        except Exception as e:
            logger.error(f"Failed to get users list: {e}")
            return []

    @classmethod
    def get_multicloud_pjname(cls) -> List[str]:
        """
        プロジェクトID一覧を取得
        Band 7改修: googleapiclient(v1) -> google-cloud-resourcemanager(v3)
        """
        try:
            # v3 APIを使用して検索
            # 注: ADCの権限で閲覧可能なすべてのプロジェクトをリストします
            req = resourcemanager_v3.SearchProjectsRequest(
                query="lifecycleState:ACTIVE"
            )
            # イテレータが自動的にページング処理を行います
            page_result = rm_client.search_projects(request=req)

            pj_list = [p.project_id for p in page_result]
            
            if not pj_list:
                logger.warning('プロジェクトが見つかりません。')
                return []

            # 重複除去してリスト返却
            return list(set(pj_list))

        except Exception as e:
            logger.error(f'プロジェクト一覧取得エラー: {e}')
            return []
