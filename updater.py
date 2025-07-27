import os
import sys
import time
import platform
import shutil
import traceback
import requests
import zipfile
import threading
from loguru import logger
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import QThread, pyqtSignal, QObject, QEventLoop
from PyQt5.uic import loadUi
from PyQt5.QtGui import QIcon
from packaging.version import Version
from qfluentwidgets import FluentWindow, FluentIcon, CaptionLabel, ProgressBar
from file import config_center

class UpdateStatus(QObject):
    status_changed = pyqtSignal(bool, str)
    def __init__(self):
        super().__init__()
        self.enabled = True
        self.text = "检查更新"
    def set(self, enabled, text):
        self.enabled = enabled
        self.text = text
        self.status_changed.emit(enabled, text)
    def get(self):
        return self.enabled, self.text

update_status = UpdateStatus()

class UnifiedUpdateThread(QThread):
    """
    统一的更新线程，只负责下载和解压，不做备份/覆盖等逻辑。
    status_signal: (enabled, text) 用于按钮状态同步
    progress_signal: 进度百分比
    finish_signal: (ok, msg) 用于通知完成
    """
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(bool, str)
    finish_signal = pyqtSignal(bool, str)

    def __init__(self, version_info=None, silent=False, parent=None):
        super().__init__(parent)
        self.version_info = version_info
        self.silent = silent

    def run(self):
        self.status_signal.emit(False, "检查更新中...")
        update_status.set(False, "检查更新中...")
        try:
            if self.version_info is None:
                from network_thread import VersionThread
                vt = VersionThread()
                loop = QEventLoop()
                def on_version(version):
                    self._on_version(version)
                    loop.quit()
                vt.version_signal.connect(on_version)
                vt.start()
                loop.exec_()
            else:
                self._on_version(self.version_info)
        except Exception as e:
            logger.error(f"更新线程异常: {e}")
            update_status.set(True, "更新失败")
            self.status_signal.emit(True, "更新失败")
            self.finish_signal.emit(False, str(e))

    def _on_version(self, version):
        try:
            channel = int(config_center.read_conf("Version", "version_channel"))
            server_version = version['version_release' if channel == 0 else 'version_beta']
            local_version = config_center.read_conf("Version", "version")
            logger.debug(f"服务端版本: {server_version}，本地版本: {local_version}")
            if Version(server_version) <= Version(local_version):
                logger.info("暂无新版本可用")
                update_status.set(True, "暂无新版本可用")
                self.status_signal.emit(True, "暂无新版本可用")
                self.finish_signal.emit(True, "无需更新")
                return

            release_info = version["releases" if channel == 0 else "releases_beta"]
            system = platform.system()
            if system == "Windows":
                system = "x64" if platform.architecture()[0] == "64bit" else "x86"
            elif system == "Darwin":
                system = "macOS"
            if system not in release_info:
                logger.info("无可用更新包")
                update_status.set(True, "无可用更新包")
                self.status_signal.emit(True, "无可用更新包")
                self.finish_signal.emit(False, "无可用更新包")
                return

            release_to_upgrade = release_info[system]
            download_url = release_to_upgrade["url"]
            self.status_signal.emit(False, "下载更新包中...")
            update_status.set(False, "下载更新包中...")
            try:
                r = requests.get(download_url, stream=True)
                total = int(r.headers.get('content-length', 0))
                zip_path = os.path.join(os.getcwd(), "updpack.zip")
                with open(zip_path, 'wb') as f:
                    downloaded = 0
                    for chunk in r.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        percent = int(downloaded / total * 100) if total else 0
                        self.progress_signal.emit(percent)
                        update_status.set(False, f"下载中 {percent}%")
                self.status_signal.emit(False, "解压更新包...")
                update_status.set(False, "解压更新包...")
                updpackage_path = os.path.join(os.getcwd(), "updpackage")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(updpackage_path)
                # 写入 update.json
                import json
                update_json_path = os.path.join(os.getcwd(), "update.json")
                update_data = {
                    "version": server_version,
                    "channel": channel,
                    "download_url": download_url,
                    "updpackage_path": updpackage_path,
                    "timestamp": time.time()
                }
                with open(update_json_path, "w", encoding="utf-8") as f:
                    json.dump(update_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"下载或解压失败: {e}")
                update_status.set(True, "下载或解压失败")
                self.status_signal.emit(True, "下载或解压失败")
                self.finish_signal.emit(False, str(e))
                return

            self.status_signal.emit(True, "下载完成")
            update_status.set(True, "下载完成")
            self.finish_signal.emit(True, "下载完成")
        except Exception as e:
            logger.error(f"版本处理异常: {e}")
            update_status.set(True, "更新失败")
            self.status_signal.emit(True, "更新失败")
            self.finish_signal.emit(False, str(e))
def start_silent_update_check():
    thread = threading.Thread(target=silent_update_check)
    thread.start()
def silent_update_check():
    try:
        update_status.set(False, "静默检测更新...")
        logger.debug("开始静默更新")
        from network_thread import VersionThread
        vt = VersionThread()
        loop = QEventLoop()
        # thread 必须提升到外部作用域，不能只在 on_version 里声明
        thread_holder = {}
        def on_version(version):
            thread = UnifiedUpdateThread(version_info=version, silent=True)
            thread_holder['thread'] = thread  # 保证 thread 不会被提前销毁
            def finish_and_quit(ok, msg):
                # 如果失败，显示错误信息
                if not ok:
                    update_status.set(True, f"更新失败：{msg}")
                else:
                    update_status.set(True, msg)
                loop.quit()
            thread.status_signal.connect(update_status.set)
            thread.progress_signal.connect(lambda p: update_status.set(False, f"下载中 {p}%"))
            thread.finish_signal.connect(finish_and_quit)
            thread.start()
        vt.version_signal.connect(on_version)
        vt.finished.connect(lambda: None)  # 不要提前退出 loop
        vt.start()
        loop.exec_()
        # loop 退出后，确保 thread 已经 finish
        thread = thread_holder.get('thread')
        if thread is not None:
            thread.wait()  # 等待线程彻底结束
        # 再次同步按钮状态，防止界面未刷新
        enabled, text = update_status.get()
        update_status.set(enabled, text)
    except Exception as e:
        logger.error(f"后台静默检测更新异常: {e}")
        update_status.set(True, f"更新失败：{e}")
        
