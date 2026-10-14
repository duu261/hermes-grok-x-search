# Hermes Grok X Search

[English](README.md) | [Tiếng Việt](README.vi.md) | 简体中文

> 本译文可能落后于英文版。如有出入，以 [README.md](README.md) 为准。

一个独立的 Hermes Agent 插件，通过运维方配置的兼容 Responses 的网关，将 xAI 的服务端 X Search 以单个面向模型的工具 `grok_x_search` 提供出来。

```text
Hermes model
  -> grok_x_search
  -> gateway /v1/responses
  -> xAI x_search
  -> answer and X citations
```

Hermes 保存一个网关凭据。上游认证、路由和限额由网关负责。

## 范围

0.1 版只提供 X Search：

- 检索 X 上公开的帖子、个人资料和讨论串
- 允许或排除指定账号（handle）的过滤
- 日期过滤
- 理解匹配帖子中的图片
- 理解匹配帖子中的视频
- 提取引用并检测降级结果

它不提供通用网页搜索、在 X 上发帖或点赞、代码执行、文件搜索、MCP、任意函数调用，也不是通用的 Responses API 客户端。

## 安装

```bash
hermes plugins install https://github.com/duu261/hermes-grok-x-search.git --enable
```

重启需要加载该插件的 Hermes 界面。gateway 的重启仍由运维方执行。

## 配置

将网关 API 密钥保存在 Hermes 的私有环境文件中：

```text
GROK_X_SEARCH_API_KEY=replace-me
```

通过 Hermes 配置设置非机密的行为参数：

```bash
hermes config set grok_x_search.base_url https://gateway.example/v1
hermes config set grok_x_search.model grok-4.6
```

可选设置：

```yaml
grok_x_search:
  base_url: https://gateway.example/v1
  model: grok-4.6
  reasoning_effort: null
  timeout_seconds: 180
  retries: 1
  retry_base_seconds: 1.5
  max_retry_after_seconds: 30
  max_response_bytes: 4194304
```

远程端点必须使用 HTTPS。明文 HTTP 只接受 `localhost`、`127.0.0.1` 或 `::1` 上的开发端点。除非配置的 URL 已以 `/responses` 结尾，插件会自动追加 `/responses`。

## 工具输入

`grok_x_search` 接受：

- `query` - 必填，检索请求
- `allowed_x_handles` - 仅包含最多 10 个账号
- `excluded_x_handles` - 排除最多 10 个账号
- `from_date` - 可选，起始日期 `YYYY-MM-DD`
- `to_date` - 可选，结束日期 `YYYY-MM-DD`
- `enable_image_understanding` - 分析匹配帖子附带的图片
- `enable_video_understanding` - 分析匹配帖子附带的视频

允许账号和排除账号不能同时使用。

## 结果

成功调用返回的 JSON 包含：

```json
{
  "success": true,
  "provider": "grok-responses",
  "credential_source": "gateway",
  "tool": "grok_x_search",
  "model": "grok-4.6",
  "answer": "...",
  "citations": [],
  "inline_citations": [],
  "degraded": false,
  "degraded_reason": null
}
```

该结果有意与 Hermes 原生 `x_search` 保持一致。当 `degraded` 为 false，且 `citations` 或 `inline_citations` 中包含有效的 X 帖子 URL 时，可视为有引用支撑。网关内部的输出类型不会暴露，因为它们属于传输诊断信息，而不是 grounding 状态。

只保留 `x.com` 或 `twitter.com` 上的 HTTPS 引用 URL。userinfo、非标准端口和无关主机都会被丢弃。

与 Hermes 原生 `x_search` 一样，带过滤条件但没有引用的 HTTP 200 回答会以 `degraded: true` 返回。请将其视为无来源的模型综合内容，而不是 X Search 已运行的证据。不带过滤条件的回答遵循原生行为，不会仅因缺少引用而被标记为降级。如果返回的引用或回答文本中的规范 X URL 指向的作者与 `allowed_x_handles` 或 `excluded_x_handles` 冲突，插件会直接拒绝（fail closed），返回 `error_type: "filter_violation"`。

## 信任边界

本插件将请求发送到配置的网关。网关运营方控制上游账号、认证、路由、日志、保留期限、计费、请求改写和可用性。安装本插件不会授予 xAI 使用资格，也不会绕过提供方的管控。

域名和账号过滤会约束所请求的搜索，但不是安全边界。在获取或依据返回的 URL 采取行动之前，请先核实它们。

插件拒绝重定向，限制响应体大小和重试等待时间，并返回经过清理的错误类别，而不是上游的原始响应体。

规范化后的工具结果上限为 100,000 个字符，与 Hermes 原生工具结果上限一致。没有 `status` 的上游响应会被接受，而明确为非 `completed` 的状态会被拒绝。过滤约束会在请求指令中再次强调，并对返回结果中可识别的 X URL 进行检查。

## 开发

```bash
python -m unittest discover -s tests -v
python -m py_compile provider.py __init__.py tests/test_provider.py tests/test_live.py tests/test_hermes_e2e.py tests/hermes_e2e_runner.py
hermes plugins doctor . --ci
git diff --check
```

带认证的线上测试：

```bash
GROK_X_SEARCH_LIVE_TESTS=1 \
GROK_X_SEARCH_LIVE_BASE_URL=https://gateway.example/v1 \
python -m unittest tests.test_live -v
```

线上测试会消耗上游配额，且绝不打印凭据或原始响应。

## 后续计划

以后可能会有一个单独的、更大的插件，提供其他 Grok Responses 能力，例如网页搜索、图片搜索、代码解释器、collections、MCP 以及混合的服务端工具工作流。这些能力有意不在本插件的初始范围内。

## 许可证

MIT
