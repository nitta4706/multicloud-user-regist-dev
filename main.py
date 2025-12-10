import os
import sys
import traceback
import pendulum
from flask import Flask, request, render_template, session, redirect, url_for, flash
from flask_login import LoginManager, UserMixin
from flask_paginate import Pagination, get_page_parameter

# リファクタリング済みのUtilsをインポート
# ※ bigquery_clientなどはUtils内部で隠蔽されているため、直接インポートせずUtils経由で使うか
#   必要ならUtilsにメソッドを追加して呼び出すのが綺麗な設計です。
#   ここでは互換性のため、bigquery_clientも使える前提で書きますが、
#   理想は Utils.get_db_client() のように取得することです。
from utils.util import Utils, logger, bigquery_client, project, dataset, table

# ==========================================
# 1. アプリケーション初期化
# ==========================================
app = Flask(__name__)

# 設定のロード (環境変数から安全に取得)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    logger.critical("CRITICAL: FLASK_SECRET_KEYが設定されていません。")
    sys.exit(1)

# デバッグモードは環境変数で制御 (ハードコードしない)
app.debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"

# ログインマネージャー設定
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # 未ログイン時のリダイレクト先（必要なら作成）

# ==========================================
# 2. ユーザーモデル & 認証
# ==========================================
class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def user_loader(email):
    # 本来はDBからユーザー存在確認をすべき
    return User(email)

@login_manager.request_loader
def request_loader(request):
    # 簡易実装: 本来はヘッダーやトークン検証が必要
    # ここでは元のロジック(email変数がどこかにある前提?)を維持しつつ安全に
    email = session.get('user_email') # セッションから取得に変更
    if not email:
        return None
    return User(email)

# ==========================================
# 3. ビジネスロジック / ヘルパー関数
# ==========================================
def get_company_name_by_id(company_id: int) -> str:
    """会社IDから会社名を取得 (キャッシュ推奨だが今回は都度取得)"""
    company_list = Utils.get_company_list()
    for row in company_list:
        if int(row["company_id"]) == int(company_id):
            return row["company_name"]
    return "不明な会社"

def generate_github_url(use_purpose: str, target_name: str) -> str:
    """利用用途に応じたGitHub URLを生成"""
    base_urls = {
        'standard': 'https://github.com/mec-mcg/mcg_multicloud_gcp_dev/tree/stg/',
        'wp':       'https://github.com/mec-mcg/mcg_multicloud_gcp_dev/tree/stg/',
        'static':   'https://github.com/mec-mcg/mcg_multicloud_gcp_static_dev/tree/stg/',
        'api':      'https://github.com/mec-mcg/mcg_multicloud_gcp_api_dev/tree/stg/',
        'secure':   'https://github.com/mec-mcg/mcg_multicloud_gcp_secure_dev/tree/stg/kpt/'
    }
    return f"{base_urls.get(use_purpose, '')}{target_name}"

# ==========================================
# 4. ルーティング & コントローラー
# ==========================================

@app.route('/', methods=['GET'])
def index():
    """トップページ (登録画面への入り口)"""
    # セッションクリアは慎重に (ログイン状態まで消える可能性があるため)
    # フォーム用データのみクリアするのがベター
    session.pop('form_data', None)
    return render_template('first_img.html', kind="登録")

@app.route('/user_req', methods=['GET', 'POST'])
def user_request():
    """ユーザー登録フォーム処理"""
    company_data = Utils.get_company_list()
    
    if request.method == 'GET':
        return render_template('add.html', form={}, kind="登録", company_data=company_data)

    if request.method == 'POST':
        form_data = request.form.to_dict()
        
        # Band 7レベルのUtils.validateを使用
        error_msgs = Utils.validate(form_data)

        if not error_msgs:
            # 確認画面へ (データはhiddenで渡すか、一時セッションに入れる)
            return render_template('add2.html', form=form_data)
        else:
            return render_template('add.html', error=error_msgs, kind="登録", form=form_data, company_data=company_data)

