import os
import sys

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QSystemTrayIcon
from loguru import logger
from PyQt5.QtCore import QSharedMemory

from file import base_directory

share = QSharedMemory('ClassWidgets')


def restart():
    logger.debug('重启程序')
    share.detach()  # 释放共享内存
    os.execl(sys.executable, sys.executable, *sys.argv)


tray_icon = None


class TrayIcon(QSystemTrayIcon):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(QIcon(f"{base_directory}/img/logo/favicon.png"))

    def push_update_notification(self, text=''):
        self.setIcon(QIcon(f"{base_directory}/img/logo/favicon-update.png"))  # tray
        self.showMessage(
            "发现 Class Widgets 新版本！",
            text,
            QIcon(f"{base_directory}/img/logo/favicon-update.png"),
            5000
        )

    def push_error_notification(self, title='检查更新失败！', text=''):
        self.setIcon(QIcon(f"{base_directory}/img/logo/favicon-error.png"))  # tray
        self.showMessage(
            title,
            text,
            QIcon(f"{base_directory}/img/logo/favicon-error.png"),
            5000
        )
