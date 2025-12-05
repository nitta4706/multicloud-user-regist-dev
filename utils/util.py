import traceback,os
from google.cloud import bigquery
from google.oauth2 import service_account
from googleapiclient.discovery import build
import re
import pendulum
import logging
import google.cloud.logging

LOG_LEVEL = 20

credentials_file = "mcg-ope-admin-dev-8d173a71f5a1.json"
credentials = service_account.Credentials.from_service_account_file(credentials_file)

logging.basicConfig(
        format = "[%(asctime)s][%(levelname)s] %(message)s",
        level = LOG_LEVEL
    )
logger = logging.getLogger()

# Cloud Logging ハンドラを logger に接続
logging_client = google.cloud.logging.Client(credentials=credentials)
logging_client.setup_logging()

logger.setLevel(LOG_LEVEL)

# サービスアカウント情報の取得(環境変数に設定)
# credentials_file = os.environ.get('MITSU_CREDENTIALS')
bigquery_client = bigquery.Client(credentials=credentials)
project = "mcg-ope-admin-dev"
## Set Dataset
dataset = "user_regist_dev"
## ログインテーブル
table = "user_regist_list"

company_list_table = "company_list"

class Utils():

    @classmethod
    # バリデーション処理
    def validate(cls, data):

        errMsg = []
        noInput = 'が正しく入力されていません。'
        if not data['username'] or len(data['username'])>100:
            errMsg.append('氏名' + noInput)
        if not re.search(r'[\w\-.-]+@[\w\-._]+\.[A-za-z]+',data['email']) or len(data['email'])>100:
            errMsg.append('メールアドレス' + noInput)
        if not re.search(r'^[0-9\-]+$',data['tel_number']) or len(data['tel_number'])>100:
            errMsg.append('電話番号' + noInput)
        if not data['regist_date']:
            errMsg.append('引き渡し希望日' + noInput)
        if not data['belonging_department'] or len(data['belonging_department'])>100:
            errMsg.append('所属部署名' + noInput)
        if not data['company_id']:
            errMsg.append('社名' + noInput)
        return errMsg

    @classmethod
    def validate2(cls, data):
        errMsg = []
        noInput = 'が正しく入力されていません。'
        if not data['project_name']:
            errMsg.append('プロジェクト名' + noInput)
        if not data['system_name']:
            errMsg.append('システム名' + noInput)
        if not data['type']:
            errMsg.append('利用用途' + noInput)
        return errMsg

    @classmethod
    def admin_valitation(cls, data):
        errMsg = []
        noInput = 'が正しく入力されていません。'
        if not re.search(r'^[a-z0-9]+$',data['manage_company_name']):
            errMsg.append('会社名は半角英数文字(英小文字)のみです。')
        if not re.search(r'^[a-z0-9]+$',data['project_name_gcp']):
            errMsg.append('プロジェクト名は半角英数文字(英小文字)のみです。')
        if not re.search(r'^[a-z0-9]+$',data['organization_name']):
            errMsg.append('組織名は半角英数文字(英小文字)のみです。')
        if data['use_purpose'] != 'wp' and data['use_purpose'] != 'static':
            if not re.search(r'^(?!10\.0\.0\.0/31$)\d+\.\d+\.\d+\.\d+/\d+$',data['subnet_info']):
                errMsg.append('利用IP範囲は半角数字及び.(ドット)/(スラッシュ)のみです。')
        if not re.search(r'^[a-z0-9\-]+$',data['group_name']):
            errMsg.append('Googleグループ名(管理者用)は半角英数文字(英小文字),-(半角ハイフン)のみです。')
        if not re.search(r'[\w\-._]+@[\w\-._]+\.[A-Za-z]+',data['group_email']):
            errMsg.append('Googleグループのemail(管理者用)' + noInput)
        if not re.search(r'^[a-z0-9\-]+$',data['user_group_name']):
            errMsg.append('Googleグループ名(利用者用)は半角英数文字(英小文字),-(半角ハイフン)のみです。')
        if not re.search(r'[\w\-._]+@[\w\-._]+\.[A-Za-z]+',data['user_group_email']):
            errMsg.append('Googleグループのemail(利用者用)' + noInput)
        if not data['env']:
            errMsg.append('環境' + noInput)
        if not data['use_purpose']:
            errMsg.append('利用用途' + noInput)
        if data['use_purpose'] == 'api':
            client_cidr_data = data['client_cidr']
            client_cidr_data = client_cidr_data.replace(' ', '')
            if not re.search(r'^(((?!10\.0\.0\.0/31$)\d+\.\d+\.\d+\.\d+/\d+)(?:,|$))+$',data['client_cidr']) and client_cidr_data != '':
                errMsg.append('アクセス元IP制限は半角数字及び.(ドット)/(スラッシュ),(カンマ)のみです。')
        if data['use_purpose'] == 'secure':
            if not re.search(r'^(((?!10\.0\.0\.0/31$)\d+\.\d+\.\d+\.\d+/\d+)(?:,|$))+$', data['client_cidr']):
                errMsg.append('アクセス元IP制限は半角数字及び.(ドット)/(スラッシュ),(カンマ)のみです。')
        if len(data['manage_company_name']) > 8:
            errMsg.append('会社名が8文字を超えています!!')
        if len(data['project_name_gcp']) > 8:
            errMsg.append('プロジェクト名が8文字を超えています!!')
        if len(data['organization_name']) > 8:
            errMsg.append('組織名が8文字を超えています!!')
        if data['use_purpose'] == 'secure':
            if 'vpc_access_conn' in data or 'connector_cidr' in data:
                if not re.search(r'^(?!10\.0\.0\.0/31$)\d+\.\d+\.\d+\.\d+/28$', data['connector_cidr']) and data['connector_cidr'] != '':
                    errMsg.append('VPCコネクター利用IP範囲が適切な形式になっていません。(空欄又は*.*.*.*/28など)。')
        if data['use_purpose'] == 'static' or data['use_purpose'] == 'wp':
            if not re.search(r'^(?![-.])[a-z0-9]([a-z0-9.-]*[a-z0-9])?(\.[a-z]{2,})+$', data['domain_name']):
                errMsg.append('無効なドメイン名です。')


        return errMsg

    @classmethod
    def get_company_list(self):

        query = f'select ' \
                f'company_id,company_name ' \
                f'from `{project}.{dataset}.{company_list_table}`'

        query_job = bigquery_client.query(query)

        company_data = []

        for row in query_job:
            data = dict()
            data["company_id"] = row['company_id']
            data["company_name"] = row['company_name']
            company_data.append(data)

        return company_data

    @classmethod
    # 申請者リスト
    def get_users_list(self):

        query = f'select ' \
                f'id,name,desired_delivery_date,tel,email,belonging_department,project_name,type,project_id_gcp,UPDATE_FLG '\
                f'from `{project}.{dataset}.{table}` order by id desc'

        query_job = bigquery_client.query(query)

        # 結果をリストとして取得
        _result = []
        for row in query_job:
            _data = dict()
            for key, val in row.items():
                _data[key] = val
            _result.append(_data)

        return _result

    @classmethod
    # プロジェクト名を一覧取得
    def get_multicloud_pjname(cls):

        credentials = service_account.Credentials.from_service_account_file(credentials_file)

        # サービスアカウントキーを使用して認証情報を取得
        sb_credentials = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=['https://www.googleapis.com/auth/cloud-platform']
        )

        discovery_url = "https://www.googleapis.com/discovery/v1/apis/cloudresourcemanager/v1/rest"
        # Resource Manager APIを初期化
        project_service = build('cloudresourcemanager', 'v1', cache_discovery=False,
                                discoveryServiceUrl=discovery_url, credentials=sb_credentials)
        # プロジェクト一覧を取得
        projects = project_service.projects().list().execute()

        unique_list = None
        # プロジェクトの一覧を表示
        if 'projects' in projects:
            pj_list = list()
            for project in projects['projects']:
                pj_list.append(project['projectId'])
            # データの重複除去
            unique_list = list(set(pj_list))
        else:
            logger.error('プロジェクトが見つかりません。')

        return unique_list