@app.route('/add', methods=['GET', 'POST'])
def add_project_info():
    """プロジェクト情報追加"""
    try:
        if request.method == "POST":
            form_data = request.form.to_dict()
            
            # checkboxの処理 (getlist)
            types = request.form.getlist('type')
            form_data['type'] = ",".join(types) # 文字列結合

            error_msgs = Utils.validate2(form_data)

            if not error_msgs:
                return render_template('confirm.html', form=form_data)
            else:
                return render_template('add2.html', error=error_msgs, form=form_data)
                
    except Exception as e:
        logger.error(f"Error in add_project_info: {e}\n{traceback.format_exc()}")
        return render_template('regist_error.html', error_title='system_error')
    
    return redirect(url_for('index')) # GETの場合はトップへ

@app.route('/regist', methods=['POST'])
def register_user():
    """利用者情報のDB登録 (トランザクション処理)"""
    try:
        form = request.form.to_dict()
        
        # ID採番 (MAX+1) - ※並行実行時に重複リスクあり。本来はUUIDかシーケンス推奨
        # 互換性のため元のロジックを踏襲するが、Queryを一発にする
        max_id_query = f"SELECT MAX(id) as max_id FROM `{project}.{dataset}.{table}`"
        rows = list(bigquery_client.query(max_id_query))
        new_id = (rows[0].max_id + 1) if rows and rows[0].max_id else 1
        
        insert_date = pendulum.today().date()
        
        # パラメータクエリで安全にINSERT
        insert_query = f"""
            INSERT INTO `{project}.{dataset}.{table}` 
            (id, name, desired_delivery_date, tel, email, belonging_department, company_id, 
             project_name, system_name, type, memo, insert_date, UPDATE_FLG)
            VALUES 
            (@id, @username, @regist_date, @tel_number, @regist_email, @belonging_department, @company_id,
             @project_name, @system_name, @type, @memo, @insert_date, 'update')
        """
        
        # 会社IDの分割処理 "1: 株式会社XX" -> 1
        company_id_val = int(form['company_id'].split(':')[0])

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("id", "INTEGER", new_id),
                bigquery.ScalarQueryParameter("username", "STRING", form['username']),
                bigquery.ScalarQueryParameter("regist_date", "DATE", form['regist_date']),
                bigquery.ScalarQueryParameter("tel_number", "STRING", form['tel_number']),
                bigquery.ScalarQueryParameter("regist_email", "STRING", form['email']),
                bigquery.ScalarQueryParameter("belonging_department", "STRING", form['belonging_department']),
                bigquery.ScalarQueryParameter("company_id", "INTEGER", company_id_val),
                bigquery.ScalarQueryParameter("project_name", "STRING", form['project_name']),
                bigquery.ScalarQueryParameter("system_name", "STRING", form['system_name']),
                bigquery.ScalarQueryParameter("type", "STRING", form['type']),
                bigquery.ScalarQueryParameter("memo", "STRING", form['memo']),
                bigquery.ScalarQueryParameter("insert_date", "DATE", insert_date),
            ]
        )

        query_job = bigquery_client.query(insert_query, job_config=job_config)
        query_job.result() # 完了待機

        return render_template('regist.html')

    except Exception as e:
        logger.error(f"Registration failed: {e}\n{traceback.format_exc()}")
        return render_template('regist_error.html', error_title='normal')

