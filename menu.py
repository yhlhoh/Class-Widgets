import datetime as dt
import json
import os
import re
import platform
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from shutil import rmtree
import re
import zipfile
import shutil
import asyncio

from PyQt5 import uic, QtCore
from PyQt5.QtCore import Qt, QTime, QUrl, QDate, pyqtSignal, QSize, QThread, QObject, QTimer
from PyQt5.QtGui import QIcon, QDesktopServices, QColor
# from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtCore import Qt, pyqtSignal, QRectF
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QApplication, QHeaderView, QTableWidgetItem, QLabel, QHBoxLayout, QSizePolicy, \
    QSpacerItem, QFileDialog, QVBoxLayout, QScroller, QWidget, QFrame, QListWidgetItem, QWidget, QStyle
from packaging.version import Version
from loguru import logger
from qfluentwidgets import (
    Theme, setTheme, FluentWindow, FluentIcon as fIcon, ToolButton, ListWidget, ComboBox, CaptionLabel,
    SpinBox, LineEdit, PrimaryPushButton, TableWidget, Flyout, InfoBarIcon, InfoBar, InfoBarPosition,
    FlyoutAnimationType, NavigationItemPosition, MessageBox, SubtitleLabel, PushButton, SwitchButton,
    CalendarPicker, BodyLabel, ColorDialog, isDarkTheme, TimeEdit, EditableComboBox, MessageBoxBase,
    SearchLineEdit, Slider, PlainTextEdit, ToolTipFilter, ToolTipPosition, RadioButton, HyperlinkLabel,
    PrimaryDropDownPushButton, Action, RoundMenu, CardWidget, ImageLabel, StrongBodyLabel, TimePicker, FlyoutViewBase,
    TransparentDropDownToolButton, Dialog, SmoothScrollArea, TransparentToolButton, TableWidget, HyperlinkButton, DropDownToolButton, HyperlinkLabel, themeColor
)
from qfluentwidgets.common import themeColor
from qfluentwidgets.components.widgets import ListItemDelegate

from basic_dirs import THEME_HOME
import conf
import list_ as list_
import tip_toast
import utils
from utils import time_manager, TimeManagerFactory
import weather
import weather as wd
from conf import base_directory, load_theme_config
from cses_mgr import CSES_Converter
from generate_speech import get_tts_voices, get_voice_id_by_name, get_voice_name_by_id, get_available_engines
import generate_speech
from file import config_center, schedule_center
import file
from network_thread import VersionThread, scheduleThread, GetUPDPack
from plugin import p_loader
from plugin_plaza import PluginPlaza
import updater

# 适配高DPI缩放
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

today = TimeManagerFactory.get_instance().get_today()
plugin_plaza = None

plugin_dict = {}  # 插件字典
enabled_plugins = {}  # 启用的插件列表

morning_st = 0
afternoon_st = 0

current_week = 0

loaded_data = schedule_center.schedule_data

schedule_dict = {}  # 对应时间线的课程表
schedule_even_dict = {}  # 对应时间线的课程表（双周）

timeline_dict = {}  # 时间线字典

countdown_dict = {}


def open_plaza():
    global plugin_plaza
    if plugin_plaza is None or not plugin_plaza.isVisible():
        plugin_plaza = PluginPlaza()
        plugin_plaza.show()
        plugin_plaza.closed.connect(cleanup_plaza)
        logger.info('打开“插件广场”')
    else:
        plugin_plaza.raise_()
        plugin_plaza.activateWindow()


def cleanup_plaza():
    global plugin_plaza
    logger.info('关闭“插件广场”')
    del plugin_plaza
    plugin_plaza = None


def get_timeline():
    global loaded_data
    loaded_data = schedule_center.schedule_data
    return loaded_data['timeline']


def open_dir(path: str):
    if sys.platform.startswith('win32'):
        os.startfile(path)
    elif sys.platform.startswith('linux'):
        subprocess.run(['xdg-open', path])
    else:
        msg_box = Dialog(
            '无法打开文件夹', f'Class Widgets 在您的系统下不支持自动打开文件夹，请手动打开以下地址：\n{path}'
        )
        msg_box.yesButton.setText('好')
        msg_box.cancelButton.hide()
        msg_box.buttonLayout.insertStretch(0, 1)
        msg_box.setFixedWidth(550)
        msg_box.exec()


def switch_checked(section, key, checked):
    if checked:
        config_center.write_conf(section, key, '1')
    else:
        config_center.write_conf(section, key, '0')
    if key == 'auto_startup':
        if checked:
            conf.add_to_startup()
        else:
            conf.remove_from_startup()


def get_theme_name():
    return load_theme_config(config_center.read_conf('General', 'theme')).path.name


def load_schedule_dict(schedule, part, part_name):
    """
    加载课表字典
    """
    schedule_dict_ = {}
    for week, item in schedule.items():
        all_class = []
        count = []  # 初始化计数器
        for i in range(len(part)):
            count.append(0)
        if str(week) in loaded_data['timeline'] and loaded_data['timeline'][str(week)]:
            timeline = get_timeline()[str(week)]
        else:
            timeline = get_timeline()['default']

        for item_name, item_time in timeline.items():
            if item_name.startswith('a'):
                try:
                    if int(item_name[1]) == 0:
                        count_num = 0
                    else:
                        count_num = sum(count[:int(item_name[1])])

                    prefix = item[int(item_name[2:]) - 1 + count_num]
                    period = part_name[str(item_name[1])]
                    all_class.append(f'{prefix}-{period}')
                except IndexError or ValueError:  # 未设置值
                    prefix = '未添加'
                    period = part_name[str(item_name[1])]
                    all_class.append(f'{prefix}-{period}')
                count[int(item_name[1])] += 1
        schedule_dict_[week] = all_class
    return schedule_dict_


def convert_to_dict(data_dict_):
    data_dict = {}
    for week, item in data_dict_.items():
        cache_list = item
        replace_list = []
        for activity_num in range(len(cache_list)):
            item_info = cache_list[int(activity_num)].split('-')
            replace_list.append(item_info[0])
        data_dict[str(week)] = replace_list
    return data_dict


def se_load_item():
    global schedule_dict
    global schedule_even_dict
    global loaded_data
    loaded_data = schedule_center.schedule_data
    part_name = loaded_data.get('part_name')
    part = loaded_data.get('part')
    schedule = loaded_data.get('schedule')
    schedule_even = loaded_data.get('schedule_even')

    schedule_dict = load_schedule_dict(schedule, part, part_name)
    schedule_even_dict = load_schedule_dict(schedule_even, part, part_name)


def cd_load_item():
    global countdown_dict
    text = config_center.read_conf('Date', 'cd_text_custom').split(',')
    date = config_center.read_conf('Date', 'countdown_date').split(',')
    if len(text) != len(date):
        countdown_dict = {"Err": f"len(cd_text_custom) (={len(text)}) != len(countdown_date) (={len(date)})"}
        raise Exception(
            f"len(cd_text_custom) (={len(text)}) != len(countdown_date) (={len(date)})"f"len(cd_text_custom) (={len(text)}) != len(countdown_date) (={len(date)}) \n 请检查 config.ini [Date] 项！！")
    countdown_dict = dict(zip(date, text))


class selectCity(MessageBoxBase):  # 选择城市
    def __init__(self, parent=None):
        super().__init__(parent)
        title_label = SubtitleLabel()
        subtitle_label = BodyLabel()
        self.search_edit = SearchLineEdit()

        title_label.setText('搜索城市')
        subtitle_label.setText('请输入当地城市名进行搜索')
        self.yesButton.setText('选择此城市')  # 按钮组件汉化
        self.cancelButton.setText('取消')

        self.search_edit.setPlaceholderText('输入城市名')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.search_city)

        self.city_list = ListWidget()
        self.city_list.addItems(wd.search_by_name(''))
        self.get_selected_city()

        # 将组件添加到布局中
        self.viewLayout.addWidget(title_label)
        self.viewLayout.addWidget(subtitle_label)
        self.viewLayout.addWidget(self.search_edit)
        self.viewLayout.addWidget(self.city_list)
        self.widget.setMinimumWidth(500)
        self.widget.setMinimumHeight(600)

    def search_city(self):
        self.city_list.clear()
        self.city_list.addItems(wd.search_by_name(self.search_edit.text()))
        self.city_list.clearSelection()  # 清除选中项

    def get_selected_city(self):
        selected_city = self.city_list.findItems(
            wd.search_by_num(str(config_center.read_conf('Weather', 'city'))), QtCore.Qt.MatchFlag.MatchExactly
        )
        if selected_city:  # 若找到该城市
            item = selected_city[0]
            # 选中该项
            self.city_list.setCurrentItem(item)
            # 聚焦该项
            self.city_list.scrollToItem(item)


class licenseDialog(MessageBoxBase):  # 显示软件许可协议
    def __init__(self, parent=None):
        super().__init__(parent)
        title_label = SubtitleLabel()
        subtitle_label = BodyLabel()
        self.license_text = PlainTextEdit()

        title_label.setText('软件许可协议')
        subtitle_label.setText('此项目 (Class Widgets) 基于 GPL-3.0 许可证授权发布，详情请参阅：')
        self.yesButton.setText('好')  # 按钮组件汉化
        self.cancelButton.hide()
        self.buttonLayout.insertStretch(0, 1)
        self.license_text.setPlainText(open('LICENSE', 'r', encoding='utf-8').read())
        self.license_text.setReadOnly(True)

        # 将组件添加到布局中
        self.viewLayout.addWidget(title_label)
        self.viewLayout.addWidget(subtitle_label)
        self.viewLayout.addWidget(self.license_text)
        self.widget.setMinimumWidth(600)
        self.widget.setMinimumHeight(500)


class PluginSettingsDialog(MessageBoxBase):  # 插件设置对话框
    def __init__(self, plugin_dir=None, parent=None):
        if plugin_dir not in p_loader.plugins_settings:
            return
            
        super().__init__(parent)
        self.plugin_widget = None
        self.plugin_dir = plugin_dir
        self.parent = parent
        self.init_ui()

    def init_ui(self):
        # 加载已定义的UI
        self.plugin_widget = p_loader.plugins_settings[self.plugin_dir]
        self.viewLayout.addWidget(self.plugin_widget)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)

        self.cancelButton.hide()
        self.buttonLayout.insertStretch(0, 1)

        self.widget.setMinimumWidth(875)
        self.widget.setMinimumHeight(625)


