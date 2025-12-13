import os, traceback, json
import sys
import flask
from flask_paginate import Pagination, get_page_parameter
import flask_login
from utils.util import Utils
from flask import Flask, request, redirect, render_template, flash, session
from google.cloud import bigquery
from google.cloud import secretmanager
from google.oauth2 import service_account
import pendulum
import logging
import google.cloud.logging
from datetime import timedelta
from werkzeug.datastructures import ImmutableMultiDict

from utils.util import Utils

LOG_LEVEL = 20

project = "mcg-ope-admin-dev"

logging.basicConfig(
        format = "[%(asctime)s][%(levelname)s] %(message)s",
        level = LOG_LEVEL
    )
logger = logging.getLogger()

try:
    # Secret Managerからサービスアカウントキーを取得
    # SecretManagerServiceClient自体は、実行環境の認証情報(ADC)を使用します。
    secret_client = secretmanager.SecretManagerServiceClient()
    secret_id = "mcg-ope-admin-dev-sa-key"  # Secret Managerに登録したシークレット名
    version_id = "latest"
    name = f"projects/{project}/secrets/{secret_id}/versions/{version_id}"
    response = secret_client.access_secret_version(request={"name": name})
    secret_payload = response.payload.data.decode("UTF-8")
    credentials_info = json.loads(secret_payload)
    credentials = service_account.Credentials.from_service_account_info(credentials_info)
except Exception as e:
    # 認証情報の取得に失敗した場合は、プログラムを続行できないため終了させます。
    # loggerはまだ設定されていない可能性があるため、標準エラー出力に書き出します。
    logger.critical(f"Secret Managerからの認証情報取得に失敗しました。アプリケーションを終了します。: {e}")
    sys.exit(1)

app = flask.Flask(__name__)

# デバッグモードを無効にする
app.debug = False

# ログインマネージャー
login_manager = flask_login.LoginManager()
login_manager.init_app(app)

# サービスアカウント情報の取得(環境変数に設定)
# Google Cloud Logging ハンドラを logger に接続
# Cloud Logging ハンドラを logger に接続
logging_client = google.cloud.logging.Client(credentials=credentials)
logging_client.setup_logging()

logger.setLevel(LOG_LEVEL)

bigquery_client = bigquery.Client(credentials=credentials)

form = dict()
app.secret_key = 'abcdefghijklmn'

## Set Dataset
dataset = "user_regist_dev"

table = "user_regist_list"

email = None

company_data = Utils.get_company_list()
mulcloud_pj = Utils.get_multicloud_pjname()

class User(flask_login.UserMixin):
    pass

@login_manager.user_loader
def user_loader(email):
    # if email not in users:
    user = User()
    user.id = email
    return user

@login_manager.request_loader
# 権限処理
def request_loader(request):

    user = User()
    user.id = email
    return user

# 会社idから会社名を取得する関数
def get_company_name(_id):

    for row in company_data:
        if int(row["company_id"]) == int(_id):
            _company_name=row["company_name"]
            break
            
    return _company_name


@app.route('/', methods=['GET'])
def regist_first_up():

    kind = "登録"

    session.clear()
    global form

    form = {}

    if request.method == 'GET':
        # TODO: id指定された場合
        # 表示処理
        return render_template('first_img.html'
                               , kind=kind
                               )

@app.route('/user_req', methods=['POST', 'GET'])
# フォーム入力⇛確認処理(バリデーション有)
def regist_first():

    global form

    view = ""
    registId = ""
    kind = "登録"
    # GETされた場合
    if request.method == 'GET':
        # TODO: id指定された場合
        # 表示処理
        return render_template('add.html'
                        , form=form
                        , kind=kind
                        , registId=registId
                        , company_data=company_data)

    # POSTされた場合
    if request.method == 'POST':

        session = request.form

        form = request.form

        registId = ""
        # バリデーション処理
        errorMsg = []
        errorMsg = Utils.validate(data=form)

        if not errorMsg:
            return render_template('add2.html'
                            , form=session
                            , registId=registId)
        else:
            return render_template('add.html'
                            , error=errorMsg
                            , kind=kind
                            , form=form
                            , registId=registId
                            , company_data=company_data)