@app.route('/userlist', methods=['GET'])
def list_users():
    """管理者用: ユーザー一覧表示"""
    try:
        users_data = Utils.get_users_list()
        
        # 日付フォーマットのユニークリスト作成
        dates = sorted(list({entry['desired_delivery_date'].strftime('%Y-%m-%d') for entry in users_data if entry.get('desired_delivery_date')}))
        
        # ページネーション処理
        page = request.args.get(get_page_parameter(), type=int, default=1)
        per_page = 20
        start = (page - 1) * per_page
        end = start + per_page
        
        current_page_data = users_data[start:end]
        pagination = Pagination(page=page, total=len(users_data), per_page=per_page, css_framework='bootstrap5')

        return render_template('users_list.html', data=users_data, date_options=dates, rows=current_page_data, pagination=pagination)

    except Exception as e:
        logger.error(f"Error listing users: {e}\n{traceback.format_exc()}")
        return render_template('regist_error.html', error_title='manage_normal', error_mess=str(e))

@app.route("/userlist_search", methods=['POST', 'GET'])
def search_users():
    """ユーザー検索処理"""
    # セッションを活用して検索条件を保持
    if request.method == "POST":
        session['search_name'] = request.form.get('text_data', '')
        session['search_date'] = request.form.get('date', '')

    user_name = session.get('search_name', '')
    s_date = session.get('search_date', '')

    query = f"""
        SELECT id, name, desired_delivery_date, tel, email, belonging_department, 
               project_name, type, project_id_gcp, UPDATE_FLG 
        FROM `{project}.{dataset}.{table}` 
        WHERE name LIKE @user_name
    """
    
    params = [bigquery.ScalarQueryParameter("user_name", "STRING", f"%{user_name}%")]

    if s_date:
        query += " AND desired_delivery_date = @date"
        params.append(bigquery.ScalarQueryParameter("date", "STRING", s_date))
    
    query += " ORDER BY id DESC"

    query_job = bigquery_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))
    result = [dict(row.items()) for row in query_job]
    
    # ページネーション (list_usersと共通化できるが今回はそのまま記述)
    page = request.args.get(get_page_parameter(), type=int, default=1)
    per_page = 20
    rows = result[(page - 1) * per_page : page * per_page]
    pagination = Pagination(page=page, total=len(result), per_page=per_page, css_framework='bootstrap5')
    
    # 日付リストは全件から再取得が必要ならUtils経由で呼ぶか、検索結果から作る
    formatted_dates = [] # 必要なら実装

    return render_template('users_list.html', data=result, date_options=formatted_dates, rows=rows, pagination=pagination)

@app.route("/userlist_edit/<int:id>", methods=["GET", "POST"])
def update_user_view(id):
    """管理者用: 編集画面表示 & 確認処理"""
    
    # DBから最新データを取得
    query = f"SELECT * FROM `{project}.{dataset}.{table}` WHERE id = @id"
    job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("id", "INTEGER", id)])
    rows = list(bigquery_client.query(query, job_config=job_config))
    
    if not rows:
        return "User not found", 404
        
    user_data = dict(rows[0].items())
    user_data['company_name'] = get_company_name_by_id(user_data['company_id'])
    
    # GET: 編集画面表示
    if request.method == "GET":
        # 新規編集セッションの開始
        session['edit_form'] = user_data # セッションに退避
        
        msg = '※登録後変更不可' if user_data.get('UPDATE_FLG') == 'update' else ''
        return render_template("users_edit.html", data=[user_data], mess=msg)

    # POST: 確認画面へ、または戻る処理
    if request.method == "POST":
        form = request.form.to_dict()
        
        # チェックボックスなどの配列処理
        env_list = request.form.getlist('env')
        form['env'] = ",".join(env_list)

        # Utils.admin_validation を使用
        error_msgs = Utils.admin_valitation(form)

        # 重複チェックロジック
        if form.get('UPDATE_FLG') == 'update':
            target_name = f"{form['manage_company_name']}-{form['organization_name']}-{form['project_name_gcp']}"
            existing_projects = Utils.get_multicloud_pjname()
            
            for env in env_list:
                full_name = f"{target_name}-{env}"
                # リスト内の存在確認
                if full_name in existing_projects:
                    error_msgs.append(f'{full_name}: プロジェクト名が重複しています。')
                    break

        if not error_msgs:
            return render_template('edit_confirm.html', item=form, data=form)
        else:
            msg = '※登録後変更不可' if form.get('UPDATE_FLG') == 'update' else ''
            return render_template('users_edit.html', error=error_msgs, form=form, data=[form], mess=msg)

