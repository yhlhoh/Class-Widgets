#import network_thread
import os
import shutil
import zipfile

import time
from loguru import logger
from PyQt5.QtWidgets import QApplication
import sys
import utils
import platform
from packaging.version import Version
from file import config_center
from loguru import logger

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QWidget
from PyQt5.uic import loadUi
from PyQt5.QtGui import QIcon
from qfluentwidgets import *


def silent_update_check():
    """
    后台静默检测更新并自动下载更新包，完成后托盘提示。
    """
    import os
    try:
        auto_check = config_center.read_conf('Version', 'auto_check_update', '1')
        if auto_check != '1':
            logger.info("未开启自动更新检测")
            return
        logger.info("后台静默检测更新...")
        from network_thread import VersionThread, GetUPDPack
        def on_version(version):
            channel = int(config_center.read_conf("Version", "version_channel"))
            server_version = version['version_release' if channel == 0 else 'version_beta']
            local_version = config_center.read_conf("Version", "version")
            logger.debug(f"服务端版本: {server_version}，本地版本: {local_version}")
            if Version(server_version) > Version(local_version):
                logger.info(f"检测到新版本 {server_version}，自动下载更新包...")
                release_info = version["releases" if channel == 0 else "releases_beta"]
                system = platform.system()
                if system == "Windows":
                    system = "x64" if platform.architecture()[0] == "64bit" else "x86"
                elif system == "Darwin":
                    system = "macOS"
                if system not in release_info:
                    logger.info("无可用更新包")
                    return
                release_to_upgrade = release_info[system]
                download_url = release_to_upgrade["url"]
                files_to_keep = ';'.join(release_to_upgrade["files_to_keep"])
                executable = os.path.join(os.getcwd(), os.path.split(release_to_upgrade["executable"])[1])
                updthread = GetUPDPack(download_url, executable, os.getcwd(), files_to_keep, executable)
                def on_finish(msg):
                    utils.tray_icon.push_update_notification(f"新版本 {server_version} 的更新已经准备好，重启应用即可自动更新。")
                    logger.info(f"新版本 {server_version} 的更新已经准备好，重启应用即可自动更新。")
                updthread.finish_signal.connect(on_finish)
                updthread.start()
            else:
                logger.info("当前已是最新版本，无需更新")
        version_thread = VersionThread()
        version_thread.version_signal.connect(on_version)
        version_thread.start()
    except Exception as e:
        logger.error(f"自动更新检测异常: {e}")
