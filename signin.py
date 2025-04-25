import json
import random
import time
import requests
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pytz import timezone
import os
import hashlib

# 修复时区为上海时区
def Shanghai(sec, what):
    tz = timezone('Asia/Shanghai')
    timenow = datetime.now(tz)
    return timenow.timetuple()

logging.Formatter.converter = Shanghai

# 日志设置
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s]:  %(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

# 静态配置
platform = '1'  # IOS平台
app_version = '1.2.2'
market_id = 'floor_huluxia'
headers = {
    "Host": "floor.huluxia.com",
    "Accept": "*/*",
    "Accept-Language": "zh-Hans-CN;q=1, en-GB;q=0.9, zh-Hant-CN;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept-Encoding": "gzip, deflate, br",
    "User-Agent": "Floor/1.2.2 (iPhone; iOS 18.2; Scale/3.00)",
    "Connection": "keep-alive"
}

# 版块信息
cat_id_dict = {
    "1": "3楼公告版", "2": "泳池", "3": "自拍", "4": "游戏", "6": "意见反馈",
    "15": "葫芦山", "16": "玩机广场", "21": "穿越火线", "22": "英雄联盟", "29": "次元阁",
    "43": "实用软件", "44": "玩机教程", "45": "原创技术", "57": "头像签名", "58": "恶搞",
    "60": "未知版块", "63": "我的世界", "67": "MC贴子", "68": "资源审核", "69": "优秀资源",
    "70": "福利活动", "71": "王者荣耀", "76": "娱乐天地", "81": "手机美化", "82": "3楼学院",
    "84": "3楼精选", "92": "模型玩具", "94": "三楼活动", "96": "技术分享", "98": "制图工坊",
    "102": "LOL手游", "107": "三两影", "108": "新游推荐", "110": "原神", "111": "Steam",
    "115": "金铲铲之战", "119": "爱国爱党", "125": "妙易堂"
}

# 从环境变量中获取账号和密码，格式为：email:password,email:password,...
accounts = []
if "HULUXIA_ACCOUNTS" in os.environ:
    accounts_env = os.environ["HULUXIA_ACCOUNTS"]
    accounts = [tuple(acc.split(":")) for acc in accounts_env.split(",")]

# 读取邮箱配置
with open("config.json", "r") as f:
    config = json.load(f)

email_config = config.get("email", {})

# 邮件推送函数
def email_push(subject, content):
    smtp_server = email_config.get("smtp_server")
    port = email_config.get("port")
    sender_email = email_config.get("sender_email")
    password = email_config.get("password")
    receiver_email = email_config.get("receiver_email")

    if not all([smtp_server, port, sender_email, password, receiver_email]):
        logger.warning("邮件推送配置不完整，无法发送邮件")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = receiver_email
        msg["Subject"] = subject
        msg.attach(MIMEText(content, "plain"))
        with smtplib.SMTP_SSL(smtp_server, port) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        logger.info("邮件推送成功")
    except Exception as e:
        logger.error(f"邮件推送失败：{e}")

# ------------------------------
# 设备随机配置及配置文件操作
# ------------------------------

# 随机生成设备配置，降低同一配置请求频率
def generate_random_device_config():
    phone_brand_type_list = ["MI", "Huawei", "UN", "OPPO", "VO"]
    device_code_random = random.randint(111, 987)
    device_code = '%5Bd%5D5125c3c6-f' + str(device_code_random) + '-4c6b-81cf-9bc467522d61'
    phone_brand_type = random.choice(phone_brand_type_list)
    return device_code, phone_brand_type

# 读取已保存的设备配置文件 hlxconfig.json
hlxconfig_path = "hlxconfig.json"
if os.path.exists(hlxconfig_path):
    with open(hlxconfig_path, "r") as f:
        hlx_config = json.load(f)
else:
    hlx_config = {}

# 将配置写回文件
def save_hlx_config():
    with open(hlxconfig_path, "w") as f:
        json.dump(hlx_config, f, indent=4)
    logger.info("hlxconfig.json 已更新")

# ------------------------------
# 会话缓存操作（保存令牌信息到本地）
# ------------------------------
session_file = "session.json"

def load_session(account):
    if os.path.exists(session_file):
        with open(session_file, "r") as f:
            sessions = json.load(f)
        if account in sessions:
            sess = sessions[account]
            try:
                expire_time = datetime.fromisoformat(sess.get("expire_time"))
            except Exception as e:
                logger.error(f"解析过期时间失败: {e}")
                return None
            tz = timezone('Asia/Shanghai')
            if datetime.now(tz) < expire_time:
                return sess
    return None

def save_session(account, _key, user_id, valid_minutes=60):
    tz = timezone('Asia/Shanghai')
    expire_time = datetime.now(tz) + timedelta(minutes=valid_minutes)
    sess = {"_key": _key, "user_id": user_id, "expire_time": expire_time.isoformat()}
    sessions = {}
    if os.path.exists(session_file):
        with open(session_file, "r") as f:
            sessions = json.load(f)
    sessions[account] = sess
    with open(session_file, "w") as f:
        json.dump(sessions, f, indent=4)

# ------------------------------
# 葫芦侠签到类
# ------------------------------
class HuluxiaSignin:
    def __init__(self):
        self._key = ''
        self.userid = ''
        self.device_code = ''
        self.phone_brand_type = ''
        self.session = requests.Session()

    def md5(self, text):
        _md5 = hashlib.md5()
        _md5.update(text.encode())
        return _md5.hexdigest()

    # 修改后的登录函数，使用新请求参数格式，避免重复登录
    def psd_login(self, account, password):
        login_url = 'https://floor.huluxia.com/account/login/IOS/1.0'
        login_data = {
            'access_token': '',
            'app_version': app_version,
            'code': '',
            'device_code': self.device_code,
            'device_model': 'iPhone14,3',
            'email': account,
            'market_id': market_id,
            'openid': '',
            'password': self.md5(password),
            'phone': '',
            'platform': platform
        }
        try:
            res = self.session.post(url=login_url, data=login_data, headers=headers)
            return res.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"登录请求失败：{e}")
            return {"status": 0}

    def set_config(self, acc, psd):
        # 根据账号判断是否已有保存的设备配置
        if acc in hlx_config:
            self.device_code = hlx_config[acc].get("device_code")
            self.phone_brand_type = hlx_config[acc].get("phone_brand_type")
            logger.info(f"使用已保存的设备配置: {self.device_code}, {self.phone_brand_type}")
        else:
            self.device_code, self.phone_brand_type = generate_random_device_config()
            logger.info(f"生成新的设备配置: {self.device_code}, {self.phone_brand_type}")

        # 尝试加载本地缓存的令牌信息，防止重复登录
        session_data = load_session(acc)
        if session_data:
            logger.info("使用本地缓存的令牌信息")
            self._key = session_data['_key']
            self.userid = session_data['user_id']
            return True

        # 无有效缓存则重新登录
        data = self.psd_login(acc, psd)
        if data.get('status') == 0:
            logger.error(f"账号 {acc} 登录失败，请检查账号或密码")
            return False

        # 更新设备配置文件
        hlx_config[acc] = {
            "device_code": self.device_code,
            "phone_brand_type": self.phone_brand_type
        }
        save_hlx_config()

        self._key = data['_key']
        self.userid = data['user']['userID']

        # 保存令牌到本地，有效期可根据实际情况调整
        save_session(acc, self._key, self.userid, valid_minutes=60)
        return True

    def user_info(self):
        info_url = f'https://floor.huluxia.com/user/info/IOS/1.0?app_version={app_version}&market_id={market_id}&platform={platform}&_key={self._key}&device_code={self.device_code}&user_id={self.userid}'
        try:
            res = self.session.get(url=info_url, headers=headers)
            data = res.json()
            return data.get('nick'), data.get('level'), data.get('exp'), data.get('nextExp')
        except Exception as e:
            logger.error(f"获取用户信息失败：{e}")
            return None, None, None, None

    def check_signin(self, cat_id):
        check_url = 'https://floor.huluxia.com/user/signin/check/IOS/1.0'
        data = {
            '_key': self._key,
            'app_version': app_version,
            'cat_id': cat_id,
            'device_code': self.device_code,
            'market_id': market_id,
            'platform': platform,
            'user_id': self.userid
        }
        try:
            res = self.session.post(url=check_url, data=data, headers=headers)
            return res.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"签到检测失败：{e}")
            return {"status": 0}

    def signin(self, cat_id):
        signin_url = 'https://floor.huluxia.com/user/signin/IOS/1.1'
        data = {
            '_key': self._key,
            'app_version': app_version,
            'cat_id': cat_id,
            'device_code': self.device_code,
            'market_id': market_id,
            'platform': platform,
            'user_id': self.userid
        }
        try:
            res = self.session.post(url=signin_url, data=data, headers=headers)
            return res.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"签到失败：{e}")
            return {"status": 0}

    def huluxia_signin(self, acc, psd):
        if not self.set_config(acc, psd):
            return f"账号 {acc} 登录失败，请检查账号或密码\n"

        nick, level, exp, next_exp = self.user_info()
        if not nick:
            return f"用户信息获取失败，跳过账号 {acc}\n"
        
        logger.info(f"正在为用户 {nick} 签到，等级: Lv.{level}, 当前经验值: {exp}/{next_exp}")
        summary = f"用户 <{nick}> 签到中...\n等级: Lv.{level}\n当前经验值: {exp}/{next_exp}\n"
        exp_get = 0

        # 对每个版块签到均加入随机延时，降低请求频率，防止风控检测
        for cat_id, cat_name in cat_id_dict.items():
            check_result = self.check_signin(cat_id)
            if check_result.get('status') == 1:
                if check_result.get('signin') == 0:
                    logger.info(f"版块 {cat_name} 未签到，正在签到...")
                    signin_result = self.signin(cat_id)
                    if signin_result.get('status') == 1:
                        exp_val = signin_result.get('experienceVal', 0)
                        exp_get += exp_val
                        logger.info(f"版块 {cat_name} 签到成功，获得经验值: {exp_val}")
                    else:
                        logger.error(f"版块 {cat_name} 签到失败")
                else:
                    logger.info(f"版块 {cat_name} 今日已签到")
            else:
                logger.error(f"版块 {cat_name} 签到检测失败")
            # 每个版块之间随机等待1~3秒
            time.sleep(random.uniform(1, 3))

        summary += f"本次签到共获得经验值: {exp_get}\n"
        return summary

# ------------------------------
# 主函数
# ------------------------------
if __name__ == "__main__":
    summary_all = ""
    # 对于多账号，每个账号之间也加上随机等待时间，降低服务器风控风险
    for acc, psd in accounts:
        signin = HuluxiaSignin()
        summary = signin.huluxia_signin(acc, psd)
        summary_all += summary + "\n"
        # 每个账号之间随机等待5~10秒
        time.sleep(random.uniform(5, 10))
    email_push("葫芦侠签到报告", summary_all)
