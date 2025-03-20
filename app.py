from functools import wraps
from flask import Flask, request, render_template, session, redirect, url_for,make_response
import pyotp
import dataset
from flask import Flask, render_template, send_from_directory, jsonify, send_file
from werkzeug.utils import safe_join
import os
from urllib.parse import quote, unquote
import mimetypes
import time
import datetime


'''
-- 一个简易的用户表结构
CREATE TABLE `user` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(255) NOT NULL,
  `password` varchar(255) NOT NULL,
  `secret_key` char(32) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8 COMMENT='用户表';

'''
#创建一个数据库连接
#db = dataset.connect('mysql+pymysql://root:root@127.0.0.1:3306/mfa_test?charset=utf8&autocommit=true')
db = dataset.connect('sqlite:///mfa.db')

#实例化，一个用户表
table=db['user']
table_token = db['token']

app = Flask(__name__)


# 视频播放器设置
app.config['HEADERS_USE_UTF8'] = True

MOVIES_FOLDER = os.path.abspath(os.path.join(app.root_path, './share_video'))#这里替换成你自己储存视频的总文件夹




@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':

        # 获取用户账户和密码和token
        username = request.form['username']
        password = request.form['password']
        code = request.form['code']
        # 如果存在登录信息,那就直接放行
        try:
            get_cookie = request.cookies.get('allowcookie')
            if cookie_status(get_cookie):
                res = make_response(redirect('/player', code=301))
                res.set_cookie(get_cookie)
                return res
        except Exception as e:
            pass


        # 根据账号密码验证用户是否存在
        results = table.find_one(username=username)
        if results==None or password!=results['password']:
            return render_template('login.html',err_msg="账号密码错误")

        # 根据用户的MFA密钥验证是否正确
        check_mfa = pyotp.TOTP(results['secret_key']).verify(code)
        if check_mfa:
            res = make_response(redirect('/player', code=301))
            cookie = pyotp.random_base32()
            table_token.insert({'username':username,'cookie':cookie,'time':datetime.datetime.now(),'update_time':datetime.datetime.now()})
            res.set_cookie('allowcookie',cookie)
            return res
        else:
            return render_template('login.html',err_msg="MFA验证码错误")
        
    else:
        return render_template('login.html',err_msg="")



def cookie_status(get_cookie):   #(request):
    # get_cookie = request.cookies.get('allowcookie')
    register_form = table_token.find_one(cookie=get_cookie)

    # 如果没有获取到这个记录 直接返回False
    if register_form==None:
        # print("没拿到")
        return False
    # 检测cookie是否过期
    elif datetime.datetime.now() - register_form['update_time'] > datetime.timedelta(minutes=120):
        # print("进检测是不存在的")
        return False
    else:
        # update 的字段是通过前面   table_token.find_one(cookie=get_cookie)来定位的
        table_token.update(
            {
                'cookie': get_cookie,
                'update_time': datetime.datetime.now()  # 更新时间为当前时间
            },
            ['cookie']  # 根据 cookie 字段定位记录
        )
        # print("检测是存在的哈")
        return True

# 登录状态装饰器
"""
终于是把装饰器写出来了!
装饰器要在路径修饰下面,否则无法获取
request是一个全局变量,python实际就是单线程的,所以在函数外也可以被获取
"""
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        get_cookie = request.cookies.get('allowcookie')
        # print("获取cookie"+ get_cookie)
        if not cookie_status(get_cookie):
            print("不存在")
            return redirect('/')  # 未登录或登录过期，重定向到登录页面
        return f(*args, **kwargs)  # 已登录，继续执行路由函数
    return decorated_function


# @app.route('/register',methods=['POST','GET'])
def register():
    if request.method == 'POST':
        # 获取用户账户和密码
        username = request.form['username']
        if table.find_one(username=username):
            return "<script>alert('该用户已经注册')</script>"

        else:
            password = request.form['password']
            # 生成一个2FA密钥
            secret_key = pyotp.random_base32()
            # 注册用户，插入数据库
            table.insert(dict(
                username=username,
                password=password,
                secret_key=secret_key
                ))
            # 生成MFA棒的二维码链接
            qr_uri = pyotp.totp.TOTP(secret_key).provisioning_uri(name='xiaozhao', issuer_name=username)

            # 让用户绑定MFA
            return render_template('bcode.html',qr_uri=qr_uri)

    else:
        return render_template('register.html')



"""
视频播放设置
"""

def get_video_files(directory):
    video_files = []
    for root, dirs, files in os.walk(directory):
        # 将根路径转换为相对路径，如果是根目录，则设置为 '.'
        relative_root = os.path.relpath(root, directory).replace("\\", "/")
        if relative_root == ".":
            relative_root = ""  # 将根目录设为空字符串或其他合适值

        for file in files:
            if file.lower().endswith(('.mp4', '.avi', '.mkv', '.mov')):#只支持这种视频文件格式，ts格式的视频不能被正常浏览器解析，mkv格式的视频只能在
                video_path = f"{relative_root}/{file}".lstrip('/')
                video_id = quote(video_path)
                video_files.append({'id': video_id, 'name': file, 'folder': relative_root})
    return video_files


@app.route('/player')
@login_required
def index():
    return render_template('index.html')



@app.route('/videos/')
@login_required
def list_videos():
    videos = get_video_files(MOVIES_FOLDER)
    return jsonify(videos)



@app.route('/videos/<path:video_path>')
@login_required
def video(video_path):
    video_path = unquote(video_path)
    path = safe_join(MOVIES_FOLDER, video_path)
    if path and os.path.isfile(path):
        response = send_from_directory(MOVIES_FOLDER, video_path, as_attachment=False)
        response.headers['Content-Type'] = mimetypes.guess_type(path)[0] or 'video/mp4'
        response.headers['Content-Disposition'] = f"inline; filename*=UTF-8''{quote(os.path.basename(path))}"
        response.headers['Accept-Ranges'] = 'bytes'
        return response
    else:
        return "File not found", 404



if __name__ == '__main__':
    app.run(debug=True,port=5888,host='0.0.0.0')