# 利用者申請(ユーザー登録)
# 登録内容:プロジェクト名・システム名・種別・備考
@app.route('/add',methods=['GET','POST'])
def add():

    try:

        if request.method == "POST":
            form = request.form.to_dict()
            form['project_name'] = request.form['project_name']
            form['system_name'] = request.form['system_name']
            string_data = ''
            for item in request.form.getlist('type'):
                string_data = f"{string_data},{item}"
            type = string_data[1:]
            form['type'] = type
            form['memo'] = request.form['memo']

            registId = ""
            # バリデーション処理
            errorMsg = []
            errorMsg = Utils.validate2(data=form)

            if not errorMsg:

                session = form

                return render_template('confirm.html'
                                       , form=form
                                       , registId=registId)
            else:
                return render_template('add2.html'
                                       , error=errorMsg
                                       , form=form
                                       , registId=registId)

    except Exception as e:
        logger.error("exceptions : {} : {}".format(e, traceback.format_exc()))

# 登録IDの最大値を取得する関数
def get_id(table):

    query = f'''
            BEGIN
            BEGIN TRANSACTION;
            select max(id) as max_id from `{project}.{dataset}.{table}`;
            COMMIT TRANSACTION;EXCEPTION
                WHEN ERROR THEN
            SELECT
                @@error.message;
            ROLLBACK TRANSACTION;
                RAISE;
            END;
            '''

    query_job = bigquery_client.query(query)

    query_job.result()

    for job in bigquery_client.list_jobs(parent_job=query_job.job_id):
        if job.statement_type == "COMMIT_TRANSACTION":
            commit_flg = "true"
        elif job.statement_type == "SELECT" and commit_flg == "true":
            rows = job.result()
            for row in rows:
                max_id = row["max_id"]
            break
        else:
            logger.error(job.result())

    if max_id == 0:
        new_id = 1
    else:
        new_id = int(max_id) + 1

    return new_id

@app.route('/regist',methods=['POST'])
# 利用者申請登録(ユーザー登録)
def regist_func():

    try:
        username = request.form['username']
        regist_date = request.form['regist_date']
        tel_number = request.form['tel_number']
        regist_email = request.form['email']
        belonging_department = request.form['belonging_department']
        _id = request.form['company_id'].split(':')
        company_id = int(_id[0])
        project_name = request.form['project_name']
        system_name = request.form['system_name']
        type = request.form['type']
        memo = request.form['memo']

        # 登録日時
        insert_date = pendulum.today().date()

        id = get_id(table)

        insert_query = f"""insert into `{project}.{dataset}.{table}` 
        (id,name,desired_delivery_date,tel,email,belonging_department,company_id,project_name,system_name,type,manage_company_name,project_name_gcp,organization_name,subnet_info,use_purpose,group_name,group_email,user_group_name,user_group_email,env,memo,insert_date,UPDATE_FLG,client_cidr) 
        values (@id,@username,@regist_date,@tel_number,@regist_email,@belonging_department,@company_id,@project_name,@system_name,@type,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,@memo,@insert_date,@update,NULL)"""

        query = f'''
                BEGIN
                BEGIN TRANSACTION;
                {insert_query};
                COMMIT TRANSACTION;EXCEPTION
                    WHEN ERROR THEN
                SELECT
                    @@error.message;
                ROLLBACK TRANSACTION;
                    RAISE;
                END;
                '''
        # パラメータ値の設定
        parameters = [
            bigquery.ScalarQueryParameter("id", "INTEGER", id),
            bigquery.ScalarQueryParameter("username", "STRING", username),
            bigquery.ScalarQueryParameter("regist_date", "DATE", regist_date),
            bigquery.ScalarQueryParameter("tel_number", "STRING", tel_number),
            bigquery.ScalarQueryParameter("regist_email", "STRING", regist_email),
            bigquery.ScalarQueryParameter("belonging_department", "STRING", belonging_department),
            bigquery.ScalarQueryParameter("company_id", "INTEGER", company_id),
            bigquery.ScalarQueryParameter("project_name", "STRING", project_name),
            bigquery.ScalarQueryParameter("system_name", "STRING", system_name),
            bigquery.ScalarQueryParameter("type", "STRING", type),
            bigquery.ScalarQueryParameter("memo", "STRING", memo),
            bigquery.ScalarQueryParameter("insert_date", "DATE", insert_date),
            bigquery.ScalarQueryParameter("update", "STRING", "update"),
        ]

        query_job = bigquery_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=parameters))

        # 非同期ジョブの完了を待機
        query_job.result()

        for job in bigquery_client.list_jobs(parent_job=query_job.job_id):
            if job.statement_type == "COMMIT_TRANSACTION":
                TRANSACTION_FLG = "DONE"
                break
            elif job.statement_type == "SELECT":
                logger.error(job.result())
                TRANSACTION_FLG = "NG"
                break

        if query_job.state == "DONE":
            return render_template('regist.html')
        else:
            raise Exception("一般利用者の登録が正常に終了しませんでした!!")

    except Exception as e:
        error_mess = "exceptions : {} : {}".format(e, traceback.format_exc())
        logger.error(error_mess)
        return render_template('regist_error.html',error_title='normal')