class UpgradeProgressWindow(FluentWindow):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.upgradeui = loadUi("./view/upgrade_progress.ui")
        self.addSubInterface(self.upgradeui, FluentIcon.SYNC, "更新")
        self.resize(800, 100)
        self.setWindowIcon(QIcon("./img/logo/favicon-update.png"))
        self.setWindowTitle("更新中")
        self.upgradeprograsslabel = self.findChild(CaptionLabel, "updprogresslabel")
        self.prograssbar = self.findChild(ProgressBar, "progressBar")
    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.do_upgrade()
    def do_upgrade(self):
        self.worker.status_signal.connect(self.update_status)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finish_signal.connect(self.finish)
        self.worker.start()
    def update_status(self, enabled, text):
        self.upgradeprograsslabel.setText(text)
    def update_progress(self, percent):
        self.prograssbar.setValue(percent)
    def finish(self, ok, msg):
        # 更新完成后关闭窗口，确保线程已结束
        if self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()
        self.close()

    def closeEvent(self, event):
        # 用户直接关闭窗口时也要确保线程安全结束，但不提前退出更新流程
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()
        super().closeEvent(event)

class Updater(QThread):
    update_signal = pyqtSignal(list)
    finish_signal = pyqtSignal()
    def __init__(self, source_dir, files_to_keep='', executable = ""):
        super().__init__()
        self.source_dir = source_dir
        self.logger = logger
        self.files_to_keep = files_to_keep.split(';')
        self.executable = executable
    def backup(self):
        files_to_backup = [dir for dir in os.listdir(self.source_dir) if (dir != "backup" and dir != "updpackage" and dir != ".git")]
        total = len(files_to_backup)
        progress = 1
        shutil.rmtree(os.path.join(self.source_dir, "backup"), ignore_errors=True)
        for file in files_to_backup:
            progress += 1
            file_path = os.path.join(self.source_dir, file)
            if os.path.isdir(file_path):
                backup_path = os.path.join(self.source_dir, "backup", file)
                if not os.path.exists(backup_path):
                    shutil.copytree(file_path, backup_path)
            elif os.path.isfile(file_path):
                backup_path = os.path.join(self.source_dir, "backup", file)
                if not os.path.exists(backup_path):
                    shutil.copy2(file_path, backup_path)
            self.update_signal.emit([f"备份中{progress}/{total} {file}",progress/total*50])
        files_to_remove = [dir for dir in os.listdir(self.source_dir) if (dir != "backup" and dir != "updpackage" and dir != ".git")]
        self.total_1 = len(files_to_remove)
        self.progress_1 = 1
        for file in files_to_remove:
            self.progress_1 += 1
            file_path = os.path.join(self.source_dir, file)
            if os.path.isdir(file_path):
                shutil.rmtree(file_path, ignore_errors=True)
            elif os.path.isfile(file_path):
                os.remove(file_path)
            self.update_signal.emit([f"删除旧文件：{self.progress_1}/{self.total_1} {file}", (self.progress_1 / self.total_1 * 25)+50])
        files_to_copy = [dir for dir in os.listdir(os.path.join(self.source_dir, "updpackage")) if (dir != "backup" and dir != ".git")]
        self.total_2 = len(files_to_copy)
        self.progress_2 = 1
        for file in files_to_copy:
            self.progress_2 += 1
            src_path = os.path.join(self.source_dir, "updpackage", file)
            dst_path = os.path.join(self.source_dir, file)
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            elif os.path.isfile(src_path):
                shutil.copy2(src_path, dst_path)
            self.update_signal.emit([f"复制新文件:{self.progress_2}/{self.total_2} {file}", (self.progress_2 / self.total_2 * 20)+75])
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
        self.finish_signal.emit()
        os.execv(self.executable, [self.executable, "--finish-update"])
    def run(self):
        # 检查 update.json 是否存在，读取参数
        import json
        update_json_path = os.path.join(self.source_dir, "update.json")
        if not os.path.exists(update_json_path):
            self.logger.error("未找到 update.json，无法启动更新！")
            self.update_signal.emit(["未找到 update.json，无法启动更新！", 0])
            self.finish_signal.emit()
            return
        try:
            with open(update_json_path, "r", encoding="utf-8") as f:
                update_data = json.load(f)
            # 可以根据 update_data 内容做自定义处理
            self.backup()
        except Exception as e:
            self.logger.error("更新失败！")
            logger.error(traceback.format_exc(limit=1))
            self.update_signal.emit([f"更新失败：{e}", 0])
            self.finish_signal.emit()

def do_upgrade(version_info):
    thread = UnifiedUpdateThread(version_info=version_info, silent=False)
    # 直接用按钮显示进度，不弹窗
    thread.status_signal.connect(update_status.set)
    thread.progress_signal.connect(lambda p: update_status.set(False, f"下载中 {p}%"))
    def finish_and_quit(ok, msg):
        update_status.set(True, msg)
    thread.finish_signal.connect(finish_and_quit)
    thread.start()

def post_upgrade():
    shutil.rmtree("updpackage", ignore_errors=True)
    shutil.rmtree("backup", ignore_errors=True)

if __name__ == "__main__":
    do_upgrade(None)