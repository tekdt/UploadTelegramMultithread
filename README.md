# UploadTelegramMultithread
Tên phần mềm: Upload Telegram Multithread
Tác giả: TekDT
Mô tả: Phần mềm tải lên tệp lên Telegram với hỗ trợ đa luồng
Ngày phát hành: 07-03-2025
Phiên bản: 1.0.0
Email: dinhtrungtek@gmail.com
Telegram: @tekdt1152
Facebook: tekdtcom

# Hướng dẫn cài đặt
* Chạy trực tiếp từ script python
- Cài đặt Python3: https://www.python.org/downloads/
- Cài đặt thư viện cần thiết: telegram, PyQt6, asyncio bằng câu lệnh python py -m pip install <tên thư viện>

* Chạy trực tiếp từ file EXE đã biên dịch (khuyến khích)

# Hướng dẫn sử dụng
Ở giao diện chương trình sẽ có tổng cộng 5 tab, bao gồm: Main và About
- Tab Main: Thiết lập để chạy chương trình
+ Nhập Telegram Bot Token: Để lấy Token, bạn vào giao diện tìm kiếm của telegram (trên ứng dụng Telegram), nhập vào @BotFather rồi gõ tiếp /newbot. Sau đó, làm theo hướng dẫn để tạo BOT. Khi tạo hoan thành sẽ có token cho bạn. Hoặc bạn có thể gõ /token để lấy lại token nếu quên.
+ Nhập Telegram User ID: Đây là User ID của tài khoản Telegram bạn muốn gửi file đến. TekDT sẽ chọn tài khoản của mình để giao tiếp với BOT. Để lấy User ID, tiếp tục tìm @ChatidTelegramBot trên thanh chat của Telegram, sau đó gõ /start là bạn sẽ thấy được User ID của mình.
+ Chọn thư mục: Đây là thư mục chứa tất cả các tập tin bạn muốn upload lên Telegram, bao gồm tập tin chứa trong các thư mục con.
+ Só luồng tải lên đồng thời: Bạn sẽ chọn được từ 1-10, số càng lớn thì tải lên càng nhanh. Nhưng cũng sẽ chiếm nhiều băng thông mạng và tài nguyên máy tính của bạn hơn.
+ Xoá lịch sử MD5: Đây là chức năng reset các file đã tải lên. Do chương trình được thiết kế tải file không giới hạn, cho nên sẽ có khả năng upload trùng file. Do đó, khi upload file thành công, chương trình sẽ tính mã MD5 và ghi lại log, để tránh upload trùng file. Nên khi nhấn nút này, chương trình sẽ reset tất cả mã MD5 của các file đã upload.
+ Tải lên/Dừng tải lên: Như tên gọi, muốn upload thì bạn nhấn nút Tải lên và ngược lại là Dừng tải lên.
  -> Chú ý: Bạn phải gõ /start hoặc chat một từ gì đó với BOT bạn vừa tạo thì BOT mới tự động gửi file được. Do BOT không thể chat được với User ID nếu chưa từng chat với nhau.
- Tab About: Chứa thông tin về tác giả, thông tin phần mềm và thông tin liên hệ.

# Trách nhiệm
TekDT không chịu trách nhiệm cho tài khoản của bạn khi bạn tải ở các nguồn khác được tuỳ biến, sửa đổi dựa trên script này. Bạn có thể sử dụng chương trình này miễn phí thì hãy tin nó. TekDT sẽ không thu thập tài khoản tài khoản hay làm bất cứ điều gì với tài khoản của bạn.
Nếu không tin TekDT hoặc sợ mất tài khoản, vui lòng thoát khỏi trang này, hãy xoá phần mềm/script đã tải.

# Hỗ trợ:
Mọi liên lạc của bạn với TekDT sẽ rất hoan nghênh và đón nhận để TekDT có thể cải tiến phần mềm/script này tốt hơn. Hãy thử liên hệ với TekDT bằng những cách sau:
- Telegram: @tekdt1152
- Zalo: 0944.095.092
- Email: dinhtrungtek@gmail.com
- Facebook: @tekdtcom

# Đóng góp:
Để phần mềm/script ngày càng hoàn thiện và nhiều tính năng hơn. TekDT cũng cần có động lực để duy trì. Nếu phần mềm/script này có ích với công việc của bạn, hãy đóng góp một chút. TekDT rất cảm kích việc làm chân thành này của bạn.
- MOMO: https://me.momo.vn/TekDT1152
