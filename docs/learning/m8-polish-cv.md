# M8: Polish cho CV

> Mục tiêu: biến một project chạy được thành một project **người khác hiểu và tin được** trong 5 phút:
> README rõ ràng, tài liệu kiến trúc, CI xanh, và câu chuyện để kể khi phỏng vấn.

File chính: `README.md`, `docs/architecture.md`, `.github/workflows/ci.yml`, `.gitattributes`,
`docs/demo.tape`, `docs/learning/interview-questions.md`.

---

## 1. Khái niệm

### README viết cho ai?
Nhà tuyển dụng hay reviewer dành khoảng **30 giây đến 2 phút** cho README. Thứ tự trong README của
minicode trả lời đúng các câu hỏi họ có trong đầu:
1. Đây là gì? (một câu, kèm GIF hoặc output thật)
2. Nó làm được gì? (features, có link vào code)
3. Chạy thử thế nào? (quick start, copy-paste được)
4. Nó được xây ra sao? (sơ đồ Mermaid)
5. Người viết có hiểu mình làm gì không? (design decisions & trade-offs)
6. Có bằng chứng không? (bảng eval với số thật)
7. Người viết có trung thực không? (limitations, roadmap)

### Design decision phải có cả cái giá
Viết "dùng exact replace vì nó tốt" thì chưa nói lên gì. Hãy viết "dùng exact replace **vì** diff dễ sai
với LLM, **cái giá** là model phải copy chính xác text". Cột *Cost* trong bảng trade-off cho thấy bạn đã
cân nhắc các phương án.

### CI: máy kiểm tra thay bạn
`ci.yml` chạy `ruff check`, `ruff format --check`, `mypy src` và `pytest` (chỉ offline) trên Ubuntu và
Windows cho mọi push và PR.
- **Offline**: CI không có API key, và không nên tốn tiền ở mỗi commit. Live test có cờ `--run-live`;
  eval thì chạy tay.
- **Ma trận hệ điều hành**: Linux là target chính, Windows là nơi phát triển. Bash có trên cả hai
  runner, nên test `run_bash` chạy được ở cả hai.
- **Pin version** của action (`setup-uv` theo commit SHA) và `uv sync --locked`, để build tái lập được.
- `.gitattributes` với `eol=lf`: fixture và test so sánh byte chính xác, nên Windows không được tự
  đổi LF thành CRLF.

### Kể chuyện bằng dữ liệu
Một project "đẹp" chưa đủ. Hãy có **số liệu** (9/9 task, $0.256 so với $0.019) và một **bug thật** cùng
cách bạn tìm ra nó. Xem `interview-questions.md`.

---

## 2. Vì sao thiết kế như vậy

| Quyết định | Phương án khác | Lý do chọn |
|---|---|---|
| Output thật (rút gọn) trong README cùng với hướng dẫn quay GIF | Chỉ có GIF | GIF cần quay bằng tay. Output dạng text thì đọc nhanh, tìm kiếm được và không bao giờ "hỏng ảnh" |
| Sơ đồ Mermaid | Ảnh PNG | GitHub render trực tiếp, sửa được bằng text, review được trong PR |
| `docs/architecture.md` riêng | Nhét hết vào README | README cho người lướt; architecture cho người sẽ sửa code |
| CI không chạy eval | Chạy eval mỗi PR | Tốn tiền, chậm, và kết quả không tất định. Hợp với chạy nightly kèm budget |
| Ghi rõ limitations | Giấu đi | Reviewer nào cũng sẽ tìm ra. Tự nói trước thể hiện sự hiểu biết |

---

## 3. Pitfalls

- README liệt kê hàng chục feature nhưng không có lệnh chạy thử nào copy-paste được.
- Số liệu trong README lệch với kết quả thật. Hãy lấy từ `evals/results/` và ghi ngày.
- CI gọi API thật nên đỏ khi không có key, hoặc tốn tiền ở mỗi commit.
- Dùng action ở version trôi nổi (`@main`), nên build hôm nay xanh mà ngày mai đỏ không rõ lý do.
- Quên `.gitattributes`: test so sánh byte xanh trên Linux nhưng đỏ trên Windows, hoặc ngược lại.
- Commit `.env` hoặc trace chứa key. Hãy kiểm tra trước khi push (M7 có bước đối chiếu với key thật).
- Sơ đồ quá chi tiết (vẽ mọi class) thì không ai đọc. Chỉ vẽ luồng dữ liệu chính.

---

## 4. Bài tập tự làm

1. Viết README cho project của bạn theo 7 câu hỏi ở mục 1. Nhờ một người chưa biết gì đọc trong
   2 phút rồi hỏi lại họ "project này làm gì?".
2. Vẽ sơ đồ Mermaid của chính agent loop bạn viết. So với sơ đồ của minicode xem bạn có bỏ sót bước nào.
3. Thêm `ci.yml`, push lên GitHub, sửa cho đến khi xanh trên cả hai hệ điều hành.
4. Quay GIF bằng `vhs docs/demo.tape` (hoặc `asciinema rec`, rồi dùng `agg` để chuyển sang GIF).
5. Tập trả lời 27 câu trong `interview-questions.md`. Với mỗi câu, mở đúng file được trỏ tới và
   giải thích bằng code của *bạn*.

Marker: `uv run pytest -m m8`. Test này kiểm tra tài liệu và CI có đủ, và số liệu eval trong README
khớp với `evals/results/`.

---

## 5. Gợi ý cải tiến

- Badge CI và coverage ở đầu README.
- Publish package (`uv build`) để chạy được bằng `uvx minicode`.
- Trang docs (MkDocs) gồm architecture, learning notes và API reference.
- Workflow eval nightly với budget, kèm biểu đồ pass rate theo thời gian.
- Một bài blog "Xây coding agent từ đầu: 8 bài học", dùng các learning note làm khung.

---

## 6. Câu hỏi tự kiểm tra

1. README của bạn trả lời được 7 câu hỏi ở mục 1 chưa? Câu nào còn yếu?
2. Vì sao CI không chạy live test và eval? Khi nào nên chạy chúng?
3. `.gitattributes` với `eol=lf` giải quyết vấn đề gì trong project này?
4. Chọn một design decision trong README và giải thích cả lợi ích lẫn cái giá của nó.
5. Kể trong 90 giây một bug thật bạn tìm ra trong project: triệu chứng, nguyên nhân, cách sửa, test.
