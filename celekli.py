#!/usr/bin/env python3
"""
浙江大学本科教务网（zdbk.zju.edu.cn）命令行访问工具

功能：获取主修成绩、全部成绩、课表、考试安排、实践分
依赖：requests, tkinter, Pillow（验证码弹窗需要）
使用示例：
    python zdbk_cli.py --username 学号 --password 密码 major
    python zdbk_cli.py --username 学号 --password 密码 --format json all
    python zdbk_cli.py --username 学号 --password 密码 timetable --year 2025 --semester 1
"""

import argparse
import json
import re
import sys
import time
import random
from typing import Dict, List, Any, Optional, Tuple, Literal

import requests

# 尝试导入 tkinter 和 PIL，若失败则验证码弹窗不可用
try:
    import tkinter as tk
    from tkinter import simpledialog
    from PIL import Image, ImageTk
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

# 全局变量：存储需要具体信息的接口
unclear_interfaces = []

REFS_MAP = {
            "major": ("xk_1", "bl", "本类(专业)选课", ""),
            "general": ("xk_b", "bl", "全部课程", ""),
            "politics": ("EA", "zl", "思政类", ""),
            "politics_c": ("EA", "zl", "思政类", "必修课程"),
            "politics_e": ("EA", "zl", "思政类", "选择性必修课程"),
            "military": ("EB", "zl", "军体类", ""),
            "lang": ("F", "zl", "外语类", ""),
            "lang1": ("F", "zl", "外语类", "英语进阶课程"),
            "lang2": ("F", "zl", "外语类", "英语发展课程"),
            "lang3": ("F", "zl", "外语类", "英语高阶课程"),
            "lang4": ("F", "zl", "外语类", "英语卓越课程"),
            "lang5": ("F", "zl", "外语类", "小语种课程"),
            "computer": ("G", "zl", "计算机类", ""),
            "science": ("T", "zl", "自然科学通识类", ""),
            "electives": ("xk_n", "bl", "全部课程", ""),
            "zhct": ("zhct", "zl", "中华传统", ""),
            "sjwm": ("sjwm", "zl", "世界文明", ""),
            "ddsh": ("ddsh", "zl", "当代社会", ""),
            "kjcx": ("kjcx", "zl", "科技创新", ""),
            "smts": ("smts", "zl", "生命探索", ""),
            "byjy": ("byjy", "zl", "博雅技艺", ""),
            "elective_core": ("xhxk", "zl", "通识核心课程", ""),
            "pe": ("xk_b", "bl", "体育课程", ""),
            "major_core": ("xk_zyjck", "bl", "专业基础课程", ""),
            "major_self": ("zy_b", "bl", "本类(专业)", ""),
            "all": ("zy_qb", "bl", "所有类(专业)", ""),
            "confirmations": ("xk_rdxkc", "bl", "qbkc", ""),
            "art": ("xk_rdxkc", "zl", "美育类", ""),
            "labour": ("xk_rdxkc", "zl", "劳育类", ""),
            "creative": ("xk_rdxkc", "zl", "创新创业类", ""),
            "mental": ("xk_rdxkc", "zl", "心理类", ""),
            "international": ("gjhkc", "zl", "国际化课程", ""),
            "ckc": ("Z", "bl", "竺可桢学院课程", ""),
            "honor": ("R", "bl", "荣誉课程", ""),
            "retry": ("xk_6", "bl", "循环补充班", ""),
            "retest": ("xk_7", "bl", "补考选课", "")
        }


