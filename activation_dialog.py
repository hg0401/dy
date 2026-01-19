import sys
import os
import json
import requests
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QApplication
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# ================== 客户端配置 ==================
# 请将此处的 IP 地址修改为运行 app.py 服务器电脑的实际局域网 IP 或公网 IP
SERVER_API_URL = "http://106.15.109.138:5000/api/validate"


# =============================================

class VerificationWorker(QThread):
    """后台验证线程"""
    finished_signal = pyqtSignal(dict)

    def __init__(self, activation_key):
        super().__init__()
        self.activation_key = activation_key

    def run(self):
        try:
            # 构造请求 URL (app.py 使用的是 GET 请求参数)
            url = f"{SERVER_API_URL}?code={self.activation_key}"

            # 发送请求，设置超时防止卡死
            response = requests.get(url, timeout=10)

            # 检查 HTTP 状态码
            if response.status_code == 200:
                result = response.json()
                # 服务器返回的数据结构示例:
                # {"valid": true, "message": "激活成功"}
                # {"valid": false, "message": "激活码已过期"}
                self.finished_signal.emit(result)
            else:
                # 如果服务器返回非200状态（如400），尝试解析错误信息
                try:
                    error_data = response.json()
                    self.finished_signal.emit({
                        "valid": False,
                        "message": f"服务器错误: {error_data.get('error', '请求失败')}"
                    })
                except:
                    self.finished_signal.emit({
                        "valid": False,
                        "message": f"HTTP 错误: {response.status_code}"
                    })

        except requests.exceptions.ConnectionError:
            self.finished_signal.emit({
                "valid": False,
                "message": "无法连接到服务器\n请检查网络或服务器地址"
            })
        except requests.exceptions.Timeout:
            self.finished_signal.emit({
                "valid": False,
                "message": "连接超时\n请检查网络状况"
            })
        except Exception as e:
            self.finished_signal.emit({
                "valid": False,
                "message": f"网络异常: {str(e)}"
            })


class ActivationDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.setWindowTitle("公开数据处理工具 V1.2.0")
        self.setFixedSize(400, 300)
        self.setupUi()

    def setupUi(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # 图标
        icon_label = QLabel("🤖", self)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 64px; font-weight: bold;")
        main_layout.addWidget(icon_label)

        # 标题
        title_label = QLabel("公开数据处理工具\nV1.2.0", self)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            font-weight: bold;
            font-size: 24px;
            color: #333;
            margin-bottom: 20px;
        """)
        main_layout.addWidget(title_label)

        # 密钥输入框
        self.activation_input = QLineEdit(self)
        self.activation_input.setPlaceholderText("请输入激活密钥")
        self.activation_input.setStyleSheet("""
            border: 2px solid #4CAF50;
            border-radius: 8px;
            padding: 10px;
            font-size: 14px;
            background-color: white;
            margin-bottom: 15px;
        """)
        main_layout.addWidget(self.activation_input)

        # 激活按钮
        activate_btn = QPushButton("激活", self)
        activate_btn.setStyleSheet("""
            background-color: #4CAF50;
            color: white;
            border-radius: 8px;
            padding: 12px;
            font-weight: bold;
            font-size: 16px;
            margin-bottom: 10px;
        """)
        activate_btn.clicked.connect(self.start_verification)
        main_layout.addWidget(activate_btn)

        # 解绑会员按钮
        unbind_btn = QPushButton("解绑会员", self)
        unbind_btn.setStyleSheet("""
            background-color: transparent;
            color: #4CAF50;
            border: 2px solid #4CAF50;
            border-radius: 8px;
            padding: 12px;
            font-weight: bold;
            font-size: 16px;
        """)
        unbind_btn.clicked.connect(self.unbind_membership)
        main_layout.addWidget(unbind_btn)

        # 底部免责声明
        disclaimer_label = QLabel(
            "本软件仅为工具\n用户自行承担使用过程中的所有责任",
            self
        )
        disclaimer_label.setAlignment(Qt.AlignCenter)
        disclaimer_label.setStyleSheet("""
            font-size: 12px;
            color: gray;
            margin-top: 20px;
            line-height: 1.4;
        """)
        main_layout.addWidget(disclaimer_label)

    def start_verification(self):
        """启动验证流程"""
        key = self.activation_input.text().strip()
        if not key:
            QMessageBox.warning(self, "提示", "请输入激活密钥")
            return

        # 禁用按钮防止重复点击
        self.sender().setEnabled(False)

        # 启动后台线程
        self.worker = VerificationWorker(key)
        self.worker.finished_signal.connect(self.on_verification_result)
        self.worker.start()

    def on_verification_result(self, result):
        """处理服务器返回的结果"""
        # 恢复按钮状态
        for btn in self.findChildren(QPushButton):
            if btn.text() == "激活":
                btn.setEnabled(True)
                break

        # 解析服务器返回的 JSON
        # result 结构: {"valid": True/False, "message": "具体信息"}
        if result.get("valid"):
            # 激活成功：保存密钥到本地配置文件
            try:
                config_data = {
                    "activation_key": self.activation_input.text().strip(),
                    "last_verified": datetime.now().isoformat(),
                    "server_message": result.get("message", "激活成功")
                }
                with open('activation_config.json', 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)

                QMessageBox.information(self, "成功", result["message"])
                self.accept()  # 关闭对话框，返回 Accepted
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存配置失败: {str(e)}")
        else:
            # 激活失败：显示服务器返回的具体原因
            # 服务器可能返回的消息包括:
            # "激活码不存在", "激活码已失效", "激活码已过期", "次数已用完"
            QMessageBox.warning(self, "失败", result.get("message", "未知错误"))

    def unbind_membership(self):
        """解绑会员：清除本地激活状态"""
        config_path = 'activation_config.json'
        if os.path.exists(config_path):
            try:
                os.remove(config_path)
                QMessageBox.information(self, "成功", "已解绑会员，请重启软件生效。")
                self.reject()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"解绑失败：{str(e)}")
        else:
            QMessageBox.information(self, "提示", "当前未激活，无需解绑。")
            self.reject()

    def check_local_activation(self):
        """
        检查本地激活状态
        如果本地有配置文件，视为已激活（防止频繁请求服务器导致无法使用）
        """
        config_path = 'activation_config.json'
        return os.path.exists(config_path)


# # --- 测试a运行 ---
# if __name__ == '__main__':
#     app = QApplication(sys.argv)
#     dialog = ActivationDialog()
#     dialog.show()
#     sys.exit(app.exec_())