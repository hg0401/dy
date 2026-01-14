import sys
import json
import subprocess
import datetime
import os
import winreg  # 操作注册表
import ctypes  # 调用系统API刷新设置
import atexit  # 退出时清理
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
                             QPushButton, QGroupBox, QCheckBox, QTextEdit, QLabel,
                             QHeaderView, QLineEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont


# ==========================================
# 0. 系统代理管理器 (核心新增组件)
# ==========================================
class SystemProxy:
    INTERNET_SETTINGS = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                       r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
                                       0, winreg.KEY_ALL_ACCESS)

    def set_proxy(self, ip, port):
        """开启系统代理"""
        try:
            proxy_addr = f"{ip}:{port}"
            # 1. 开启代理 (ProxyEnable = 1)
            winreg.SetValueEx(self.INTERNET_SETTINGS, 'ProxyEnable', 0, winreg.REG_DWORD, 1)
            # 2. 设置地址 (ProxyServer = 127.0.0.1:8081)
            winreg.SetValueEx(self.INTERNET_SETTINGS, 'ProxyServer', 0, winreg.REG_SZ, proxy_addr)
            # 3. 刷新系统设置，使其立即生效
            self.refresh_system()
            print(f">>> 系统代理已自动开启: {proxy_addr}")
        except Exception as e:
            print(f"❌ 设置代理失败: {e}")

    def unset_proxy(self):
        """关闭系统代理"""
        try:
            # 1. 关闭代理 (ProxyEnable = 0)
            winreg.SetValueEx(self.INTERNET_SETTINGS, 'ProxyEnable', 0, winreg.REG_DWORD, 0)
            # 2. 刷新系统设置
            self.refresh_system()
            print(">>> 系统代理已自动关闭，恢复直连")
        except Exception as e:
            print(f"❌ 关闭代理失败: {e}")

    def refresh_system(self):
        """通知 Windows 设置已改变，必须执行这一步，否则注册表改了也不生效"""
        INTERNET_OPTION_SETTINGS_CHANGED = 39
        INTERNET_OPTION_REFRESH = 37
        ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)