class ZDBKClient:
    """浙江大学本科教务网客户端，封装登录和业务接口"""

    CAS_BASE = "https://zjuam.zju.edu.cn/cas"
    ZDBK_BASE = "https://zdbk.zju.edu.cn"
    SERVICE_URL = "https://zdbk.zju.edu.cn/jwglxt/xtgl/login_ssologin.html"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://zdbk.zju.edu.cn/jwglxt/xtgl/index_initMenu.html",
        "Connection": "close",
    }
    COURSE_CATEGORY = {
        
    }
    # 其实没啥用：
    SEMESTER_MAP = {"1": "12", "2": "16"}

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.iplanet_cookie = None  # SSO cookie
        self.jsessionid = None
        self.route = None
        self.timeout_coeff = 2.5
        self.timeout_coeff_min = 1.5
        self.timeout_coeff_max = 5

    def _log(self, msg: str):
        """简单日志输出到 stderr"""
        print(f"[*] {msg}", file=sys.stderr)

    def _extract_execution(self, html: str) -> str:
        """从 CAS 登录页提取 execution 参数"""
        match = re.search(r'name="execution" value="([^"]+)"', html)
        if not match:
            raise RuntimeError("无法从登录页提取 execution 参数")
        return match.group(1)

    def _rsa_encrypt_password(self, modulus_hex: str, exponent_hex: str) -> str:
        """
        按教务网规则对密码进行 RSA 加密
        返回十六进制字符串，左补零到 128 位
        """
        modulus = int(modulus_hex, 16)
        exponent = int(exponent_hex, 16)
        # 密码 UTF-8 字节转十六进制字符串
        pwd_hex = self.password.encode('utf-8').hex()
        pwd_int = int(pwd_hex, 16)
        encrypted = pow(pwd_int, exponent, modulus)
        encrypted_hex = format(encrypted, 'x')
        # 左补零到 128 位（512 字节十六进制）
        return encrypted_hex.zfill(128)

    def login(self) -> None:
        """
        完整登录流程：
        1. CAS 获取登录页 -> execution
        2. 获取 RSA 公钥
        3. 加密密码并提交登录表单，获取 iPlanetDirectoryPro cookie
        4. 使用 SSO cookie 获取教务网 ticket
        5. 用 ticket 交换教务网 JSESSIONID 和 route
        """
        global log_level
        self._log("开始 CAS 登录...")
        time.sleep(1)
        # 步骤1：获取登录页
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        })
        resp = self.session.get(
            f"{self.CAS_BASE}/login"
        )
        if resp.status_code != 200:
            if log_level >= 1:
                self._log(resp.text)
            raise RuntimeError(f"获取登录页失败: HTTP {resp.status_code}")
        self.session.headers.update(self.HEADERS)
        execution = self._extract_execution(resp.text)

        # 步骤2：获取公钥
        resp = self.session.get(f"{self.CAS_BASE}/v2/getPubKey")
        if resp.status_code != 200:
            raise RuntimeError(f"获取公钥失败: HTTP {resp.status_code}")
        pubkey = resp.json()
        modulus = pubkey["modulus"]
        exponent = pubkey["exponent"]

        # 步骤3：加密密码并提交登录
        encrypted_pwd = self._rsa_encrypt_password(modulus, exponent)
        login_data = {
            "username": self.username,
            "password": encrypted_pwd,
            "execution": execution,
            "_eventId": "submit",
            "rememberMe": "true",
        }
        resp = self.session.post(
            f"{self.CAS_BASE}/login",
            data=login_data,
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
            allow_redirects=False
        )
        # 从响应头提取 iPlanetDirectoryPro cookie
        if "iPlanetDirectoryPro" not in resp.headers.get("Set-Cookie", ""):
            # 可能失败，尝试从响应体判断
            if "用户名或密码错误" in resp.text or "认证失败" in resp.text:
                raise RuntimeError("用户名或密码错误")
            raise RuntimeError("登录失败：未获取到 SSO Cookie")
        # 从 cookies 中提取（requests 会自动解析 Set-Cookie 到 session.cookies）
        self.iplanet_cookie = self.session.cookies.get("iPlanetDirectoryPro", domain=".zju.edu.cn")
        if not self.iplanet_cookie:
            # 可能 cookie 域不同，手动设置
            for cookie in self.session.cookies:
                if cookie.name == "iPlanetDirectoryPro":
                    self.iplanet_cookie = cookie.value
                    break
        if not self.iplanet_cookie:
            raise RuntimeError("登录失败：未找到 iPlanetDirectoryPro Cookie")
        self._log("CAS 登录成功，获取到 SSO Cookie")

        # 步骤4：获取教务网 ticket（使用独立会话，仅携带 SSO Cookie）
        service_url = self.SERVICE_URL
        # 创建新的请求，不重用 self.session，避免多余 cookie 干扰
        _cookies = {'iPlanetDirectoryPro': self.iplanet_cookie}
        _headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        tmp_session = requests.Session()
        tmp_session.headers.update(_headers)
        tmp_session.cookies.update(_cookies)
        resp = tmp_session.get(
            f"{self.CAS_BASE}/login",
            params={"service": service_url},
            allow_redirects=False
        )
        if resp.status_code != 302:
            if log_level >= 1:
                self._log(f"Unexpected response code {resp.status_code}")
                self._log(resp.text)
            raise RuntimeError("获取教务网 ticket 失败：无重定向")
        location = resp.headers.get("Location", "")
        if "ticket=" not in location:
            raise RuntimeError("重定向地址中未找到 ticket 参数")
        ticket = re.search(r'ticket=([^&]+)', location).group(1)
        self._log("获取到教务网 ticket")

        # TODO: 可能需要合并些数据……？
        if log_level >= 2:
            self._log(f"Tmp session cookies: {tmp_session.cookies}")
        self.jsessionid = tmp_session.cookies.get("JSESSIONID")
        self.route = tmp_session.cookies.get("route")

        # 步骤5：交换教务网会话 Cookie
        resp = self.session.get(location.replace("http://", "https://"), allow_redirects=False)
        if resp.status_code not in (200, 302):
            raise RuntimeError(f"交换教务网 Cookie 失败: HTTP {resp.status_code}")
        self.jsessionid = self.jsessionid or self.session.cookies.get("JSESSIONID")
        self.route = self.route or self.session.cookies.get("route")
        if log_level >= 2:
            self._log(f"session cookies: {self.session.cookies}")
        if not self.jsessionid or not self.route:
            if log_level >= 1:
                self._log(f"At least one of the followings is 'None': {self.jsessionid}, {self.route}")
            raise RuntimeError("未获取到教务网 JSESSIONID 或 route Cookie")
        self._log("教务网会话建立成功")

    def _ensure_login(self):
        """确保已登录，若会话可能过期则重新登录"""
        if not self.jsessionid or not self.route:
            self.login()

    def _request_with_auth_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        发送请求，若返回 401/403 或包含认证失败标识，则重新登录并重试一次
        """
        self._ensure_login()
        resp = self.session.request(method, url, **kwargs)
        self._log("已获取数据...")
        time.sleep(random.random() * self.timeout_coeff)
        self.timeout_coeff += random.random()
        if self.timeout_coeff >= self.timeout_coeff_max:
            self.timeout_coeff = self.timeout_coeff_min
        if resp.status_code in (401, 403) or "认证失败" in resp.text:
            self._log("会话可能过期，尝试重新登录...")
            self.login()
            resp = self.session.request(method, url, **kwargs)
        return resp

    def get_major_grades(self) -> List[Dict[str, Any]]:
        """获取主修成绩（用于计算 GPA）"""
        self._ensure_login()
        url = f"{self.ZDBK_BASE}/jwglxt/zycjtj/xszgkc_cxXsZgkcIndex.html"
        params = {"doType": "query", "queryModel.showCount": "5000"}
        resp = self._request_with_auth_retry("POST", url, params=params, data={})
        if resp.status_code != 200:
            raise RuntimeError(f"获取主修成绩失败: HTTP {resp.status_code}")
        try:
            data = resp.json()
            return data.get("items", [])
        except json.JSONDecodeError:
            raise RuntimeError("主修成绩响应不是有效 JSON")

    def get_all_grades(self) -> List[Dict[str, Any]]:
        """获取全部成绩（成绩单）"""
        self._ensure_login()
        url = f"{self.ZDBK_BASE}/jwglxt/cxdy/xscjcx_cxXscjIndex.html"
        params = {"doType": "query", "queryModel.showCount": "5000"}
        resp = self._request_with_auth_retry("POST", url, params=params, data={})
        if resp.status_code != 200:
            raise RuntimeError(f"获取全部成绩失败: HTTP {resp.status_code}")
        try:
            data = resp.json()
            return data.get("items", [])
        except json.JSONDecodeError:
            raise RuntimeError("全部成绩响应不是有效 JSON")

    def _get_captcha_image(self) -> bytes:
        """获取验证码图片二进制数据"""
        self._ensure_login()
        url = f"{self.ZDBK_BASE}/jwglxt/kaptcha"
        params = {"time": int(time.time() * 1000)}
        resp = self._request_with_auth_retry("GET", url, params=params)
        if resp.status_code != 200:
            raise RuntimeError("获取验证码图片失败")
        return resp.content

    def _prompt_captcha(self, image_bytes: bytes) -> str:
        """
        使用 tkinter 弹窗显示验证码图片并让用户输入
        若 GUI 不可用则抛出异常
        """
        if not GUI_AVAILABLE:
            raise RuntimeError("当前环境不支持 GUI，无法处理验证码（需要 tkinter 和 PIL）")
        # 创建窗口
        root = tk.Tk()
        root.title("验证码输入")
        # 将图片字节转为 PhotoImage
        from PIL import ImageTk, Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        photo = ImageTk.PhotoImage(img)
        label = tk.Label(root, image=photo)
        #label.image = photo  # 保持引用
        label.pack()
        # 输入框
        captcha_var = tk.StringVar()
        entry = tk.Entry(root, textvariable=captcha_var)
        entry.pack()
        entry.focus_set()
        # 确认按钮
        def on_ok():
            root.quit()
        button = tk.Button(root, text="确定", command=on_ok)
        button.pack()
        root.mainloop()
        captcha = captcha_var.get().strip()
        root.destroy()
        return captcha

    def get_timetable(self, year: str, semester: str, captcha: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取课表
        :param year: 学年，如 "2025"
        :param semester: 学期，如 "1" 或 "2"（映射见内部表）
        :param captcha: 验证码（若需要）
        """
        self._ensure_login()
        # 学期编码映射（若 semester 不在映射中，则属于未清楚接口）
        semester_map = self.SEMESTER_MAP  # 第一学期和第二学期（？）
        if semester not in semester_map:
            unclear_interfaces.append(f"课表接口 xqm 参数完整映射（当前仅支持 {semester_map}）")
            raise ValueError(f"未知学期编号 {semester}，请直接提供 xqm 编码")
        xqm = semester_map[semester]
        url = f"{self.ZDBK_BASE}/jwglxt/kbcx/xskbcx_cxXsKb.html"
        data = {
            "xnm": year,
            "xqm": xqm,
        }
        if captcha:
            data["captcha_value"] = captcha
        resp = self._request_with_auth_retry("POST", url, data=data)
        if resp.status_code != 200:
            raise RuntimeError(f"获取课表失败: HTTP {resp.status_code}")
        # 检查是否需要验证码
        if "captcha_error" in resp.text:
            self._log("课表接口要求验证码，获取验证码图片...")
            img_bytes = self._get_captcha_image()
            captcha_input = self._prompt_captcha(img_bytes)
            if not captcha_input:
                raise RuntimeError("验证码输入为空")
            return self.get_timetable(year, semester, captcha=captcha_input)
        try:
            data = resp.json()
            return data.get("kbList", [])
        except json.JSONDecodeError:
            raise RuntimeError("课表响应不是有效 JSON")

    def get_exams(self) -> List[Dict[str, Any]]:
        """获取考试安排"""
        self._ensure_login()
        url = f"{self.ZDBK_BASE}/jwglxt/xskscx/kscx_cxXsgrksIndex.html"
        params = {"doType": "query", "queryModel.showCount": "5000"}
        resp = self._request_with_auth_retry("POST", url, params=params, data={})
        if resp.status_code != 200:
            raise RuntimeError(f"获取考试安排失败: HTTP {resp.status_code}")
        try:
            data = resp.json()
            return data.get("items", [])
        except json.JSONDecodeError:
            raise RuntimeError("考试安排响应不是有效 JSON")

    def get_practice_scores(self) -> Dict[str, str]:
        """
        获取实践分（第二、三、四课堂）
        返回字典，键为课堂名称，值为分数字符串
        """
        self._ensure_login()
        url = f"{self.ZDBK_BASE}/jwglxt/dessktgl/dessktcx_cxDessktcxIndex.html"
        params = {
            "gnmkdm": "N108001",
            "layout": "default",
            "su": self.username,
        }
        headers = {"Accept": "text/html, */*; q=0.01"}
        resp = self._request_with_auth_retry("GET", url, params=params, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"获取实践分失败: HTTP {resp.status_code}")
        html = resp.text
        # 解析 HTML 表格
        scores = {}
        # 首选正则：<td>第二课堂</td><td>分数</td>
        pattern1 = re.compile(r'<td[^>]*>\s*(第二课堂|第三课堂|第四课堂)\s*</td>\s*<td[^>]*>\s*([^<]*?)\s*</td>', re.IGNORECASE)
        matches = pattern1.findall(html)
        if matches:
            for name, score in matches:
                scores[name] = score.strip()
        else:
            # 后备正则：可能结构不同
            pattern2 = re.compile(r'(第二课堂|第三课堂|第四课堂)\s*</td>\s*<td[^>]*>\s*([^<]*?)\s*</td>', re.IGNORECASE)
            matches = pattern2.findall(html)
            if matches:
                for name, score in matches:
                    scores[name] = score.strip()
            else:
                unclear_interfaces.append("实践分页面 HTML 解析规则（当前正则可能无法匹配实际结构）")
                # 占位：返回空字典
                scores = {}
        return scores

    # Manually written
    def _request_json(self, method: Literal['GET', 'POST'], url: str, params: dict[str, str], data: dict[str, str]) -> Any:
        resp = self._request_with_auth_retry(method, url, params=params, data=data)
        if resp.status_code != 200:
            raise RuntimeError(f"JSON 获取失败：{url} 返回 {resp.status_code} 状态码")
        try:
            return resp.json()
        except requests.exceptions.JSONDecodeError:
            if log_level >= 1:
                self._log(resp.text)
            raise RuntimeError(f"JSON 获取失败：{url} 未返回合法数据")

    # ---------- 选课相关接口 ----------

    def get_selected_courses(self, xn: str, xq: str) -> List[dict]:
        """
        获取当前已选课程
        :param xn: 学年（如 "2026-2027"）
        :param xq: 学期（如 "1"）
        """
        path = f"{self.ZDBK_BASE}/jwglxt/xsxk/zzxkghb_cxZzxkGhbChoosed.html"
        params = {
            "gnmkdm": "N253530",
            "su": self.username,
        }
        data = {
            "xn": xn,
            "xq": xq,
        }
        resp = self._request_json("POST", path, params=params, data=data)
        return resp if isinstance(resp, list) else resp.get("items", [])

    def get_available_courses(self, xn: str, xq: str, nj: str, zydm: str,
                              dl: str, lx: str = "",
                              xkmc: str = "", kcbs: str = "",
                              page_size: int = 10) -> List[dict]:
        """
        获取可选课程（自动分页获取全部）
        :param xn: 学年（如 "2026-2027"）
        :param xq: 学期（如 "1"）
        :param nj: 年级（如 "2026"）
        :param zydm: 专业代码（如 "2211"）
        :param dl: 课程分类标识
        :param lx: 课程分类表示
        :param xkmc: 学科名称
        :param kcbs: 课程标识
        :param page_size: 每页请求课程数
        """
        path = f"{self.ZDBK_BASE}/jwglxt/xsxk/zzxkghb_cxZzxkGhbKcList.html"
        params = {
            "gnmkdm": "N253530",
            "su": self.username,
        }
        jxjhh = nj + zydm
        xnxq = f"({xn}-{xq})-"
        all_courses = []
        kspage = 1
        while True:
            jspage = kspage + page_size - 1
            data = {
                "dl": dl,
                "nj": nj,
                "xn": xn,
                "xq": xq,
                "zydm": zydm,
                "jxjhh": jxjhh,
                "xnxq": xnxq,
                "kspage": str(kspage),
                "jspage": str(jspage),
            }
            if lx:
                data["lx"] = lx
            if xkmc:
                data["xkmc"] = xkmc
            if kcbs:
                data["kcbs"] = kcbs
            resp = self._request_json("POST", path, params=params, data=data)
            courses = resp if isinstance(resp, list) else resp.get("items", [])
            if not courses:
                break
            all_courses.extend(courses)
            if len(courses) < page_size:
                break
            kspage += page_size
        return all_courses

    def get_teaching_classes(self, xn: str, xq: str, dl: str,
                             kcdm: str, xkkh: str) -> List[dict]:
        """
        获取指定课程的教学班列表
        :param xn: 学年（如 "2026-2027"）
        :param xq: 学期（如 "1"）
        :param dl: 课程分类标识（与获取可选课程时一致）
        :param kcdm: 课程代码
        :param xkkh: 内部查询字符串（必须来自可选课程接口）
        """
        path = f"{self.ZDBK_BASE}/jwglxt/xsxk/zzxkghb_cxZzxkGhbJxbList.html"
        params = {
            "gnmkdm": "N253530",
            "su": self.username,
        }
        data = {
            "dl": dl,
            "xn": xn,
            "xq": xq,
            "kcdm": kcdm,
            "xkkh": xkkh,
            "ylxs": "0",
        }
        if log_level >= 2:
            self._log(f"Requested data {data}")
        resp = self._request_json("POST", path, params=params, data=data)
        return resp if isinstance(resp, list) else resp.get("items", [])

    def get_available_courses_full(self, xn: str, xq: str, nj: str, zydm: str,
                                  dl: str, lx: str = "",
                                  xkmc: str = "", kcbs: str = "",
                                  page_size: int = 10) -> List[dict]:
        """
        Simultaneously get courses and classes.
        """

        result: list[dict[str, Any]] = self.get_available_courses(xn, xq, nj, zydm, dl, lx, xkmc, kcbs, page_size)
        #return list(map(fetch_classes, result))
        finals = []
        for idx, x in enumerate(result):
            self._log(f"已获取教学班：{idx}/{len(result)}")
            classes = self.get_teaching_classes(xn, xq, dl, x.get("kcdm", ""), "-".join(x.get("xkkh", "").split("-")[:4]))
            for i in classes:
                finals.append({**x, **i})
        return finals



