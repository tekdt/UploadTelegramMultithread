import os
import gc
import hashlib
import json
import sys
import asyncio
import aiofiles
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError, NetworkError
import httpx
from httpx import TimeoutException as TimedOut
import threading
import io
from PyQt6.QtWidgets import (
    QApplication, QTabWidget, QWidget, QVBoxLayout, QPushButton, QTextEdit,
    QFileDialog, QLabel, QLineEdit, QProgressBar, QSpinBox
)
from PyQt6.QtCore import QThread, pyqtSignal
from telegram.request import HTTPXRequest
from PyQt6.QtGui import QIcon

# Cấu hình
CONFIG_FILE = "config.json"
version = "23/04/2025"
released_date = "1.2.2"

# Quản lý event loop trong luồng nền
class AsyncExecutor:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.run_loop, daemon=True)
        self.thread.start()

    def run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_async(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    def shutdown(self):
        def stop_loop():
            try:
                # Lấy danh sách tất cả các tác vụ đang chạy, trừ tác vụ hiện tại
                tasks = [t for t in asyncio.all_tasks(self.loop) if t is not asyncio.current_task()]
                # Hủy tất cả các tác vụ
                for task in tasks:
                    task.cancel()
                # Chờ các tác vụ hoàn thành hoặc bị hủy, bỏ qua lỗi nếu có
                self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                # Đóng các async generator (nếu có)
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                # Đóng event loop
                self.loop.close()
            except Exception as e:
                print(f"Lỗi khi shutdown loop: {e}")

        # Gọi hàm stop_loop qua luồng an toàn
        self.loop.call_soon_threadsafe(stop_loop)
        self.thread.join(timeout=5.0)  # Chờ tối đa 5 giây

# Tính toán MD5
def calculate_md5(file_path):
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
    except FileNotFoundError:
        return None
    return hash_md5.hexdigest().strip()

# Thao tác với file config bất đồng bộ
async def save_config(token, user_id, selected_directory=None, thread_count=None):
    try:
        config = await load_config()
        config.update({"token": token, "user_id": user_id})
        if selected_directory is not None:
            config["selected_directory"] = selected_directory
        if thread_count is not None:
            config["thread_count"] = thread_count
        async with aiofiles.open(CONFIG_FILE, "w", encoding="utf-8") as f:
            await f.write(json.dumps(config, indent=4))
    except Exception as e:
        raise

async def load_config():
    try:
        async with aiofiles.open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.loads(await f.read())
            if "hash_string" not in data:
                data["hash_string"] = []
            return data
    except FileNotFoundError:
        return {"hash_string": []}
    except Exception as e:
        raise

async def save_md5(md5_hash, config_lock):
    async with config_lock:
        try:
            config = await load_config()
            if "hash_string" not in config:
                config["hash_string"] = []
            if md5_hash not in config["hash_string"]:
                config["hash_string"].append(md5_hash)
                async with aiofiles.open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(config, indent=4))
        except Exception as e:
            raise

async def is_md5_uploaded(md5_hash, config_lock):
    async with config_lock:
        try:
            config = await load_config()
            return md5_hash in config.get("hash_string", [])
        except Exception as e:
            raise