# ==========================================
# 1. 后台抓取线程
# ==========================================
class CaptureWorker(QThread):
    log_signal = pyqtSignal(str, str)
    data_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.process = None
        self.is_running = True

    def run(self):
        python_exe = sys.executable
        script_path = "addon_backend.py"

        if not os.path.exists(script_path):
            self.log_signal.emit('sys', f"❌ 错误：找不到 {script_path}")
            return

        try:
            # 端口固定 8081
            cmd = [python_exe, script_path]
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            self.log_signal.emit('sys', '>>> 抓包服务已启动 (Port: 8081)...')
        except Exception as e:
            self.log_signal.emit('sys', f"❌ 启动失败: {str(e)}")
            return

        while self.is_running:
            if not self.process: break
            try:
                line = self.process.stdout.readline()
                if not line and self.process.poll() is not None: break

                if line:
                    line = line.strip()
                    if line.startswith("DY_DATA::"):
                        json_str = line.replace("DY_DATA::", "")
                        try:
                            data = json.loads(json_str)
                            self.data_signal.emit(data)
                        except:
                            pass
                    elif "Error" in line:
                        self.log_signal.emit('sys', f"[后端报错] {line}")
            except Exception:
                break

    def stop(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
            except:
                pass


# ==========================================
# 2. 自定义控件
# ==========================================
class AnchorInfoCard(QGroupBox):
    def __init__(self):
        super().__init__("当前监测主播信息")
        self.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #ccc; margin-top: 10px; background: white; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
        layout = QHBoxLayout()
        self.avatar_label = QLabel("头像")
        self.avatar_label.setFixedSize(80, 80)
        self.avatar_label.setStyleSheet("background-color: #eee; border-radius: 5px; qproperty-alignment: AlignCenter;")
        layout.addWidget(self.avatar_label)

        info_layout = QVBoxLayout()
        name_layout = QHBoxLayout()
        self.lbl_name = QLabel("待连接...")
        self.lbl_name.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        name_layout.addWidget(self.lbl_name)
        info_layout.addLayout(name_layout)

        self.lbl_id = QLabel("抖音号: ---")
        self.lbl_id.setStyleSheet("color: #666;")
        info_layout.addWidget(self.lbl_id)

        stats_layout = QHBoxLayout()
        stats_layout.addWidget(QLabel("粉丝: --"))
        stats_layout.addWidget(QLabel("获赞: --"))
        stats_layout.addStretch()
        info_layout.addLayout(stats_layout)
        layout.addLayout(info_layout)
        self.setLayout(layout)


# ==========================================
# 3. 主界面
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("抖音直播监控中控台 - 自动代理版")
        self.resize(1300, 850)

        self.setStyleSheet("""
            QMainWindow { background-color: #f0f2f5; }
            QPushButton { background-color: #568668; color: white; border-radius: 4px; padding: 5px; font-weight: bold; }
            QPushButton:hover { background-color: #4a755a; }
            QLineEdit { border: 1px solid #ccc; border-radius: 4px; padding: 6px; background: white; }
            QGroupBox { background: white; border: 1px solid #e0e0e0; border-radius: 6px; margin-top: 10px; }
            QTableWidget { background-color: white; border: none; gridline-color: #f0f0f0; }
            QHeaderView::section { background-color: #f8f9fa; border: none; padding: 6px; font-weight: bold; color: #555; }
        """)

        # --- 自动设置系统代理 ---
        self.proxy_manager = SystemProxy()
        self.proxy_manager.set_proxy("127.0.0.1", "8081")

        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.document().setMaximumBlockCount(500)

        self.room_map = {}
        self.pending_browsers = {}
        self.blacklisted_rooms = set()
        self.filters = {'sys': True, 'gift': True, 'chat': True}

        # --- UI 构建 ---
        central = QWidget();
        self.setCentralWidget(central);
        main_layout = QHBoxLayout(central)
        left_widget = QWidget();
        left_layout = QVBoxLayout(left_widget)
        top_container = QWidget();
        top_layout = QHBoxLayout(top_container)
        table_area = QWidget();
        table_layout = QVBoxLayout(table_area)

        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("输入直播间链接...")
        self.btn_add = QPushButton("添加直播间")
        self.btn_add.setFixedWidth(100)
        self.btn_add.clicked.connect(self.add_room_from_url)
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(self.btn_add)
        table_layout.addLayout(input_layout)

        self.table_rooms = QTableWidget(0, 9)
        cols = ["序号", "主播/房间", "标题/ID", "消息数", "开播", "监控", "状态", "操作", "工具"]
        self.table_rooms.setHorizontalHeaderLabels(cols)
        self.table_rooms.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_rooms.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_rooms.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table_rooms.verticalHeader().setVisible(False)
        self.table_rooms.setAlternatingRowColors(True)
        table_layout.addWidget(self.table_rooms)
        top_layout.addWidget(table_area, stretch=4)

        btn_strip = QWidget();
        btn_layout = QVBoxLayout(btn_strip)
        ctrl_btns = ["全部启动", "全部关闭", "清空直播间", "清空日志"]
        for text in ctrl_btns:
            btn = QPushButton(text)
            btn.setFixedHeight(35)
            btn_layout.addWidget(btn)
            if text == "清空直播间": btn.clicked.connect(self.clear_rooms)
            if text == "清空日志": btn.clicked.connect(lambda: self.text_log.clear())
        btn_layout.addStretch()
        top_layout.addWidget(btn_strip, stretch=1)
        left_layout.addWidget(top_container, stretch=3)

        group_data = QGroupBox("实时抓取数据");
        l_data = QVBoxLayout()
        self.table_details = QTableWidget(0, 5)
        self.table_details.setHorizontalHeaderLabels(["房间ID", "用户", "类型", "内容", "时间"])
        self.table_details.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_details.setAlternatingRowColors(True)
        l_data.addWidget(self.table_details)
        group_data.setLayout(l_data)
        left_layout.addWidget(group_data, stretch=2)

        right_widget = QWidget();
        right_widget.setFixedWidth(380);
        right_layout = QVBoxLayout(right_widget)
        self.card_info = AnchorInfoCard();
        right_layout.addWidget(self.card_info)
        group_cond = QGroupBox("抓取条件");
        gl = QGridLayout()
        self.add_cb("进入", 'enter', 0, 0, gl);
        self.add_cb("礼物", 'gift', 0, 1, gl)
        self.add_cb("弹幕", 'chat', 0, 2, gl);
        self.add_cb("关注", 'follow', 1, 0, gl)
        self.add_cb("点赞", 'like', 1, 1, gl);
        self.add_cb("升级", 'up', 1, 2, gl)
        group_cond.setLayout(gl);
        right_layout.addWidget(group_cond)
        group_log = QGroupBox("系统日志");
        log_l = QVBoxLayout()
        log_l.addWidget(self.text_log);
        group_log.setLayout(log_l);
        right_layout.addWidget(group_log, stretch=1)
        main_layout.addWidget(left_widget, stretch=3);
        main_layout.addWidget(right_widget, stretch=1)

        self.worker = CaptureWorker()
        self.worker.log_signal.connect(self.handle_log)
        self.worker.data_signal.connect(self.handle_data)
        self.worker.start()

    def add_cb(self, text, key, r, c, layout):
        cb = QCheckBox(text)
        cb.setChecked(self.filters.get(key, False))
        cb.stateChanged.connect(lambda s, k=key: self.filters.update({k: s == 2}))
        layout.addWidget(cb, r, c)

    def open_headless_browser(self, url):
        browser_path = None
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ]
        for path in candidates:
            if os.path.exists(path):
                browser_path = path
                break

        if not browser_path: return None

        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        cmd = [
            browser_path,
            "--proxy-server=http://127.0.0.1:8081",
            f"--user-agent={user_agent}",

            # === 核心去自动化特征参数 ===
            "--disable-blink-features=AutomationControlled",  # <--- 关键！防止被识别为机器人
            "--exclude-switches=enable-automation",

            # === 性能参数 ===
            "--autoplay-policy=no-user-gesture-required",
            "--disable-quic",
            "--ignore-certificate-errors",
            "--no-first-run",
            "--no-sandbox",
            "--mute-audio",

            # 开启 GPU 加速 (解决卡顿)
            "--enable-gpu-rasterization",
            "--ignore-gpu-blocklist",

            url
        ]

        try:
            return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.PIPE)
        except:
            return None

    def add_room_from_url(self):
        url = self.url_input.text().strip()
        if not url: return
        self.add_table_row(url=url)
        self.url_input.clear()

    def add_table_row(self, url="", user="待连接", room_id="", is_external=False):
        row = self.table_rooms.rowCount()
        self.table_rooms.insertRow(row)

        self.table_rooms.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table_rooms.setItem(row, 1, QTableWidgetItem(user))
        display_text = url if url else f"ID:{room_id}"
        if is_external: display_text = f"外部ID:{room_id}"
        self.table_rooms.setItem(row, 2, QTableWidgetItem(display_text))
        self.table_rooms.setItem(row, 3, QTableWidgetItem("0"))
        self.table_rooms.setItem(row, 4, QTableWidgetItem("🕒"))

        cb = QCheckBox();
        cb.setChecked(True)
        container = QWidget();
        ly = QHBoxLayout(container);
        ly.addWidget(cb);
        ly.setAlignment(Qt.AlignmentFlag.AlignCenter);
        ly.setContentsMargins(0, 0, 0, 0)
        self.table_rooms.setCellWidget(row, 5, container)

        self.table_rooms.setItem(row, 6, QTableWidgetItem("未运行"))

        btn = QPushButton("启动" if not is_external else "移除")
        btn.setStyleSheet(
            "background-color: #568668; font-size: 11px;" if not is_external else "background-color: #6c757d;")
        if not is_external:
            btn.clicked.connect(lambda _, b=btn, u=url: self.toggle_browser(b, u))
        else:
            btn.clicked.connect(lambda _, b=btn: self.remove_room(b, room_id))
        self.table_rooms.setCellWidget(row, 7, btn)

        btn_refresh = QPushButton("刷新")
        btn_refresh.setStyleSheet("background-color: #17a2b8; font-size: 11px;")
        if is_external:
            btn_refresh.setEnabled(False)
        else:
            btn_refresh.clicked.connect(lambda _, r=row: self.refresh_browser(r))
        self.table_rooms.setCellWidget(row, 8, btn_refresh)

    def toggle_browser(self, btn, url):
        row = self.table_rooms.indexAt(btn.pos()).row()
        if row == -1: return
        if btn.text() == "启动":
            proc = self.open_headless_browser(url)
            if proc:
                self.pending_browsers[row] = proc
                btn.setText("关闭");
                btn.setStyleSheet("background-color: #d9534f;")
                self.table_rooms.setItem(row, 6, QTableWidgetItem("运行中"))
                self.table_rooms.item(row, 6).setForeground(QColor("green"))
        else:
            self.kill_browser(row)
            btn.setText("启动");
            btn.setStyleSheet("background-color: #568668;")
            self.table_rooms.setItem(row, 6, QTableWidgetItem("已停止"))
            self.table_rooms.item(row, 6).setForeground(QColor("black"))
            self.table_rooms.setItem(row, 1, QTableWidgetItem("待连接"))

    def kill_browser(self, row):
        if row in self.pending_browsers:
            try:
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.pending_browsers[row].pid)])
            except:
                pass
            del self.pending_browsers[row]

        target_id = None
        for r_id, info in self.room_map.items():
            if info['row'] == row:
                target_id = r_id
                if info.get('browser_proc'):
                    try:
                        subprocess.call(['taskkill', '/F', '/T', '/PID', str(info['browser_proc'].pid)])
                    except:
                        pass
                break
        if target_id: del self.room_map[target_id]

    def remove_room(self, btn, room_id):
        row = self.table_rooms.indexAt(btn.pos()).row()
        if row == -1: return
        if room_id: self.blacklisted_rooms.add(room_id)
        self.kill_browser(row)
        self.table_rooms.removeRow(row)
        for r_id in self.room_map:
            if self.room_map[r_id]['row'] > row: self.room_map[r_id]['row'] -= 1
        new_pending = {}
        for r, proc in self.pending_browsers.items():
            if r > row:
                new_pending[r - 1] = proc
            elif r < row:
                new_pending[r] = proc
        self.pending_browsers = new_pending
        for i in range(self.table_rooms.rowCount()):
            self.table_rooms.setItem(i, 0, QTableWidgetItem(str(i + 1)))

    def clear_rooms(self):
        for proc in self.pending_browsers.values():
            try:
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)])
            except:
                pass
        for r_id, info in self.room_map.items():
            if info.get('browser_proc'):
                try:
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(info['browser_proc'].pid)])
                except:
                    pass
            self.blacklisted_rooms.add(r_id)
        self.pending_browsers.clear()
        self.room_map.clear()
        self.table_rooms.setRowCount(0)

    def refresh_browser(self, row):
        url_item = self.table_rooms.item(row, 2)
        if not url_item: return
        url = url_item.text()
        if "http" not in url: return
        self.kill_browser(row)
        proc = self.open_headless_browser(url)
        if proc:
            self.pending_browsers[row] = proc
            self.table_rooms.setItem(row, 6, QTableWidgetItem("刷新中..."))

    def handle_log(self, type, text):
        if self.filters.get(type, True): self.text_log.append(text)

    def handle_data(self, data):
        room_id = data.get('room_id', 'UNKNOWN')
        msg_type = data.get('type')
        if room_id == 'UNKNOWN': return
        if room_id in self.blacklisted_rooms: return

        if room_id not in self.room_map:
            matched_row = -1
            if self.pending_browsers:
                matched_row = min(self.pending_browsers.keys())
                proc = self.pending_browsers[matched_row]
                del self.pending_browsers[matched_row]
                self.room_map[room_id] = {'row': matched_row, 'browser_proc': proc}
                self.table_rooms.setItem(matched_row, 2, QTableWidgetItem(f"ID:{room_id}"))
                self.table_rooms.setItem(matched_row, 1, QTableWidgetItem(data.get('user', '获取中...')))
                self.table_rooms.setItem(matched_row, 4, QTableWidgetItem("✅"))
            else:
                self.add_table_row(user=data.get('user', '获取中...'), room_id=room_id, is_external=True)
                row = self.table_rooms.rowCount() - 1
                self.room_map[room_id] = {'row': row, 'browser_proc': None}

        if room_id in self.room_map:
            row = self.room_map[room_id]['row']
            if msg_type == 'anchor_info':
                self.table_rooms.setItem(row, 1, QTableWidgetItem(data.get('user')))
                douyin_id = data.get('douyin_id', '')
                if douyin_id: self.table_rooms.setItem(row, 2, QTableWidgetItem(f"{douyin_id}"))
                self.card_info.lbl_name.setText(data.get('user'))
                self.card_info.lbl_id.setText(f"抖音号: {douyin_id}")
            elif "获取中" in self.table_rooms.item(row, 1).text() and data.get('user'):
                self.table_rooms.setItem(row, 1, QTableWidgetItem(f"<{data.get('user')}>"))

            container = self.table_rooms.cellWidget(row, 5)
            if container:
                cb = container.findChild(QCheckBox)
                if cb and not cb.isChecked(): return

            if msg_type in ['chat', 'gift']:
                cnt_item = self.table_rooms.item(row, 3)
                if cnt_item: self.table_rooms.setItem(row, 3, QTableWidgetItem(str(int(cnt_item.text()) + 1)))

        if msg_type not in ['discovery', 'anchor_info', 'heartbeat']:
            user = data.get('user', '')
            content = data.get('content',
                               '') if msg_type == 'chat' else f"送 {data.get('gift_name')} x{data.get('count')}"
            d_row = self.table_details.rowCount()
            self.table_details.insertRow(d_row)
            self.table_details.setItem(d_row, 0, QTableWidgetItem(str(room_id)))
            self.table_details.setItem(d_row, 1, QTableWidgetItem(user))
            self.table_details.setItem(d_row, 2, QTableWidgetItem("弹幕" if msg_type == 'chat' else "礼物"))
            self.table_details.setItem(d_row, 3, QTableWidgetItem(content))
            self.table_details.setItem(d_row, 4, QTableWidgetItem(datetime.datetime.now().strftime('%H:%M:%S')))
            if d_row > 200: self.table_details.removeRow(0)
            self.table_details.scrollToBottom()

    def closeEvent(self, event):
        # 1. 恢复系统代理
        try:
            self.proxy_manager.unset_proxy()
        except:
            pass

        # 2. 清理所有后台进程
        self.clear_rooms()

        # 3. 停止抓包线程
        if self.worker:
            self.worker.stop()

        event.accept()


# === 全局防崩: 如果直接杀进程，尝试恢复代理 (尽力而为) ===
# 注意：如果是 taskkill /F 强杀，这个可能来不及执行，所以推荐用 closeEvent
def emergency_restore():
    try:
        pm = SystemProxy()
        pm.unset_proxy()
    except:
        pass


atexit.register(emergency_restore)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
