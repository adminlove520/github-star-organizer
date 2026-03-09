# GitHub Actions 部署指南

## 1. Fork 项目

把 `github-star-organizer` fork 到你的 GitHub 账号

## 2. 添加 Secrets

在 forked 仓库的 Settings → Secrets and variables → Actions 中添加：

| Secret | 说明 | 示例 |
|--------|------|------|
| `GITHUB_USERNAME` | 你的 GitHub 用户名 | `adminlove520` |
| `GITHUB_TOKEN` | GitHub Personal Access Token | `ghp_xxx` |
| `GITHUB_COOKIES` | 浏览器 cookie 字符串 | `_octo=...; user_session=...` |
| `LLM_BASE_URL` | LLM API 端点 | `https://api.openai.com/v1` |
| `LLM_API_KEY` | LLM API Key | `sk-xxx` |
| `LLM_MODEL` | 模型名 | `gpt-4o` |

## 3. 获取 GitHub Token

1. Settings → Developer settings → Personal access tokens → Tokens (classic)
2. 生成新 token，勾选 `repo` 权限

## 4. 获取 Cookie

1. 登录 GitHub
2. F12 打开 DevTools
3. Network → 任意 github.com 请求 → Headers → Cookie
4. 复制完整 cookie 字符串

## 5. 运行 Workflow

- **手动**: GitHub 仓库 → Actions → Organize GitHub Stars → Run workflow
- **自动**: 每周日 18:00 自动运行

## 6. 使用其他 LLM

如果想用 MiniMax（需要 API 代理或 VPN）：

```toml
[llm]
base_url = "http://your-proxy.com/v1"  # 代理地址
api_key = "sk-xxx"
model = "gpt-4o"
```

或者用 OpenAI API（香港/新加坡节点）：
```toml
base_url = "https://api.openai.com/v1"
```