@app.route('/userlist', methods=['get'])
# ユーザー登録(管理者画面の登録内容一覧表示)
def users_list():

    global formatted_dates

    try:
        session.clear()
        users_data = Utils.get_users_list()

        desired_delivery_dates = list({entry['desired_delivery_date'] for entry in users_data})
        formatted_dates = [date.strftime('%Y-%m-%d') for date in desired_delivery_dates]
        page = request.args.get(get_page_parameter(), type=int, default=1)
        per_page = 20
        # 表示対象のデータをスライス
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        res = users_data[start_index:end_index]
        pagination = Pagination(page=page, total=len(users_data), per_page=per_page, css_framework='bootstrap5')

        return render_template('users_list.html',data=users_data, date_options=formatted_dates,rows=res, pagination=pagination)

    except Exception as e:
        error_mess = "exceptions : {} : {}".format(e, traceback.format_exc())
        logger.error(error_mess)
        return render_template('regist_error.html',error_title='manage_normal', error_mess=error_mess)

@app.route("/userlist_search",methods=['POST','GET'])
def users_search():

    if request.method == "POST":

        user_name = request.form['text_data']
        s_date = request.form["date"]
        session['user_name'] = user_name
        session['s_date'] = s_date

    else:
        user_name = session['user_name']
        s_date = session['s_date']

    if s_date != '':
        add_sql_conditions = 'and desired_delivery_date = @date'
    else:
        add_sql_conditions =''

    query = f"select " \
            f"id,name,desired_delivery_date,tel,email,belonging_department,project_name,type,project_id_gcp,UPDATE_FLG " \
            f"from `{project}.{dataset}.{table}` where name like @user_name {add_sql_conditions} order by id desc"

    # パラメータ値の設定
    param = [
        bigquery.ScalarQueryParameter("user_name", "STRING", f"%{user_name}%")
    ]

    if s_date != '':
        param.append(bigquery.ScalarQueryParameter("date", "STRING", f"{s_date}"))

    query_job = bigquery_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=param))

    # 非同期ジョブの完了を待機
    query_job.result()

    # 結果をリストとして取得
    _result = []
    for row in query_job:
        _data = dict()
        for key, val in row.items():
            _data[key] = val
        _result.append(_data)

    page = request.args.get(get_page_parameter(), type=int, default=1)
    per_page = 20
    # 表示対象のデータをスライス
    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    res = _result[start_index:end_index]
    pagination = Pagination(page=page, total=len(_result), per_page=per_page, css_framework='bootstrap5')
    return render_template('users_list.html', data=_result,date_options=formatted_dates, rows=res, pagination=pagination)