class UploadWorker:
    def __init__(self, bot_token, user_id, log_callback):
        request = HTTPXRequest(
            connection_pool_size=8,
            pool_timeout=120.0
        )
        self.bot = Bot(token=bot_token, request=request)
        self.user_id = user_id
        self.log_callback = log_callback
        self.config_lock = asyncio.Lock()

    async def close(self):
        print("Đã đóng UploadWorker")

    async def upload_file(self, file_path, max_retries=2, chunk_size=1024 * 1024):
        file_md5 = calculate_md5(file_path)
        if not file_md5:
            return f"❌ Không thể tính MD5: {file_path.name}"

        if await is_md5_uploaded(file_md5, self.config_lock):
            return f"⚡ Bỏ qua: {file_path.name} (đã tải trước đó)"

        # Kiểm tra kích thước file
        file_size = os.path.getsize(file_path)
        if file_size > 4 * 1024 * 1024 * 1024:  # 4GB
            return f"❌ File quá lớn: {file_path.name} ({file_size / 1024 / 1024:.2f}MB)"

        for attempt in range(max_retries):
            try:
                async with aiofiles.open(file_path, 'rb') as f:
                    # Tạo một BytesIO object để chứa toàn bộ file
                    file_content = io.BytesIO()
                    
                    # Đọc file theo chunk và ghi vào BytesIO object
                    while True:
                        chunk = await f.read(chunk_size)
                        if not chunk:
                            break
                        file_content.write(chunk)
                    
                    # Đưa con trỏ về đầu file để chuẩn bị gửi
                    file_content.seek(0)
                    file_content.name = file_path.name  # Đặt tên file

                    await self.bot.send_document(
                        chat_id=self.user_id,
                        document=file_content
                    )

                await save_md5(file_md5, self.config_lock)
                return f"✅ Đã tải lên: {file_path.name}"
            except TelegramError as e:
                error_str = str(e)
                if "Flood control exceeded" in error_str:
                    import re
                    m = re.search(r"Retry in (\d+) seconds", error_str)
                    if m:
                        wait_seconds = int(m.group(1))
                        self.log_callback(f"⚠️ Flood control: tạm dừng {wait_seconds} giây...")
                        await asyncio.sleep(wait_seconds)
                        continue
                elif "Too Many Requests" in str(e):  # Kiểm tra lỗi 429
                    wait_time = 5  # Chờ 5 giây
                    self.log_callback(f"⚠️ Quá nhiều yêu cầu, chờ {wait_time} giây trước khi thử lại...")
                    await asyncio.sleep(wait_time)
                    continue  # Thử lại
                elif isinstance(e, TimedOut):
                    if attempt < max_retries - 1:
                        self.log_callback(f"⚠️ Timed out, thử lại lần {attempt + 2}")
                        await asyncio.sleep(5)
                        continue
                    return f"❌ Lỗi khi tải {file_path.name}: {e}"
                else:
                    # Xử lý các lỗi khác của Telegram
                    self.log_callback(f"❌ Lỗi Telegram: {e}")
                    break
            except NetworkError as e:
                if "Request Entity Too Large" in str(e):
                    return f"❌ File quá lớn: {file_path.name}"
                if attempt < max_retries - 1:
                    self.log_callback(f"⚠️ Lỗi mạng, thử lại lần {attempt + 2}: {str(e)}")
                    await asyncio.sleep(2)
                    continue
                return f"❌ Lỗi mạng khi tải {file_path.name}: {e}"
            except Exception as e:
                # Xử lý lỗi chung
                self.log_callback(f"❌ Lỗi không xác định: {e}")
                break
        else:
            # Nếu hết số lần thử mà vẫn thất bại
            return f"❌ Thất bại sau {max_retries} lần thử: {file_path.name}"
        return f"✅ Tải lên thành công: {file_path.name}"

class UploadThread(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, bot_token, directory, user_id, max_workers, async_executor):
        super().__init__()
        self.bot_token = bot_token
        self.directory = Path(directory).resolve()
        self.user_id = user_id
        self.max_workers = min(max_workers, 8)
        self.running = True
        self.async_executor = async_executor
        self.semaphore = None
        self.worker = UploadWorker(self.bot_token, self.user_id, self.log.emit)

    def stop(self):
        self.running = False

    def run(self):
        try:
            self.async_executor.run_async(self.upload_files())
        except Exception as e:
            self.log.emit(f"❌ Lỗi: {str(e)}")
        finally:
            self.async_executor.run_async(self.worker.close())
        self.finished_signal.emit()

    async def upload_files(self):
        self.semaphore = asyncio.Semaphore(self.max_workers)
        files = [file_path for file_path in self.directory.rglob("*") if file_path.is_file()]
        total_files = len(files)
        self.log.emit(f"🔎 Tổng số tệp cần tải lên: {total_files}")
        if total_files == 0:
            self.log.emit("🚀 Không có tệp nào cần tải lên.")
            return

        batch_size = 100
        uploaded_count = 0

        for i in range(0, total_files, batch_size):
            if not self.running:
                self.log.emit("🔥 Tải lên đã bị dừng.")
                break
            batch = files[i:i + batch_size]
            tasks = [self.process_file(file_path) for file_path in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, str):
                    uploaded_count += 1
                    # Emit progress less frequently to reduce GUI load
                    if uploaded_count % 10 == 0 or uploaded_count == total_files:
                        self.progress.emit(int((uploaded_count / total_files) * 100))
                    self.log.emit(result)
                elif isinstance(result, Exception):
                    self.log.emit(f"❌ Lỗi trong batch: {str(result)}")
            if i % (batch_size * 10) == 0:  # Gọi gc sau mỗi 10 batch
                gc.collect()

    async def process_file(self, file_path):
        async with self.semaphore:
            if not self.running:
                return None
            return await self.worker.upload_file(file_path, chunk_size=1024 * 1024)

