import os
import gc
import hashlib
import json
import sys
import asyncio
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError
import httpx
from PyQt6.QtWidgets import (QApplication, QTabWidget, QWidget, QVBoxLayout, QPushButton, QTextEdit, 
                            QFileDialog, QLabel, QLineEdit, QProgressBar, QSpinBox)
from PyQt6.QtCore import QThread, pyqtSignal
from telegram.request import HTTPXRequest
from PyQt6.QtGui import QIcon

# Cấu hình logger
CONFIG_FILE = "config.json"
version = "17/04/2025"
released_date = "1.2.1"

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
def save_config(token, user_id, selected_directory=None, thread_count=None):
    config = load_config()  # Tải config hiện tại
    config.update({"token": token, "user_id": user_id})
    if selected_directory is not None:
        config["selected_directory"] = selected_directory
    if thread_count is not None:
        config["thread_count"] = thread_count
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

async def load_config_async():
    return await asyncio.to_thread(load_config)

async def save_md5_async(md5_hash, config_lock):
    async with config_lock:
        await asyncio.to_thread(save_md5, md5_hash)

async def is_md5_uploaded_async(md5_hash, config_lock):
    async with config_lock:
        return await asyncio.to_thread(is_md5_uploaded, md5_hash)

class UploadWorker:
    def __init__(self, bot_token, user_id, log_callback):
        request = HTTPXRequest(connection_pool_size=20, pool_timeout=60.0)
        self.bot = Bot(token=bot_token, request=request)
        self.user_id = user_id
        self.log_callback = log_callback  # Callback để log thông báo
        self.config_lock = asyncio.Lock()
            
    async def upload_file(self, file_path):
        file_md5 = calculate_md5(file_path)
        if not file_md5:
            return f"❌ Không thể tính MD5: {file_path.name}"
        
        # Kiểm tra MD5 với khóa
        if await is_md5_uploaded_async(file_md5, self.config_lock):
            return f"⚡ Bỏ qua: {file_path.name} (đã tải trước đó)"
        
        try:
            with open(file_path, 'rb') as f:
                await self.bot.send_document(chat_id=self.user_id, document=f)
            # Lưu MD5 với khóa
            await save_md5_async(file_md5, self.config_lock)
            return f"✅ Đã tải lên: {file_path.name}"
        except TelegramError as e:
            error_str = str(e)
            if "Flood control exceeded" in error_str:
                import re
                m = re.search(r"Retry in (\d+) seconds", error_str)
                if m:
                    wait_seconds = int(m.group(1))
                    self.log_callback(f"⚠️ Flood control: tạm dừng {wait_seconds} giây trước khi thử lại...")
                    await asyncio.sleep(wait_seconds)
                    try:
                        with open(file_path, 'rb') as f:
                            await self.bot.send_document(chat_id=self.user_id, document=f)
                        await save_md5_async(file_md5, self.config_lock)
                        return f"✅ Đã tải lên sau khi chờ: {file_path.name}"
                    except TelegramError as e2:
                        return f"❌ Lỗi khi tải {file_path.name} sau khi chờ: {e2}"
            return f"❌ Lỗi khi tải {file_path.name}: {e}"
        finally:
            gc.collect()

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
        self.worker = UploadWorker(self.bot_token, self.user_id, self.log.emit)

    def stop(self):
        self.running = False

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.upload_files())
        self.finished_signal.emit()
                
    async def upload_files(self):
        files = [file_path for file_path in self.directory.rglob("*") if file_path.is_file()]
        total_files = len(files)
        self.log.emit(f"🔎 Tổng số tệp cần tải lên: {total_files}")
        if total_files == 0:
            self.log.emit("🚀 Không có tệp nào cần tải lên.")
            return

        batch_size = 100  # Số file mỗi batch
        uploaded_count = 0

        for i in range(0, total_files, batch_size):
            if not self.running:  # Kiểm tra nếu quá trình bị dừng
                self.log.emit("🔥 Tải lên đã bị dừng.")
                break
            batch = files[i:i + batch_size]  # Lấy một batch file
            tasks = [self.process_file(file_path) for file_path in batch]
            results = await asyncio.gather(*tasks)  # Chạy đồng thời trong batch
            for result in results:
                if result:
                    uploaded_count += 1
                    self.progress.emit(int((uploaded_count / total_files) * 100))
                    self.log.emit(result)
            gc.collect()  # Thu gom rác sau mỗi batch

    async def process_file(self, file_path):
        async with self.semaphore:
            if not self.running:
                return None
            return await self.worker.upload_file(file_path)

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

        self.thread_label = QLabel("Số luồng tải lên đồng thời (1-10):")
        layout.addWidget(self.thread_label)
        self.thread_count = QSpinBox()
        self.thread_count.setRange(1, 10)
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
        save_config(token, user_id, self.selected_directory, self.thread_count.value())
    
    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Chọn thư mục")
        if directory:
            self.selected_directory = directory
            self.label.setText(f"Thư mục đã chọn: {directory}")
            save_config(self.input_token.text().strip(), self.input_user_id.text().strip(), directory)

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

        save_config(token, user_id)
        self.upload_thread = UploadThread(token, self.selected_directory, user_id, max_workers)
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
        config = load_config()
        config["hash_string"] = []
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        self.log_display.append("🗑️ Đã reset lịch sử MD5.")
        
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
        self.main_tab = MainWidget()
        self.about_tab = AboutWidget()
        self.addTab(self.main_tab, "Main")
        self.addTab(self.about_tab, "About")
        self.setWindowTitle("Upload Telegram Multithread")
        self.resize(500, 550)

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
    app.exec()