# 管理者画面から選択した編集したいコンテンツを抽出して、
# users_edit.htmlファイルに表示(GET)・編集・登録する(POST)処理
# (編集登録時にはバリデーション処理有り)
@app.route("/userlist_edit/<int:id>", methods=["GET", "POST"])
def users_update(id):

    global connector_cidr_val

    query = f"select * from `{project}.{dataset}.{table}` where id ={id}"

    if 'UPDATE_FLG' not in session:
        session.clear()

    if request.method == "GET":

        if not session:

            query_job = bigquery_client.query(query)
            edit_data = []
            before_data = []
            for row in query_job:
                _data = dict()
                for key, val in row.items():
                    if key == 'company_id':
                        _company_name = get_company_name(val)
                        _data['company_name'] = _company_name
                    else:
                        _data[key] = val

                edit_data.append(_data)

            if edit_data[0]['UPDATE_FLG'] == 'update':
                session['mess'] = '※登録後変更不可'
            else:
                session['mess'] = ''
                if edit_data[0]['use_purpose'] == 'secure':
                    connector_cidr_val = edit_data[0]['connector_cidr']

            return render_template("users_edit.html", data=edit_data, mess=session['mess'])

        else:
            session_list = list()
            if session["UPDATE_FLG"] == 'update':
                if 'use_purpose' in session:
                    del session["use_purpose"]
                if 'env' in session:
                    del session["env"]
                session["mess"] = '※登録後変更不可'
            else:
                session["mess"] = ''
                if session['use_purpose'] == 'secure':
                    session['connector_cidr'] = connector_cidr_val

            session_list.append(session)
            return render_template("users_edit.html", data=session_list,mess=session['mess'])

    if request.method == "POST":

        for key,val in request.form.items():
            session[key] = val

        # 既に登録済みの場合
        if request.form['UPDATE_FLG'] == 'operate_complete':

            immutable_multidict = ImmutableMultiDict(request.form)

            key_value_list = list(immutable_multidict.items())

            result = dict(key_value_list)
            if 'client_cidr2' in result:
                result['client_cidr'] = result['client_cidr2']

            form = request.form.to_dict()
            form['id'] = request.form['id']
            form['manage_company_name'] = result['manage_company_name']
            form['project_name_gcp'] = result['project_name_gcp']
            form['organization_name'] = result['organization_name']
            form['env'] = result['env']
            form['subnet_info'] = result['subnet_info']
            form['group_name'] = result['group_name']
            form['group_email'] = result['group_email']
            form['user_group_name'] = result['user_group_name']
            form['user_group_email'] = result['user_group_email']
            form['use_purpose'] = result['use_purpose']
            form['client_cidr'] = result['client_cidr']
            form['UPDATE_FLG'] = result['UPDATE_FLG']

            # 利用用途:セキュアの場合
            if request.form['use_purpose'] == 'secure':
                if 'vpc_access_conn' in request.form:
                    if request.form['vpc_access_conn'] != 'None':
                        vpc_access_conn_value = request.form.get('vpc_access_conn', '')
                        if vpc_access_conn_value != '':
                            form['vpc_access_conn'] = request.form['vpc_access_conn']
                    else:
                        if request.form['vpc_access_conn'] == 'None':
                            form['vpc_access_conn'] = ''
                        else:
                            form['vpc_access_conn'] = request.form['vpc_access_conn']
                    form['connector_cidr'] = request.form['connector_cidr']
                if 'connector_cidr' in result:
                    form['connector_cidr'] = result['connector_cidr']
                if 'vpc_access_conn' in result:
                    form['vpc_access_conn'] = result['vpc_access_conn']
                if 'connector_cidr2' in result:
                    result['connector_cidr'] = result['connector_cidr2']
                if result['vpc_access_conn'] is None:
                    result['vpc_access_conn'] = ''
                # connector_cidrを生成してない場合は、対象から外す
                if form['connector_cidr'] == 'None' or form['connector_cidr'] == '':
                    del form['connector_cidr']
                    del form['vpc_access_conn']

        else:

            form = request.form.to_dict()

            form['manage_company_name'] = request.form['manage_company_name']
            form['project_name_gcp'] = request.form['project_name_gcp']
            form['organization_name'] = request.form['organization_name']
            string_data = ''
            for item in request.form.getlist('env'):
                string_data = f"{string_data},{item}"
            env = string_data[1:]
            form['env'] = env
            form['group_name'] = request.form['group_name']
            form['group_email'] = request.form['group_email']
            form['user_group_name'] = request.form['user_group_name']
            form['user_group_email'] = request.form['user_group_email']
            use_purpose = request.form.get('use_purpose')
            if use_purpose != 'wp' and use_purpose != 'static':
                form['subnet_info'] = request.form['subnet_info']
            form['use_purpose'] = use_purpose
            if use_purpose != 'standard' and use_purpose != 'wp' and use_purpose != 'static' and use_purpose is not None:
                form['client_cidr'] = request.form['client_cidr']
            if use_purpose == 'secure':
                if 'vpc_access_conn' in request.form:
                    form['vpc_access_conn'] = request.form['vpc_access_conn']
                    form['connector_cidr'] = request.form['connector_cidr']
            form['id'] = request.form['id']
            form['project_name'] = request.form['project_name']
            form['system_name'] = request.form['system_name']
            form['type'] = request.form['type']
            form['company_name'] = request.form['company_name']
            form['name'] = request.form['name']
            form['tel'] = request.form['tel']
            form['email'] = request.form['email']
            form['belonging_department'] = request.form['belonging_department']
            form['memo'] = request.form['memo']
            form['UPDATE_FLG'] = request.form['UPDATE_FLG']

        if 'client_cidr2' in form:
            form["client_cidr"] = form['client_cidr2']
        if 'connector_cidr2' in form:
            form["connector_cidr"] = form['connector_cidr2']

        # バリデーション処理
        errorMsg = []
        errorMsg = Utils.admin_valitation(data=form)

        target_name = f"{form['manage_company_name']}-{form['organization_name']}-{form['project_name_gcp']}"

        if request.form['UPDATE_FLG'] == 'update':

            if ',' in env:
                cr_env = env.split(',')
            else:
                cr_env = list()
                cr_env.append(env)

            for _env in cr_env:
                target_name_v2 = f"{target_name}-{_env}"
                if mulcloud_pj.count(target_name_v2) > 0:
                    errorMsg.append(f'{target_name_v2}:社名・組織名・PJ名・環境名(prd/stg/dev)の組み合わせが重複です。')
                    break
                else:
                    pass
        else:
            pass

        if not errorMsg:

            global users_data
            key_list = flask.request.form.keys()

            edit_dict = dict()

            for key,val in form.items():

                edit_dict[key] = val

            if 'client_cidr' in key_list:
                _check_client_cidr = form['client_cidr']
                _check_client_cidr = _check_client_cidr.replace(' ','')
                if _check_client_cidr == '':
                    client_cidr = '0.0.0.0/0'
                else:
                    client_cidr = f'{_check_client_cidr}'
            else:
                client_cidr = 'NULL'

            edit_dict['client_cidr'] = client_cidr

            if form['use_purpose'] == 'secure' and form['UPDATE_FLG'] == 'operate_complete':

                if 'client_cidr2' in form:
                    edit_dict["client_cidr"] = form['client_cidr2']
                if 'connector_cidr2' in form:
                    edit_dict["connector_cidr"] = form['connector_cidr2']
                if 'vpc_access_conn' in form:
                    if form['vpc_access_conn'] == 'None':
                        edit_dict['vpc_access_conn'] = ''
                if 'vpc_access_conn' not in form and "connector_cidr" not in form:
                    edit_dict["vpc_access_conn"] = ''
                    edit_dict["connector_cidr"] = ''
            if form['use_purpose'] == 'static' or form['use_purpose'] == 'wp':
                edit_dict["domain_name"] = form["domain_name"]

            for key,val in edit_dict.items():
                session[key] = val

            return render_template('edit_confirm.html'
                                   , item=edit_dict
                                   , data=session)
        else:
            validate_data = list()

            for key,val in request.form.items():
                form[key] = val

            if form['UPDATE_FLG'] == 'update':
                form['use_purpose'] = ''
                form['env'] = ''
                session['mess']='※登録後変更不可'
            validate_data.append(form)

            if session['UPDATE_FLG'] == 'operate_complete':
                session['mess'] = ''

            return render_template('users_edit.html'
                                   , error=errorMsg
                                   , form=form
                                   , data=validate_data
                                   , mess=session['mess'])

