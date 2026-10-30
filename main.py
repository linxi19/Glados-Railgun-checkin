"""GLaDOS daily check-in. Python 3.12+, standard library only."""

import json
import math
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ALLOWED_HOSTS = {"glados.cloud", "glados.rocks", "railgun.info", "glados-facility.com"}
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class CheckinError(Exception):
    """A safe, human-readable error without response bodies or credentials."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the authentication Cookie to a redirected destination.
        return None


def read_config():
    cookie = (os.getenv("GLADOS_COOKIE") or os.getenv("GLADOS_COOKIES") or "").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    if not cookie:
        raise CheckinError("缺少 GLADOS_COOKIE（也兼容原有 GLADOS_COOKIES）Secret。")
    if "\r" in cookie or "\n" in cookie or cookie.count("koa:sess=") > 1:
        raise CheckinError("Cookie 格式错误；请填写一个账号的一行 Cookie 值。")

    base = (os.getenv("GLADOS_BASE_URL") or "https://glados.cloud").strip().rstrip("/")
    url = urlsplit(base)
    if (
        url.scheme != "https"
        or url.netloc not in ALLOWED_HOSTS
        or url.path
        or url.query
        or url.fragment
    ):
        raise CheckinError("GLADOS_BASE_URL 必须是支持的 GLaDOS HTTPS 域名（含 glados-facility.com）。")
    ua = (os.getenv("GLADOS_USER_AGENT") or DEFAULT_UA).strip()
    if not ua or "\r" in ua or "\n" in ua:
        raise CheckinError("GLADOS_USER_AGENT 必须是一行浏览器 User-Agent。")
    return cookie, base, ua


def api_request(opener, base, headers, path, method="GET"):
    body = urlencode({"token": urlsplit(base).hostname}).encode() if method == "POST" else None
    request = Request(base + path, data=body, headers=headers, method=method)
    for attempt in range(3):
        try:
            with opener.open(request, timeout=25) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise CheckinError("接口响应过大，无法确认结果。")
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                raise CheckinError("接口没有返回有效 JSON，可能是登录页或人机验证页；请在浏览器检查。") from None
            if not isinstance(data, dict) or type(data.get("code")) is not int:
                raise CheckinError("接口返回格式改变或缺少整数 code，无法确认结果。")
            if data["code"] == -2:
                raise CheckinError("接口返回 -2：没有权限。请检查账号状态、登录域名及 Cookie，并更新 Secret。")
            return data
        except HTTPError as error:
            status = error.code
            error.close()
            if status in (401, 403):
                raise CheckinError(f"HTTP {status}：认证或访问受限，请在浏览器检查登录状态及验证页面。") from None
            if 300 <= status < 400:
                raise CheckinError("接口发生重定向，已停止发送 Cookie；请核对实际登录域名。") from None
            if status != 429 and not 500 <= status < 600:
                raise CheckinError(f"HTTP {status}：接口请求失败。") from None
            failure = f"HTTP {status}"
        except (URLError, TimeoutError, socket.timeout, OSError):
            failure = "网络连接失败或超时"
        if attempt == 2:
            raise CheckinError(f"{failure}，重试三次仍失败。")
        print(f"[重试] {failure}；准备第 {attempt + 2}/3 次请求。")
        time.sleep(2 ** (attempt + 1))


def numeric(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise CheckinError(f"{label}字段缺失或格式异常。")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise CheckinError(f"{label}字段无法解析。") from None
    if not math.isfinite(number):
        raise CheckinError(f"{label}字段不是有限数字。")
    return f"{number:g}"


def run_checkin():
    cookie, base, ua = read_config()
    headers = {
        "Cookie": cookie,
        "User-Agent": ua,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": base,
        "Referer": base + "/console/checkin",
    }
    opener = build_opener(NoRedirect())
    print(f"[开始] 使用 {base}；仅输出结果，不输出 Cookie 或邮箱。")
    checkin = api_request(opener, base, headers, "/api/user/checkin", "POST")
    if checkin["code"] not in (0, 1):
        if checkin["code"] == 4:
            raise CheckinError("签到返回 code=4，可能是登录设备不匹配；请设置与登录浏览器一致的 GLADOS_USER_AGENT。")
        raise CheckinError(f"签到未成功：code={checkin['code']}。请在网页检查，不能按成功处理。")

    result = "接口确认签到成功（code=0）" if checkin["code"] == 0 else "接口报告今日已签到（code=1）"
    lines = [result]
    print(f"[签到] {result}")
    try:
        status = api_request(opener, base, headers, "/api/user/status")
        if status["code"] != 0 or not isinstance(status.get("data"), dict):
            raise CheckinError("账号状态接口未返回有效的成功结果。")
        lines.append("剩余天数：" + numeric(status["data"].get("leftDays"), "剩余天数"))
    except CheckinError as error:
        raise CheckinError(f"{result}，但账号状态复核失败：{error}") from None

    # Points are supplementary: a failed points query must never be shown as 0.
    try:
        points = api_request(opener, base, headers, "/api/user/points")
        if points["code"] != 0:
            raise CheckinError(f"积分查询未成功：code={points['code']}。")
        balance = numeric(points.get("points"), "积分余额")
        lines.append("积分余额：" + balance)
    except CheckinError as error:
        lines.append("积分余额：未能获取（不代表余额为零）")
        print(f"::warning::{error}")
    return lines


def write_summary(lines):
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S 北京时间")
    text = "\n".join(["## GLaDOS 签到结果", "", stamp, ""] + ["- " + line for line in lines]) + "\n"
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with Path(summary).open("a", encoding="utf-8") as output:
                output.write(text)
        except OSError:
            print("::warning::无法写入运行摘要，请查看上面的执行日志。")


def main():
    try:
        lines = run_checkin()
    except CheckinError as error:
        message = str(error)
        print(f"::error::{message}")
        write_summary(["失败 / 结果未能完整确认", message])
        return 1
    except Exception:
        # Do not print raw exceptions: third-party responses can contain secrets.
        print("::error::发生未预期错误，未按成功处理；请检查配置及接口变化。")
        write_summary(["失败：发生未预期错误，未按成功处理。"])
        return 1
    for line in lines[1:]:
        print("[结果] " + line)
    write_summary(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
