# 双账号签到部署

工作流调用 `main.py`，两个账号在独立任务中运行。一个账号失败不会取消另一个账号的任务；缺少 Cookie 或认证失败会使对应任务报错。

| 配置 | 账号 1 | 账号 2 |
| --- | --- | --- |
| Repository Secret | 原有 `GLADOS_COOKIE`，兼容 `GLADOS_COOKIES` | `GLADOS_COOKIE_2` |
| 可选 Repository Variable：登录域名 | `GLADOS_BASE_URL` | `GLADOS_BASE_URL_2` |
| 未设置域名时的默认值 | `https://glados.cloud` | `https://glados-facility.com` |
| 可选 Repository Variable：浏览器 UA | `GLADOS_USER_AGENT` | `GLADOS_USER_AGENT_2` |

## 保存第二个账号的 Cookie

1. 在浏览器登录第二个 GLaDOS 账号，确认使用 `https://glados-facility.com`。
2. 按 F12，进入 Network，刷新页面，选择 `/api/user/status` 请求，在 Request Headers 中复制整行 Cookie 的值。
3. 打开仓库 Settings → Secrets and variables → Actions → New repository secret，名称填 `GLADOS_COOKIE_2`，值填第二个账号的 Cookie，保存。
4. 打开 Actions → GLaDOS Checkin → Run workflow，选择 `master` 后运行。
5. 确认 `Account 1`、`Account 2` 都通过，并分别查看结果摘要。缺少第二个 Cookie 时，`Account 2` 会失败，表示尚未配置完成。

不要覆盖第一个账号的 Secret，不要使用旧 README 中以 `&` 拼接多个 Cookie 的方法；当前工作流每个账号读取独立 Secret。不要把 Cookie 提交到代码、Issue、日志或聊天。

定时计划保持为北京时间每日 09:23、15:23、21:23；GitHub 定时任务可能延迟。电脑关闭后仍由 GitHub 执行。

程序只签到和查询状态、积分，不自动兑换积分。