class PluginCard(CardWidget):  # 插件卡片
    def __init__(
            self, icon, title='Unknown', content='Unknown', version='1.0.0', plugin_dir='', author=None, parent=None,
            enable_settings=None, url=''
    ):
        super().__init__(parent)
        icon_radius = 5
        self.plugin_dir = plugin_dir
        self.title = title
        self.parent = parent
        self.url = url
        self.enable_settings = enable_settings

        self.iconWidget = ImageLabel(icon)  # 插件图标
        self.titleLabel = StrongBodyLabel(title, self)  # 插件名
        self.versionLabel = BodyLabel(version, self)  # 插件版本
        self.authorLabel = BodyLabel(author, self)  # 插件作者
        self.contentLabel = CaptionLabel(content, self)  # 插件描述
        self.enableButton = SwitchButton()
        self.moreButton = TransparentDropDownToolButton()
        self.moreMenu = RoundMenu(parent=self.moreButton)
        self.settingsBtn = TransparentToolButton()  # 设置按钮
        self.settingsBtn.hide()

        self.hBoxLayout = QHBoxLayout()
        self.hBoxLayout_Title = QHBoxLayout()
        self.vBoxLayout = QVBoxLayout()

        menu_actions = [
            Action(
                fIcon.FOLDER, f'打开“{title}”插件文件夹',
                triggered=lambda: open_dir(os.path.join(base_directory, conf.PLUGINS_DIR, self.plugin_dir))
            )
        ]
        if self.url:
            menu_actions.append(
                Action(
                    fIcon.LINK, f'访问“{title}”插件页面',
                    triggered=lambda: QDesktopServices.openUrl(QUrl(self.url))
                )
            )
        menu_actions.append(
            Action(
                fIcon.DELETE, f'卸载“{title}”插件',
                triggered=self.remove_plugin
            )
        )
        self.moreMenu.addActions(menu_actions)

        plugin_config = conf.load_plugin_config()
        is_temp_disabled = plugin_dir in plugin_config.get('temp_disabled_plugins', [])
        
        if plugin_dir in enabled_plugins['enabled_plugins']:  # 插件是否启用
            self.enableButton.setChecked(True)
            if enable_settings and plugin_dir in p_loader.plugins_settings:
                self.moreMenu.addSeparator()
                self.moreMenu.addAction(Action(fIcon.SETTING, f'"{title}"插件设置', triggered=self.show_settings))
                self.settingsBtn.show()
        if is_temp_disabled:
            self.enableButton.setEnabled(False)
            self.enableButton.setChecked(False)
            self.enableButton.setToolTip('此插件被临时禁用,重启后将尝试重新加载')
            self.titleLabel.setText(f'{title} (已临时禁用)')
            self.titleLabel.setStyleSheet('color: #999999;')

        self.setFixedHeight(73)
        self.iconWidget.setFixedSize(48, 48)
        self.moreButton.setFixedSize(34, 34)
        self.iconWidget.setBorderRadius(icon_radius, icon_radius, icon_radius, icon_radius)  # 圆角
        self.contentLabel.setTextColor("#606060", "#d2d2d2")
        self.contentLabel.setMaximumWidth(500)
        self.contentLabel.setWordWrap(True)  # 自动换行
        self.versionLabel.setTextColor("#999999", "#999999")
        self.authorLabel.setTextColor("#606060", "#d2d2d2")
        self.enableButton.checkedChanged.connect(self.set_enable)
        self.enableButton.setOffText('禁用')
        self.enableButton.setOnText('启用')
        self.moreButton.setMenu(self.moreMenu)
        self.settingsBtn.setIcon(fIcon.SETTING)
        self.settingsBtn.clicked.connect(self.show_settings)

        self.hBoxLayout.setContentsMargins(20, 11, 11, 11)
        self.hBoxLayout.setSpacing(15)
        self.hBoxLayout.addWidget(self.iconWidget)

        # 内容
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addLayout(self.hBoxLayout_Title)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        self.vBoxLayout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout, 1)  # !!!

        # 标题栏
        self.hBoxLayout_Title.setSpacing(12)
        self.hBoxLayout_Title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.hBoxLayout_Title.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hBoxLayout_Title.addWidget(self.authorLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hBoxLayout_Title.addWidget(self.versionLabel, 0, Qt.AlignmentFlag.AlignVCenter)

        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addWidget(self.settingsBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addWidget(self.enableButton, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addWidget(self.moreButton, 0, Qt.AlignmentFlag.AlignRight)
        self.setLayout(self.hBoxLayout)

    def set_enable(self):
        global enabled_plugins
        if self.enableButton.isChecked():
            enabled_plugins['enabled_plugins'].append(self.plugin_dir)
            conf.save_plugin_config(enabled_plugins)
        else:
            enabled_plugins['enabled_plugins'].remove(self.plugin_dir)
            conf.save_plugin_config(enabled_plugins)

    def show_settings(self):
        w = PluginSettingsDialog(self.plugin_dir, self.parent)
        if w:
            w.exec()

    def remove_plugin(self):
        alert = MessageBox(f"您确定要删除插件“{self.title}”吗？", "删除此插件后，将无法恢复。", self.parent)
        alert.yesButton.setText('永久删除')
        alert.yesButton.setStyleSheet("""
                PushButton{
                    border-radius: 5px;
                    padding: 5px 12px 6px 12px;
                    outline: none;
                }
                PrimaryPushButton{
                    color: white;
                    background-color: #FF6167;
                    border: 1px solid #FF8585;
                    border-bottom: 1px solid #943333;
                }
                PrimaryPushButton:hover{
                    background-color: #FF7E83;
                    border: 1px solid #FF8084;
                    border-bottom: 1px solid #B13939;
                }
                PrimaryPushButton:pressed{
                    color: rgba(255, 255, 255, 0.63);
                    background-color: #DB5359;
                    border: 1px solid #DB5359;
                }
            """)
        alert.cancelButton.setText('我再想想……')
        if alert.exec():
            success = p_loader.delete_plugin(self.plugin_dir)
            if success:
                try:
                    with open(f'{base_directory}/plugins/plugins_from_pp.json', 'r', encoding='utf-8') as f:
                        installed_data = json.load(f)
                    installed_plugins = installed_data.get('plugins', [])
                    if self.plugin_dir in installed_plugins:
                        installed_plugins.remove(self.plugin_dir)
                        conf.save_installed_plugin(installed_plugins)
                except Exception as e:
                    logger.error(f"更新已安装插件列表失败: {e}")

                InfoBar.success(
                    title='卸载成功',
                    content=f'插件 “{self.title}” 已卸载。请重启 Class Widgets 以完全移除。',
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    duration=5000,
                    parent=self.window()
                )
                self.deleteLater()  # 删除卡片
            else:
                InfoBar.error(
                    title='卸载失败',
                    content=f'卸载插件 “{self.title}” 时出错，请查看日志获取详细信息。',
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    duration=5000,
                    parent=self.window()
                )


class TextFieldMessageBox(MessageBoxBase):
    """ Custom message box """

    def __init__(
            self, parent=None, title='标题', text='请输入内容', default_text='', enable_check = False, check_func = None):
        super().__init__(parent)
        self.fail_color = (QColor('#c42b1c'), QColor('#ff99a4'))
        self.success_color = (QColor('#0f7b0f'), QColor('#6ccb5f'))
        self.check_list = enable_check

        self.titleLabel = SubtitleLabel()
        self.titleLabel.setText(title)
        self.subtitleLabel = BodyLabel()
        self.subtitleLabel.setText(text)
        self.textField = LineEdit()
        self.tipsLabel = CaptionLabel()
        self.tipsLabel.setText('')
        self.yesButton.setText('确定')
        self.check_func = check_func

        self.fieldLayout = QVBoxLayout()
        self.textField.setPlaceholderText(default_text)
        self.textField.setClearButtonEnabled(True)
        if enable_check:
            self.textField.textChanged.connect(self.check_text)
            self.yesButton.setEnabled(False)

        # 将组件添加到布局中
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.subtitleLabel)
        self.viewLayout.addLayout(self.fieldLayout)
        self.fieldLayout.addWidget(self.textField)
        self.fieldLayout.addWidget(self.tipsLabel)

        # 设置对话框的最小宽度
        self.widget.setMinimumWidth(350)

    def check_text(self):
        self.tipsLabel.setTextColor(self.fail_color[0], self.fail_color[1])
        self.yesButton.setEnabled(False)
        if self.textField.text() == '':
            self.tipsLabel.setText('不能为空值啊 ( •̀ ω •́ )✧')
            return
        if f'{self.textField.text()}.json' in self.check_list:
            self.tipsLabel.setText('不可以和之前的课程名重复哦 o(TヘTo)')
            return
        if not (self.check_func is None):
            is_valid, message = self.check_func(self.textField.text())
            if not is_valid:
                self.tipsLabel.setText(message)
                return 

        self.yesButton.setEnabled(True)
        self.tipsLabel.setTextColor(self.success_color[0], self.success_color[1])
        self.tipsLabel.setText('很好！就这样！ヾ(≧▽≦*)o')


class TTSVoiceLoaderThread(QThread):
    voicesLoaded = pyqtSignal(list)
    errorOccurred = pyqtSignal(str)
    previewFinished = pyqtSignal(bool)

    def __init__(self, engine_filter=None, parent=None):
        super().__init__(parent)
        self.engine_filter = engine_filter

    def run(self):
        try:
            if self.engine_filter == "pyttsx3" and platform.system() != "Windows":
                logger.warning("当前系统不是Windows,跳过pyttsx3 TTS预览")
                self.previewFinished.emit(False)
                return
            if self.isInterruptionRequested():
                return
            if self.engine_filter == "pyttsx3" and platform.system() != "Windows":
                logger.warning("当前系统不是Windows,跳过pyttsx3语音加载")
                self.voicesLoaded.emit([])
                return
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            available_voices, error_message = loop.run_until_complete(get_tts_voices(engine_filter=self.engine_filter))
            loop.close()
            if self.isInterruptionRequested():
                return

            if error_message:
                self.errorOccurred.emit(error_message)
            else:
                self.voicesLoaded.emit(available_voices)
        except Exception as e:
            logger.error(f"加载TTS语音列表时出错: {e}")
            self.errorOccurred.emit(str(e))


class TTSPreviewThread(QThread):
    previewFinished = pyqtSignal(bool)
    previewError = pyqtSignal(str)

    def __init__(self, text, engine, voice, parent=None):
        super().__init__(parent)
        self.text = text
        self.engine = engine
        self.voice = voice

    def run(self):
        try:
            if self.engine == "pyttsx3" and platform.system() != "Windows":
                logger.warning("当前系统不是Windows，跳过pyttsx3 TTS预览。")
                self.previewFinished.emit(False)
                return
            if self.isInterruptionRequested():
                logger.info("TTS预览线程收到中断请求，正在退出...")
                return
                
            from generate_speech import generate_speech_sync, TTSEngine
            from play_audio import play_audio
            import os
            
            logger.info(f"使用引擎 {self.engine} 生成预览语音")
            audio_file = generate_speech_sync(
                text=self.text,
                engine=self.engine,
                voice=self.voice,
                auto_fallback=True,
                timeout=10.0
            )
            
            # 再次检查是否有中断请求
            if self.isInterruptionRequested():
                logger.info("TTS预览线程收到中断请求，正在退出...")
                # 删除已生成的音频文件
                TTSEngine.delete_audio_file(audio_file)
                return
            
            # 检查文件是否存在且有效
            if not os.path.exists(audio_file):
                raise FileNotFoundError(f"生成的音频文件不存在: {audio_file}")
                
            # 检查文件大小是否正常（小于10字节的文件可能是损坏的）
            file_size = os.path.getsize(audio_file)
            if file_size < 10:
                logger.warning(f"生成的音频文件可能无效，大小仅为 {file_size} 字节: {audio_file}")
                # 删除可能损坏的文件
                TTSEngine.delete_audio_file(audio_file)
                raise ValueError(f"生成的音频文件可能无效，大小仅为 {file_size} 字节")
                
            play_audio(audio_file, tts_delete_after=True)
            self.previewFinished.emit(True)
        except Exception as e:
            logger.error(f"TTS预览生成失败: {str(e)}")
            self.previewError.emit(str(e))


class SettingsMenu(FluentWindow):
    closed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.tts_voice_loader_thread = None
        self.button_clear_log = None
        self.version_thread = None
        self.engine_selector = None # TTS引擎选择器
        self.current_loaded_engine = config_center.read_conf('TTS', 'engine') # 加载的TTS引擎

        # 创建子页面
        self.spInterface = uic.loadUi(f'{base_directory}/view/menu/preview.ui')  # 预览
        self.spInterface.setObjectName("spInterface")
        self.teInterface = uic.loadUi(f'{base_directory}/view/menu/timeline_edit.ui')  # 时间线编辑
        self.teInterface.setObjectName("teInterface")
        self.seInterface = uic.loadUi(f'{base_directory}/view/menu/schedule_edit.ui')  # 课程表编辑
        self.seInterface.setObjectName("seInterface")
        self.cdInterface = uic.loadUi(f'{base_directory}/view/menu/countdown_custom_edit.ui')  # 倒计日编辑
        self.cdInterface.setObjectName("cdInterface")
        self.adInterface = uic.loadUi(f'{base_directory}/view/menu/advance.ui')  # 高级选项
        self.adInterface.setObjectName("adInterface")
        self.ifInterface = uic.loadUi(f'{base_directory}/view/menu/about.ui')  # 关于
        self.ifInterface.setObjectName("ifInterface")
        self.ctInterface = uic.loadUi(f'{base_directory}/view/menu/custom.ui')  # 自定义
        self.ctInterface.setObjectName("ctInterface")
        self.cfInterface = uic.loadUi(f'{base_directory}/view/menu/configs.ui')  # 配置文件
        self.cfInterface.setObjectName("cfInterface")
        self.sdInterface = uic.loadUi(f'{base_directory}/view/menu/sound.ui')  # 通知
        self.sdInterface.setObjectName("sdInterface")
        self.hdInterface = uic.loadUi(f'{base_directory}/view/menu/help.ui')  # 帮助
        self.hdInterface.setObjectName("hdInterface")
        self.plInterface = uic.loadUi(f'{base_directory}/view/menu/plugin_mgr.ui')  # 插件
        self.plInterface.setObjectName("plInterface")
        self.version_number_label = self.ifInterface.findChild(QLabel, 'version_number_label')
        self.build_commit_label = self.ifInterface.findChild(QLabel, 'build_commit_label')
        self.build_uuid_label = self.ifInterface.findChild(QLabel, 'build_uuid_label')
        self.build_date_label = self.ifInterface.findChild(QLabel, 'build_date_label')

        self.init_nav()
        self.init_window()

    def init_font(self):  # 设置字体
        self.setStyleSheet("""QLabel {
                    font-family: 'Microsoft YaHei';
                }""")

    def load_all_item(self):
        self.setup_timeline_edit()
        self.setup_schedule_edit()
        self.setup_schedule_preview()
        self.setup_advance_interface()
        self.setup_about_interface()
        self.setup_customization_interface()
        self.setup_configs_interface()
        self.setup_sound_interface()
        self.setup_help_interface()
        self.setup_plugin_mgr_interface()
        self.setup_countdown_edit()

    # 初始化界面
    def setup_plugin_mgr_interface(self):
        pm_scroll = self.findChild(SmoothScrollArea, 'pm_scroll')
        QScroller.grabGesture(pm_scroll.viewport(), QScroller.LeftMouseButtonGesture)  # 触摸屏适配

        global plugin_dict, enabled_plugins
        enabled_plugins = conf.load_plugin_config()  # 加载启用的插件
        plugin_dict = (conf.load_plugins())  # 加载插件信息

        self.plugin_search = self.findChild(SearchLineEdit, 'plugin_search')
        self.filter_combo = self.findChild(ComboBox, 'filter_combo')
        self.refresh_btn = self.findChild(ToolButton, 'refresh_btn')
        self.import_plugin_btn = self.findChild(PushButton, 'import_plugin_btn')
        self.plugin_count_label = self.findChild(CaptionLabel, 'plugin_count_label')
        self.plugin_card_layout = self.findChild(QVBoxLayout, 'plugin_card_layout')
        self.tips_plugin_empty = self.findChild(QLabel, 'tips_plugin_empty')
        self.all_plugin_cards = []
        self.filter_combo.addItems(['全部插件', '已启用', '已禁用', '有设置项', '无设置项'])
        self.refresh_btn.setIcon(fIcon.SYNC)
        self.plugin_search.textChanged.connect(self.filter_plugins)
        self.filter_combo.currentTextChanged.connect(self.filter_plugins)
        self.refresh_btn.clicked.connect(self.refresh_plugin_list)
        self.import_plugin_btn.clicked.connect(self.import_plugin_from_file)

        open_pp = self.findChild(PushButton, 'open_plugin_plaza')
        open_pp.clicked.connect(open_plaza)  # 打开插件广场

        open_pp2 = self.findChild(PushButton, 'open_plugin_plaza_2')
        open_pp2.clicked.connect(open_plaza)  # 打开插件广场

        auto_delay = self.findChild(SpinBox, 'auto_delay')
        auto_delay.setValue(int(config_center.read_conf('Plugin', 'auto_delay')))
        auto_delay.valueChanged.connect(
            lambda: config_center.write_conf('Plugin', 'auto_delay', str(auto_delay.value())))
        # 设置自动化延迟

        open_plugin_folder = self.findChild(PushButton, 'open_plugin_folder')
        open_plugin_folder.clicked.connect(lambda: open_dir(os.path.join(base_directory, conf.PLUGINS_DIR)))  # 打开插件目录

        # 安全插件加载开关
        switch_safe_plugin = self.findChild(SwitchButton, 'switch_safe_plugin')
        switch_safe_plugin.setChecked(int(config_center.read_conf('Other', 'safe_plugin')))
        switch_safe_plugin.checkedChanged.connect(
            lambda checked: switch_checked('Other', 'safe_plugin', checked)
        )

        if not p_loader.plugins_settings:  # 若插件设置为空
            p_loader.load_plugins()  # 加载插件设置

        self.load_plugin_cards()
        self.update_plugin_count()

    def load_plugin_cards(self):
        """加载插件卡片"""
        self.clear_plugin_cards()
        container_widget = self.plugin_card_layout.parentWidget()
        if container_widget:
            container_widget.setUpdatesEnabled(False)
        
        for plugin in plugin_dict:
            if (Path(conf.PLUGINS_DIR) / plugin / 'icon.png').exists():  # 若插件目录存在icon.png
                icon_path = f'{base_directory}/plugins/{plugin}/icon.png'
            else:
                icon_path = f'{base_directory}/img/settings/plugin-icon.png'
            card = PluginCard(
                icon=icon_path,
                title=plugin_dict[plugin]['name'],
                version=plugin_dict[plugin]['version'],
                author=plugin_dict[plugin]['author'],
                plugin_dir=plugin,
                content=plugin_dict[plugin]['description'],
                enable_settings=plugin_dict[plugin]['settings'],
                url=plugin_dict[plugin].get('url', ''),
                parent=self
            )
            self.all_plugin_cards.append(card)
            self.plugin_card_layout.addWidget(card)

        if plugin_dict:
            self.tips_plugin_empty.hide()
        else:
            self.tips_plugin_empty.show()
        if container_widget:
            container_widget.setUpdatesEnabled(True)
    
    def clear_plugin_cards(self):
        """清空插件卡片"""
        container_widget = self.plugin_card_layout.parentWidget()
        if container_widget:
            container_widget.setUpdatesEnabled(False)
        for card in self.all_plugin_cards:
            card.hide()
            self.plugin_card_layout.removeWidget(card)
            card.deleteLater()
        self.all_plugin_cards.clear()
        if container_widget:
            container_widget.setUpdatesEnabled(True)
    
    def update_plugin_count(self):
        """更新计数显示"""
        total_count = len(plugin_dict)
        enabled_count = len([p for p in plugin_dict if plugin_dict[p]['name'] in enabled_plugins])
        self.plugin_count_label.setText(f'已安装 {total_count} 个插件，已启用 {enabled_count} 个')
    
    def filter_plugins(self):
        """根据搜索条件和过滤器过滤插件"""
        search_text = self.plugin_search.text().lower()
        filter_type = self.filter_combo.currentText()
        
        visible_count = 0
        valid_cards = []
        for card in self.all_plugin_cards:
            try:
                _ = card.title
                valid_cards.append(card)
            except RuntimeError:
                continue
        self.all_plugin_cards = valid_cards
        
        for card in self.all_plugin_cards:
            should_show = True
            if search_text:
                plugin_name = card.title.lower()
                plugin_author = card.authorLabel.text().lower() if card.authorLabel.text() else ''
                plugin_desc = card.contentLabel.text().lower()
                if not (search_text in plugin_name or search_text in plugin_author or search_text in plugin_desc):
                    should_show = False
            if should_show and filter_type != '全部插件':
                is_enabled = card.plugin_dir in enabled_plugins.get('enabled_plugins', [])
                has_settings = bool(card.enable_settings)
                if filter_type == '已启用' and not is_enabled:
                    should_show = False
                elif filter_type == '已禁用' and is_enabled:
                    should_show = False
                elif filter_type == '有设置项' and not has_settings:
                    should_show = False
                elif filter_type == '无设置项' and has_settings:
                    should_show = False
            card.setVisible(should_show)
            if should_show:
                visible_count += 1
        if visible_count == 0:
            self.tips_plugin_empty.setText('没有找到匹配的插件')
            self.tips_plugin_empty.show()
        else:
            self.tips_plugin_empty.hide()
    
    def refresh_plugin_list(self):
        """刷新插件列表"""
        global plugin_dict, enabled_plugins
        enabled_plugins = conf.load_plugin_config()
        plugin_dict = conf.load_plugins()
        self.load_plugin_cards()
        self.update_plugin_count()
        self.filter_plugins()
        InfoBar.success(
            title='刷新完成',
            content='插件列表已刷新',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=3000,
            parent=self.window()
        )
    
    def import_plugin_from_file(self):
        """从文件导入插件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            '选择插件文件', 
            '', 
            'ZIP文件 (*.zip);;JSON配置文件 (*.json);;所有文件 (*)'
        )
        if not file_path:
            return
        try:
            if file_path.endswith('.json') and os.path.basename(file_path) == 'plugin.json':
                self._import_from_plugin_json(file_path)
            else:
                self._import_from_zip(file_path)
                
        except Exception as e:
            logger.error(f"插件导入失败 - 未知错误: {file_path}, 错误类型: {type(e).__name__}, 错误详情: {str(e)}")
            self._show_error_dialog(f'导入插件时发生错误：{str(e)}')
    
    def _import_from_plugin_json(self, json_file_path):
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                plugin_info = json.loads(f.read())
            plugin_name = plugin_info.get('name', '未知插件')
            source_dir = os.path.dirname(json_file_path)
            plugin_dir_name = os.path.basename(source_dir)
            target_dir = os.path.join(base_directory, conf.PLUGINS_DIR, plugin_dir_name)
            if os.path.exists(target_dir):
                reply = MessageBox(
                    '插件已存在', 
                    f'插件 "{plugin_name}" 已存在，是否覆盖？', 
                    self
                ).exec_()
                if reply != MessageBox.Yes:
                    return
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            self.refresh_plugin_list()
            w = MessageBox(
                '导入成功', 
                f'插件 "{plugin_name}" 导入成功！\n重启应用后生效。', 
                self
            )
            w.yesButton.setText('好')
            w.cancelButton.hide()
            w.exec_()
            
        except json.JSONDecodeError as e:
            logger.error(f"插件导入失败 - JSON配置文件格式错误: {json_file_path}, 错误详情: {str(e)}")
            self._show_error_dialog('插件配置文件格式错误')
        except Exception as e:
            logger.error(f"插件导入失败 - 文件夹复制错误: {json_file_path}, 错误详情: {str(e)}")
            self._show_error_dialog(f'复制插件文件夹时发生错误：{str(e)}')
    
    def _import_from_zip(self, zip_file_path):
        try:
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                if 'plugin.json' not in zip_ref.namelist():
                    self._show_error_dialog('无效的插件文件：缺少 plugin.json 配置文件')
                    return
                with zip_ref.open('plugin.json') as f:
                    plugin_info = json.loads(f.read().decode('utf-8'))
                plugin_name = plugin_info.get('name', '未知插件')
                plugin_dir_name = os.path.splitext(os.path.basename(zip_file_path))[0]
                target_dir = os.path.join(base_directory, conf.PLUGINS_DIR, plugin_dir_name)
                if os.path.exists(target_dir):
                    reply = MessageBox(
                        '插件已存在', 
                        f'插件 "{plugin_name}" 已存在，是否覆盖？', 
                        self
                    ).exec_()
                    if reply != MessageBox.Yes:
                        return
                    shutil.rmtree(target_dir)
                zip_ref.extractall(target_dir)
                self.refresh_plugin_list()
                w = MessageBox(
                    '导入成功', 
                    f'插件 "{plugin_name}" 导入成功！\n重启应用后生效。', 
                    self
                )
                w.yesButton.setText('好')
                w.cancelButton.hide()
                w.exec_()
                
        except zipfile.BadZipFile as e:
            logger.error(f"插件导入失败 - 无效的ZIP文件: {zip_file_path}, 错误详情: {str(e)}")
            self._show_error_dialog('无效的ZIP文件')
        except json.JSONDecodeError as e:
            logger.error(f"插件导入失败 - JSON配置文件格式错误: {zip_file_path}, 错误详情: {str(e)}")
            self._show_error_dialog('插件配置文件格式错误')

    def _show_error_dialog(self, message):
        w = MessageBox('错误', message, self)
        w.yesButton.setText('好')
        w.yesButton.setStyleSheet("""
            PushButton{
                border-radius: 5px;
                padding: 5px 12px 6px 12px;
                outline: none;
            }
            PrimaryPushButton{
                color: white;
                background-color: #FF6167;
                border: 1px solid #FF8585;
                border-bottom: 1px solid #943333;
            }
            PrimaryPushButton:hover{
                background-color: #FF7E83;
                border: 1px solid #FF8084;
                border-bottom: 1px solid #B13939;
            }
            PrimaryPushButton:pressed{
                color: rgba(255, 255, 255, 0.63);
                background-color: #DB5359;
                border: 1px solid #DB5359;
            }
        """)
        w.cancelButton.hide()
        w.exec_()

    def setup_help_interface(self):
        open_by_browser = self.findChild(PushButton, 'open_by_browser')
        open_by_browser.setIcon(fIcon.LINK)
        open_by_browser.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            'https://classwidgets.rinlit.cn/docs-user/'
        )))

    def setup_sound_interface(self):
        sd_scroll = self.findChild(SmoothScrollArea, 'sd_scroll')  # 触摸屏适配
        QScroller.grabGesture(sd_scroll.viewport(), QScroller.LeftMouseButtonGesture)

        switch_enable_toast = self.findChild(SwitchButton, 'switch_enable_attend')
        switch_enable_toast.setChecked(int(config_center.read_conf('Toast', 'attend_class')))
        switch_enable_toast.checkedChanged.connect(lambda checked: switch_checked('Toast', 'attend_class', checked))
        # 上课提醒开关

        switch_enable_finish = self.findChild(SwitchButton, 'switch_enable_finish')
        switch_enable_finish.setChecked(int(config_center.read_conf('Toast', 'finish_class')))
        switch_enable_finish.checkedChanged.connect(lambda checked: switch_checked('Toast', 'finish_class', checked))
        # 下课提醒开关

        switch_enable_finish = self.findChild(SwitchButton, 'switch_enable_schoolout')
        switch_enable_finish.setChecked(int(config_center.read_conf('Toast', 'after_school')))
        switch_enable_finish.checkedChanged.connect(lambda checked: switch_checked('Toast', 'after_school', checked))
        # 放学提醒开关

        switch_enable_prepare = self.findChild(SwitchButton, 'switch_enable_prepare')
        switch_enable_prepare.setChecked(int(config_center.read_conf('Toast', 'prepare_class')))
        switch_enable_prepare.checkedChanged.connect(lambda checked: switch_checked('Toast', 'prepare_class', checked))
        # 预备铃开关

        switch_enable_pin_toast = self.findChild(SwitchButton, 'switch_enable_pin_toast')
        switch_enable_pin_toast.setChecked(int(config_center.read_conf('Toast', 'pin_on_top')))
        switch_enable_pin_toast.checkedChanged.connect(lambda checked: switch_checked('Toast', 'pin_on_top', checked))
        # 置顶开关

        slider_volume = self.findChild(Slider, 'slider_volume')
        slider_volume.setValue(int(config_center.read_conf('Audio', 'volume')))
        slider_volume.valueChanged.connect(self.save_volume)  # 音量滑块

        preview_toast_button = self.findChild(PrimaryDropDownPushButton, 'preview')

        pre_toast_menu = RoundMenu(parent=preview_toast_button)
        pre_toast_menu.addActions([
            Action(fIcon.EDUCATION, '上课提醒',
                   triggered=lambda: tip_toast.push_notification(1, lesson_name='信息技术')),
            Action(fIcon.CAFE, '下课提醒',
                   triggered=lambda: tip_toast.push_notification(0, lesson_name='信息技术')),
            Action(fIcon.BOOK_SHELF, '预备提醒',
                   triggered=lambda: tip_toast.push_notification(3, lesson_name='信息技术')),
            Action(fIcon.CODE, '其他提醒',
                   triggered=lambda: tip_toast.push_notification(4, title='通知', subtitle='测试通知示例',
                                                                 content='这是一条测试通知ヾ(≧▽≦*)o'))
        ])
        preview_toast_button.setMenu(pre_toast_menu)  # 预览通知栏

        switch_wave_effect = self.findChild(SwitchButton, 'switch_enable_wave')
        switch_wave_effect.setChecked(int(config_center.read_conf('Toast', 'wave')))
        switch_wave_effect.checkedChanged.connect(lambda checked: switch_checked('Toast', 'wave', checked))  # 波纹开关

        spin_prepare_time = self.findChild(SpinBox, 'spin_prepare_class')
        spin_prepare_time.setValue(int(config_center.read_conf('Toast', 'prepare_minutes')))
        spin_prepare_time.valueChanged.connect(self.save_prepare_time)  # 准备时间

        # TTS
        tts_settings = self.findChild(PushButton, 'TTS_PushButton')
        tts_settings.clicked.connect(self.open_tts_settings)
        self.available_voices = None
        self.current_loaded_engine = config_center.read_conf('TTS', 'engine') # 加载的TTS引擎

        self.voice_selector = None
        self.switch_enable_TTS = None

    def available_voices_cnt(self, voices):
        self.available_voices = voices
        if hasattr(self, 'voice_selector') and self.voice_selector and hasattr(self, 'update_tts_voices') and self.TTSSettingsDialog and not self.TTSSettingsDialog.isHidden():
            self.update_tts_voices(self.available_voices)
        self.switch_enable_TTS.setEnabled(True if voices else False)
        self.voice_selector.setEnabled(True if voices else False)

    class TTSSettings(MessageBoxBase): # TTS设置页
        def __init__(self, parent=None):
            super().__init__(parent)
            self.parent_menu = parent # 保存父菜单的引用
            self.temp_widget = QWidget()
            ui_path = f'{base_directory}/view/menu/tts_settings.ui'
            uic.loadUi(ui_path, self.temp_widget)
            self.viewLayout.addWidget(self.temp_widget)

            self.viewLayout.setContentsMargins(0, 0, 0, 0)
            self.cancelButton.hide()
            self.widget.setMinimumWidth(parent.width()//3*2)
            self.widget.setMinimumHeight(parent.height())
            switch_enable_TTS = self.widget.findChild(SwitchButton, 'switch_enable_tts')
            slider_speed_tts = self.widget.findChild(Slider, 'slider_tts_speed')
            tts_enabled = int(config_center.read_conf('TTS', 'enable'))
            switch_enable_TTS.setChecked(tts_enabled)
            slider_speed_tts.setValue(int(config_center.read_conf('TTS', 'speed')))

            switch_enable_TTS.checkedChanged.connect(parent.toggle_tts_settings)
            slider_speed_tts.valueChanged.connect(parent.save_tts_speed)

            voice_selector = self.widget.findChild(ComboBox, 'voice_selector')
            voice_selector.clear()
            voice_selector.addItem("加载中...", userData=None)
            voice_selector.setEnabled(False)
            switch_enable_TTS.setEnabled(False)

            # TTS引擎选择器
            parent.engine_selector = self.widget.findChild(ComboBox, 'engine_selector')
            if not parent.engine_selector:
                parent.engine_selector = ComboBox(self.widget)
            parent.populate_tts_engines()
            parent.engine_selector.currentTextChanged.connect(parent.on_engine_selected)
            parent.engine_note_label = self.widget.findChild(HyperlinkLabel, 'engine_note')
            parent.engine_note_label.clicked.connect(parent.show_engine_note)

            parent.voice_selector = self.widget.findChild(ComboBox, 'voice_selector')
            parent.switch_enable_TTS = self.widget.findChild(SwitchButton, 'switch_enable_tts')
            self.tts_vocab_button = self.widget.findChild(PushButton, 'tts_vocab_button')
            def show_vocab_note():
                w = MessageBox('小语法?',
                               '可以使用以下占位符来动态插入信息：\n'\
                               '- `{lesson_name}`: 开始&结束&下节的课程名(例如：信息技术)\n'\
                               '- `{minutes}`: 分钟数 (例如：5) *其他\n'\
                               '- `{title}`: 通知标题 (例如：重要通知) *其他\n'\
                               '- `{content}`: 通知内容 (例如：这是一条测试通知) *其他\n', self)
                w.cancelButton.hide()
                w.exec()
            self.tts_vocab_button.clicked.connect(show_vocab_note)

            if parent.available_voices is not None and parent.current_loaded_engine == parent.engine_selector.currentData():
                parent.update_tts_voices(parent.available_voices)
            else:
                # 启动由 open_tts_settings 处理
                voice_selector.clear()
                voice_selector.addItem("加载中...", userData=None)
                voice_selector.setEnabled(False)

            text_attend_class = self.widget.findChild(LineEdit, 'text_attend_class')
            text_attend_class.setText(config_center.read_conf('TTS', 'attend_class'))
            text_attend_class.textChanged.connect(lambda: config_center.write_conf('TTS', 'attend_class', text_attend_class.text()))

            text_prepare_class = self.widget.findChild(LineEdit, 'text_prepare_class')
            text_prepare_class.setText(config_center.read_conf('TTS', 'prepare_class'))
            text_prepare_class.textChanged.connect(lambda: config_center.write_conf('TTS', 'prepare_class', text_prepare_class.text()))

            text_finish_class = self.widget.findChild(LineEdit, 'text_finish_class')
            text_finish_class.setText(config_center.read_conf('TTS', 'finish_class'))
            text_finish_class.textChanged.connect(lambda: config_center.write_conf('TTS', 'finish_class', text_finish_class.text()))

            text_after_school = self.widget.findChild(LineEdit, 'text_after_school')
            text_after_school.setText(config_center.read_conf('TTS', 'after_school'))
            text_after_school.textChanged.connect(lambda: config_center.write_conf('TTS', 'after_school', text_after_school.text()))

            text_notification = self.widget.findChild(LineEdit, 'text_notification')
            text_notification.setText(config_center.read_conf('TTS', 'otherwise'))
            text_notification.textChanged.connect(lambda: config_center.write_conf('TTS', 'otherwise', text_notification.text()))

            # 预览
            preview_tts_button = self.widget.findChild(PrimaryDropDownPushButton, 'preview')
            preview_tts_menu = RoundMenu(parent=preview_tts_button)
            preview_tts_menu.addActions([
                Action(fIcon.EDUCATION, '上课提醒', triggered=lambda: self.play_tts_preview('attend_class')),
                Action(fIcon.CAFE, '下课提醒', triggered=lambda: self.play_tts_preview('finish_class')),
                Action(fIcon.BOOK_SHELF, '预备提醒', triggered=lambda: self.play_tts_preview('prepare_class')),
                Action(fIcon.EMBED, '放学提醒', triggered=lambda: self.play_tts_preview('after_school')),
                Action(fIcon.CODE, '其他提醒', triggered=lambda: self.play_tts_preview('otherwise'))
            ])
            preview_tts_button.setMenu(preview_tts_menu)

        def play_tts_preview(self, text_type):
            text_template = config_center.read_conf('TTS', text_type)
            from collections import defaultdict
            format_values = defaultdict(str, {
                'lesson_name': '信息技术',
                'minutes': '5',
                'title': '通知',
                'content': '这是一条测试通知ヾ(≧▽≦*)o'
            })
            if text_type == 'attend_class':
                text_to_speak = text_template.format_map(format_values)
            elif text_type == 'finish_class':
                text_to_speak = text_template.format_map(format_values)
            elif text_type == 'prepare_class':
                text_to_speak = text_template.format_map(format_values)
            elif text_type == 'after_school':
                text_to_speak = text_template.format_map(format_values)
            elif text_type == 'otherwise':
                text_to_speak = text_template.format_map(format_values)
            else:
                text_to_speak = text_template.format_map(format_values)

            logger.debug(f"生成TTS文本: {text_to_speak}")
            
            try:
                current_engine = self.parent_menu.engine_selector.currentData()
                current_voice = None
                if self.parent_menu.voice_selector and self.parent_menu.voice_selector.currentData():
                    current_voice = self.parent_menu.voice_selector.currentData()
                
                if hasattr(self, 'tts_preview_thread') and self.tts_preview_thread and self.tts_preview_thread.isRunning():
                    self.tts_preview_thread.requestInterruption()
                    self.tts_preview_thread.quit()
                    if not self.tts_preview_thread.wait(1000):
                        logger.warning("旧TTS预览线程未能在超时时间内退出，将在后台继续运行")
                self.tts_preview_thread = TTSPreviewThread(
                    text=text_to_speak,
                    engine=current_engine,
                    voice=current_voice,
                    parent=self
                )
                
                self.tts_preview_thread.previewError.connect(self.handle_tts_preview_error)
                self.tts_preview_thread.start()
                
            except Exception as e:
                logger.error(f"启动TTS预览线程失败: {str(e)}")
                from qfluentwidgets import MessageBox
                MessageBox(
                    "TTS预览失败",
                    f"启动TTS预览时出错: {str(e)}",
                    self
                ).exec()
                
        def handle_tts_preview_error(self, error_message):
            logger.error(f"TTS生成预览失败: {error_message}")
            from qfluentwidgets import MessageBox
            MessageBox(
                "TTS生成失败",
                f"生成或播放语音时出错: {error_message}",
                self
            ).exec()


    def open_tts_settings(self):
        if not hasattr(self, 'TTSSettingsDialog') or not self.TTSSettingsDialog:
            self.TTSSettingsDialog = self.TTSSettings(self)
        current_selected_engine_in_selector = self.engine_selector.currentData()
        tts_enabled = config_center.read_conf('TTS', 'enable') == '1'

        if tts_enabled:
            self.voice_selector.clear()
            self.voice_selector.addItem("加载中...", userData=None)
            self.voice_selector.setEnabled(False)
            self.switch_enable_TTS.setEnabled(True)
        else:
            self.voice_selector.clear()
            self.voice_selector.addItem("未启用", userData=None)
            self.voice_selector.setEnabled(False)
            self.switch_enable_TTS.setEnabled(True)

        self.toggle_tts_settings(tts_enabled)
        self.TTSSettingsDialog.show()
        self.TTSSettingsDialog.exec()
        logger.debug(f"加载引擎: {self.current_loaded_engine},{current_selected_engine_in_selector}(选择器)")
        if tts_enabled:
            self.load_tts_voices_for_engine(current_selected_engine_in_selector)
        else:
            self.voice_selector.clear()
            self.voice_selector.addItem("未启用", userData=None)
            self.voice_selector.setEnabled(False)
            self.switch_enable_TTS.setEnabled(True)

    def on_engine_selected(self, engine_text):
        selected_engine_key = self.engine_selector.currentData()
        if selected_engine_key and selected_engine_key != self.current_loaded_engine:
            logger.debug(f"TTS引擎被更改,尝试更新列表: {selected_engine_key}")
            config_center.write_conf('TTS', 'engine', selected_engine_key)
            self.current_loaded_engine = selected_engine_key # 更新当前加载的引擎
            self.load_tts_voices_for_engine(selected_engine_key)
        elif not selected_engine_key:
            logger.warning("选择的TTS引擎键为空")

    def load_tts_voices_for_engine(self, engine_key):
        if config_center.read_conf('TTS', 'enable') == '0':
            self.voice_selector.clear()
            self.voice_selector.addItem("未启用", userData=None)
            self.voice_selector.setEnabled(False)
            self.switch_enable_TTS.setEnabled(True)
            return
        self.voice_selector.clear()
        self.voice_selector.addItem("加载中...", userData=None)
        self.voice_selector.setEnabled(False)
        if hasattr(self, 'TTSSettingsDialog') and self.TTSSettingsDialog.isVisible():
            self.switch_enable_TTS.setEnabled(False) # 临时禁用TTS开关

        if self.tts_voice_loader_thread and self.tts_voice_loader_thread.isRunning():
            self.tts_voice_loader_thread.requestInterruption()
            self.tts_voice_loader_thread.quit()
            if not self.tts_voice_loader_thread.wait(2000):
                logger.warning("旧TTS加载线程未能在超时时间内退出，将在后台继续运行")
        self.tts_voice_loader_thread = None

        self.current_loaded_engine = engine_key
        self.available_voices = None
        self.tts_voice_loader_thread = TTSVoiceLoaderThread(engine_filter=engine_key)
        self.tts_voice_loader_thread.voicesLoaded.connect(lambda voices: self.available_voices_cnt(voices) or self.switch_enable_TTS.setEnabled(True))
        self.tts_voice_loader_thread.errorOccurred.connect(lambda error: self.handle_tts_load_error(error) or self.switch_enable_TTS.setEnabled(True))
        self.tts_voice_loader_thread.start()

    def populate_tts_engines(self):
        # 填充TTS引擎选项
        self.engine_selector.clear()
        available_engines = generate_speech.get_available_engines() #  假设 generate_speech 有这个方法
        logger.debug(f"可用TTS引擎: {available_engines}")
        for engine_key, engine_name in available_engines.items():
            if engine_key == 'pyttsx3' and platform.system() != "Windows":
                continue
            self.engine_selector.addItem(engine_name, userData=engine_key)
        
        current_engine = config_center.read_conf('TTS', 'engine')
        if current_engine in available_engines:
            if current_engine == 'pyttsx3' and platform.system() != "Windows":
                if self.engine_selector.count() > 0:
                    self.engine_selector.setCurrentIndex(0)
                    config_center.write_conf('TTS', 'engine', self.engine_selector.currentData())
                    logger.warning(f"当前系统不支持pyttsx3，已自动切换到引擎: {self.engine_selector.currentData()}")
                else:
                    logger.error("没有可用的TTS引擎!")
            else:
                index = self.engine_selector.findData(current_engine)
                if index != -1:
                    self.engine_selector.setCurrentIndex(index)
        elif self.engine_selector.count() > 0:
            self.engine_selector.setCurrentIndex(0)
            config_center.write_conf('TTS', 'engine', self.engine_selector.currentData())

    def show_engine_note(self):
        if not hasattr(self, 'engine_selector') or not self.engine_selector:
            logger.warning("引擎选择器未初始化")
            return

        current_engine_key = self.engine_selector.currentData()
        title = "引擎小提示"
        message = ""
        if current_engine_key == "edge":
            message = ("Edge TTS 需要联网才能正常发声哦~\n"
                       "请确保网络连接,不然会说不出话来(>﹏<)\n"
                       "* 可能会有一定的延迟,耐心等待一下~")
            w = MessageBox(title, message, self.TTSSettingsDialog if hasattr(self, 'TTSSettingsDialog') and self.TTSSettingsDialog else self.parent_menu)
            w.yesButton.setText('知道啦~')
            w.cancelButton.hide()
            w.show()
        elif current_engine_key == "pyttsx3" and platform.system() == "Windows":
            class CustomMessageBox(MessageBoxBase):
                def __init__(self, parent=None):
                    super().__init__(parent)
                    self.titleLabel = StrongBodyLabel(title, self)
                    self.contentLabel = BodyLabel(
                        "系统 TTS（pyttsx3）用的是系统自带的语音服务噢~\n"
                        "您可以在系统设置里添加更多语音(*≧▽≦)", 
                        self)
                    self.hyperlinkLabel = HyperlinkLabel("打开Windows语音设置", self)
                    self.hyperlinkLabel.clicked.connect(self._open_settings)
                    self.viewLayout.addWidget(self.titleLabel)
                    self.viewLayout.addWidget(self.contentLabel)
                    self.viewLayout.addWidget(self.hyperlinkLabel)
                    self.yesButton.setText('知道啦~')
                    self.cancelButton.hide()
                def _open_settings(self):
                    QDesktopServices.openUrl(QUrl("file:///C:/Windows/System32/Speech/SpeechUX/sapi.cpl"))
            w = CustomMessageBox(self.TTSSettingsDialog if hasattr(self, 'TTSSettingsDialog') and self.TTSSettingsDialog else self.parent_menu)
            w.exec()
        else:
            message = "这个语音引擎还没有提示信息呢~(・ω<)"
            w = MessageBox(title, message, self.TTSSettingsDialog if hasattr(self, 'TTSSettingsDialog') and self.TTSSettingsDialog else self.parent_menu)
            w.yesButton.setText('知道啦~')
            w.cancelButton.hide()
            w.show()


    def toggle_tts_settings(self, checked):
        switch_checked('TTS', 'enable', checked)

        tts_dialog_widget = self.TTSSettingsDialog.widget if hasattr(self, 'TTSSettingsDialog') and self.TTSSettingsDialog else None
        if not tts_dialog_widget:
            return
        card_tts_speed = tts_dialog_widget.findChild(CardWidget, 'CardWidget_7')
        card_tts_speed.setVisible(checked)
        if checked:
            self.engine_selector.setEnabled(True)
            if self.voice_selector.itemText(0) in ["未启用", "加载失败", "无可用语音"] or self.voice_selector.count() == 0:
                self.voice_selector.clear()
                self.voice_selector.addItem("加载中...", userData=None)
            self.voice_selector.setEnabled(False)
            self.switch_enable_TTS.setEnabled(False)
            current_engine = self.engine_selector.currentData()
            if current_engine:
                self.load_tts_voices_for_engine(current_engine)
            else:
                logger.warning("TTS启用但未选择引擎，无法加载语音")
                self.voice_selector.clear()
                self.voice_selector.addItem("请选择引擎", userData=None)
                self.voice_selector.setEnabled(False)
                self.switch_enable_TTS.setEnabled(True)
        else:
            self.engine_selector.setEnabled(False)
            self.voice_selector.clear()
            self.voice_selector.addItem("未启用", userData=None)
            self.voice_selector.setEnabled(False)
            self.switch_enable_TTS.setEnabled(True)
            if self.tts_voice_loader_thread and self.tts_voice_loader_thread.isRunning():
                self.tts_voice_loader_thread.requestInterruption()
                self.tts_voice_loader_thread.quit()
                if not self.tts_voice_loader_thread.wait(1000):
                    logger.warning("TTS语音加载线程未能及时停止")

    def save_tts_speed(self, value):
        config_center.write_conf('TTS', 'speed', str(value))

    def update_tts_voices(self, available_voices):
        voice_selector = self.voice_selector
        switch_enable_TTS = self.switch_enable_TTS
        try:
            if voice_selector.currentTextChanged.disconnect():
                pass
        except TypeError:
            pass
        except Exception as e:
            logger.warning(f"断开voice_selector信号连接失败: {e}")
        voice_selector.clear()

        if not available_voices:
            logger.warning("未找到可用的TTS语音引擎或语音包")
            if voice_selector.count() == 0 or voice_selector.itemText(0) == "加载中...":
                voice_selector.clear()
                voice_selector.addItem("无可用语音", userData=None)
                voice_selector.setEnabled(False)
            switch_enable_TTS.setEnabled(True)
            card_tts_speed = self.findChild(CardWidget, 'CardWidget_7')
            if card_tts_speed: card_tts_speed.setVisible(False)

        for voice in available_voices:
            voice_selector.addItem(voice['name'], userData=voice['id'])
        current_voice_id = config_center.read_conf('TTS', 'voice_id')
        current_voice_name = get_voice_name_by_id(current_voice_id, available_voices)
        if current_voice_name:
            index_to_select = -1
            for i in range(voice_selector.count()):
                if voice_selector.itemData(i) == current_voice_id:
                    index_to_select = i
                    break
            if index_to_select != -1:
                voice_selector.setCurrentIndex(index_to_select)
                config_center.write_conf('TTS', 'voice_id', current_voice_id)
            else:
                if available_voices:
                    voice_selector.setCurrentIndex(0)
                    first_voice_id = available_voices[0]['id']
                    config_center.write_conf('TTS', 'voice_id', first_voice_id)
                else:
                    voice_selector.setEnabled(False)
                    switch_enable_TTS.setEnabled(False)
        elif available_voices: # 默认选择
            voice_selector.setCurrentIndex(0)
            first_voice_id = available_voices[0]['id']
            config_center.write_conf('TTS', 'voice_id', first_voice_id)
        else: # 理论不会到这里
             voice_selector.setEnabled(False)
             switch_enable_TTS.setEnabled(False)

        voice_selector.setEnabled(True)
        switch_enable_TTS.setEnabled(True)
        voice_selector.currentTextChanged.connect(lambda name: config_center.write_conf('TTS', 'voice_id', voice_selector.currentData()) if voice_selector.currentData() else None)

    def handle_tts_load_error(self, error_message):
        if not self.voice_selector or not self.switch_enable_TTS:
            logger.warning("voice_selector 或 switch_enable_TTS 未初始化")
            return
            
        voice_selector = self.voice_selector
        switch_enable_TTS = self.switch_enable_TTS
        voice_selector.clear()
        voice_selector.addItem("加载失败", userData=None)
        voice_selector.setEnabled(False)
        logger.error(f"处理TTS语音加载错误: {error_message}")
        if self.TTSSettingsDialog and not self.TTSSettingsDialog.isHidden():
            parent_widget = self.TTSSettingsDialog if isinstance(self.TTSSettingsDialog, QWidget) else self
            MessageBox("TTS语音加载失败", f"加载TTS语音时发生错误:\n{error_message}", parent_widget)

    class cfFileItem(QWidget, uic.loadUiType(f'{base_directory}/view/menu/file_item.ui')[0]):
        def __init__(self, file_name='', file_path='local', id=None, parent=None):
            super().__init__()
            self.setupUi(self)

            self.url = file_path
            self.parent_widget = parent  # 保存父组件引用
            self.current_file_name = file_name  # 保存文件名

            self.file_name = self.findChild(StrongBodyLabel, 'file_name')
            self.file_name.setText(file_name)
            self.file_path = self.findChild(BodyLabel, 'file_path')
            self.file_path.setWordWrap(False)

            self.set_file_path(file_path)
            
            self.settings = self.findChild(DropDownToolButton, 'file_item_settings')

            self.context_menu = RoundMenu(parent=self)
            self.context_menu.addAction(Action(fIcon.SAVE, '导出', triggered=lambda: parent.cf_export_schedule(file_name)))
            self.context_menu.addAction(Action(fIcon.SAVE, '导出为 CSES', triggered=lambda: parent.cf_export_schedule_cses(file_name)))
            self.settings.setMenu(self.context_menu)
            self.id = id

        def contextMenuEvent(self, event):
            self.context_menu.exec(event.globalPos())
            event.accept()

        def set_file_path(self, file_path):
            self.url = file_path
            is_db = False
            for db in list_.schedule_dbs:
                if file_path.startswith(list_.schedule_dbs[db]):
                    file_path = file_path.replace(list_.schedule_dbs[db], db)
                    is_db = True
                    break
            if not is_db:
                if file_path.startswith('http://'):
                    file_path = file_path.replace('http://', '')
                elif file_path.startswith('https://'):
                    file_path = file_path.replace('https://', '')
            self.file_path.setText(file_path)

    def cf_add_item(self, file_name, file_path, id):
        item_widget = self.cfFileItem(file_name, file_path, id, self)
        it = QListWidgetItem()
        # 初始 sizeHint 只需定高，高度交给 gridSize 来控制宽度
        it.setSizeHint(QSize(self.table.min_item_width, self.table.item_height))
        self.table.addItem(it)
        self.table.setItemWidget(it, item_widget)
        item_widget.setFixedWidth(self.table.gridSize().width())
        return item_widget
    
    def setup_configs_interface(self):  # 配置界面
        self.config_url = self.cfInterface.findChild(LineEdit, 'config_url')

        self.config_download = self.cfInterface.findChild(PushButton, 'config_download')
        self.config_download.clicked.connect(self.cf_load_schedule_from_db)  # 下载配置
        
        self.update_now = self.cfInterface.findChild(PushButton, 'config_update')
        self.update_now.clicked.connect(self.cf_get_schedule)  # 更新当前

        self.config_new = self.cfInterface.findChild(PushButton, 'config_new')
        self.config_new.clicked.connect(self.cf_new_config)

        self.config_upload = self.cfInterface.findChild(PushButton, 'config_upload')
        self.config_upload.clicked.connect(self.cf_post_schedule)  # 上传配置

        self.import_from_file = self.cfInterface.findChild(PushButton, 'config_import')
        self.import_from_file.clicked.connect(self.cf_import_schedule)  # 从文件导入

        # 用自定义的 UniformListWidget 替换原 table
        old = self.cfInterface.findChild(ListWidget, 'config_table')
        parent_layout = old.parent().layout()
        idx = parent_layout.indexOf(old)
        parent_layout.takeAt(idx)
        old.deleteLater()

        class UniformListWidget(ListWidget):
            class cfCustomDelegate(ListItemDelegate):
                def paint(self, painter: QPainter, option, index):
                    painter.save()
                    painter.setPen(Qt.NoPen)
                    painter.setRenderHint(painter.Antialiasing)
                    painter.setClipping(True)
                    painter.setClipRect(option.rect)

                    isDark = isDarkTheme()
                    alpha = 15 if isDark else 9
                    c = 255 if isDark else 0
                    painter.setBrush(QColor(c, c, c, alpha))
                    margin = 8
                    bg_rect = option.rect.adjusted(0, margin, 0, -margin)
                    painter.drawRoundedRect(bg_rect, 5, 5)

                    y, h = option.rect.y(), option.rect.height()
                    ph = round(0.35 * h if self.pressedRow == index.row() else 0.257 * h)
                    if index.row() in self.selectedRows:
                        painter.setBrush(themeColor())
                    else:
                        painter.setBrush(QColor("#e0e0e0"))
                    painter.drawRoundedRect(option.rect.x(), ph + y, 3, h - 2 * ph, 1.5, 1.5)

                    painter.restore()
                    super().paint(painter, option, index)
                
                def _drawBackground(self, painter, option, index):
                    pass

            def __init__(self, *args, min_item_width=200, max_item_width=400, item_height=75, **kwargs):
                super().__init__(*args, **kwargs)
                self.min_item_width = min_item_width
                self.max_item_width = max_item_width
                self.item_height = item_height
                self.setResizeMode(ListWidget.Adjust)
                self.setFlow(ListWidget.LeftToRight)
                self.setWrapping(True)
                self.setSpacing(16)
                self.setGridSize(QSize(self.min_item_width, self.item_height))
                self.setItemDelegate(self.cfCustomDelegate(self))  # 使用自定义的 Delegate
                self.setViewMode(ListWidget.ListMode)
                self.setContentsMargins(0, 12, 0, 12)
                self.setDragEnabled(False)
                self.setDragDropMode(ListWidget.NoDragDrop)
                self.setDefaultDropAction(Qt.IgnoreAction)

            def resizeEvent(self, event):
                spacing = self.spacing()
                margins = self.contentsMargins()
                available_width = self.width() - margins.left() - margins.right()
                n = max(1, available_width // (self.min_item_width + spacing))
                item_width = (available_width - (n - 1) * spacing) // n
                item_width = min(max(item_width, self.min_item_width), self.max_item_width)
                self.setGridSize(QSize(item_width, self.item_height))
                for i in range(self.count()):
                    item = self.item(i)
                    widget = self.itemWidget(item)
                    if widget:
                        widget.setFixedWidth(item_width - spacing)
                    item.setSizeHint(QSize(item_width - spacing, self.item_height))
                if event:
                    super().resizeEvent(event)
            
        self.table = UniformListWidget(parent=self.cfInterface)
        parent_layout.insertWidget(idx, self.table)

        self.cf_reload_table()

    def setup_customization_interface(self):
        ct_scroll = self.findChild(SmoothScrollArea, 'ct_scroll')  # 触摸屏适配
        QScroller.grabGesture(ct_scroll.viewport(), QScroller.LeftMouseButtonGesture)

        self.ct_update_preview()

        widgets_list_widgets = self.findChild(ListWidget, 'widgets_list')
        widgets_list = []
        for key in list_.get_widget_config():
            try:
                widgets_list.append(list_.widget_name[key])
            except KeyError:
                logger.warning(f'未知的组件：{key}')
            except Exception as e:
                logger.error(f'获取组件名称时发生错误：{sys.exc_info()[0]}/{e}')
        widgets_list_widgets.addItems(widgets_list)
        widgets_list_widgets.sizePolicy().setVerticalPolicy(QSizePolicy.Policy.MinimumExpanding)

        save_config_button = self.findChild(PrimaryPushButton, 'save_config')
        save_config_button.clicked.connect(self.ct_save_widget_config)

        set_ac_color = self.findChild(PushButton, 'set_ac_color')  # 主题色
        set_ac_color.clicked.connect(self.ct_set_ac_color)
        set_fc_color = self.findChild(PushButton, 'set_fc_color')
        set_fc_color.clicked.connect(self.ct_set_fc_color)
        set_floating_time_color = self.findChild(PushButton, 'set_fc_color_2')
        set_floating_time_color.clicked.connect(self.ct_set_floating_time_color)

        open_theme_folder = self.findChild(HyperlinkLabel, 'open_theme_folder')  # 打开主题文件夹
        open_theme_folder.clicked.connect(lambda: open_dir(str(THEME_HOME)))

        select_theme_combo = self.findChild(ComboBox, 'combo_theme_select')  # 主题选择
        select_theme_combo.addItems(list_.theme_names)
        print(list_.theme_folder, list_.theme_names, get_theme_name())
        select_theme_combo.setCurrentIndex(list_.theme_folder.index(get_theme_name()))
        select_theme_combo.currentIndexChanged.connect(
            lambda: config_center.write_conf('General', 'theme',
                                             list_.get_theme_ui_path(select_theme_combo.currentText())))

        color_mode_combo = self.findChild(ComboBox, 'combo_color_mode')  # 颜色模式选择
        color_mode_combo.addItems(list_.color_mode)
        color_mode_combo.setCurrentIndex(int(config_center.read_conf('General', 'color_mode')))
        color_mode_combo.currentIndexChanged.connect(self.ct_change_color_mode)

        widgets_combo = self.findChild(ComboBox, 'widgets_combo')  # 组件选择
        widgets_combo.addItems(list_.get_widget_names())

        search_city_button = self.findChild(PushButton, 'select_city')  # 查找城市
        search_city_button.clicked.connect(self.show_search_city)

        add_widget_button = self.findChild(PrimaryPushButton, 'add_widget')
        add_widget_button.clicked.connect(self.ct_add_widget)

        remove_widget_button = self.findChild(PushButton, 'remove_widget')
        remove_widget_button.clicked.connect(self.ct_remove_widget)

        slider_opacity = self.findChild(Slider, 'slider_opacity')
        slider_opacity.setValue(int(config_center.read_conf('General', 'opacity')))
        slider_opacity.valueChanged.connect(
            lambda: config_center.write_conf('General', 'opacity', str(slider_opacity.value()))
        )  # 透明度

        blur_countdown = self.findChild(SwitchButton, 'switch_blur_countdown')
        blur_countdown.setChecked(int(config_center.read_conf('General', 'blur_countdown')))
        blur_countdown.checkedChanged.connect(lambda checked: switch_checked('General', 'blur_countdown', checked))
        # 模糊倒计时
        switch_blur_floating = self.findChild(SwitchButton, 'switch_blur_countdown_2')
        switch_blur_floating.setChecked(int(config_center.read_conf('General', 'blur_floating_countdown')))
        switch_blur_floating.checkedChanged.connect(
            lambda checked: config_center.write_conf('General', 'blur_floating_countdown', int(checked))
        )

        switch_enable_display_full_next_lessons = self.findChild(SwitchButton, 'switch_enable_display_full_next_lessons')
        switch_enable_display_full_next_lessons.setChecked(int(config_center.read_conf('General', 'enable_display_full_next_lessons')))
        switch_enable_display_full_next_lessons.checkedChanged.connect(
            lambda checked: switch_checked('General', 'enable_display_full_next_lessons', checked))

        select_weather_api = self.findChild(ComboBox, 'select_weather_api')  # 天气API选择
        select_weather_api.addItems(weather.weather_manager.api_config['weather_api_list_zhCN'])
        select_weather_api.setCurrentIndex(weather.weather_manager.api_config['weather_api_list'].index(
            config_center.read_conf('Weather', 'api')
        ))
        select_weather_api.currentIndexChanged.connect(
            lambda: config_center.write_conf('Weather', 'api',
                                             weather.weather_manager.api_config['weather_api_list'][
                                                 select_weather_api.currentIndex()])
        )

        api_key_edit = self.findChild(LineEdit, 'api_key_edit')  # API密钥
        api_key_edit.setText(config_center.read_conf('Weather', 'api_key'))
        api_key_edit.textChanged.connect(lambda: config_center.write_conf('Weather', 'api_key', api_key_edit.text()))

    def setup_about_interface(self):
        ab_scroll = self.findChild(SmoothScrollArea, 'ab_scroll')  # 触摸屏适配
        QScroller.grabGesture(ab_scroll.viewport(), QScroller.LeftMouseButtonGesture)

        self.version = self.findChild(BodyLabel, 'version')

        check_update_btn = self.findChild(PrimaryPushButton, 'check_update')
        check_update_btn.setIcon(fIcon.SYNC)
        check_update_btn.clicked.connect(self.check_update)

        self.auto_check_update = self.ifInterface.findChild(SwitchButton, 'auto_check_update')
        self.auto_check_update.setChecked(int(config_center.read_conf("Version", "auto_check_update", "1")))
        self.auto_check_update.checkedChanged.connect(
            lambda checked: switch_checked("Version", "auto_check_update", checked)
        )  # 自动检查更新

        self.auto_upgrade = self.ifInterface.findChild(SwitchButton,"switch_auto_upgrade_2")
        self.auto_upgrade.setChecked(int(config_center.read_conf("Version", "auto_upgrade", "1")))
        self.auto_upgrade.checkedChanged.connect(
            lambda checked: switch_checked("Version","auto_upgrade",checked)
        )
        self.auto_check_update.checkedChanged.connect(
            lambda checked: self.auto_upgrade.setEnabled(checked)
        )
        self.auto_check_update.checkedChanged.connect(
            lambda checked: self.auto_upgrade.setChecked(checked)
        )
        self.version_channel = self.findChild(ComboBox, 'version_channel')
        self.version_channel.addItems(list_.version_channel)
        self.version_channel.setCurrentIndex(int(config_center.read_conf("Version", "version_channel")))
        self.version_channel.currentIndexChanged.connect(
            lambda: config_center.write_conf("Version", "version_channel", self.version_channel.currentIndex())
        )  # 版本更新通道
        self.do_upgrade_button = self.findChild(PrimaryPushButton,"do_upgrade")
        self.do_upgrade_button.clicked.connect(self.do_upgrade)

        github_page = self.findChild(PushButton, "button_github")
        github_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            'https://github.com/RinLit-233-shiroko/Class-Widgets')))

        bilibili_page = self.findChild(PushButton, 'button_bilibili')
        bilibili_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            'https://space.bilibili.com/569522843')))

        license_button = self.findChild(PushButton, 'button_show_license')
        license_button.clicked.connect(self.show_license)

        thanks_button = self.findChild(PushButton, 'button_thanks')
        thanks_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            'https://github.com/RinLit-233-shiroko/Class-Widgets?tab=readme-ov-file#致谢')))

        self.check_update()

    def setup_advance_interface(self):
        adv_scroll = self.adInterface.findChild(SmoothScrollArea, 'adv_scroll')  # 触摸屏适配
        QScroller.grabGesture(adv_scroll.viewport(), QScroller.LeftMouseButtonGesture)

        margin_spin = self.adInterface.findChild(SpinBox, 'margin_spin')
        margin_spin.setValue(int(config_center.read_conf('General', 'margin')))
        margin_spin.valueChanged.connect(
            lambda: config_center.write_conf('General', 'margin', str(margin_spin.value()))
        )  # 保存边距设定

        window_status_combo = self.adInterface.findChild(ComboBox, 'window_status_combo')
        window_status_combo.addItems(list_.window_status)
        window_status_combo.setCurrentIndex(int(config_center.read_conf('General', 'pin_on_top')))
        window_status_combo.currentIndexChanged.connect(
            lambda: config_center.write_conf('General', 'pin_on_top', str(window_status_combo.currentIndex()))
        )  # 窗口状态

        switch_startup = self.adInterface.findChild(SwitchButton, 'switch_startup')
        switch_startup.setChecked(int(config_center.read_conf('General', 'auto_startup')))
        switch_startup.checkedChanged.connect(lambda checked: switch_checked('General', 'auto_startup', checked))
        # 开机自启
        if os.name != 'nt':
            switch_startup.setEnabled(False)

        hide_mode_combo = self.adInterface.findChild(ComboBox, 'hide_mode_combo')
        hide_mode_combo.addItems(list_.hide_mode if os.name == 'nt' else list_.non_nt_hide_mode)
        hide_mode_combo.setCurrentIndex(int(config_center.read_conf('General', 'hide')))
        hide_mode_combo.currentIndexChanged.connect(
            lambda: config_center.write_conf('General', 'hide', str(hide_mode_combo.currentIndex()))
        )  # 隐藏模式

        hide_method_default = self.adInterface.findChild(RadioButton, 'hide_method_default')
        hide_method_default.setChecked(config_center.read_conf('General', 'hide_method') == '0')
        hide_method_default.toggled.connect(lambda: config_center.write_conf('General', 'hide_method', '0'))
        if os.name != 'nt':
            hide_method_default.setEnabled(False)
        # 默认隐藏

        hide_method_all = self.adInterface.findChild(RadioButton, 'hide_method_all')
        hide_method_all.setChecked(config_center.read_conf('General', 'hide_method') == '1')
        hide_method_all.toggled.connect(lambda: config_center.write_conf('General', 'hide_method', '1'))
        # 单击全部隐藏

        hide_method_floating = self.adInterface.findChild(RadioButton, 'hide_method_floating')
        hide_method_floating.setChecked(config_center.read_conf('General', 'hide_method') == '2')
        hide_method_floating.toggled.connect(lambda: config_center.write_conf('General', 'hide_method', '2'))
        # 最小化为浮窗

        switch_enable_exclude = self.adInterface.findChild(SwitchButton, 'switch_exclude_startup')
        switch_enable_exclude.setChecked(int(config_center.read_conf('General', 'excluded_lesson')))
        switch_enable_exclude.checkedChanged.connect(
            lambda checked: switch_checked('General', 'excluded_lesson', checked))
        # 允许排除课程

        exclude_lesson = self.adInterface.findChild(LineEdit, 'excluded_lessons')
        exclude_lesson.setText(config_center.read_conf('General', 'excluded_lessons'))
        exclude_lesson.textChanged.connect(
            lambda: config_center.write_conf('General', 'excluded_lessons', exclude_lesson.text()))
        # 排除课程

        switch_enable_click = self.adInterface.findChild(SwitchButton, 'switch_enable_click')
        switch_enable_click.setChecked(int(config_center.read_conf('General', 'enable_click')))
        switch_enable_click.checkedChanged.connect(lambda checked: switch_checked('General', 'enable_click', checked))
        # 允许点击

        switch_enable_alt_schedule = self.adInterface.findChild(SwitchButton, 'switch_enable_alt_schedule')
        switch_enable_alt_schedule.setChecked(int(config_center.read_conf('General', 'enable_alt_schedule')))
        switch_enable_alt_schedule.checkedChanged.connect(
            lambda checked: switch_checked('General', 'enable_alt_schedule', checked)
        )  # 安全模式

        switch_enable_safe_mode = self.adInterface.findChild(SwitchButton, 'switch_safe_mode')
        switch_enable_safe_mode.setChecked(int(config_center.read_conf('Other', 'safe_mode')))
        switch_enable_safe_mode.checkedChanged.connect(
            lambda checked: switch_checked('Other', 'safe_mode', checked)
        )
        # 安全模式开关

        switch_enable_multiple_programs = self.adInterface.findChild(SwitchButton, 'switch_multiple_programs')
        switch_enable_multiple_programs.setChecked(int(config_center.read_conf('Other', 'multiple_programs')))
        switch_enable_multiple_programs.checkedChanged.connect(
            lambda checked: switch_checked('Other', 'multiple_programs', checked)
        )  # 多开程序

        switch_disable_log = self.adInterface.findChild(SwitchButton, 'switch_disable_log')
        switch_disable_log.setChecked(int(config_center.read_conf('Other', 'do_not_log')))
        switch_disable_log.checkedChanged.connect(
            lambda checked: switch_checked('Other', 'do_not_log', checked)
        )  # 禁用日志

        button_clear_log = self.adInterface.findChild(PushButton, 'button_clear_log')
        button_clear_log.clicked.connect(self.clear_log)  # 清空日志

        set_start_date = self.adInterface.findChild(CalendarPicker, 'set_start_date')  # 日期
        if config_center.read_conf('Date', 'start_date') != '':
            set_start_date.setDate(QDate.fromString(config_center.read_conf('Date', 'start_date'), 'yyyy-M-d'))
        set_start_date.dateChanged.connect(
            lambda: config_center.write_conf('Date', 'start_date', set_start_date.date.toString('yyyy-M-d')))  # 开学日期

        offset_spin = self.adInterface.findChild(SpinBox, 'offset_spin')
        offset_spin.setValue(int(config_center.read_conf('Time', 'time_offset')))
        offset_spin.valueChanged.connect(
            lambda: config_center.write_conf('Time', 'time_offset', str(offset_spin.value()))
        )  # 保存时差偏移

        text_scale_factor = self.adInterface.findChild(LineEdit, 'text_scale_factor')
        text_scale_factor.setText(str(float(config_center.read_conf('General', 'scale')) * 100) + '%')  # 初始化缩放系数显示

        slider_scale_factor = self.adInterface.findChild(Slider, 'slider_scale_factor')
        slider_scale_factor.setValue(int(float(config_center.read_conf('General', 'scale')) * 100))
        slider_scale_factor.valueChanged.connect(
            lambda: (config_center.write_conf('General', 'scale', str(slider_scale_factor.value() / 100)),
                     text_scale_factor.setText(str(slider_scale_factor.value()) + '%'))
        )  # 保存缩放系数

        what_is_hide_mode_3 = self.adInterface.findChild(HyperlinkLabel, 'what_is_hide_mode_3')
  
        def what_is_hide_mode_3_clicked():
            w = MessageBox('灵活模式', '灵活模式为上课时自动隐藏，可手动改变隐藏状态，当前课程状态（上课/课间）改变后会清除手动隐藏状态，重新转为自动隐藏。', self)
            w.cancelButton.hide()
            w.exec()
        what_is_hide_mode_3.clicked.connect(what_is_hide_mode_3_clicked)
        
        # 时间获得方法配置
        conf_time_get = self.adInterface.findChild(ComboBox, 'conf_time_get')
        conf_time_get.addItems(['系统时间', 'NTP时间'])
        current_time_type = config_center.read_conf('Time', 'type')
        if current_time_type == 'ntp':
            conf_time_get.setCurrentIndex(1)
        else:
            conf_time_get.setCurrentIndex(0)
        conf_time_get.currentIndexChanged.connect(self.on_time_method_changed)
        
        # NTP服务器配置
        ntp_server_url = self.adInterface.findChild(LineEdit, 'ntp_server_url')
        ntp_server_url.setText(config_center.read_conf('Time', 'ntp_server'))
        ntp_server_url.textChanged.connect(
            lambda: self.on_ntp_server_url_changed(ntp_server_url.text())
        )
        ntp_refresh_button = self.adInterface.findChild(ToolButton, 'ntp_refresh_button')
        ntp_refresh_button.setIcon(fIcon.SYNC)
        ntp_refresh_button.setToolTip('立即同步NTP时间')
        ntp_refresh_button.installEventFilter(ToolTipFilter(ntp_refresh_button, showDelay=300, position=ToolTipPosition.TOP))
        ntp_refresh_button.clicked.connect(self.on_ntp_refresh_clicked)
        ntp_refresh_picker = self.adInterface.findChild(SpinBox, 'ntp_refresh_picker')
        auto_refresh_minutes = int(config_center.read_conf('Time', 'ntp_auto_refresh'))
        ntp_refresh_picker.setMinimum(1)
        ntp_refresh_picker.setMaximum(1440)  # 最大24小时
        ntp_refresh_picker.setSuffix(' 分钟')
        ntp_refresh_picker.setValue(auto_refresh_minutes)
        ntp_refresh_picker.valueChanged.connect(self.on_ntp_auto_refresh_changed)
        ntp_sync_timezone = self.adInterface.findChild(ComboBox, 'ntp_sync_timezone')
        timezone_options = [
            ('系统时区', 'local'),
            ('(UTC+0)  伦敦时间', 'Europe/London'),
            ('(UTC+1)  巴黎时间', 'Europe/Paris'),
            ('(UTC+3)  莫斯科时间', 'Europe/Moscow'),
            ('(UTC+8)  北京时间', 'Asia/Shanghai'),
            ('(UTC+8)  新加坡时间', 'Asia/Singapore'),
            ('(UTC+9)  东京时间', 'Asia/Tokyo'),
            ('(UTC+10)  悉尼时间', 'Australia/Sydney'),
            ('(UTC-8)  洛杉矶时间', 'America/Los_Angeles'),
            ('(UTC-5)  纽约时间', 'America/New_York')
        ]
        for display_name, timezone_value in timezone_options:
            ntp_sync_timezone.addItem(display_name)
            ntp_sync_timezone.setItemData(ntp_sync_timezone.count() - 1, timezone_value)
        current_timezone = config_center.read_conf('Time', 'timezone', 'local')
        timezone_found = False
        for i, (_, timezone_value) in enumerate(timezone_options):
            if timezone_value == current_timezone:
                ntp_sync_timezone.setCurrentIndex(i)
                timezone_found = True
                break
        if not timezone_found:
            ntp_sync_timezone.setCurrentIndex(0)
            config_center.write_conf('Time', 'timezone', 'local')
        ntp_sync_timezone.currentIndexChanged.connect(self.on_ntp_timezone_changed)
        switch_enable_ntp_auto_sync = self.adInterface.findChild(SwitchButton, 'switch_enable_ntp_auto_sync')
        auto_sync_enabled = int(config_center.read_conf('Time', 'switch_enable_ntp_auto_sync', '1'))
        switch_enable_ntp_auto_sync.setChecked(bool(auto_sync_enabled))
        switch_enable_ntp_auto_sync.checkedChanged.connect(self.on_ntp_auto_sync_switch_changed)
        self.ntp_card_widget = self.adInterface.findChild(CardWidget, 'CardWidget_17')
        self.update_ntp_status_display()
        self.update_ntp_ui_visibility()
        if config_center.read_conf('Time', 'type') == 'ntp' and auto_sync_enabled:
            self._add_ntp_auto_sync_callback()

    def on_time_method_changed(self):
        """时间获得方法改变时的处理"""
        conf_time_get = self.adInterface.findChild(ComboBox, 'conf_time_get')
        is_ntp = conf_time_get.currentIndex() == 1
        config_center.write_conf('Time', 'type', 'ntp' if is_ntp else 'local')
        try:
            new_manager = TimeManagerFactory.reset_instance()
            utils.time_manager = new_manager
            try:
                if hasattr(self, 'parent') and self.parent and hasattr(self.parent, 'update_data'):
                    self.parent.update_data()
            except Exception:
                pass
            try:
                current_manager = utils.time_manager
                self._remove_ntp_auto_sync_callback()
                if is_ntp:
                    self.show_info_toast('时间设置', '已切换到NTP时间,正在同步时间~')
                    self._start_async_ntp_sync(current_manager)
                    auto_sync_enabled = int(config_center.read_conf('Time', 'switch_enable_ntp_auto_sync', '1'))
                    if auto_sync_enabled:
                        self._add_ntp_auto_sync_callback()
                else:
                    self.show_success_toast('时间设置', '已切换到系统时间')
            except Exception as e:
                logger.error(f"管理NTP自动同步回调失败: {e}")
            
            self.update_ntp_status_display()
            self.update_ntp_ui_visibility()
        except Exception as e:
            logger.error(f"时间管理器切换失败: {e}")
            self.show_warning_toast('时间设置', '切换失败')
    
    def on_ntp_refresh_clicked(self):
        """NTP刷新按钮"""
        try:
            current_manager = utils.time_manager
            if isinstance(current_manager, utils.LocalTimeManager):
                self.show_warning_toast('NTP同步', '当前无需NTP同步')
                return
            if not isinstance(current_manager, utils.NTPTimeManager):
                self.show_warning_toast('NTP同步', '当前时间管理器不支持NTP同步')
                return
            self.show_info_toast('NTP同步', '正在同步NTP时间~')
            self._start_async_ntp_sync(current_manager)
        except Exception as e:
            logger.error(f"NTP同步失败: {e}")
            self.show_warning_toast('NTP同步', 'NTP时间同步失败')
    
    def on_ntp_auto_refresh_changed(self, value):
        """修改ntp自动刷新时间"""
        config_center.write_conf('Time', 'ntp_auto_refresh', str(value))
        try:
            if config_center.read_conf('Time', 'type') == 'ntp' and int(config_center.read_conf('Time', 'switch_enable_ntp_auto_sync', '1')):
                self._remove_ntp_auto_sync_callback()
                self._add_ntp_auto_sync_callback()
        except Exception as e:
            logger.error(f"更新NTP自动同步间隔失败: {e}")
    
    def on_ntp_auto_sync_switch_changed(self, checked):
        """NTP自动同步开关"""
        try:
            config_center.write_conf('Time', 'switch_enable_ntp_auto_sync', '1' if checked else '0')
            if config_center.read_conf('Time', 'type') == 'ntp':
                if checked:
                    self._add_ntp_auto_sync_callback()
                    self.show_success_toast('NTP设置', '已开启NTP自动同步ヾ(≧▽≦*)o')
                else:
                    self._remove_ntp_auto_sync_callback()
                    self.show_info_toast('NTP设置', '已关闭NTP自动同步(≧﹏ ≦)')
        except Exception as e:
            logger.error(f"NTP自动同步开关设置失败: {e}")
            self.show_warning_toast('NTP设置', '设置失败 (╥﹏╥)')
    
    def on_ntp_timezone_changed(self):
        """NTP时区设置改变时的处理"""
        try:
            ntp_sync_timezone = self.adInterface.findChild(ComboBox, 'ntp_sync_timezone')
            selected_timezone = ntp_sync_timezone.itemData(ntp_sync_timezone.currentIndex())
            config_center.write_conf('Time', 'timezone', selected_timezone)
            if config_center.read_conf('Time', 'type') == 'ntp':
                try:
                    self.show_info_toast('时区设置', f'时区已更新为 {ntp_sync_timezone.currentText()}，正在重新同步时间~')
                    TimeManagerFactory.reset_instance()
                    QTimer.singleShot(100, self.update_ntp_status_display)
                    self._start_async_ntp_sync(utils.time_manager)
                except Exception as e:
                    logger.error(f"应用新时区失败: {e}")
            else:
                self.show_success_toast('时区设置', f'时区已设置为 {ntp_sync_timezone.currentText()}')
        except Exception as e:
            logger.error(f"时区设置失败: {e}")
            self.show_error_toast('时区设置', '时区设置失败')
    
    def _add_ntp_auto_sync_callback(self):
        """添加NTP自动同步回调"""
        try:
            from utils import update_timer
            def ntp_auto_sync_callback():
                """NTP自动同步回调函数"""
                try:
                    if config_center.read_conf('Time', 'type') != 'ntp':
                        return
                    current_manager = utils.time_manager
                    if not isinstance(current_manager, utils.NTPTimeManager):
                        return
                    success = current_manager.sync_with_ntp()
                    if success:
                        try:
                            self.update_ntp_status_display()
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"NTP自动同步异常: {e}")
            self._ntp_auto_sync_callback = ntp_auto_sync_callback
            ntp_auto_refresh_minutes = int(config_center.read_conf('Time', 'ntp_auto_refresh'))
            ntp_auto_refresh_seconds = ntp_auto_refresh_minutes * 60
            update_timer.add_callback(ntp_auto_sync_callback, ntp_auto_refresh_seconds)
            
        except Exception as e:
            logger.error(f"添加NTP自动同步回调失败: {e}")
    
    def _remove_ntp_auto_sync_callback(self):
        """移除NTP自动同步回调"""
        try:
            from utils import update_timer
            if hasattr(self, '_ntp_auto_sync_callback'):
                update_timer.remove_callback(self._ntp_auto_sync_callback)
                delattr(self, '_ntp_auto_sync_callback')
        except Exception as e:
            logger.error(f"移除NTP自动同步回调失败: {e}")
    
    def on_ntp_server_url_changed(self, url: str):
        """修改 NTP 服务器 URL"""
        url = url.strip()
        ntp_server_url_widget = self.adInterface.findChild(LineEdit, 'ntp_server_url')
        if hasattr(self, '_ntp_flyout_timer'):
            self._ntp_flyout_timer.stop()
        self._ntp_flyout_timer = QTimer()
        self._ntp_flyout_timer.setSingleShot(True)
        self._ntp_flyout_timer.timeout.connect(lambda: self._process_ntp_url_change(url, ntp_server_url_widget))
        self._ntp_flyout_timer.start(1500)  # 1.5秒延迟
    
    def _process_ntp_url_change(self, url: str, ntp_server_url_widget):
        """处理NTP URL变更的实际逻辑"""
        if not url:
            self._show_ntp_flyout(
                ntp_server_url_widget, 
                'warning', 
                "NTP服务器URL不能为空 o(〃＾▽＾〃)o\n请输入有效的NTP服务器地址",
                ""
            )
            return
        # 验证url的正则
        # 筛选demo:
        # 域名: pool.ntp.org, time.windows.com, cn.pool.ntp.org
        # IP(v4): 192.168.1.1, 203.107.6.88, 120.25.115.20
        # time.nist.gov:123, 192.168.1.1:123
        pattern = re.compile(
            r'^('
                # 域名筛选
                r'([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+'
                r'[a-zA-Z]{2,}' # 顶级域名(至少2个字母)
            r'|'
                # IP(v4)检查
                r'(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.' # 每个字节（0-255）4个字节使用'.'分隔
                r'(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.'
                r'(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.'
                r'(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)'
            r')'
            # 端口
            r'(?::(6553[0-5]|655[0-2]\d|65[0-4]\d{2}|6[0-4]\d{3}|[1-5]?\d{1,4}))?' # 端口号部分 (1-65535 的端口)
            r'$',
            re.IGNORECASE
        )
        if pattern.match(url):
            config_center.write_conf('Time', 'ntp_server', url)
            self._show_ntp_flyout(
                ntp_server_url_widget, 
                'success', 
                f"NTP服务器已更新: {url}"
            )
            # logger.debug(f"NTP服务器URL已更新: {url}")
        else:
            config_center.write_conf('Time', 'ntp_server', url)
            self._show_ntp_flyout(
                ntp_server_url_widget, 
                'warning', 
                f"URL格式可能不正确: {url}\n请检查是否为有效的域名或IP地址（︶^︶）",
                url
            )
            logger.warning(f"NTP服务器URL格式可能不正确: {url}")
    
    def _show_ntp_flyout(self, target_widget, flyout_type: str, message: str, invalid_url: str = None):
        if hasattr(self, '_current_ntp_flyout') and self._current_ntp_flyout:
            try:
                self._current_ntp_flyout.close()
            except:
                pass
            self._current_ntp_flyout = None
        
        class NTPServerFlyoutView(FlyoutViewBase):
            def __init__(self, flyout_type: str, message: str, invalid_url: str = None, parent=None):
                super().__init__(parent)
                self.flyout_type = flyout_type
                self.invalid_url = invalid_url
                self.parent_menu = parent
                self.vBoxLayout = QVBoxLayout(self)
                self.setFocusPolicy(Qt.NoFocus)
                icon_label = ImageLabel()
                if flyout_type == 'success':
                    icon_label.setPixmap(InfoBarIcon.SUCCESS.icon().pixmap(24, 24))
                    title = '设置成功 ✨'
                elif flyout_type == 'warning':
                    icon_label.setPixmap(InfoBarIcon.WARNING.icon().pixmap(24, 24))
                    title = '格式警告'
                else:
                    icon_label.setPixmap(InfoBarIcon.INFORMATION.icon().pixmap(24, 24))
                    title = 'NTP设置'
                title_layout = QHBoxLayout()
                title_layout.addWidget(icon_label)
                title_label = StrongBodyLabel(title)
                title_layout.addWidget(title_label)
                title_layout.addStretch()
                self.message_label = BodyLabel(message)
                self.message_label.setWordWrap(True)
                self.vBoxLayout.setSpacing(8)
                self.vBoxLayout.setContentsMargins(16, 12, 16, 12)
                self.vBoxLayout.addLayout(title_layout)
                self.vBoxLayout.addWidget(self.message_label)
                if flyout_type == 'warning':
                    if invalid_url is not None:
                        self._add_suggestion_buttons(invalid_url)
                    self._add_save_confirmation()
            
            def _add_suggestion_buttons(self, invalid_url: str):
                """为无效URL添加建议修正按钮"""
                suggestions = self._get_url_suggestions(invalid_url)
                if suggestions:
                    if invalid_url == "":
                        suggestion_label = CaptionLabel("推荐的NTP服务器:")
                    else:
                        suggestion_label = CaptionLabel("建议的修正:")
                    self.vBoxLayout.addWidget(suggestion_label)
                    button_layout = QHBoxLayout()
                    for suggestion in suggestions[:3]:
                        btn = PushButton(suggestion)
                        btn.setFixedHeight(28)
                        btn.setMaximumWidth(150)
                        btn.setFocusPolicy(Qt.NoFocus)
                        btn.clicked.connect(lambda checked, s=suggestion: self._apply_suggestion_and_close(s))
                        button_layout.addWidget(btn)
                    button_layout.addStretch()
                    self.vBoxLayout.addLayout(button_layout)
            
            def _add_save_confirmation(self):
                """添加保存确认按钮"""
                separator = QFrame()
                separator.setFrameShape(QFrame.HLine)
                separator.setFrameShadow(QFrame.Sunken)
                separator.setStyleSheet("QFrame { color: rgba(255, 255, 255, 0.1); }")
                self.vBoxLayout.addWidget(separator)
                confirm_label = CaptionLabel("执意保存当前输入的内容?")
                confirm_label.setObjectName("confirmLabel")
                if isDarkTheme():
                    confirm_label.setStyleSheet("""
                        QLabel#confirmLabel {
                            color: rgba(255, 255, 255, 0.8);
                        }
                    """)
                else:
                    confirm_label.setStyleSheet("""
                        QLabel#confirmLabel {
                            color: rgba(0, 0, 0, 0.8);
                        }
                    """)
                self.vBoxLayout.addWidget(confirm_label)
                button_layout = QHBoxLayout()
                button_layout.setSpacing(8)
                save_btn = PrimaryPushButton("执意保存")
                save_btn.setFixedHeight(32)
                save_btn.setFixedWidth(150)
                save_btn.clicked.connect(self._save_and_close)
                button_layout.addStretch()
                button_layout.addWidget(save_btn)
                self.vBoxLayout.addLayout(button_layout)
            
            def _get_url_suggestions(self, invalid_url: str) -> list:
                suggestions = []
                common_servers = ['ntp.tencent.com', 'ntp.aliyun.com', 'pool.ntp.org', \
                    'ntp.ntsc.ac.cn', 'cn.ntp.org.cn','time.cloudflare.com' , 'time1.google.com', \
                        'time.windows.com', 'ntp1.nim.ac.cn']
                if not invalid_url or invalid_url.strip() == "":
                    return common_servers[:3]
                url = invalid_url.strip()
                if url.startswith(('http://', 'https://')):
                    url = url.split('://', 1)[1]
                valid_domain_pattern = re.compile(
                    r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
                )
                if re.search(r'[`~!@#$%^&*()+=\[\]{}|\\:;"<>?/]', url):
                    pass
                elif valid_domain_pattern.match(url):
                    if not re.search(r'\.\.|\.\-|\-\.|^\.|\.$', url):
                        tld = url.split('.')[-1]
                        if len(tld) >= 2 and tld.isalpha():
                            suggestions.append(url)
                # 好一个智能匹配(闲)
                def calculate_similarity(server: str, user_input: str) -> float:
                    """计算url和输入的相似度"""
                    server_lower = server.lower()
                    user_lower = user_input.lower()
                    if server_lower == user_lower:
                        return 100.0
                    if server_lower.startswith(user_lower):
                        return 90.0 + (len(user_lower) / len(server_lower)) * 10
                    if user_lower in server_lower:
                        return 70.0 + (len(user_lower) / len(server_lower)) * 20
                    user_parts = user_lower.replace('.', ' ').split()
                    server_parts = server_lower.replace('.', ' ').split()
                    match_score = 0
                    for user_part in user_parts:
                        if len(user_part) >= 2:
                            for server_part in server_parts:
                                if user_part in server_part:
                                    match_score += len(user_part) / len(server_part) * 30
                                elif server_part.startswith(user_part):
                                    match_score += len(user_part) / len(server_part) * 25
                    return match_score
                server_scores = []
                for server in common_servers:
                    score = calculate_similarity(server, url)
                    server_scores.append((server, score))
                server_scores.sort(key=lambda x: x[1], reverse=True)
                for server, score in server_scores:
                    if server not in suggestions:
                        suggestions.append(server)
                        if len(suggestions) >= 3:
                            break
                
                return suggestions
            
            def _apply_suggestion_and_close(self, suggestion: str):
                try:
                    if self.parent_menu and hasattr(self.parent_menu, 'adInterface'):
                        ntp_url_widget = self.parent_menu.adInterface.findChild(LineEdit, 'ntp_server_url')
                        if ntp_url_widget:
                            if hasattr(self.parent_menu, '_ntp_flyout_timer'):
                                self.parent_menu._ntp_flyout_timer.stop()
                            try:
                                ntp_url_widget.textChanged.disconnect()
                            except TypeError:
                                pass
                            ntp_url_widget.setText(suggestion)
                            self._close_flyout()
                            ntp_url_widget.textChanged.connect(self.parent_menu.on_ntp_server_url_changed)
                            config_center.write_conf('Time', 'ntp_server', suggestion)
                            self.parent_menu._show_ntp_flyout(
                                ntp_url_widget, 
                                'success', 
                                f"NTP服务器已更新: {suggestion}"
                            )
                            if hasattr(self.parent_menu, 'update_ntp_status_display'):
                                self.parent_menu.update_ntp_status_display()
                except Exception as e:
                    logger.error(f"应用NTP服务器建议失败: {e}")
            
            def _save_and_close(self):
                try:
                    if self.parent_menu:
                        current_url = ""
                        if hasattr(self.parent_menu, 'adInterface'):
                            ntp_url_widget = self.parent_menu.adInterface.findChild(LineEdit, 'ntp_server_url')
                            if ntp_url_widget:
                                current_url = ntp_url_widget.text()
                        self._close_flyout()
                        if hasattr(self.parent_menu, '_show_ntp_flyout'):
                            self.parent_menu._show_ntp_flyout(
                                ntp_url_widget if ntp_url_widget else None,
                                'success',
                                '设置已保存ヾ(≧▽≦*)o'
                            )
                except Exception as e:
                    logger.error(f"保存操作失败: {e}")

            def _close_flyout(self):
                try:
                    if self.parent_menu and hasattr(self.parent_menu, '_current_ntp_flyout'):
                        self.parent_menu._current_ntp_flyout = None
                    flyout_widget = self
                    while flyout_widget and not hasattr(flyout_widget, 'close'):
                        flyout_widget = flyout_widget.parent()
                    
                    if flyout_widget and hasattr(flyout_widget, 'close'):
                        flyout_widget.close()
                except Exception as e:
                    logger.error(f"关闭flyout失败: {e}")
        try:
            flyout_view = NTPServerFlyoutView(flyout_type, message, invalid_url, self)
            flyout = Flyout.make(
                flyout_view, 
                target_widget, 
                self, 
                aniType=FlyoutAnimationType.PULL_UP
            )
            flyout.setWindowFlags(flyout.windowFlags() | Qt.Tool)
            flyout.setFocusPolicy(Qt.NoFocus)
            def custom_show_event(event):
                QWidget.showEvent(flyout, event)
            flyout.showEvent = custom_show_event
            flyout.show()
            self._current_ntp_flyout = flyout
            if flyout_type == 'success':
                import weakref
                flyout_ref = weakref.ref(flyout)
                def safe_close():
                    flyout_obj = flyout_ref()
                    if flyout_obj and not flyout_obj.isHidden():
                        try:
                            flyout_obj.close()
                        except RuntimeError:
                            pass
                QTimer.singleShot(2000, safe_close)
            return flyout
        except Exception as e:
            logger.error(f"显示NTP Flyout失败: {e}")
            if flyout_type == 'success':
                self.show_success_toast('NTP设置', message)
            elif flyout_type == 'warning':
                self.show_warning_toast('NTP设置', message)
            return None

    
    def update_ntp_status_display(self):
        """更新NTP状态显示"""
        try:
            current_manager = utils.time_manager
            caption_label = self.adInterface.findChild(CaptionLabel, 'CaptionLabel_20')
            if isinstance(current_manager, utils.LocalTimeManager):
                caption_label.setText('当前使用: 系统本地时间')
            elif isinstance(current_manager, utils.NTPTimeManager):
                last_sync = current_manager.get_last_ntp_sync()
                if last_sync:
                    sync_time_str = last_sync.strftime('%Y年%m月%d日 - %H:%M:%S')
                    caption_label.setText(f'上次NTP校准: {sync_time_str}')
                else:
                    caption_label.setText('NTP时间: 尚未进行校准')
            else:
                caption_label.setText('时间状态: 未知')
                
        except Exception as e:
            logger.error(f"更新NTP状态显示失败: {e}")
    
    def update_ntp_ui_visibility(self):
        """更新NTP组件的可见性"""
        try:
            current_manager = utils.time_manager
            is_ntp_mode = isinstance(current_manager, utils.NTPTimeManager)
            if hasattr(self, 'ntp_card_widget') and self.ntp_card_widget:
                self.ntp_card_widget.setVisible(is_ntp_mode)
                # logger.debug(f"NTP UI组件可见性: {'显示' if is_ntp_mode else '隐藏'}")
        except Exception as e:
            logger.error(f"更新UI可见性失败: {e}")
    
    def _start_async_ntp_sync(self, time_manager):
        """启动NTP同步"""
        try:
            if hasattr(self, 'ntp_thread') and self.ntp_thread:
                try:
                    if self.ntp_thread.isRunning():
                        self.show_warning_toast('NTP同步', '同步正在进行中,请稍候~')
                        return
                except RuntimeError:
                    self.ntp_thread = None
                    if hasattr(self, 'ntp_worker'):
                        self.ntp_worker = None
            self._cleanup_ntp_thread()
            self.ntp_thread = QThread()
            self.ntp_worker = NTPSyncWorker(time_manager)
            self.ntp_worker.moveToThread(self.ntp_thread)
            self.ntp_thread.started.connect(self.ntp_worker.sync_ntp)
            self.ntp_worker.sync_finished.connect(self._on_ntp_sync_finished)
            self.ntp_worker.sync_finished.connect(self.ntp_thread.quit)
            self.ntp_worker.sync_finished.connect(self.ntp_worker.deleteLater)
            self.ntp_thread.finished.connect(self.ntp_thread.deleteLater)
            self.ntp_thread.start()
        except Exception as e:
            logger.error(f"启动NTP同步时失败: {e}")
            self.show_warning_toast('NTP同步', '启动同步失败')
            self._cleanup_ntp_thread()
    
    def _on_ntp_sync_finished(self, success):
        """NTP同步完成"""
        try:
            if success:
                self.show_success_toast('NTP同步', 'NTP时间同步成功!')
                # 异步更新UI状态，避免阻塞
                QTimer.singleShot(50, self.update_ntp_status_display)
                # 延迟更新父组件数据
                if hasattr(self, 'parent') and self.parent and hasattr(self.parent, 'update_data'):
                    QTimer.singleShot(100, self.parent.update_data)
            else:
                self.show_warning_toast('NTP同步', 'NTP时间同步失败,请检查网络连接和url地址!')
        except Exception as e:
            logger.error(f"NTP同步完成回调失败: {e}")
        finally:
            QTimer.singleShot(100, self._cleanup_ntp_thread)
    
    def _cleanup_ntp_thread(self):
        """清理NTP线程资源"""
        try:
            if hasattr(self, 'ntp_thread') and self.ntp_thread:
                try:
                    if self.ntp_thread.isRunning():
                        if not self.ntp_thread.wait(3000):
                            logger.warning("NTP线程未能在3秒内正常结束，强制终止")
                            self.ntp_thread.terminate()
                            self.ntp_thread.wait(1000)
                except RuntimeError:
                    logger.warning("已删除的QThread对象")
                try:
                    self.ntp_thread.started.disconnect()
                    if hasattr(self, 'ntp_worker') and self.ntp_worker:
                        self.ntp_worker.sync_finished.disconnect()
                except (TypeError, RuntimeError):
                    pass
                
                self.ntp_thread = None
            if hasattr(self, 'ntp_worker') and self.ntp_worker:
                self.ntp_worker = None
        except Exception as e:
            logger.error(f"清理NTP线程资源时出错: {e}")
    # 神经病犯了
    def show_info_toast(self, title: str, message: str):
        try:
            InfoBar.info(
                title=title,
                content=message,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
        except Exception as e:
            logger.error(f"显示信息提示失败: {e}")

    def show_success_toast(self, title: str, message: str):
        try:
            InfoBar.success(
                title=title,
                content=message,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
        except Exception as e:
            logger.error(f"显示成功提示失败: {e}")
    
    def show_warning_toast(self, title: str, message: str):
        try:
            InfoBar.warning(
                title=title,
                content=message,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        except Exception as e:
            logger.error(f"显示错误提示失败: {e}")

    def show_error_toast(self, title: str, message: str):
        try:
            InfoBar.error(
                title=title,
                content=message,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        except Exception as e:
            logger.error(f"显示错误提示失败: {e}")
        
    def setup_schedule_edit(self):
        se_load_item()
        se_set_button = self.findChild(ToolButton, 'set_button')
        se_set_button.setIcon(fIcon.EDIT)
        se_set_button.setToolTip('编辑课程')
        se_set_button.installEventFilter(ToolTipFilter(se_set_button, showDelay=300, position=ToolTipPosition.TOP))
        se_set_button.clicked.connect(self.se_edit_item)

        se_clear_button = self.findChild(ToolButton, 'clear_button')
        se_clear_button.setIcon(fIcon.DELETE)
        se_clear_button.setToolTip('清空课程')
        se_clear_button.installEventFilter(ToolTipFilter(se_clear_button, showDelay=300, position=ToolTipPosition.TOP))
        se_clear_button.clicked.connect(self.se_delete_item)

        se_class_kind_combo = self.findChild(ComboBox, 'class_combo')  # 课程类型
        se_class_kind_combo.addItems(list_.class_kind)

        se_week_combo = self.findChild(ComboBox, 'week_combo')  # 星期
        se_week_combo.addItems(list_.week)
        se_week_combo.currentIndexChanged.connect(self.se_upload_list)

        se_schedule_list = self.findChild(ListWidget, 'schedule_list')
        se_schedule_list.addItems(schedule_dict[str(current_week)])
        se_schedule_list.itemChanged.connect(self.se_upload_item)
        QScroller.grabGesture(se_schedule_list.viewport(), QScroller.LeftMouseButtonGesture)  # 触摸屏适配

        se_save_button = self.findChild(PrimaryPushButton, 'save_schedule')
        se_save_button.clicked.connect(self.se_save_item)

        se_week_type_combo = self.findChild(ComboBox, 'week_type_combo')
        se_week_type_combo.addItems(list_.week_type)
        se_week_type_combo.currentIndexChanged.connect(self.se_upload_list)

        se_copy_schedule_button = self.findChild(PushButton, 'copy_schedule')
        se_copy_schedule_button.hide()
        se_copy_schedule_button.clicked.connect(self.se_copy_odd_schedule)

        quick_set_schedule = self.findChild(ListWidget, 'subject_list')
        quick_set_schedule.addItems(list_.class_kind[1:])
        quick_set_schedule.itemClicked.connect(self.se_quick_set_schedule)

        quick_select_week_button = self.findChild(PushButton, 'quick_select_week')
        quick_select_week_button.clicked.connect(self.se_quick_select_week)

    def setup_timeline_edit(self):  # 底层大改
        self.te_load_item()  # 加载时段
        # teInterface
        te_add_button = self.findChild(ToolButton, 'add_button')  # 添加
        te_add_button.setIcon(fIcon.ADD)
        te_add_button.setToolTip('添加时间线')  # 增加提示
        te_add_button.installEventFilter(ToolTipFilter(te_add_button, showDelay=300, position=ToolTipPosition.TOP))
        te_add_button.clicked.connect(self.te_add_item)
        te_add_button.clicked.connect(self.te_upload_item)

        te_add_part_button = self.findChild(ToolButton, 'add_part_button')  # 添加节点
        te_add_part_button.setIcon(fIcon.ADD)
        te_add_part_button.setToolTip('添加节点')
        te_add_part_button.installEventFilter(
            ToolTipFilter(te_add_part_button, showDelay=300, position=ToolTipPosition.TOP))
        te_add_part_button.clicked.connect(self.te_add_part)

        te_part_type_combo = self.findChild(ComboBox, 'part_type')  # 节次类型
        te_part_type_combo.clear()
        te_part_type_combo.addItems(list_.part_type)

        te_name_edit = self.findChild(EditableComboBox, 'name_part_combo')  # 名称
        te_name_edit.addItems(list_.time)

        te_edit_part_button = self.findChild(ToolButton, 'edit_part_button')  # 编辑节点开始时间
        te_edit_part_button.setIcon(fIcon.EDIT)
        te_edit_part_button.setToolTip('编辑节点开始时间')
        te_edit_part_button.installEventFilter(
            ToolTipFilter(te_edit_part_button, showDelay=300, position=ToolTipPosition.TOP))
        te_edit_part_button.clicked.connect(self.te_edit_part_time)

        te_delete_part_button = self.findChild(ToolButton, 'delete_part_button')  # 删除节点
        te_delete_part_button.setIcon(fIcon.DELETE)
        te_delete_part_button.setToolTip('删除节点')
        te_delete_part_button.installEventFilter(
            ToolTipFilter(te_delete_part_button, showDelay=300, position=ToolTipPosition.TOP))
        te_delete_part_button.clicked.connect(self.te_delete_part)

        te_edit_button = self.findChild(ToolButton, 'edit_button')  # 编辑
        te_edit_button.setIcon(fIcon.EDIT)
        te_edit_button.setToolTip('编辑时间线')
        te_edit_button.installEventFilter(ToolTipFilter(te_edit_button, showDelay=300, position=ToolTipPosition.TOP))
        te_edit_button.clicked.connect(self.te_edit_item)

        te_delete_button = self.findChild(ToolButton, 'delete_button')  # 删除
        te_delete_button.setIcon(fIcon.DELETE)
        te_delete_button.setToolTip('删除时间线')
        te_delete_button.installEventFilter(
            ToolTipFilter(te_delete_button, showDelay=300, position=ToolTipPosition.TOP))
        te_delete_button.clicked.connect(self.te_delete_item)
        te_delete_button.clicked.connect(self.te_upload_item)

        te_class_activity_combo = self.findChild(ComboBox, 'class_activity')  # 活动类型
        te_class_activity_combo.addItems(list_.class_activity)
        te_class_activity_combo.setToolTip('选择活动类型（“课程”或“课间”）')
        te_class_activity_combo.currentIndexChanged.connect(self.te_sync_time)

        te_select_timeline = self.findChild(ComboBox, 'select_timeline')  # 选择时间线
        te_select_timeline.addItem('默认')
        te_select_timeline.addItems(list_.week)
        te_select_timeline.setToolTip('选择一周内的某一天的时间线')
        te_select_timeline.currentIndexChanged.connect(self.te_upload_list)

        te_timeline_list = self.findChild(ListWidget, 'timeline_list')  # 所选时间线列表
        te_timeline_list.addItems(timeline_dict['default'])
        te_timeline_list.itemChanged.connect(self.te_upload_item)

        te_part_time = self.teInterface.findChild(TimeEdit, 'part_time')  # 节次时间
        te_part_time.timeChanged.connect(
            lambda: self.show_tip_flyout('重要提示', '请使用 24 小时制', te_part_time)
        )

        te_save_button = self.findChild(PrimaryPushButton, 'save')  # 保存
        te_save_button.clicked.connect(self.te_save_item)

        part_list = self.findChild(ListWidget, 'part_list')
        QScroller.grabGesture(te_timeline_list.viewport(), QScroller.LeftMouseButtonGesture)  # 触摸屏适配
        QScroller.grabGesture(part_list.viewport(), QScroller.LeftMouseButtonGesture)  # 触摸屏适配
        self.te_detect_item()
        self.te_update_parts_name()

    def te_edit_part_time(self):
        """编辑选中节点的开始时间"""
        te_part_list = self.findChild(ListWidget, 'part_list')
        te_part_time = self.findChild(TimeEdit, 'part_time')
        selected_items = te_part_list.selectedItems()
        if not selected_items:
            Flyout.create(
                icon=InfoBarIcon.WARNING,
                title='请先选择一个节点 o(TヘTo)',
                content='在编辑节点时间前，请先在左侧列表中选择要编辑的节点',
                target=self.findChild(ToolButton, 'edit_part_button'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )
            return
        selected_item = selected_items[0]
        item_text = selected_item.text()
        item_info = item_text.split(' - ')
        if len(item_info) >= 3:
            part_name = item_info[0]
            part_type = item_info[2]
            new_time = te_part_time.time().toString("h:mm")
            new_text = f'{part_name} - {new_time} - {part_type}'
            selected_item.setText(new_text)
            self.te_detect_item()
            self.te_update_parts_name()
            Flyout.create(
                icon=InfoBarIcon.SUCCESS,
                title='节点时间已更新 ヾ(≧▽≦*)o',
                content=f'节点 "{part_name}" 的开始时间已更新为 {new_time}',
                target=self.findChild(ToolButton, 'edit_part_button'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )
        else:
            Flyout.create(
                icon=InfoBarIcon.ERROR,
                title='节点格式异常 (╥﹏╥)',
                content='选中的节点格式不正确，无法编辑',
                target=self.findChild(ToolButton, 'edit_part_button'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )

    def setup_schedule_preview(self):
        subtitle = self.findChild(SubtitleLabel, 'subtitle_file')
        subtitle.setText(f'预览  -  {config_center.schedule_name[:-5]}')

        schedule_view = self.findChild(TableWidget, 'schedule_view')
        schedule_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)  # 使列表自动等宽

        sp_week_type_combo = self.findChild(ComboBox, 'pre_week_type_combo')
        sp_week_type_combo.addItems(list_.week_type)
        sp_week_type_combo.currentIndexChanged.connect(self.sp_fill_grid_row)

        # 设置表格
        schedule_view.setColumnCount(7)
        schedule_view.setHorizontalHeaderLabels(list_.week[0:7])
        schedule_view.setBorderVisible(True)
        schedule_view.verticalHeader().hide()
        schedule_view.setBorderRadius(8)
        QScroller.grabGesture(schedule_view.viewport(), QScroller.LeftMouseButtonGesture)  # 触摸屏适配
        self.sp_fill_grid_row()

    def save_volume(self):
        slider_volume = self.findChild(Slider, 'slider_volume')
        config_center.write_conf('Audio', 'volume', str(slider_volume.value()))

    def show_search_city(self):
        search_city_dialog = selectCity(self)
        if search_city_dialog.exec():
            selected_city = search_city_dialog.city_list.selectedItems()
            if selected_city:
                config_center.write_conf('Weather', 'city', wd.search_code_by_name((selected_city[0].text(),'')))

    def show_license(self):
        license_dialog = licenseDialog(self)
        license_dialog.exec()

    def save_prepare_time(self):
        prepare_time_spin = self.findChild(SpinBox, 'spin_prepare_class')
        config_center.write_conf('Toast', 'prepare_minutes', str(prepare_time_spin.value()))

    def clear_log(self):  # 清空日志
        def get_directory_size(path):  # 计算目录大小
            total_size = 0
            for dir_path, dir_names, filenames in os.walk(path):
                for file_name in filenames:
                    file_path = os.path.join(dir_path, file_name)
                    total_size += os.path.getsize(file_path)
            total_size /= 1024
            return round(total_size, 2)

        self.button_clear_log = self.adInterface.findChild(PushButton, 'button_clear_log')
        size = get_directory_size('log')

        try:
            if os.path.exists('log'):
                rmtree('log')
                Flyout.create(
                    icon=InfoBarIcon.SUCCESS,
                    title='已清除日志',
                    content=f"已清空所有日志文件，约 {size} KB",
                    target=self.button_clear_log,
                    parent=self,
                    isClosable=True,
                    aniType=FlyoutAnimationType.PULL_UP
                )
            else:
                Flyout.create(
                    icon=InfoBarIcon.INFORMATION,
                    title='未找到日志',
                    content="日志目录下为空，已清理完成。",
                    target=self.button_clear_log,
                    parent=self,
                    isClosable=True,
                    aniType=FlyoutAnimationType.PULL_UP
                )
        except OSError:  # 遇到程序正在使用的log，忽略
            Flyout.create(
                icon=InfoBarIcon.SUCCESS,
                title='已清除日志',
                content=f"已清空所有日志文件，约 {size} KB",
                target=self.button_clear_log,
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )
        except Exception as e:
            Flyout.create(
                icon=InfoBarIcon.ERROR,
                title='清除日志失败！',
                content=f"清除日志失败：{e}",
                target=self.button_clear_log,
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )

    def ct_change_color_mode(self):
        color_mode_combo = self.findChild(ComboBox, 'combo_color_mode')
        config_center.write_conf('General', 'color_mode', str(color_mode_combo.currentIndex()))
        if color_mode_combo.currentIndex() == 0:
            tg_theme = Theme.LIGHT
        elif color_mode_combo.currentIndex() == 1:
            tg_theme = Theme.DARK
        else:
            tg_theme = Theme.AUTO
        setTheme(tg_theme)
        self.ct_update_preview()

    def ct_add_widget(self):
        widgets_list = self.findChild(ListWidget, 'widgets_list')
        widgets_combo = self.findChild(ComboBox, 'widgets_combo')
        if (not widgets_list.findItems(widgets_combo.currentText(), QtCore.Qt.MatchFlag.MatchExactly)) or widgets_combo.currentText() in list_.native_widget_name:
            widgets_list.addItem(widgets_combo.currentText())
        self.ct_update_preview()

    def ct_remove_widget(self):
        widgets_list = self.findChild(ListWidget, 'widgets_list')
        if widgets_list.count() > 2:
            widgets_list.takeItem(widgets_list.currentRow())
            self.ct_update_preview()
        else:
            w = MessageBox('无法删除', '至少需要保留两个小组件。', self)
            w.cancelButton.hide()  # 隐藏取消按钮
            w.buttonLayout.insertStretch(0, 1)
            w.exec()

    def ct_set_ac_color(self):
        current_color = QColor(f'#{config_center.read_conf("Color", "attend_class")}')
        w = ColorDialog(current_color, "更改上课时主题色", self, enableAlpha=False)
        w.colorChanged.connect(lambda color: config_center.write_conf('Color', 'attend_class', color.name()[1:]))
        w.exec()

    def ct_set_fc_color(self):
        current_color = QColor(f'#{config_center.read_conf("Color", "finish_class")}')
        w = ColorDialog(current_color, "更改课间时主题色", self, enableAlpha=False)
        w.colorChanged.connect(lambda color: config_center.write_conf('Color', 'finish_class', color.name()[1:]))
        w.exec()

    def ct_set_floating_time_color(self):
        current_color = QColor(f'#{config_center.read_conf("Color", "floating_time")}')
        w = ColorDialog(current_color, "更改浮窗时间颜色", self, enableAlpha=False)
        w.colorChanged.connect(lambda color: config_center.write_conf('Color', 'floating_time', color.name()[1:]))
        w.exec()
        self.ct_update_preview()

    def cf_export_schedule(self, file_name):  # 导出课程表
        file_path, _ = QFileDialog.getSaveFileName(self, "保存文件", file_name,
                                                   "Json 配置文件 (*.json)")
        if file_path:
            if list_.export_schedule(file_path, file_name):
                self.show_tip_flyout('您已成功导出课程表配置文件',
                                   f'文件将导出于{file_path}', self.cfInterface, InfoBarIcon.SUCCESS, FlyoutAnimationType.PULL_UP)
            else:
                self.show_tip_flyout('导出失败！',
                                   '课程表文件导出失败，\n'
                                   '可能为文件损坏，请将此情况反馈给开发者。', self.cfInterface, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)

    def check_update(self):
        self.version_thread = VersionThread()
        self.version_thread.version_signal.connect(self.check_version)
        self.version_thread.start()

    def check_version(self, version):  # 检查更新
        if 'error' in version:
            self.version_number_label.setText(f'版本号：获取失败！')
            self.build_commit_label.setText(f'获取失败！')
            self.build_uuid_label.setText(f'获取失败！')
            self.build_date_label.setText(f'获取失败！')

            if utils.tray_icon:
                utils.tray_icon.push_error_notification(
                    "检查更新失败！",
                    f"检查更新失败！\n{version['error']}"
                )
            return False

        channel = int(config_center.read_conf("Version", "version_channel"))
        new_version = version['version_release' if channel == 0 else 'version_beta']
        local_version = config_center.read_conf("Version", "version") or "0.0.0"
        build_commit = config_center.read_conf("Version", "build_commit")
        build_branch = config_center.read_conf("Version", "build_branch")
        build_runid = config_center.read_conf("Version", "build_runid")
        build_type = config_center.read_conf("Version", "build_type")
        build_time = config_center.read_conf("Version", "build_time")

        logger.debug(f"服务端版本: {Version(new_version)}，本地版本: {Version(local_version)}")
        if Version(new_version) <= Version(local_version):
            self.version_number_label.setText(f'版本号：{local_version}\n已是最新版本！')
            self.build_commit_label.setText(f'{build_commit if build_commit != "__BUILD_COMMIT__" else "Debug"}({build_branch if build_branch != "__BUILD_BRANCH__" else "Debug"})')
            self.build_uuid_label.setText(f'{build_runid if build_runid != "__BUILD_RUNID__" else "Debug"} - {build_type if build_type != "__BUILD_TYPE__" else "Debug"}')
            self.build_date_label.setText(f'{build_time if build_time != "__BUILD_TIME__" else "Debug"}')
        else:
            self.version_number_label.setText(f'版本号：{local_version}\n可更新版本: {new_version}')
            self.build_commit_label.setText(f'{build_commit if build_commit != "__BUILD_COMMIT__" else "Debug"}({build_branch if build_branch != "__BUILD_BRANCH__" else "Debug"})')
            self.build_uuid_label.setText(f'{build_runid if build_runid != "__BUILD_RUNID__" else "Debug"} - {build_type if build_type != "__BUILD_TYPE__" else "Debug"}')
            self.build_date_label.setText(f'{build_time if build_time != "__BUILD_TIME__" else "Debug"}')

            if utils.tray_icon:
                utils.tray_icon.push_update_notification(f"新版本速递：{new_version}")
            if config_center.read_conf("Version","auto_upgrade"):
                self.do_upgrade_button.setEnabled(True)
                self.do_upgrade_button.setText("立即更新")
        self.version_info = version
    def cf_import_schedule_cses(self, file_path):  # 导入课程表（CSES）
        if file_path:
            file_name = file_path.split("/")[-1]
            save_path = base_directory / "config" / "schedule" / \
                f"{file_name.replace('.yaml', '.json')}"

            if os.path.exists(save_path):
                overwrite = MessageBox('文件已存在', f'文件 {file_name} 已存在，是否覆盖？', self)
                overwrite.yesButton.setText('覆盖')
                if not overwrite.exec():
                    return
        
            importer = CSES_Converter(file_path)
            importer.load_parser()
            cw_data = importer.convert_to_cw()
            if not cw_data:
                self.show_tip_flyout('转换失败！',
                                   '课程表文件转换失败！\n'
                                   '可能为格式错误或文件损坏，请检查此文件是否为正确的 CSES 课程表文件。\n'
                                   '详情请查看Log日志，日志位于./log/下。', self.import_from_file, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)
            try:
                with open(save_path, 'w', encoding='utf-8') as f:
                    json.dump(cw_data, f, ensure_ascii=False, indent=4)
                    self.cf_reload_table()
                    self.show_tip_flyout('导入成功！',
                                   '课程表文件导入成功！\n'
                                   '请手动切换您的配置文件。', self.import_from_file, InfoBarIcon.SUCCESS, FlyoutAnimationType.PULL_UP)
            except Exception as e:
                logger.error(f'导入课程表时发生错误：{e}')
                self.show_tip_flyout('导入失败！',
                                   '课程表文件导入失败！\n'
                                   '可能为格式错误或文件损坏，请检查此文件是否为正确的 CSES 课程表文件。\n'
                                   '详情请查看Log日志，日志位于./log/下。', self.import_from_file, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)

    def cf_export_schedule_cses(self, file_name):  # 导出课程表（CSES）
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存文件", file_name.replace('.json', '.yaml'), "CSES 通用课程表交换文件 (*.yaml)")
        if file_path:
            exporter = CSES_Converter(file_path)
            exporter.load_generator()
            if exporter.convert_to_cses(cw_path=f'{base_directory}/config/schedule/{file_name}'):
                self.show_tip_flyout('您已成功导出课程表配置文件',
                                   f'文件将导出于{file_path}', self.cfInterface, InfoBarIcon.SUCCESS, FlyoutAnimationType.PULL_UP)
            else:
                self.show_tip_flyout('导出失败！',
                                   '课程表文件导出失败，\n'
                                   '可能为文件损坏，请将此情况反馈给开发者。', self, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)

    def cf_import_schedule(self):  # 导入课程表
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "支持的文件类型 (*.json *.yaml *.yml);;Json 配置文件 (*.json);;CSES 通用课程表交换文件 (*.yaml) (*.yaml *.yml)")
        if file_path:
            if file_path.endswith('.yaml') or file_path.endswith('.yml'):
                return self.cf_import_schedule_cses(file_path)
            file_name = file_path.split("/")[-1]

            save_path = base_directory / "config" / "schedule" / file_name
            if os.path.exists(save_path):
                overwrite = MessageBox('文件已存在', f'文件 {file_name} 已存在，是否覆盖？', self)
                overwrite.yesButton.setText('覆盖')
                if not overwrite.exec():
                    return
        
            if list_.import_schedule(file_path, file_name):
                self.cf_reload_table()
                self.show_tip_flyout('您已成功导入课程表配置文件',
                                   f'文件将导入于{file_name}，请手动切换您的配置文件。', self.import_from_file, InfoBarIcon.SUCCESS, FlyoutAnimationType.PULL_UP)
            else:
                self.show_tip_flyout('导入失败！',
                                   '课程表文件导入失败！\n'
                                   '可能为格式错误或文件损坏，请检查此文件是否为 Class Widgets 课程表文件。\n'
                                   '详情请查看Log日志，日志位于./log/下。\n'
                                   '注意: 尚不支持 json 格式的 CSES 课表导入', self.import_from_file, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)

    def ct_save_widget_config(self):
        widgets_list = self.findChild(ListWidget, 'widgets_list')
        widget_config = {'widgets': []}
        for i in range(widgets_list.count()):
            widget_config['widgets'].append(list_.widget_conf[widgets_list.item(i).text()])
        if conf.save_widget_conf_to_json(widget_config):
            self.ct_update_preview()
            Flyout.create(
                icon=InfoBarIcon.SUCCESS,
                title='保存成功',
                content=f"已保存至 ./config/widget.json",
                target=self.findChild(PrimaryPushButton, 'save_config'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )

    def ct_update_preview(self):
        try:
            widgets_preview = self.findChild(QHBoxLayout, 'widgets_preview')
            # 获取配置列表
            widget_config = list_.get_widget_config()
            while widgets_preview.count() > 0:  # 清空预览界面
                item = widgets_preview.itemAt(0)
                if item:
                    widget = item.widget()
                    if widget:
                        widget.deleteLater()
                    widgets_preview.removeItem(item)

            left_spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            widgets_preview.addItem(left_spacer)

            theme_folder = config_center.read_conf("General", "theme")
            theme_info = load_theme_config(str(theme_folder))
            theme_config = theme_info.config
            theme_path = theme_info.path
            for i in range(len(widget_config)):
                widget_name: str = widget_config[i] # type: ignore
                preview_path = theme_path / f'preview/{widget_name[:-3]}.png'
                if isDarkTheme() and theme_config.support_dark_mode:
                    if (theme_path / 'dark' / preview_path).exists():
                        path = theme_path / 'dark' / preview_path
                    else:
                        path = theme_path / 'dark/preview/widget-custom.png'
                else:
                    if (theme_path / preview_path).exists():
                        path = theme_path / preview_path
                    else:
                        path = theme_path / 'preview/widget-custom.png'

                label = ImageLabel()
                label.setImage(str(path))
                widgets_preview.addWidget(label)
                widget_config[i] = label
            right_spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            widgets_preview.addItem(right_spacer)
        except Exception as e:
            logger.error(f'更新预览界面时发生错误：{e}')

    def cf_reload_table(self):
        try:
            self.table.currentRowChanged.disconnect()
        except:
            pass

        self.table.clear()
        
        config_list = list_.get_schedule_config()
        self.cf_file_list = []
        for i, cfg in enumerate(config_list):
            url = file.load_from_json(cfg).get('url','local')
            self.cf_file_list.append(self.cf_add_item(cfg, url, i))

        cur = config_list.index(config_center.read_conf('General','schedule'))
        self.table.setCurrentRow(cur)
        
        self.table.currentRowChanged.connect(self.cf_change_file)
        self.table.resizeEvent(None)

    def cf_new_config(self):
        try:
            def is_valid_filename(file_name):
                # 检查是否为空
                if not file_name.strip():
                    return False, "文件名不能为空"
                
                # 检查非法字符
                invalid_chars = r'[\\/:*?"<>|]'
                if re.search(invalid_chars, file_name):
                    return False, "文件名包含非法字符"
                
                # 检查长度
                if len(file_name) > 255:
                    return False, "文件名过长"
                
                # 检查保留名称
                reserved_names = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                                "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
                if file_name.upper() in reserved_names:
                    return False, "文件名是保留名称"
                
                # 检查路径分隔符
                if os.path.sep in file_name:
                    return False, "文件名不能包含路径分隔符"
                
                return True, "文件名合法"
            
            n2_dialog = TextFieldMessageBox(
                        self, '请输入新课表名称',
                        '请命名您的课程表计划：', '新课表 - 1', list_.get_schedule_config(), is_valid_filename
                    )
            if not n2_dialog.exec():
                return

            new_name = n2_dialog.textField.text()

            list_.create_new_profile(f'{new_name}.json')
            config_center.write_conf('General', 'schedule', f'{new_name}.json')
            config_center.schedule_name = f'{new_name}.json'
            schedule_center.update_schedule()
            self.te_load_item()
            self.te_upload_list()
            self.te_update_parts_name()
            se_load_item()
            self.se_upload_list()
            self.sp_fill_grid_row()

            self.table.clear()

            config_list = list_.get_schedule_config()
            self.cf_file_list.clear()

            for id in range(len(config_list)):
                self.cf_file_list.append(self.cf_add_item(config_list[id],'local',id))

            self.table.setCurrentRow(list_.get_schedule_config().index(f'{new_name}.json'))
            self.table.currentRowChanged.connect(self.cf_change_file)
            self.table.resizeEvent(None)
        except Exception as e:
            logger.error(f'新建配置文件时发生错误：{e}')

    def cf_change_file(self):  # 切换课程文件
        try:
            if self.cf_file_list[self.table.currentIndex().row()].file_name.text():
                new_name = self.cf_file_list[self.table.currentIndex().row()].file_name.text()
                config_center.write_conf('General', 'schedule', new_name)
                utils.tray_icon.update_tooltip()
            else:
                logger.error(f'切换课程文件时列表选择异常：{self.cf_file_list[self.table.currentIndex().row()].file_name.text()}')
                Flyout.create(
                    icon=InfoBarIcon.ERROR,
                    title='错误！',
                    content=f"列表选项异常！{self.cf_file_list[self.table.currentIndex().row()].file_name.text()}",
                    target=self.table,
                    parent=self,
                    isClosable=True,
                    aniType=FlyoutAnimationType.DROP_DOWN
                )
                return
            global loaded_data

            config_center.schedule_name = config_center.read_conf('General', 'schedule')
            schedule_center.update_schedule()
            loaded_data = schedule_center.schedule_data
            self.te_load_item()
            self.te_upload_list()
            self.te_update_parts_name()
            se_load_item()
            self.se_upload_list()
            self.sp_fill_grid_row()
        except Exception as e:
            logger.error(f'切换配置文件时发生错误：{e}')

    def cf_get_schedule(self):
        url = schedule_center.schedule_data.get('url', 'local')
        if url == 'local':
            self.show_tip_flyout('获取配置文件失败',
                                   '当前课表为本地课表，无法获取配置文件。请上传课表后再尝试获取配置文件。',
                                   self.config_download, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)
            return
        self.schedule_get_thread = scheduleThread(url)
        self.schedule_get_thread.update_signal.connect(self.cf_receive_schedule)
        self.schedule_get_thread.start()

    def cf_receive_schedule(self, data):
        if not (data.get('error', None) is None):
            self.show_tip_flyout('获取配置文件失败',
                                   data['error'], self.config_download, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)
            return
        try:
            schedule_center.save_data(data, config_center.schedule_name)
        except ValueError as e:
            logger.error(f'更新配置文件 {config_center.schedule_name} 时发生错误：{e}')
            self.show_tip_flyout('更新配置文件失败',
                                   f"{e}", self.config_download, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)  
            return
        schedule_center.update_schedule()

    def cf_load_schedule_from_db(self):
        try:
            self.config_url:LineEdit = self.cfInterface.findChild(LineEdit, 'config_url')
            url = self.config_url.text()
            if url == '':
                self.show_tip_flyout('请输入配置文件链接',
                                   '请输入配置文件链接', self.config_url, InfoBarIcon.WARNING, FlyoutAnimationType.DROP_DOWN)
                return        
            self.schedule_load_thread = scheduleThread(url)
            self.schedule_load_thread.update_signal.connect(self.cf_receive_schedule_from_db)
            self.schedule_load_thread.start()
            self.config_url.setEnabled(False)
            
        except Exception as e:
            logger.error(f'获取配置文件 {url} 时发生错误：{e}')
    
    def cf_receive_schedule_from_db(self, data):
        if not (data.get('error', None) is None):
            self.show_tip_flyout('获取配置文件失败',
                                   data['error'], self.config_download, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)
            self.config_url.setEnabled(True)
            return
        self.cf_new_config()
        self.config_url = self.cfInterface.findChild(LineEdit, 'config_url')
        url = self.config_url.text()
        data['url'] = url
        try:
            schedule_center.save_data(data, config_center.schedule_name)
        except ValueError as e:
            logger.error(f'保存配置文件 {url} 时发生错误：{e}')
            self.show_tip_flyout('保存配置文件失败，将自动保存为空课表',
                                   f"{e}", self.config_download, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)
            self.config_url.setEnabled(True)
            return
        self.config_url.setEnabled(True)
        self.config_url.clear()

    def cf_post_schedule(self):
        url = self.cf_file_list[self.table.currentIndex().row()].url
        try:
            if url == '' or url == 'local':
                n2_dialog = TextFieldMessageBox(
                        self, '请输入课表链接',
                        f'当前可缩写数据库：\n{list_.schedule_dbs}\n你可以使用缩写来代替完整的数据库链接', '')
                if not n2_dialog.exec():
                    return
                url = n2_dialog.textField.text()

                for db in list_.schedule_dbs:
                    if url.startswith(db):
                        url = url.replace(db, list_.schedule_dbs[db])
                        break
                
                self.cf_file_list[self.table.currentIndex().row()].set_file_path(url)
                schedule_center.update_url(url)

            self.schedule_post_thread = scheduleThread(url, 'POST', data=schedule_center.schedule_data)
            self.schedule_post_thread.update_signal.connect(self.cf_receive_schedule_from_post)
            self.schedule_post_thread.start()
            
        except Exception as e:
            logger.error(f'上传配置文件 {url} 时发生错误：{e}')
            self.show_tip_flyout('上传配置文件失败',
                                   f"{e}", self.config_upload, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)

    def cf_receive_schedule_from_post(self, data):
        if data.get('error', None):
            self.show_tip_flyout('上传配置文件失败',
                                   data['error'], self.config_upload, InfoBarIcon.ERROR, FlyoutAnimationType.PULL_UP)

    def check_and_disable_schedule_edit(self):
        """检查是否存在调休状态，如果存在则禁用课程表编辑功能"""
        adjusted_classes = schedule_center.schedule_data.get('adjusted_classes', {})
        is_adjusted = bool(adjusted_classes)

        if is_adjusted:
            se_set_button = self.findChild(ToolButton, 'set_button')
            se_clear_button = self.findChild(ToolButton, 'clear_button')
            se_class_kind_combo = self.findChild(ComboBox, 'class_combo')
            se_custom_class_text = self.findChild(LineEdit, 'custom_class')
            se_save_button = self.findChild(PrimaryPushButton, 'save_schedule')
            se_copy_schedule_button = self.findChild(PushButton, 'copy_schedule')
            quick_set_schedule = self.findChild(ListWidget, 'subject_list')
            quick_select_week_button = self.findChild(PushButton, 'quick_select_week')
            se_set_button.setEnabled(False)
            se_clear_button.setEnabled(False)
            se_class_kind_combo.setEnabled(False)
            se_custom_class_text.setEnabled(False)
            se_save_button.setEnabled(False)
            se_copy_schedule_button.setEnabled(False)
            quick_set_schedule.setEnabled(False)
            quick_select_week_button.setEnabled(False)

    def check_and_disable_timeline_edit(self):
        """检查是否存在调休状态，如果存在则禁用时间线编辑功能"""
        adjusted_classes = schedule_center.schedule_data.get('adjusted_classes', {})
        is_adjusted = bool(adjusted_classes)
        if is_adjusted:
            te_add_button = self.findChild(ToolButton, 'add_button')
            te_add_part_button = self.findChild(ToolButton, 'add_part_button')
            te_delete_part_button = self.findChild(ToolButton, 'delete_part_button')
            te_edit_button = self.findChild(ToolButton, 'edit_button')
            te_delete_button = self.findChild(ToolButton, 'delete_button')
            te_save_button = self.findChild(PrimaryPushButton, 'save')
            te_add_button.setEnabled(False)
            te_add_part_button.setEnabled(False)
            te_delete_part_button.setEnabled(False)
            te_edit_button.setEnabled(False)
            te_delete_button.setEnabled(False)
            te_save_button.setEnabled(False)

    def sp_fill_grid_row(self):  # 填充预览表格
        subtitle = self.findChild(SubtitleLabel, 'subtitle_file')
        adjusted_classes = schedule_center.schedule_data.get('adjusted_classes', {})

        sp_week_type_combo = self.findChild(ComboBox, 'pre_week_type_combo')
        if sp_week_type_combo.currentIndex() == 1:
            schedule_dict_sp = schedule_even_dict
            week_type = 'even'
        else:
            schedule_dict_sp = schedule_dict
            week_type = 'odd'
        is_adjusted = any(adjusted_classes.get(f'{week_type}_{i}', False) for i in range(len(schedule_dict_sp)))
        schedule_name = config_center.schedule_name[:-5]
        if is_adjusted:
            subtitle.setText(f'预览  -  [调休] {schedule_name}')
        else:
            subtitle.setText(f'预览  -  {schedule_name}')
        schedule_view = self.findChild(TableWidget, 'schedule_view')
        schedule_view.setRowCount(sp_get_class_num())

        for i in range(len(schedule_dict_sp)):  # 周数
            for j in range(len(schedule_dict_sp[str(i)])):  # 一天内全部课程
                item_text = schedule_dict_sp[str(i)][j].split('-')[0]
                if item_text != '未添加':
                    if adjusted_classes.get(f'{week_type}_{i}', False):
                        item = QTableWidgetItem(f'{item_text}')
                        color = themeColor()
                        color.setAlpha(64)
                        item.setBackground(color)
                    else:
                        item = QTableWidgetItem(item_text)
                else:
                    item = QTableWidgetItem('')
                schedule_view.setItem(j, i, item)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    # 加载时间线
    def te_load_item(self):
        global morning_st, afternoon_st, loaded_data, timeline_dict
        loaded_data = schedule_center.schedule_data
        part = loaded_data.get('part')
        part_name = loaded_data.get('part_name')
        timeline = get_timeline()
        # 找控件
        te_timeline_list = self.findChild(ListWidget, 'timeline_list')
        te_timeline_list.clear()
        part_list = self.findChild(ListWidget, 'part_list')
        part_list.clear()

        for part_num, part_time in part.items():  # 加载节点
            prefix = part_name[part_num]
            time = QTime(int(part_time[0]), int(part_time[1])).toString('h:mm')
            period = time
            try:
                part_type = part_time[2]
            except IndexError:
                part_type = 'part'

            part_type = list_.part_type[part_type == 'break']
            text = f'{prefix} - {period} - {part_type}'
            part_list.addItem(text)

        for week, _ in timeline.items():  # 加载节点
            all_line = []
            for item_name, time in timeline[week].items():  # 加载时间线
                prefix = ''
                item_time = f'{timeline[week][item_name]}分钟'
                # 判断前缀和时段
                if item_name.startswith('a'):
                    prefix = '课程'
                elif item_name.startswith('f'):
                    prefix = '课间'
                period = part_name[item_name[1]]

                # 还原 item_text
                item_text = f"{prefix} - {item_time} - {period}"
                all_line.append(item_text)
            timeline_dict[week] = all_line

    def se_copy_odd_schedule(self):
        logger.info('复制单周课表')
        global schedule_dict, schedule_even_dict
        schedule_even_dict = deepcopy(schedule_dict)
        self.se_upload_list()

    def te_upload_list(self):  # 更新时间线到列表组件
        logger.info('更新列表：时间线编辑')
        te_timeline_list = self.findChild(ListWidget, 'timeline_list')
        te_select_timeline = self.findChild(ComboBox, 'select_timeline')
        try:
            if te_select_timeline.currentIndex() == 0:
                te_timeline_list.clear()
                te_timeline_list.addItems(timeline_dict['default'])
            else:
                te_timeline_list.clear()
                te_timeline_list.addItems(timeline_dict[str(te_select_timeline.currentIndex() - 1)])
            self.te_detect_item()
        except Exception as e:
            print(f'加载时间线时发生错误：{e}')

    def show_tip_flyout(self, title, content, target, status=InfoBarIcon.WARNING, aniType=FlyoutAnimationType.PULL_UP):
        Flyout.create(
            icon=status,
            title=title,
            content=content,
            target=target,
            parent=self,
            isClosable=True,
            aniType=aniType,
            
        )

    # 上传课表到列表组件
    def se_upload_list(self):  # 更新课表到列表组件
        logger.info('更新列表：课程表编辑')
        se_schedule_list = self.findChild(ListWidget, 'schedule_list')
        se_schedule_list.clearSelection()
        se_week_combo = self.findChild(ComboBox, 'week_combo')
        se_week_type_combo = self.findChild(ComboBox, 'week_type_combo')
        se_copy_schedule_button = self.findChild(PushButton, 'copy_schedule')
        global current_week
        try:
            if se_week_type_combo.currentIndex() == 1:
                se_copy_schedule_button.show()
                current_week = se_week_combo.currentIndex()
                se_schedule_list.clear()
                se_schedule_list.addItems(schedule_even_dict[str(current_week)])
            else:
                se_copy_schedule_button.hide()
                current_week = se_week_combo.currentIndex()
                se_schedule_list.clear()
                se_schedule_list.addItems(schedule_dict[str(current_week)])
        except Exception as e:
            print(f'加载课表时发生错误：{e}')

    def se_upload_item(self):  # 保存列表内容到课表文件
        se_schedule_list = self.findChild(ListWidget, 'schedule_list')
        se_week_type_combo = self.findChild(ComboBox, 'week_type_combo')
        if se_week_type_combo.currentIndex() == 1:
            global schedule_even_dict
            try:
                cache_list = []
                for i in range(se_schedule_list.count()):
                    item_text = se_schedule_list.item(i).text()
                    cache_list.append(item_text)
                schedule_even_dict[str(current_week)][:] = cache_list
            except Exception as e:
                print(f'加载双周课表时发生错误：{e}')
        else:
            global schedule_dict
            cache_list = []
            for i in range(se_schedule_list.count()):
                item_text = se_schedule_list.item(i).text()
                cache_list.append(item_text)
            schedule_dict[str(current_week)][:] = cache_list

    # 保存课程
    def se_save_item(self):
        try:
            data_dict = deepcopy(schedule_dict)
            data_dict_even = deepcopy(schedule_even_dict)  # 单双周保存

            data_dict = convert_to_dict(data_dict)
            data_dict_even = convert_to_dict(data_dict_even)

            # 写入
            data_dict_even = {"schedule_even": data_dict_even}
            schedule_center.save_data(data_dict_even, config_center.schedule_name)
            data_dict = {"schedule": data_dict}
            schedule_center.save_data(data_dict, config_center.schedule_name)
            Flyout.create(
                icon=InfoBarIcon.SUCCESS,
                title='保存成功',
                content=f"已保存至 ./config/schedule/{config_center.schedule_name}",
                target=self.findChild(PrimaryPushButton, 'save_schedule'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )
            self.sp_fill_grid_row()
        except Exception as e:
            logger.error(f'保存课表时发生错误: {e}')

    def te_upload_item(self):  # 上传时间线到列表组件
        te_timeline_list = self.findChild(ListWidget, 'timeline_list')
        te_select_timeline = self.findChild(ComboBox, 'select_timeline')
        global timeline_dict
        cache_list = []
        for i in range(te_timeline_list.count()):
            item_text = te_timeline_list.item(i).text()
            cache_list.append(item_text)
        if te_select_timeline.currentIndex() == 0:
            timeline_dict['default'] = cache_list
        else:
            timeline_dict[str(te_select_timeline.currentIndex() - 1)] = cache_list

    # 保存时间线
    def te_save_item(self):
        te_part_list = self.findChild(ListWidget, 'part_list')
        data_dict = {"part": {}, "part_name": {}, "timeline": {'default': {}, **{str(w): {} for w in range(7)}}}
        data_timeline_dict = deepcopy(timeline_dict)
        # 逐条把列表里的信息整理保存
        for i in range(te_part_list.count()):
            item_text = te_part_list.item(i).text()
            item_info = item_text.split(' - ')
            time_tostring = item_info[1].split(':')
            if len(item_info) == 3:
                part_type = ['part', 'break'][item_info[2] == '休息段']
            else:
                part_type = 'part'
            data_dict['part'][str(i)] = [int(time_tostring[0]), int(time_tostring[1]), part_type]
            data_dict['part_name'][str(i)] = item_info[0]

        try:
            for week, _ in data_timeline_dict.items():
                counter = []  # 初始化计数器
                for i in range(len(data_dict['part'])):
                    counter.append(0)
                counter_key = 0
                lesson_num = 0
                for i in range(len(data_timeline_dict[week])):
                    item_text = data_timeline_dict[week][i]
                    item_info = item_text.split(' - ')
                    item_name = ''
                    if item_info[0] == '课程':
                        item_name += 'a'
                        lesson_num += 1
                    if item_info[0] == '课间':
                        item_name += 'f'

                    for key, value in data_dict['part_name'].items():  # 节点计数
                        if value == item_info[2]:
                            item_name += str(key)  # +节点序数
                            counter_key = int(key)  # 记录节点序数
                            break

                    if item_name.startswith('a'):
                        counter[counter_key] += 1

                    item_name += str(lesson_num - sum(counter[:counter_key]))  # 课程序数
                    item_time = item_info[1][0:len(item_info[1]) - 2]
                    data_dict['timeline'][str(week)][item_name] = item_time

            schedule_center.save_data(data_dict, config_center.schedule_name)
            self.te_detect_item()
            se_load_item()
            self.se_upload_list()
            self.se_upload_item()
            self.te_upload_item()
            self.sp_fill_grid_row()
            Flyout.create(
                icon=InfoBarIcon.SUCCESS,
                title='保存成功',
                content=f"已保存至 ./config/schedule/{config_center.schedule_name}",
                target=self.findChild(PrimaryPushButton, 'save'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )
        except Exception as e:
            logger.error(f'保存时间线时发生错误: {e}')
            Flyout.create(
                icon=InfoBarIcon.ERROR,
                title='保存失败!',
                content=f"{e}\n保存失败，请将 ./log/ 中的日志提交给开发者以反馈问题。",
                target=self.findChild(PrimaryPushButton, 'save'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )

    def te_sync_time(self):
        te_class_activity_combo = self.findChild(ComboBox, 'class_activity')
        spin_time = self.findChild(SpinBox, 'spin_time')
        if te_class_activity_combo.currentIndex() == 0:
            spin_time.setValue(40)
        if te_class_activity_combo.currentIndex() == 1:
            spin_time.setValue(10)

    def te_detect_item(self):
        timeline_list = self.findChild(ListWidget, 'timeline_list')
        part_list = self.findChild(ListWidget, 'part_list')
        tips = self.findChild(CaptionLabel, 'tips_2')
        tips_part = self.findChild(CaptionLabel, 'tips_1')
        if part_list.count() > 0:
            tips_part.hide()
        else:
            tips_part.show()
        if timeline_list.count() > 0:
            tips.hide()
        else:
            tips.show()

    def te_add_item(self):
        te_timeline_list = self.findChild(ListWidget, 'timeline_list')
        class_activity = self.findChild(ComboBox, 'class_activity')
        spin_time = self.findChild(SpinBox, 'spin_time')
        time_period = self.findChild(ComboBox, 'time_period')
        if time_period.currentText() == "":  # 时间段不能为空 修复 #184
            Flyout.create(
                icon=InfoBarIcon.WARNING,
                title='无法添加时间线 o(TヘTo)',
                content='在添加时间线前，先任意添加一个节点',
                target=self.findChild(ToolButton, 'add_button'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )
            return  # 时间段不能为空
        te_timeline_list.addItem(
            f'{class_activity.currentText()} - {spin_time.value()}分钟 - {time_period.currentText()}'
        )
        self.te_detect_item()

    def te_add_part(self):
        te_part_list = self.findChild(ListWidget, 'part_list')
        te_name_part = self.findChild(EditableComboBox, 'name_part_combo')
        te_part_time = self.findChild(TimeEdit, 'part_time')
        te_part_type = self.findChild(ComboBox, 'part_type')
        if te_part_list.count() < 10:
            te_part_list.addItem(
                f'{te_name_part.currentText()} - {te_part_time.time().toString("h:mm")} - {te_part_type.currentText()}'
            )
        else:  # 最多只能添加9个节点
            Flyout.create(
                icon=InfoBarIcon.WARNING,
                title='没办法继续添加了 o(TヘTo)',
                content='Class Widgets 最多只能添加10个“节点”！',
                target=self.findChild(ToolButton, 'add_part_button'),
                parent=self,
                isClosable=True,
                aniType=FlyoutAnimationType.PULL_UP
            )
        self.te_detect_item()
        self.te_update_parts_name()

    def te_delete_part(self):
        alert = MessageBox("您确定要删除这个时段吗？", "删除该节点后，将一并删除该节点下所有课程安排，且无法恢复。", self)
        alert.yesButton.setText('删除')
        alert.yesButton.setStyleSheet("""
        PushButton{
            border-radius: 5px;
            padding: 5px 12px 6px 12px;
            outline: none;
        }
        PrimaryPushButton{
            color: white;
            background-color: #FF6167;
            border: 1px solid #FF8585;
            border-bottom: 1px solid #943333;
        }
        PrimaryPushButton:hover{
            background-color: #FF7E83;
            border: 1px solid #FF8084;
            border-bottom: 1px solid #B13939;
        }
        PrimaryPushButton:pressed{
            color: rgba(255, 255, 255, 0.63);
            background-color: #DB5359;
            border: 1px solid #DB5359;
        }
    """)
        alert.cancelButton.setText('取消')
        if alert.exec():
            global timeline_dict, schedule_dict
            te_part_list = self.findChild(ListWidget, 'part_list')
            selected_items = te_part_list.selectedItems()
            if not selected_items:
                return

            deleted_part_name = selected_items[0].text().split(' - ')[0]
            for item in selected_items:
                te_part_list.takeItem(te_part_list.row(item))

            # 修复了删除时段没能同步删除时间线的Bug #123
            for day in timeline_dict:  # 删除时间线
                count = 0
                break_count = 0
                delete_schedule_list = []
                delete_schedule_even_list = []
                delete_part_list = []
                for i in range(len(timeline_dict[day])):
                    act = timeline_dict[day][i]
                    count += 1
                    item_info = act.split(' - ')

                    if item_info[0] == '课间':
                        break_count += 1

                    if item_info[2] == deleted_part_name:
                        delete_part_list.append(act)
                        if item_info[0] != '课间':
                            if day != 'default':
                                delete_schedule_list.append(schedule_dict[day][count - break_count - 1])
                                delete_schedule_even_list.append(schedule_even_dict[day][count - break_count - 1])
                            else:
                                for j in range(7):
                                    try:
                                        for item in schedule_dict[str(j)]:
                                            if item.split('-')[1] == deleted_part_name:
                                                delete_schedule_list.append(
                                                    schedule_dict[str(j)][count - break_count - 1])
                                        for item in schedule_even_dict[str(j)]:
                                            if item.split('-')[1] == deleted_part_name:
                                                delete_schedule_even_list.append(
                                                    schedule_dict[str(j)][count - break_count - 1])
                                    except Exception as e:
                                        logger.warning(f'删除时段时发生错误：{e}')

                for item in delete_part_list:  # 删除时间线
                    timeline_dict[day].remove(item)
                if day != 'default':  # 删除课表
                    for item in delete_schedule_list:
                        schedule_dict[day].remove(item)

            for day in range(7):  # 删除默认课程表
                delete_schedule_list = []
                delete_schedule_even_list = []
                for item in schedule_dict[str(day)]:  # 单周
                    if item.split('-')[1] == deleted_part_name:
                        delete_schedule_list.append(item)
                for item in delete_schedule_list:
                    schedule_dict[str(day)].remove(item)

                for item in schedule_even_dict[str(day)]:  # 双周
                    if item.split('-')[1] == deleted_part_name:
                        delete_schedule_even_list.append(item)
                for item in delete_schedule_even_list:
                    schedule_even_dict[str(day)].remove(item)

            self.te_upload_list()
            self.se_upload_list()
            self.te_update_parts_name()
        else:
            return

    def te_update_parts_name(self):
        rl = []
        te_time_combo = self.findChild(ComboBox, 'time_period')  # 时段
        te_time_combo.clear()
        part_list = self.findChild(ListWidget, 'part_list')
        for i in range(part_list.count()):
            info = part_list.item(i).text().split(' - ')
            rl.append(info[0])
        te_time_combo.addItems(rl)

    def te_edit_item(self):
        te_timeline_list = self.findChild(ListWidget, 'timeline_list')
        class_activity = self.findChild(ComboBox, 'class_activity')
        spin_time = self.findChild(SpinBox, 'spin_time')
        time_period = self.findChild(ComboBox, 'time_period')
        selected_items = te_timeline_list.selectedItems()

        if selected_items:
            selected_item = selected_items[0]  # 取第一个选中的项目
            selected_item.setText(
                f'{class_activity.currentText()} - {spin_time.value()}分钟 - {time_period.currentText()}'
            )

    def se_edit_item(self):
        se_schedule_list = self.findChild(ListWidget, 'schedule_list')
        se_class_combo = self.findChild(ComboBox, 'class_combo')
        se_custom_class_text = self.findChild(LineEdit, 'custom_class')
        selected_items = se_schedule_list.selectedItems()

        if selected_items:
            selected_item = selected_items[0]
            name_list = selected_item.text().split('-')
            if se_class_combo.currentIndex() != 0:
                selected_item.setText(
                    f'{se_class_combo.currentText()}-{name_list[1]}'
                )
            else:
                if se_custom_class_text.text() != '':
                    selected_item.setText(
                        f'{se_custom_class_text.text()}-{name_list[1]}'
                    )
                    se_class_combo.addItem(se_custom_class_text.text())

    def se_quick_set_schedule(self):  # 快速设置课表
        se_schedule_list = self.findChild(ListWidget, 'schedule_list')
        quick_set_schedule = self.findChild(ListWidget, 'subject_list')
        selected_items = se_schedule_list.selectedItems()
        selected_subject = quick_set_schedule.currentItem().text()
        if se_schedule_list.count() > 0:
            if not selected_items:
                se_schedule_list.setCurrentRow(0)

            selected_row = se_schedule_list.currentRow()
            selected_item = se_schedule_list.item(selected_row)
            name_list = selected_item.text().split('-')
            selected_item.setText(
                f'{selected_subject}-{name_list[1]}'
            )

            if se_schedule_list.count() > selected_row + 1:  # 选择下一行
                se_schedule_list.setCurrentRow(selected_row + 1)

    def se_quick_select_week(self):  # 快速选择周
        se_week_combo = self.findChild(ComboBox, 'week_combo')
        if se_week_combo.currentIndex() != 6:
            se_week_combo.setCurrentIndex(se_week_combo.currentIndex() + 1)

    def te_delete_item(self):
        te_timeline_list = self.findChild(ListWidget, 'timeline_list')
        selected_items = te_timeline_list.selectedItems()
        for item in selected_items:
            te_timeline_list.takeItem(te_timeline_list.row(item))
        self.te_detect_item()

    def se_delete_item(self):
        se_schedule_list = self.findChild(ListWidget, 'schedule_list')
        selected_items = se_schedule_list.selectedItems()
        if selected_items:
            selected_item = selected_items[0]
            name_list = selected_item.text().split('-')
            selected_item.setText(
                f'未添加-{name_list[1]}'
            )

    def cd_edit_item(self):
        cd_countdown_list = self.findChild(ListWidget, 'countdown_list')
        cd_text_cd = self.findChild(LineEdit, 'text_cd')
        cd_set_countdown_date = self.findChild(CalendarPicker, 'set_countdown_date')
        selected_items = cd_countdown_list.selectedItems()
        if selected_items:
            selected_item = selected_items[0]
            selected_item.setText(
                f"{cd_set_countdown_date.date.toString('yyyy-M-d')} - {cd_text_cd.text()}"
            )

    def cd_delete_item(self):
        cd_countdown_list = self.findChild(ListWidget, 'countdown_list')
        selected_items = cd_countdown_list.selectedItems()
        if selected_items:
            item = selected_items[0]
            cd_countdown_list.takeItem(cd_countdown_list.row(item))

    def cd_add_item(self):
        cd_countdown_list = self.findChild(ListWidget, 'countdown_list')
        cd_text_cd = self.findChild(LineEdit, 'text_cd')
        cd_set_countdown_date = self.findChild(CalendarPicker, 'set_countdown_date')
        cd_countdown_list.addItem(
            f"{cd_set_countdown_date.date.toString('yyyy-M-d')} - {cd_text_cd.text()}"
        )

    def cd_save_item(self):
        cd_countdown_list = self.findChild(ListWidget, 'countdown_list')
        countdown_date = []
        cd_text_custom = []

        for i in range(cd_countdown_list.count()):
            item = cd_countdown_list.item(i)
            text = item.text().split(' - ')
            countdown_date.append(text[0])
            cd_text_custom.append(text[1])

        Flyout.create(
            icon=InfoBarIcon.SUCCESS,
            title='保存成功',
            content=f"已保存至 ./config.ini",
            target=self.findChild(PrimaryPushButton, 'save_countdown'),
            parent=self,
            isClosable=True,
            aniType=FlyoutAnimationType.PULL_UP
        )

        config_center.write_conf('Date', 'countdown_date', ','.join(countdown_date))
        config_center.write_conf('Date', 'cd_text_custom', ','.join(cd_text_custom))

    def setup_countdown_edit(self):
        cd_load_item()
        logger.debug(f"{countdown_dict}")
        cd_set_button = self.findChild(ToolButton, 'set_button_cd')
        cd_set_button.setIcon(fIcon.EDIT)
        cd_set_button.setToolTip('编辑倒计日')
        cd_set_button.installEventFilter(ToolTipFilter(cd_set_button, showDelay=300, position=ToolTipPosition.TOP))
        cd_set_button.clicked.connect(self.cd_edit_item)

        cd_clear_button = self.findChild(ToolButton, 'clear_button_cd')
        cd_clear_button.setIcon(fIcon.DELETE)
        cd_clear_button.setToolTip('删除倒计日')
        cd_clear_button.installEventFilter(ToolTipFilter(cd_clear_button, showDelay=300, position=ToolTipPosition.TOP))
        cd_clear_button.clicked.connect(self.cd_delete_item)

        cd_add_button = self.findChild(ToolButton, 'add_button_cd')
        cd_add_button.setIcon(fIcon.ADD)
        cd_add_button.setToolTip('添加倒计日')
        cd_add_button.installEventFilter(ToolTipFilter(cd_add_button, showDelay=300, position=ToolTipPosition.TOP))
        cd_add_button.clicked.connect(self.cd_add_item)

        cd_schedule_list = self.findChild(ListWidget, 'countdown_list')
        cd_schedule_list.addItems([f"{date} - {countdown_dict[date]}" for date in countdown_dict])

        cd_save_button = self.findChild(PrimaryPushButton, 'save_countdown')
        cd_save_button.clicked.connect(self.cd_save_item)

        cd_mode = self.findChild(ComboBox, 'countdown_mode')
        cd_mode.addItems(list_.countdown_modes)
        cd_mode.setCurrentIndex(int(config_center.read_conf('Date', 'countdown_custom_mode')))
        cd_mode.currentIndexChanged.connect(
            lambda: config_center.write_conf('Date', 'countdown_custom_mode', str(cd_mode.currentIndex())))

        cd_upd_cd = self.findChild(SpinBox, 'countdown_upd_cd')
        cd_upd_cd.setValue(int(config_center.read_conf('Date', 'countdown_upd_cd')))
        cd_upd_cd.valueChanged.connect(
            lambda: config_center.write_conf('Date', 'countdown_upd_cd', str(cd_upd_cd.value())))

    def m_start_time_changed(self):
        global morning_st
        te_m_start_time = self.findChild(TimeEdit, 'morningStartTime')
        unformatted_time = te_m_start_time.time()
        h = unformatted_time.hour()
        m = unformatted_time.minute()
        morning_st = (h, m)

    def a_start_time_changed(self):
        global afternoon_st
        te_m_start_time = self.findChild(TimeEdit, 'afternoonStartTime')
        unformatted_time = te_m_start_time.time()
        h = unformatted_time.hour()
        m = unformatted_time.minute()
        afternoon_st = (h, m)

    def init_nav(self):
        self.addSubInterface(self.spInterface, fIcon.HOME, '课表预览')
        self.addSubInterface(self.teInterface, fIcon.DATE_TIME, '时间线编辑')
        self.addSubInterface(self.seInterface, fIcon.EDUCATION, '课程表编辑')
        self.addSubInterface(self.cdInterface, fIcon.CALENDAR, '倒计日编辑')
        self.addSubInterface(self.cfInterface, fIcon.FOLDER, '配置文件')
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.hdInterface, fIcon.QUESTION, '帮助')
        self.addSubInterface(self.plInterface, fIcon.APPLICATION, '插件', NavigationItemPosition.BOTTOM)
        self.navigationInterface.addSeparator(NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.ctInterface, fIcon.BRUSH, '自定义', NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.sdInterface, fIcon.RINGER, '提醒', NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.adInterface, fIcon.SETTING, '高级选项', NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.ifInterface, fIcon.INFO, '关于本产品', NavigationItemPosition.BOTTOM)
        try:
            self.navigationInterface.currentItemChanged.connect(self._on_page_changed)
        except AttributeError:
            try:
                self.stackedWidget.currentChanged.connect(self._on_page_changed)
            except AttributeError:
                pass
    def do_upgrade(self):# 手动更新
        system=platform.system()
        if system == "Windows":
            system = "x64" if platform.architecture()[0]=="64bit" else "x86"
        if system == 'Darwin':
            system = 'macOS'
        channel = int(config_center.read_conf("Version", "version_channel"))
        if channel == 0:
            release_info = self.version_info["releases"]
        else:
            release_info = self.version_info["releases_beta"]
        if not system in release_info:  # 没有更新包，退出
            logger.info("无可用更新包")
            self.do_upgrade_button.setEnabled(False)
            self.do_upgrade_button.setText("没有可用的自动更新包，请手动更新")
            InfoBar.error(
                title='更新失败',
                content=f"无可用更新包",
                parent=self,
                isClosable=True,
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP,
                duration=2000
            )
        else:
            self.do_upgrade_button.setEnabled(False)
            self.do_upgrade_button.setText("正在更新")
            release_to_upgrade = release_info[system]
            logger.info(f"开始更新，更新频道：{channel}，系统：{system}")
            download_url = release_to_upgrade["url"]
            logger.debug(f"下载更新包：{download_url}，系统：{system}")
            params = []
            params.append(os.getcwd())
            params.append(';'.join(release_to_upgrade["files_to_keep"]))
            params.append( #运行参数
                os.path.join(
                    os.getcwd(),
                    os.path.split(release_to_upgrade["executable"])[1]
                )
            )
            logger.debug(f"传入参数：{params}")
            updthread = GetUPDPack(download_url,os.path.join(os.getcwd(),release_to_upgrade["executable"],),*params)
            updwindow = updater.UpgradeProgressWindow(updthread,self)
            updwindow.show()
    def init_window(self):
        self.stackedWidget.setCurrentIndex(0)  # 设置初始页面
        self.load_all_item()
        self.check_and_disable_schedule_edit()
        self.check_and_disable_timeline_edit()
        self.setMinimumWidth(700)
        self.setMinimumHeight(400)
        self.navigationInterface.setExpandWidth(250)
        self.navigationInterface.setCollapsible(False)
        self.setMicaEffectEnabled(True)

        # 修复设置窗口在各个屏幕分辨率DPI下的窗口大小
        screen_geometry = QApplication.primaryScreen().geometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        width = int(screen_width * 0.6)
        height = int(screen_height * 0.7)

        self.move(int(screen_width / 2 - width / 2), 150)
        self.resize(width, height)

        self.setWindowTitle('Class Widgets - 设置')
        self.setWindowIcon(QIcon(f'{base_directory}/img/logo/favicon-settings.ico'))

        self.init_font()  # 设置字体

    def _on_page_changed(self):
        """清理NTP flyout"""
        try:
            if hasattr(self, '_current_ntp_flyout') and self._current_ntp_flyout:
                self._current_ntp_flyout.close()
                self._current_ntp_flyout = None
        except Exception as e:
            logger.error(f"页面切换时清理NTP flyout失败: {e}")
    
    def closeEvent(self, event):
        try:
            if hasattr(self, '_current_ntp_flyout') and self._current_ntp_flyout:
                self._current_ntp_flyout.close()
                self._current_ntp_flyout = None
        except Exception as e:
            logger.error(f"关闭窗口时清理NTP flyout失败: {e}")
        try:
            self._remove_ntp_auto_sync_callback()
        except Exception as e:
            logger.error(f"清理NTP自动同步回调失败: {e}")
        
        self.closed.emit()
        event.accept()

class NTPSyncWorker(QObject):
    """NTP异步同步工作线程"""
    sync_finished = pyqtSignal(bool)
    def __init__(self, time_manager):
        super().__init__()
        self.time_manager = time_manager
    
    def sync_ntp(self):
        """执行NTP同步"""
        try:
            success = self.time_manager.sync_with_ntp()
            self.sync_finished.emit(success)
        except Exception as e:
            logger.error(f"异步NTP同步失败: {e}")
            self.sync_finished.emit(False)

def sp_get_class_num():  # 获取当前周课程数（未完成）
    highest_count = 0
    for timeline_ in get_timeline().keys():
        timeline = get_timeline()[timeline_]
        count = 0
        for item_name, item_time in timeline.items():
            if item_name.startswith('a'):
                count += 1
        if count > highest_count:
            highest_count = count
    return highest_count


if __name__ == '__main__':
    app = QApplication(sys.argv)
    settings = SettingsMenu()
    settings.show()
    # settings.setMicaEffectEnabled(True)
    sys.exit(app.exec())
