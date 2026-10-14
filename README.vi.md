# Hermes Grok X Search

[English](README.md) | Tiếng Việt | [简体中文](README.zh-CN.md)

> Bản dịch này có thể chậm hơn bản tiếng Anh. Khi có khác biệt, [README.md](README.md) là bản chuẩn.

Một plugin Hermes Agent độc lập, cung cấp X Search phía máy chủ của xAI dưới dạng một tool duy nhất cho mô hình, `grok_x_search`, thông qua một gateway tương thích Responses do người vận hành cấu hình.

```text
Hermes model
  -> grok_x_search
  -> gateway /v1/responses
  -> xAI x_search
  -> answer and X citations
```

Hermes lưu một credential của gateway. Gateway lo xác thực với upstream, định tuyến và giới hạn.

## Phạm vi

Phiên bản 0.1 chỉ cung cấp X Search:

- tra cứu bài đăng, hồ sơ và thread công khai trên X
- bộ lọc handle cho phép hoặc loại trừ
- bộ lọc ngày
- hiểu hình ảnh của các bài đăng khớp
- hiểu video của các bài đăng khớp
- trích xuất trích dẫn và phát hiện kết quả suy giảm (degraded)

Plugin không cung cấp tìm kiếm web chung, đăng bài hay thích bài trên X, chạy code, tìm kiếm file, MCP, gọi hàm tùy ý, hay một client Responses API tổng quát.

## Cài đặt

```bash
hermes plugins install https://github.com/duu261/hermes-grok-x-search.git --enable
```

Khởi động lại bề mặt Hermes cần nạp plugin. Khởi động lại gateway vẫn là việc của người vận hành.

## Cấu hình

Lưu API key của gateway trong file môi trường riêng tư của Hermes:

```text
GROK_X_SEARCH_API_KEY=replace-me
```

Đặt các hành vi không bí mật qua cấu hình Hermes:

```bash
hermes config set grok_x_search.base_url https://gateway.example/v1
hermes config set grok_x_search.model grok-4.6
```

Các thiết lập tùy chọn:

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

Endpoint từ xa phải dùng HTTPS. HTTP không mã hóa chỉ được chấp nhận cho endpoint phát triển `localhost`, `127.0.0.1` hoặc `::1`. Plugin nối thêm `/responses` trừ khi URL đã cấu hình kết thúc bằng `/responses`.

## Đầu vào của tool

`grok_x_search` nhận:

- `query` - yêu cầu tra cứu, bắt buộc
- `allowed_x_handles` - chỉ bao gồm tối đa 10 handle
- `excluded_x_handles` - loại trừ tối đa 10 handle
- `from_date` - ngày bắt đầu `YYYY-MM-DD`, tùy chọn
- `to_date` - ngày kết thúc `YYYY-MM-DD`, tùy chọn
- `enable_image_understanding` - phân tích hình ảnh đính kèm bài đăng khớp
- `enable_video_understanding` - phân tích video đính kèm bài đăng khớp

Không thể kết hợp handle cho phép và handle loại trừ.

## Kết quả

Lời gọi thành công trả về JSON gồm:

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

Kết quả được thiết kế giống `x_search` gốc của Hermes. Coi kết quả là có trích dẫn hỗ trợ khi `degraded` là false và `citations` hoặc `inline_citations` chứa URL bài đăng X hợp lệ. Các loại output nội bộ của gateway không được hiển thị vì chúng là thông tin chẩn đoán đường truyền, không phải trạng thái grounding.

Chỉ giữ URL trích dẫn HTTPS trên `x.com` hoặc `twitter.com`. Userinfo, cổng không chuẩn và host không liên quan bị loại bỏ.

Giống `x_search` gốc của Hermes, một câu trả lời HTTP 200 có lọc mà không có trích dẫn sẽ được trả về với `degraded: true`. Hãy coi đó là tổng hợp của mô hình không có nguồn, không phải bằng chứng X Search đã chạy. Câu trả lời không có bộ lọc thì theo hành vi gốc và không bị đánh dấu degraded chỉ vì thiếu trích dẫn. Nếu một URL X chuẩn trong trích dẫn trả về hoặc trong câu trả lời xác định một tác giả mâu thuẫn với `allowed_x_handles` hoặc `excluded_x_handles`, plugin từ chối kết quả (fail closed) với `error_type: "filter_violation"`.

## Ranh giới tin cậy

Plugin này gửi request tới gateway đã cấu hình. Người vận hành gateway kiểm soát tài khoản upstream, xác thực, định tuyến, log, thời gian lưu giữ, tính phí, việc viết lại request và tính sẵn sàng. Cài plugin này không cấp quyền sử dụng xAI và không vượt qua các kiểm soát của nhà cung cấp.

Bộ lọc domain và handle giới hạn phạm vi tìm kiếm được yêu cầu nhưng không phải ranh giới bảo mật. Hãy kiểm tra URL trả về trước khi tải hoặc hành động dựa trên chúng.

Plugin từ chối redirect, giới hạn kích thước body response và thời gian chờ retry, và trả về loại lỗi đã làm sạch thay vì body thô từ upstream.

Kết quả tool đã chuẩn hóa bị giới hạn ở 100.000 ký tự, khớp với giới hạn kết quả tool gốc của Hermes. Response từ upstream không có `status` được chấp nhận, còn `status` khác `completed` được nêu rõ thì bị từ chối. Ràng buộc bộ lọc được nhắc lại trong chỉ dẫn của request và được kiểm tra với các URL X xác định được trong kết quả.

## Phát triển

```bash
python -m unittest discover -s tests -v
python -m py_compile provider.py __init__.py tests/test_provider.py tests/test_live.py tests/test_hermes_e2e.py tests/hermes_e2e_runner.py
hermes plugins doctor . --ci
git diff --check
```

Kiểm thử live có xác thực:

```bash
GROK_X_SEARCH_LIVE_TESTS=1 \
GROK_X_SEARCH_LIVE_BASE_URL=https://gateway.example/v1 \
python -m unittest tests.test_live -v
```

Kiểm thử live tiêu tốn quota upstream và không bao giờ in credential hay response thô.

## Hướng phát triển

Sau này một plugin riêng, lớn hơn, có thể cung cấp các khả năng Grok Responses khác như tìm kiếm web, tìm kiếm hình ảnh, code interpreter, collections, MCP và các luồng kết hợp nhiều tool phía máy chủ. Các khả năng đó cố ý nằm ngoài phạm vi ban đầu của plugin này.

## Giấy phép

MIT
