import sys
import os
import time
import pathlib
from typing import Optional, Dict, Any

import pygame
import pygame.mixer
from PyQt5.QtCore import QThread, pyqtSignal
from loguru import logger

import conf
from file import config_center

sound_cache: Dict[str, Any] = {}


class PlayAudio(QThread):
    play_back_signal = pyqtSignal(bool)

    def __init__(self, file_path: str, tts_delete_after: bool = False):
        super().__init__()
        self.file_path = file_path
        self.tts_delete_after = tts_delete_after

    def run(self) -> None:
        play_audio(self.file_path, self.tts_delete_after)
        self.play_back_signal.emit(True)


def play_audio(file_path: str, tts_delete_after: bool = False, volume: Optional[float] = None) -> bool:
    sound = None
    channel = None
    relative_path = os.path.relpath(file_path, conf.base_directory)
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"音频文件不存在: {relative_path}")

        if not pygame.mixer.get_init():
            try:
                pygame.mixer.quit()
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            except pygame.error:
                logger.warning("标准 Mixer 初始化失败，尝试兼容模式...")
                try:
                    pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=1024)
                    logger.info("使用兼容设置成功初始化 Mixer")
                except pygame.error as e_fallback:
                    logger.error(f"Pygame mixer 初始化失败: {e_fallback}")
                    return False

        # 检查文件是否可读
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            start_time = time.time()
            while time.time() - start_time < 4:
                if os.path.getsize(file_path) > 0:
                    break
                time.sleep(0.1)
            else:
                logger.error(f"音频文件写入超时或为空: {relative_path}")
                if tts_delete_after:
                    from generate_speech import on_audio_played
                    on_audio_played(file_path)
                return False
        file_size = os.path.getsize(file_path)
        if file_size < 10:
            logger.warning(f"音频文件可能无效或不完整，大小仅为 {file_size} 字节: {relative_path}")
            if tts_delete_after:
                from generate_speech import on_audio_played
                on_audio_played(file_path)
            return False

        try:
            is_in_cache_dir = 'cache' in pathlib.Path(file_path).parts
            if not is_in_cache_dir and file_path in sound_cache:
                sound = sound_cache[file_path]
                logger.debug(f'调用缓存音频: {relative_path}')
            else:
                sound = pygame.mixer.Sound(file_path)
                if not is_in_cache_dir:
                    sound_cache[file_path] = sound
        except pygame.error as e_load:
            logger.error(f"加载音频文件失败: {relative_path} | 错误: {e_load}")
            if tts_delete_after:
                from generate_speech import on_audio_played
                on_audio_played(file_path)
            return False

        if volume is not None:
            final_volume = max(0.0, min(1.0, volume))  # 限制在 0.0-1.0 范围内
        else:
            final_volume = int(config_center.read_conf('Audio', 'volume')) / 100
        sound.set_volume(final_volume)
        channel = sound.play()
        if channel:
            channel.set_volume(final_volume)
            while channel.get_busy():
                pygame.time.wait(100)
        else:
            logger.error(f"无法获取播放通道: {relative_path}")
            if tts_delete_after:
                from generate_speech import on_audio_played
                on_audio_played(file_path)
            return False

        logger.debug(f'成功播放音频: {relative_path}')
        if tts_delete_after:
            from generate_speech import on_audio_played
            on_audio_played(file_path)
        return True

    except FileNotFoundError as e:
        logger.error(f'音频文件未找到 | 路径: {relative_path} | 错误: {str(e)}')
        return False
    except IOError as e:
        logger.error(f'音频文件读取错误或超时 | 路径: {relative_path} | 错误: {str(e)}')
        return False
    except pygame.error as e:
        logger.error(f'Pygame 播放错误 | 路径: {relative_path} | 错误: {str(e)}')
        return False
    except Exception as e:
        logger.error(f'未知播放失败 | 路径: {relative_path} | 错误: {str(e)}')
        return False
    finally:
        if channel and channel.get_busy():
            channel.stop()
        if sound:
            sound.stop()

def is_playing() -> bool:
    """检查是否有音频正在播放"""
    return pygame.mixer.get_busy()

def stop_audio():
    """停止所有正在播放的音频"""
    pygame.mixer.stop()