def format_table(data: List[Dict[str, Any]], headers: List[str]) -> str:
    """
    将字典列表格式化为 TAB 分隔的表格字符串
    :param data: 数据列表
    :param headers: 表头列表（键名）
    :return: 表格字符串
    """
    if not data:
        return "（无数据）"
    lines = []
    # 表头
    lines.append("\t".join(headers))
    # 数据行
    for item in data:
        row = [str(item.get(h, "")) for h in headers]
        lines.append("\t".join(row))
    return "\n".join(lines)

def print_result(result):
    if isinstance(result, list):
        if result:
            # 自动选择常见表头（可根据实际字段调整）
            # 这里简化处理，使用第一个元素的所有键
            # TODO: 增加表头描述，如果可用
            headers = list(result[0].keys())
            print(format_table(result, headers))
        else:
            print("（无数据）")
    elif isinstance(result, dict):
        # 对于实践分这种字典，直接输出键值对
        for k, v in result.items():
            print(f"{k}\t{v}")
    else:
        print(result)

def main():
    global log_level

    def work():
        nonlocal args, client
        type1, type2, subject, lesson = '', '', '', ''
        if args.command == "lessons":
            if hasattr(args, 'type') and getattr(args, 'type'):
                type1, type2, subject, lesson = REFS_MAP[args.type]
            else:
                type1, type2, subject, lesson = args.type1, args.type2, args.subject, args.lesson
        COMMAND_MAP = {
            "major": client.get_major_grades,
            "all": client.get_all_grades,
            "timetable": lambda: client.get_timetable(args.year, args.semester),
            "exams": client.get_exams,
            "practice": client.get_practice_scores,
            "selected": lambda: client.get_selected_courses(args.year, args.semester),
            "lessons": lambda: (client.get_available_courses_full if args.partial else client.get_available_courses)(
                args.year, args.semester, args.grade, args.major, type1, type2, subject, lesson
            )
        }
        return COMMAND_MAP[args.command]()

    parser = argparse.ArgumentParser(description="浙江大学本科教务网命令行访问工具")
    parser.add_argument("-u", "--username", required=True, help="学号/工号")
    parser.add_argument("-p", "--password", required=True, help="密码")
    parser.add_argument("-f", "--format", choices=["table", "json"], default="table",
                        help="输出格式：table（TAB表格）或 json（默认：table）")
    parser.add_argument("--log-level", type = int, default="0", help="日志输出等级")
    subparsers = parser.add_subparsers(dest="command", required=True, help="子命令")

    # 子命令：获取主修成绩
    subparsers.add_parser("major", help="获取主修成绩")

    # 子命令：获取全部成绩
    subparsers.add_parser("all", help="获取全部成绩")

    # 子命令：获取课表（需要学年和学期）
    timetable_parser = subparsers.add_parser("timetable", help="获取课表")
    timetable_parser.add_argument("-y", "--year", required=True, help="学年，如 2025-2026")
    timetable_parser.add_argument("-s", "--semester", choices=["1", "2"], default="1",
                                  help="学期编号")
    # This is not really working...

    # 子命令：获取考试安排
    subparsers.add_parser("exams", help="获取考试安排")

    # 子命令：获取实践分
    subparsers.add_parser("practice", help="获取实践分")

    # TODO: 添加选课子命令！
    lessons_parser = subparsers.add_parser("selected", help="获取已选课程")
    lessons_parser.add_argument("-y", "--year", required=True, help="学年，如 2025-2026")
    lessons_parser.add_argument("-s", "--semester", choices=["1", "2"], default="1",
                                      help="学期编号")

    elective_parser = subparsers.add_parser("lessons", help="获取可选课程")
    elective_parser.add_argument("-y", "--year", required=True, help="学年，如 2025-2026")
    elective_parser.add_argument("-s", "--semester", choices=["1", "2"], default="1",
                                          help="学期编号")
    elective_parser.add_argument("-g", "--grade", required=True, help="年级，如 2026")
    elective_parser.add_argument("-m", "--major", required=True, help="专业代码（数字）")
    elective_parser.add_argument("-t", "--type", default="", help="选择课程类型", choices=list(REFS_MAP)+[''])
    elective_parser.add_argument("--type1", "-t1", default="", help="课程分类标识 1")
    elective_parser.add_argument("--type2", "-t2", default="", help="课程分类标识 2")
    elective_parser.add_argument("--subject", default="", help="学科名称")
    elective_parser.add_argument("--lesson", default="", help="课程标识")
    elective_parser.add_argument("--partial", action='store_false', help="不获取所有教学班")


    args = parser.parse_args()
    log_level = int(args.log_level)

    client = ZDBKClient(args.username, args.password)

    try:
        client.login()
    except Exception as e:
        print(f"登录失败: {e}", file=sys.stderr)
        sys.exit(1)

    result = None
    if log_level >= 100:
        work()
    else:
        try:
            result = work()
        except Exception as e:
            print(f"获取数据失败: {e}", file=sys.stderr)
            sys.exit(1)

    # 输出结果
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_result(result)

    # 输出需要具体信息的接口
    if unclear_interfaces:
        print("\n[!] 以下接口可能未完善：", file=sys.stderr)
        for item in unclear_interfaces:
            print(f"  - {item}", file=sys.stderr)


if __name__ == "__main__":
    main()