# BQにデータを格納するためのパラメーター設定をする関数
def change_updatedata_dict(update_data):

    update_data["UPDATE_FLG"] = "operate"

    target_sql = ''
    parameters = []
    for key, val in update_data.items():
        target_sql += f' {key}=@{key},'
        parameters.append(bigquery.ScalarQueryParameter(key, "STRING", val))

    target_sql = target_sql[:-1]

    return target_sql,parameters

@app.route("/userlist_update/<int:id>", methods=["POST"])
# 管理者画面から入力した内容をBQにinsertする(ID毎)
def edit_update(id):

    try:
        update_data = dict()

        update_data["manage_company_name"] = request.form["manage_company_name"]
        update_data["organization_name"] = request.form["organization_name"]
        update_data["project_name_gcp"] = request.form["project_name_gcp"]
        update_data["group_name"] = request.form["group_name"]
        update_data["group_email"] = request.form["group_email"]
        update_data["user_group_name"] = request.form["user_group_name"]
        update_data["user_group_email"] = request.form["user_group_email"]
        update_data["env"] = request.form["env"]
        update_data["use_purpose"] = request.form["use_purpose"]
        if update_data["use_purpose"] != 'wp' and update_data["use_purpose"] != 'static':
            update_data["subnet_info"] = request.form["subnet_info"]
            update_data["client_cidr"] = request.form["client_cidr"]
        if update_data["use_purpose"] == 'static' or update_data["use_purpose"] == 'wp':
            update_data["domain_name"] = request.form["domain_name"]
        update_data["UPDATE_FLG"] = request.form["UPDATE_FLG"]

        # 利用目的:セキュアの場合
        if update_data["use_purpose"] == 'secure':
            if 'vpc_access_conn' in request.form:
                if request.form['vpc_access_conn'] == '' or request.form['vpc_access_conn'] == 'None':
                    update_data['vpc_access_conn'] = None
                else:
                    update_data['vpc_access_conn'] = request.form['vpc_access_conn']
            if 'connector_cidr' in request.form:
                if request.form['connector_cidr'] == '' or request.form['connector_cidr'] == 'None':
                    update_data['connector_cidr'] = None
                else:
                    update_data['connector_cidr'] = request.form['connector_cidr']

        if 'vpc_access_conn' not in update_data and 'connector_cidr' in update_data:
            update_data["vpc_access_conn"] = None

        target_name = f"{update_data['manage_company_name']}-{update_data['organization_name']}-{update_data['project_name_gcp']}"

        query = ''
        # 管理者側から新規で登録する場合の処理
        if update_data["UPDATE_FLG"] == 'update':

            # BQにデータを格納するためのパラメーター設定をする
            target_sql, params = change_updatedata_dict(update_data)
            query = f"""update `{project}.{dataset}.{table}` set {target_sql} where id = {id}"""

            query_job = bigquery_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))

            # 非同期ジョブの完了を待機
            query_job.result()

        # 管理者側から登録後、client_cidrを変更した場合の処理
        if update_data["UPDATE_FLG"] == 'operate_complete':

            if update_data["use_purpose"] == 'wp' or update_data["use_purpose"] == 'static':
                domain_name = update_data["domain_name"]
            else:
                client_cidr = update_data["client_cidr"]

            if 'vpc_access_conn' in update_data and 'connector_cidr' in update_data and update_data["use_purpose"] == 'secure':

                query = f"""update `{project}.{dataset}.{table}` set UPDATE_FLG="operate", client_cidr=@client_cidr, vpc_access_conn=@vpc_access_conn, connector_cidr=@connector_cidr where id = {id}"""

                params = [
                    bigquery.ScalarQueryParameter("client_cidr", "STRING", client_cidr),
                    bigquery.ScalarQueryParameter("vpc_access_conn", "STRING", update_data["vpc_access_conn"]),
                    bigquery.ScalarQueryParameter("connector_cidr", "STRING", update_data["connector_cidr"])
                ]

            else:

                if update_data["use_purpose"] == 'api':

                    query = f"""update `{project}.{dataset}.{table}` set UPDATE_FLG="operate",client_cidr=@client_cidr where id = {id}"""

                    params = [
                        bigquery.ScalarQueryParameter("client_cidr", "STRING", client_cidr)
                    ]
                else:
                    query = f"""update `{project}.{dataset}.{table}` set UPDATE_FLG="operate",domain_name=@domain_name where id = {id}"""

                    params = [
                        bigquery.ScalarQueryParameter("domain_name", "STRING", domain_name)
                    ]

            query_job = bigquery_client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))

            # 非同期ジョブの完了を待機
            query_job.result()

        if query_job.state == "DONE":
            github_url = ''
            if update_data['use_purpose'] == 'standard' or update_data['use_purpose'] == 'wp':
                github_url = f'https://github.com/mec-mcg/mcg_multicloud_gcp_dev/tree/stg/{target_name}'
            if update_data['use_purpose'] == 'static':
                github_url = f'https://github.com/mec-mcg/mcg_multicloud_gcp_static_dev/tree/stg/{target_name}'
            if update_data['use_purpose'] == 'api':
                github_url = f'https://github.com/mec-mcg/mcg_multicloud_gcp_api_dev/tree/stg/{target_name}'
            if update_data['use_purpose'] == 'secure':
                github_url = f'https://github.com/mec-mcg/mcg_multicloud_gcp_secure_dev/tree/stg/kpt/{target_name}'

            return render_template('regist_complete.html',
                                   target_url=github_url)

        else:
            raise Exception("管理者からの登録が正常に終了しませんでした!!")

    except Exception as e:
        error_mess = "exceptions : {} : {}".format(e, traceback.format_exc())
        logger.error(error_mess)
        return render_template('regist_error.html',error_title='manage_normal',error_mess=error_mess)