class Updater(QThread):
    update_signal = pyqtSignal(list)
    finish_signal = pyqtSignal()
    def __init__(self, source_dir, files_to_keep='', executable = ""):
        # 初始化，设置源目录、日志记录器和需要保留的文件列表
        super().__init__()
        self.source_dir = source_dir
        self.logger = logger
        self.files_to_keep = files_to_keep.split(';')

        self.executable = executable
    def backup(self):
        # 备份除 backup 和 updpackage 目录外的所有文件和文件夹
        files_to_backup = [dir for dir in os.listdir(self.source_dir) if (dir != "backup" and dir != "updpackage" and dir != ".git")]
        total = len(files_to_backup)
        progress = 1

        shutil.rmtree(os.path.join(self.source_dir, "backup"), ignore_errors=True)  # 清空旧备份
        for file in files_to_backup:
            progress += 1
            file_path = os.path.join(self.source_dir, file)
            if os.path.isdir(file_path):
                backup_path = os.path.join(self.source_dir, "backup", file)
                if not os.path.exists(backup_path):
                    shutil.copytree(file_path, backup_path)
                    self.logger.info(f"已备份 {file} -> {backup_path}")
            elif os.path.isfile(file_path):
                backup_path = os.path.join(self.source_dir, "backup", file)
                if not os.path.exists(backup_path):
                    shutil.copy2(file_path, backup_path)
                    self.logger.info(f"已备份 {file} -> {backup_path}")
            self.update_signal.emit([f"备份中{progress}/{total} {file}",progress/total*50])
        files_to_remove = [dir for dir in os.listdir(self.source_dir) if (dir != "backup" and dir != "updpackage" and dir != ".git")]
        self.total_1 = len(files_to_remove)

        self.progress_1 = 1

        for file in files_to_remove:
            self.progress_1 += 1
            file_path = os.path.join(self.source_dir, file)
            if os.path.isdir(file_path):
                shutil.rmtree(file_path, ignore_errors=True)
                self.logger.info(f"已删除目录 {file}")
            elif os.path.isfile(file_path):
                os.remove(file_path)
                self.logger.info(f"已删除文件 {file}")
            self.update_signal.emit([f"删除旧文件：{self.progress_1}/{self.total_1} {file}", (self.progress_1 / self.total_1 * 25)+50])
        # 从 updpackage 目录复制新文件到源目录
        files_to_copy = [dir for dir in os.listdir(os.path.join(self.source_dir, "updpackage")) if (dir != "backup" and dir != ".git")]
        self.total_2 = len(files_to_copy)
        self.progress_2 = 1

        for file in files_to_copy:
            self.progress_2 += 1
            src_path = os.path.join(self.source_dir, "updpackage", file)
            dst_path = os.path.join(self.source_dir, file)
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                self.logger.info(f"已更新目录 {file} -> {dst_path}")
            elif os.path.isfile(src_path):
                shutil.copy2(src_path, dst_path)
                self.logger.info(f"已更新文件 {file} -> {dst_path}")
            self.update_signal.emit([f"复制新文件:{self.progress_2}/{self.total_2} {file}", (self.progress_2 / self.total_2 * 20)+75])
        # 复制需要保留的文件到 backup 目录

        self.total_3 = len(self.files_to_keep) + 1
        self.progress_3 = 1
        for file in self.files_to_keep:
            self.progress_3 += 1
            try:
                shutil.copy(os.path.join(self.source_dir, file), os.path.join(self.source_dir, "backup", file))
                self.update_signal.emit([f"迁入配置:{self.progress_3}/{self.total_3} {file}", (self.progress_3 / self.total_3 * 5)+95])
            except:
                pass
        self.logger.info("更新完成")
        self.update_signal.emit(["更新完成，即将重启软件",100])
        time.sleep(3)
        logger.debug("完成等待")
        self.finish_signal.emit()
        # 重启程序，传递 --finish-update 参数
        os.execv(self.executable, [self.executable, "--finish-update"])
    def run(self):
        self.stage = 1
        try:
            self.backup()
            self.stage += 1
            self.update()
        except:
            import sys
            self.logger.error("更新失败！")
            import traceback
            logger.error(traceback.format_exc(limit=1))
            if self.stage == 2:
                self.update_signal.emit(["更新失败，正在回滚",100])
                # 更新失败时，清理已删除的文件和目录并回滚

                # 回滚：将 backup 目录下的文件和文件夹恢复到源目录
                backup_dir = os.path.join(self.source_dir, "backup")
                if os.path.exists(backup_dir):
                    for item in os.listdir(backup_dir):
                        src_path = os.path.join(backup_dir, item)
                        dst_path = os.path.join(self.source_dir, item)
                        if os.path.isdir(src_path):
                            if os.path.exists(dst_path):
                                shutil.rmtree(dst_path, ignore_errors=True)
                            shutil.copytree(src_path, dst_path)
                            self.logger.info(f"已回滚目录 {item} -> {dst_path}")
                        elif os.path.isfile(src_path):
                            shutil.copy2(src_path, dst_path)
                            self.logger.info(f"已回滚文件 {item} -> {dst_path}")
                    self.logger.info("回滚完成")
                    self.finish_signal.emit()
                files_to_remove = [dir for dir in os.listdir(self.source_dir) if dir != "backup" and dir != "updpackage"]
                for file in files_to_remove:
                    file_path = os.path.join(self.source_dir, file)
                    if os.path.isdir(file_path):
                        shutil.rmtree(file_path, ignore_errors=True)
                        self.logger.info(f"已删除目录 {file}")
                    elif os.path.isfile(file_path):
                        os.remove(file_path)
                        self.logger.info(f"已删除文件 {file}")
            else:
                self.update_signal.emit(["更新失败，正在删除备份",100])
                shutil.rmtree(os.path.join(self.source_dir, "backup"))
                self.finish_signal.emit()
            traceback.print_exc()

class UpgradeProgressWindow(FluentWindow):
    def __init__(self,worker,parent=None):
        super().__init__()
        self.worker = worker
        self.upgradeui = loadUi("./view/upgrade_progress.ui")
        self.addSubInterface(self.upgradeui,FluentIcon.SYNC,"更新")
        self.resize(800,100)
        self.setWindowIcon(QIcon("./img/logo/favicon-update.png"))
        self.setWindowTitle("更新中")
        self.upgradeprograsslabel = self.findChild(CaptionLabel,"updprogresslabel")
        self.prograssbar = self.findChild(ProgressBar,"progressBar")

    def showEvent(self, event): # type: ignore

        """窗口显示时触发"""
        super().showEvent(event)
        # 检查是否是首次显示
        if not hasattr(self, '_initialized'):
            self._initialized = True
            print("窗口初始化完成，首次显示")
            self.do_upgrade()
    def do_upgrade(self):
        self.worker.update_signal.connect(self.update_w)
        self.worker.finish_signal.connect(self.finish)
        self.worker.start()
    def finish(self):
        """更新完成"""
        #post_upgrade()

        self.close()
    def update_w(self, message):
        """更新进度"""
        self.upgradeprograsslabel.setText(message[0])
        self.prograssbar.setValue(message[1])
        

def do_upgrade(*params):
    worker = Updater(*params)
    app = QApplication(sys.argv)
    w = UpgradeProgressWindow(worker=worker)
    w.show()
    app.exec()
def post_upgrade():
    shutil.rmtree("updpackage", ignore_errors=True)  # 删除 updpackage 目录
    shutil.rmtree("backup",ignore_errors=True)
if __name__ == "__main__":
    do_upgrade()

