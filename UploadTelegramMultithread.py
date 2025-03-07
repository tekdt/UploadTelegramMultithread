import os
import hashlib
import json
import asyncio
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError
import httpx
from PyQt6.QtWidgets import (QApplication, QTabWidget, QWidget, QVBoxLayout, QPushButton, QTextEdit, 
                            QFileDialog, QLabel, QLineEdit, QProgressBar, QSpinBox)
from PyQt6.QtCore import QThread, pyqtSignal
from telegram.request import HTTPXRequest

# Cấu hình logger
CONFIG_FILE = "config.json"

# Hàm tính MD5
def calculate_md5(file_path):
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
    except FileNotFoundError:
        return None
    return hash_md5.hexdigest().strip()

# Hàm lưu cấu hình
def save_config(token, user_id, selected_directory=None):
    config = load_config()  # Tải config hiện tại
    config.update({"token": token, "user_id": user_id})
    if selected_directory is not None:
        config["selected_directory"] = selected_directory
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "hash_string" not in data:
                data["hash_string"] = []
            return data
    return {"hash_string": []}

def save_md5(md5_hash):
    config = load_config()
    if "hash_string" not in config:
        config["hash_string"] = []
    if md5_hash not in config["hash_string"]:
        config["hash_string"].append(md5_hash)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def is_md5_uploaded(md5_hash):
    config = load_config()
    return md5_hash in config.get("hash_string", [])

class UploadWorker:
    def __init__(self, bot_token, user_id):
        request = HTTPXRequest(connection_pool_size=20, pool_timeout=60.0)
        self.bot = Bot(token=bot_token, request=request)
        self.user_id = user_id

    async def upload_file(self, file_path):
        file_md5 = calculate_md5(file_path)
        if not file_md5:
            return f"❌ Không thể tính MD5: {file_path.name}"
        
        if is_md5_uploaded(file_md5):
            return f"⚡ Bỏ qua: {file_path.name} (đã tải trước đó)"
        
        try:
            with open(file_path, 'rb') as f:
                await self.bot.send_document(chat_id=self.user_id, document=f)
            save_md5(file_md5)
            return f"✅ Đã tải lên: {file_path.name}"
        except TelegramError as e:
            return f"❌ Lỗi khi tải {file_path.name}: {e}"

class UploadThread(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, bot_token, directory, user_id, max_workers):
        super().__init__()
        self.bot_token = bot_token
        self.directory = Path(directory).resolve()
        self.user_id = user_id
        self.max_workers = min(max_workers, 10)
        self.running = True
        self.semaphore = asyncio.Semaphore(self.max_workers)

    def stop(self):
        self.running = False

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.upload_files())
        self.finished_signal.emit()

    async def upload_files(self):
        files = []
        for root, _, filenames in os.walk(self.directory):
            for filename in filenames:
                file_path = Path(root) / filename
                if file_path.exists() and os.access(file_path, os.R_OK):
                    files.append(file_path)

        total_files = len(files)
        self.log.emit(f"🔎 Tổng số tệp cần tải lên: {total_files}")
        if total_files == 0:
            self.log.emit("🚀 Không có tệp nào cần tải lên.")
            return

        worker = UploadWorker(self.bot_token, self.user_id)
        uploaded_count = 0

        async def process_file(file_path):
            async with self.semaphore:
                if not self.running:
                    return None
                return await worker.upload_file(file_path)

        tasks = [process_file(file_path) for file_path in files]
        
        for i, future in enumerate(asyncio.as_completed(tasks)):
            if not self.running:
                self.log.emit("🔥 Tải lên đã bị dừng.")
                break
            try:
                result = await future
                if result:
                    uploaded_count += 1
                    self.progress.emit(int((uploaded_count / total_files) * 100))
                    self.log.emit(result)
            except Exception as e:
                self.log.emit(f"❌ Lỗi không xác định: {e}")

class MainWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.config = load_config()
        self.input_token.setText(self.config.get("token", ""))
        self.input_user_id.setText(self.config.get("user_id", ""))
        self.selected_directory = self.config.get("selected_directory", "")
        if self.selected_directory:
            self.label.setText(f"Thư mục đã chọn: {self.selected_directory}")
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

        self.thread_label = QLabel("Số luồng tải lên đồng thời (1-10):")
        layout.addWidget(self.thread_label)
        self.thread_count = QSpinBox()
        self.thread_count.setRange(1, 10)
        self.thread_count.setValue(4)
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

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Chọn thư mục")
        if directory:
            self.selected_directory = directory
            self.label.setText(f"Thư mục đã chọn: {directory}")
            save_config(self.input_token.text().strip(), self.input_user_id.text().strip(), directory)

    def start_upload(self):
        self.upload_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.log_display.append("Bắt đầu")

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

        save_config(token, user_id)
        self.upload_thread = UploadThread(token, self.selected_directory, user_id, max_workers)
        self.upload_thread.progress.connect(self.progress_bar.setValue)
        self.upload_thread.log.connect(self.log_display.append)
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
        config = load_config()
        config["hash_string"] = []
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        self.log_display.append("🗑️ Đã reset lịch sử MD5.")

class AboutWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        # Thông tin phần mềm
        info = {
            "Tên phần mềm": "Upload Telegram Multithread",
            "Tác giả": "TekDT",
            "Mô tả": "Phần mềm tải lên tệp lên Telegram với hỗ trợ đa luồng",
            "Ngày phát hành": "07-03-2025",
            "Phiên bản": "1.0.0",
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
        # Tạo các widget cho từng tab
        self.main_tab = MainWidget()
        self.about_tab = AboutWidget()

        # Thêm các tab
        self.addTab(self.main_tab, "Main")
        self.addTab(self.about_tab, "About")

        # Thiết lập tiêu đề và kích thước cửa sổ
        self.setWindowTitle("Upload Telegram Multithread")
        self.resize(500, 550)

if __name__ == "__main__":
    app = QApplication([])
    window = TelegramUploader()
    window.show()
    app.exec()
