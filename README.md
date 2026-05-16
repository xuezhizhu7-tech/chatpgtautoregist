# GPT Auto Registry 使用说明

这是一个 Python 自动化项目，分为两个主要阶段：

- 第一阶段：通过手机号和短信验证码完成账号注册流程。
- 第二阶段：读取已注册账号，通过 OAuth 流程导入到 Sub2API。
- 可选监控：监控短信号码库存，有库存时自动启动批次任务。

请只在你有权限操作的账号、服务和基础设施中使用。密钥、账号记录、日志文件都应该只保存在本地，不要提交到 git。

## 目录结构

```text
step_01_config/      公共配置，以及本地密钥读取逻辑
step_02_shared/      浏览器 CDP 工具、日志和记录工具
step_03_clients/     HeroSMS、邮箱、Sub2API 客户端
step_04_register/    第一阶段：手机号注册入口
step_05_import/      第二阶段：OAuth 导入入口
step_06_monitor/     短信库存监控和批量任务入口
```

## 环境要求

- Python 3.10 或更高版本
- `curl`
- Chromium/Chrome
- Python 依赖：`websockets`
- 可访问你配置的 HeroSMS、邮箱服务、Sub2API 服务
- 当前浏览器启动逻辑更偏向 Linux/Xvfb 环境，见 `step_02_shared/browser_cdp.py`

安装 Python 依赖：

```bash
python -m pip install websockets
```

如果在 Windows 上运行，需要保证环境里有 `bash`、`DISPLAY=:99`、以及脚本中指定路径的 Chromium。否则需要按你的本机环境调整 `step_02_shared/browser_cdp.py` 里的浏览器启动命令。

## 配置密钥

密钥可以通过环境变量提供，也可以写到本地文件：

```text
step_01_config/local_secrets.py
```

这个文件已经加入 `.gitignore`，不要提交。

示例：

```python
HEROSMS_KEY = "你的 HeroSMS API Key"

SUB2API = "http://localhost:8080"
SUB2API_EMAIL = "你的 Sub2API 管理员邮箱"
SUB2API_PASS = "你的 Sub2API 密码"

CLOUD_MAIL_URL = "https://mail.example.com"
CLOUD_MAIL_EMAIL = "你的邮箱服务账号"
CLOUD_MAIL_PASS = "你的邮箱服务密码"
EMAIL_DOMAIN = "example.com"

DEFAULT_PASSWORD = "注册账号时使用的默认密码"
ACCOUNTS_LOG = "/home/ubuntu/chatgpt-accounts-new.jsonl"
```

必须配置：

```text
HEROSMS_KEY
SUB2API_EMAIL
SUB2API_PASS
CLOUD_MAIL_EMAIL
CLOUD_MAIL_PASS
EMAIL_DOMAIN
```

常用可选配置：

```text
HEROSMS=https://hero-sms.com/stubs/handler_api.php
HEROSMS_SERVICE=dr
HEROSMS_MAX_PRICE=0.03
CDP_PORT=9336
PROXY_PORT=7892
SUB2API=http://localhost:8080
DEFAULT_PASSWORD=
ACCOUNTS_LOG=/home/ubuntu/chatgpt-accounts-new.jsonl
LOG_DIR=~/auto_batch_logs
STATE_FILE=~/auto_batch_state.json
BATCH_SIZE=5
MAX_PER_PROXY=10
```

## 运行前检查

确认配置能正常加载：

```bash
python -c "import step_01_config.config as c; print('config ok')"
```

如果要运行导入阶段，确认 Sub2API 可以访问：

```bash
curl -sS http://localhost:8080
```

确认浏览器 CDP 端口可用。默认端口是 `9336`，脚本会通过下面的地址连接浏览器：

```text
http://127.0.0.1:9336/json/list
```

确认 `ACCOUNTS_LOG` 指向一个私有路径。这个文件会保存账号流程记录，其中手机号和密码字段只是 base64 编码，不是加密。

## 第一阶段：注册账号

注册 1 个账号：

```bash
python step_04_register/register.py 1
```

注册多个账号：

```bash
python step_04_register/register.py 5
```

临时指定国家：

```bash
python step_04_register/register.py 2 --country 151 --dial 56 --iso CL
```

不使用代理：

```bash
python step_04_register/register.py 1 --no-proxy
```

成功注册后，会往 `ACCOUNTS_LOG` 追加记录，通常包含：

```text
phase: 1
status: registered
```

## 第二阶段：OAuth 导入

导入 `ACCOUNTS_LOG` 中所有未导入的账号：

```bash
python step_05_import/oauth_import.py
```

最多导入 5 个：

```bash
python step_05_import/oauth_import.py --count 5
```

指定账号记录文件：

```bash
python step_05_import/oauth_import.py --file /path/to/accounts.jsonl --count 1
```

成功导入后，会追加第二阶段记录：

```text
phase: 2
status: imported
```

失败时会记录更具体的状态，例如：

```text
email_otp_failed
exchange_failed
oauth_failed
```

## 可选：库存监控和批量任务

启动监控：

```bash
python step_06_monitor/auto_batch_monitor.py
```

监控脚本会：

- 检查 HeroSMS 库存和价格
- 有库存时启动注册批次
- 根据配置轮换代理
- 把批次日志写入 `LOG_DIR`
- 把监控状态写入 `STATE_FILE`

代理配置在 `step_01_config/config.py`：

```python
PROXIES = [
    {"name": "direct", "mihomo": None},
    {"name": "jp-residential", "mihomo": "jp-residential"},
    {"name": "us99-ss", "mihomo": "us99-ss"},
    {"name": "kkyun-ss", "mihomo": "kkyun-ss"},
]
```

使用前请把代理名称改成你本机 Mihomo 里的实际节点名称。

## 输出文件

常见输出文件：

```text
ACCOUNTS_LOG              账号流程记录，JSONL 格式
LOG_DIR/batch_*.log       监控脚本生成的批次日志
STATE_FILE                监控脚本状态文件
```

这些文件可能包含手机号、密码、邮箱、token、接口返回信息或运行细节，请不要提交。

## Git 安全注意事项

当前已忽略：

```text
.env
step_01_config/local_secrets.py
__pycache__/
*.pyc
```

提交前先检查：

```bash
git status --short
git diff --cached --stat
```

不要提交这些内容：

```text
step_01_config/local_secrets.py
.env
*.jsonl 账号记录
批次日志
状态文件
本地工具或缓存目录
```

## 常见问题

`Missing required secret`

缺少必填密钥。把提示中的变量加到 `step_01_config/local_secrets.py`，或者设置到环境变量。

`Accounts file not found`

账号记录文件不存在。检查 `ACCOUNTS_LOG`，或者运行 `oauth_import.py` 时用 `--file` 指定文件。

浏览器或 CDP 连接失败

检查 Chromium 是否启动成功，`CDP_PORT` 是否被占用，以及下面地址是否能返回页面目标：

```text
http://127.0.0.1:9336/json/list
```

短信没有库存

检查 `HEROSMS_SERVICE`、`HEROSMS_MAX_PRICE`、国家 ID、HeroSMS 余额和供应商库存。

邮箱验证码超时

检查 Cloud Mail 配置、`EMAIL_DOMAIN`、邮箱是否创建成功，以及验证码邮件是否能正常收到。

Sub2API 导入失败

检查 Sub2API 地址、管理员账号密码、回调地址和接口返回日志。