@app.route("/userlist_delete/<int:id>", methods=["GET", "POST"])
# 管理者TOP画面から削除対象のデータを選択し、削除する処理(SQLのUPDATE文でステータスカラムに『DLT』の文字でカラムを更新)
# (削除詳細)
# 実際には、削除はせず対象ブランチ(or フォルダ)のgithubのブランチのREADME.mdファイルに
# 『{stg/prd}/${会社名}-${組織名}-${PJ名}:カーカイブ済みプロジェクト』を記載する⇛ここはGCFで実施
def users_delete(id):

    query = f"select " \
            f"id,project_name,system_name,type,company_id,manage_company_name,project_name_gcp,organization_name,subnet_info,client_cidr,env,use_purpose " \
            f"from `{project}.{dataset}.{table}` where id ={id}"

    query_job = bigquery_client.query(query)

    delete_data = []
    for row in query_job:
        _data = dict()
        for key, val in row.items():
            if key == 'company_id':
                _company_name = get_company_name(val)
                _data['company_name'] = _company_name
            else:
                _data[key] = val
        delete_data.append(_data)
    # 利用用途
    use_purpose = delete_data[0]['use_purpose']
    # ブランチ名⇛${会社名}-${組織名}-${PJ名}
    target_name = f"{delete_data[0]['manage_company_name']}-{delete_data[0]['organization_name']}-{delete_data[0]['project_name_gcp']}"

    if request.method == "GET":
        # 削除対象の内容を一旦、users_delete.htmlに表示
        return render_template("users_delete.html",data=delete_data)

    if request.method == "POST":

        # 削除対象のデータのUPDATE_FLGカラムを『DLT』に更新
        query = f'update `{project}.{dataset}.{table}` set UPDATE_FLG = "DLT" where id = {id}'

        rows = bigquery_client.query(query)

        rows.result()

        github_url = ''
        if use_purpose == 'standard' or use_purpose == 'wp':
            github_url = f'https://github.com/mec-mcg/mcg_multicloud_gcp_dev/tree/stg/{target_name}'
        if use_purpose == 'static':
            github_url = f'https://github.com/mec-mcg/mcg_multicloud_gcp_static_dev/tree/stg/{target_name}'
        if use_purpose == 'api':
            github_url = f'https://github.com/mec-mcg/mcg_multicloud_gcp_api_dev/tree/stg/{target_name}'
        if use_purpose == 'secure':
            github_url = f'https://github.com/mec-mcg/mcg_multicloud_gcp_secure_dev/tree/stg/kpt/{target_name}'

        return render_template('regist_complete.html',
                               target_url=github_url)

if __name__ == '__main__':

    app.run(host="0.0.0.0",port=8080,debug=True)