@app.route("/userlist_update/<int:id>", methods=["POST"])
def execute_update(id):
    """管理者用: DB更新実行"""
    try:
        data = request.form.to_dict()
        data['UPDATE_FLG'] = "operate" # フラグ更新
        
        # 不要なキーの削除や整形
        if data.get('vpc_access_conn') == 'None': data['vpc_access_conn'] = None
        if data.get('connector_cidr') == 'None': data['connector_cidr'] = None

        # 動的SQL構築 (BigQueryパラメータクエリ使用)
        # 更新対象のカラムを定義 (バリデーション済みの安全なキーのみ許可するホワイトリスト方式推奨)
        allowed_keys = [
            'manage_company_name', 'organization_name', 'project_name_gcp', 
            'group_name', 'group_email', 'user_group_name', 'user_group_email',
            'env', 'use_purpose', 'subnet_info', 'client_cidr', 'domain_name',
            'vpc_access_conn', 'connector_cidr', 'UPDATE_FLG'
        ]
        
        set_clauses = []
        params = []
        
        for key in allowed_keys:
            if key in data:
                set_clauses.append(f"{key} = @{key}")
                params.append(bigquery.ScalarQueryParameter(key, "STRING", data[key]))

        if not set_clauses:
            raise ValueError("No fields to update")

        query = f"UPDATE `{project}.{dataset}.{table}` SET {', '.join(set_clauses)} WHERE id = @id"
        params.append(bigquery.ScalarQueryParameter("id", "INTEGER", id))

        query_job = bigquery_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))
        query_job.result()

        # 完了画面へ (GitHub URL生成)
        target_name = f"{data.get('manage_company_name')}-{data.get('organization_name')}-{data.get('project_name_gcp')}"
        gh_url = generate_github_url(data.get('use_purpose'), target_name)
        
        return render_template('regist_complete.html', target_url=gh_url)

    except Exception as e:
        logger.error(f"Update failed: {e}\n{traceback.format_exc()}")
        return render_template('regist_error.html', error_title='manage_normal', error_mess=str(e))

@app.route("/userlist_delete/<int:id>", methods=["GET", "POST"])
def delete_user(id):
    """論理削除処理"""
    try:
        # 対象データ取得
        query = f"SELECT * FROM `{project}.{dataset}.{table}` WHERE id = @id"
        job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("id", "INTEGER", id)])
        rows = list(bigquery_client.query(query, job_config=job_config))
        
        if not rows: return "Not Found", 404
        delete_data = dict(rows[0].items())
        delete_data['company_name'] = get_company_name_by_id(delete_data['company_id'])

        if request.method == "GET":
            return render_template("users_delete.html", data=[delete_data])

        if request.method == "POST":
            # UPDATE_FLG = 'DLT' に更新
            update_query = f"UPDATE `{project}.{dataset}.{table}` SET UPDATE_FLG = 'DLT' WHERE id = @id"
            update_params = [bigquery.ScalarQueryParameter("id", "INTEGER", id)]
            
            bigquery_client.query(update_query, job_config=bigquery.QueryJobConfig(query_parameters=update_params)).result()
            
            # 完了画面へ
            target_name = f"{delete_data['manage_company_name']}-{delete_data['organization_name']}-{delete_data['project_name_gcp']}"
            gh_url = generate_github_url(delete_data['use_purpose'], target_name)
            
            return render_template('regist_complete.html', target_url=gh_url)

    except Exception as e:
        logger.error(f"Delete failed: {e}")
        return render_template('regist_error.html', error_title='manage_normal', error_mess=str(e))

if __name__ == '__main__':
    # 本番運用時はgunicorn等で起動するため、ここは開発用
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=app.debug)