class MainWidget(QWidget):
    def __init__(self, async_executor):
        super().__init__()
        self.async_executor = async_executor
        self.init_ui()
        self.config = self.async_executor.run_async(load_config())
        self.input_token.setText(self.config.get("token", ""))
        self.input_user_id.setText(self.config.get("user_id", ""))
        self.selected_directory = self.config.get("selected_directory", "")
        if self.selected_directory:
            self.label.setText(f"Thư mục đã chọn: {self.selected_directory}")
        self.thread_count.setValue(self.config.get("thread_count", 4))
        self.upload_thread = None

    def init_ui(self):
        layout = QVBoxLayout()

        self.label_token = QLabel("Nhập Telegram Bot Token:")
        layout.addWidget(self.label_token)
        self.input_token = QLineEdit()
        layout.addWidget(self.input_token)

        self.label_user_id = QLabel("Nhập Telegram User ID:")
        layout.addWidget(self.label_user_id)
        self.input_user_id = QLineEdit()
        layout.addWidget(self.input_user_id)

        self.label = QLabel("Chọn thư mục chứa tệp cần tải lên:")
        layout.addWidget(self.label)

        self.select_button = QPushButton("Chọn thư mục")
        self.select_button.clicked.connect(self.select_directory)
        layout.addWidget(self.select_button)

        self.thread_label = QLabel("Số luồng tải lên đồng thời (1-8):")
        layout.addWidget(self.thread_label)
        self.thread_count = QSpinBox()
        self.thread_count.setRange(1, 8)
        self.thread_count.setValue(4)
        self.thread_count.valueChanged.connect(self.update_thread_count)
        layout.addWidget(self.thread_count)

        self.upload_button = QPushButton("Tải lên Telegram")
        self.upload_button.clicked.connect(self.start_upload)
        layout.addWidget(self.upload_button)

        self.stop_button = QPushButton("Dừng tải lên")
        self.stop_button.clicked.connect(self.stop_upload)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.reset_button = QPushButton("Xóa lịch sử MD5")
        self.reset_button.clicked.connect(self.reset_md5_history)
        layout.addWidget(self.reset_button)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)

        self.setLayout(layout)

    def update_thread_count(self):
        token = self.input_token.text().strip()
        user_id = self.input_user_id.text().strip()
        self.async_executor.run_async(save_config(token, user_id, self.selected_directory, self.thread_count.value()))

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Chọn thư mục")
        if directory:
            self.selected_directory = directory
            self.label.setText(f"Thư mục đã chọn: {directory}")
            self.async_executor.run_async(save_config(self.input_token.text().strip(), self.input_user_id.text().strip(), directory))

    def start_upload(self):
        self.upload_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.log_display.append("Bắt đầu. Đang tính số lượng tập tin...")

        token = self.input_token.text().strip()
        user_id = self.input_user_id.text().strip()
        max_workers = self.thread_count.value()

        if not token or not user_id:
            self.log_display.append("Vui lòng nhập Token và User ID!")
            self.upload_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            return

        if not self.selected_directory:
            self.selected_directory = self.config.get("selected_directory", "")
            if not self.selected_directory:
                self.log_display.append("Vui lòng chọn thư mục trước!")
                self.upload_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                return

        self.async_executor.run_async(save_config(token, user_id))
        self.upload_thread = UploadThread(token, self.selected_directory, user_id, max_workers, self.async_executor)
        self.upload_thread.progress.connect(self.progress_bar.setValue)
        self.upload_thread.log.connect(self.append_limited_log)
        self.upload_thread.finished_signal.connect(self.upload_finished)
        self.upload_thread.start()

    def stop_upload(self):
        if self.upload_thread and self.upload_thread.isRunning():
            self.upload_thread.stop()
            self.upload_button.setEnabled(True)
            self.stop_button.setEnabled(False)

    def upload_finished(self):
        self.upload_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.log_display.append("🚀 Quá trình tải lên đã hoàn thành.")

    def reset_md5_history(self):
        self.async_executor.run_async(self._reset_md5_history_async())
        self.log_display.append("🗑️ Đã reset lịch sử MD5.")

    async def _reset_md5_history_async(self):
        try:
            config = await load_config()
            config["hash_string"] = []
            async with aiofiles.open(CONFIG_FILE, "w", encoding="utf-8") as f:
                await f.write(json.dumps(config, indent=4))
        except Exception as e:
            raise

    def append_limited_log(self, message):
        document = self.log_display.document()
        if document.blockCount() > 1000:
            self.log_display.clear()
        self.log_display.append(message)

class AboutWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        info = {
            "Tên phần mềm": "Upload Telegram Multithread",
            "Tác giả": "TekDT",
            "Mô tả": "Phần mềm tải lên tệp lên Telegram với hỗ trợ đa luồng",
            "Ngày phát hành": released_date,
            "Phiên bản": version,
            "Email": "dinhtrungtek@gmail.com",
            "Telegram": "@tekdt1152",
            "Facebook": "tekdtcom"
        }

        for key, value in info.items():
            label = QLabel(f"{key}: {value}")
            layout.addWidget(label)

        self.setLayout(layout)

class TelegramUploader(QTabWidget):
    def __init__(self):
        super().__init__()
        self.async_executor = AsyncExecutor()
        self.main_tab = MainWidget(self.async_executor)
        self.about_tab = AboutWidget()
        self.addTab(self.main_tab, "Main")
        self.addTab(self.about_tab, "About")
        self.setWindowTitle("Upload Telegram Multithread")
        self.resize(500, 550)

    def closeEvent(self, event):
        self.async_executor.shutdown()
        event.accept()

if __name__ == "__main__":
    app = QApplication([])
    if hasattr(sys, "_MEIPASS"):
        icon_path = os.path.join(sys._MEIPASS, "logo.ico")
    else:
        icon_path = "logo.ico"

    app.setWindowIcon(QIcon(icon_path))
    window = TelegramUploader()
    window.setWindowIcon(QIcon(icon_path))
    window.show()
    sys.exit(app.exec())
