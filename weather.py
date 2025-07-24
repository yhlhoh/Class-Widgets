"""
weather.py

天气数据相关接口封装
"""

import json
import sqlite3
import datetime
import time
import requests
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple, Type, Union
from PyQt5.QtCore import QThread, pyqtSignal, QEventLoop
from loguru import logger
from functools import wraps

from conf import base_directory  # type: ignore[attr-defined]
from file import config_center

def cache_result(expire_seconds: int = 300):
    """缓存装饰器 """
    # 她还是忘了不了她的缓存
    def decorator(func):
        cache: Dict[str, Tuple[Any, float]] = {}

        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = str(args) + str(sorted(kwargs.items()))
            current_time = time.time()
            if cache_key in cache:
                result, timestamp = cache[cache_key]
                if current_time - timestamp < expire_seconds:
                    #logger.debug(f"使用缓存结果: {func.__name__}")
                    return result
            result = func(*args, **kwargs)
            cache[cache_key] = (result, current_time)
            return result
        return wrapper
    return decorator


def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    """重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(f"{func.__name__} 第{attempt + 1}次尝试失败: {e},{delay}秒后重试")
                        time.sleep(delay)
                    else:
                        logger.error(f"{func.__name__} 所有重试均失败: {e}")
            if last_exception is None:
                raise RuntimeError(f"{func.__name__} 在 {max_retries} 次重试后出现未知问题")
            raise last_exception
        return wrapper
    return decorator

class WeatherapiProvider(ABC):
    """天气api数据基类"""

    def __init__(self, api_name: str, config: Dict[str, Any]):
        self.api_name = api_name
        self.config = config
        self.base_url = config.get('url', '')
        self.parameters = config.get('parameters', {})

    @abstractmethod
    def fetch_current_weather(self, location_key: str, api_key: str) -> Dict[str, Any]:
        """获取当前天气数据"""
        pass

    @abstractmethod
    def fetch_weather_alerts(self, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """获取天气预警数据"""
        pass

    @abstractmethod
    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据"""
        pass

    @abstractmethod
    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码"""
        pass

    @abstractmethod
    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气描述"""
        pass

    def supports_alerts(self) -> bool:
        """检查是否支持天气预警"""
        return 'alerts' in self.config and bool(self.config['alerts'])

    def get_database_name(self) -> str:
        """获取数据库文件名"""
        return self.config.get('database', 'xiaomi_weather.db')


@dataclass
class WeatherExtractionContext:
    """天气数据提取"""
    current_params: Dict[str, Any]
    key: str
    weather_data: Dict[str, Any]
    current_api: str = ''
    parameter_path: str = ''


class WeatherDataCache:
    """天气数据缓存管理器"""

    def __init__(self, default_expire: int = 300):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self.default_expire = default_expire

    def get(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self.default_expire:
                return data
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: Any, expire: Optional[int] = None) -> None:
        """设置缓存数据"""
        self._cache[key] = (value, time.time())

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()


class WeatherManager:
    """天气管理"""

    def __init__(self):
        self.api_config = self._load_api_config()
        self.cache = WeatherDataCache()
        self.providers = self._initialize_providers()
        self.current_weather_data = None
        self.current_alert_data = None

    def _load_api_config(self) -> Dict[str, Any]:
        """加载天气api"""
        try:
            api_config_path = os.path.join(base_directory, 'config', 'data', 'weather_api.json')
            with open(api_config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f'加载天气api配置失败: {e}')
            return {}

    def _initialize_providers(self) -> Dict[str, WeatherapiProvider]:
        """初始化天气api数据"""
        providers = {}
        for api_name in self.api_config.get('weather_api_list', []):
            try:
                provider = self._create_single_provider(api_name)
                if provider:
                    providers[api_name] = provider
            except Exception as e:
                logger.error(f'初始化天气提供者 {api_name} 失败: {e}')
        return providers

    def _create_single_provider(self, api_name: str) -> Optional[WeatherapiProvider]:
        """创建提供者"""
        api_params = self.api_config.get('weather_api_parameters', {}).get(api_name, {})
        weather_api_url = self.api_config.get('weather_api', {}).get(api_name, '')

        config = self._build_provider_config(api_params, weather_api_url)
        provider_class = self._get_provider_class(api_name)

        return provider_class(api_name, config)

    def _build_provider_config(self, api_params: Dict[str, Any], weather_api_url: str) -> Dict[str, Any]:
        """构建配置"""
        return {
            'url': weather_api_url,
            'parameters': api_params,
            'alerts': api_params.get('alerts', {}),
            'database': api_params.get('database', 'xiaomi_weather.db'),
            'return_desc': api_params.get('return_desc', False)
        }

    def _get_provider_class(self, api_name: str) -> Type[WeatherapiProvider]:
        """获得提供类"""
        if api_name == 'xiaomi_weather':
            provider_class_name = 'XiaomiWeatherProvider'
        elif api_name == 'qweather':
            provider_class_name = 'QWeatherProvider'
        else:
            provider_class_name = f'{api_name.capitalize()}WeatherProvider'
        if provider_class_name in globals():
            return globals()[provider_class_name]  # type: ignore[no-any-return]
        # 通用(你认为永远是你认为的)
        return GenericWeatherProvider

    def get_current_api(self) -> str:
        """获取当前选择的天气api"""
        result = config_center.read_conf('Weather', 'api')
        return str(result) if result is not None else ''

    def get_current_provider(self) -> Optional[WeatherapiProvider]:
        """获取当前天气api提供者"""
        current_api = self.get_current_api()
        return self.providers.get(current_api)

    def get_api_list(self) -> List[str]:
        """获取可用的天气api列表"""
        result = self.api_config.get('weather_api_list', [])
        return result if isinstance(result, list) else []

    def get_api_list_zh(self) -> List[str]:
        """获取天气api中文名称列表"""
        result = self.api_config.get('weather_api_list_zhCN', [])
        return result if isinstance(result, list) else []

    def on_api_changed(self, new_api: str):
        """清理缓存"""
        self.cache.clear()
        self.current_weather_data = None
        self.current_alert_data = None

    def clear_processor_cache(self, processor):
        """清理数据处理器缓存"""
        if hasattr(processor, 'clear_cache'):
            processor.clear_cache()

    @retry_on_failure(max_retries=3, delay=1.0)
    @cache_result(expire_seconds=300)
    def fetch_weather_data(self) -> Dict[str, Any]:
        """获取天气数据"""
        provider = self.get_current_provider()
        if not provider:
            logger.error(f'未找到天气提供源: {self.get_current_api()}')
            return self._get_fallback_data()

        try:
            validation_result = self._validate_weather_params()
            if validation_result:
                return validation_result
            location_key = self._get_location_key()
            api_key = config_center.read_conf('Weather', 'api_key')
            weather_data = provider.fetch_current_weather(location_key, api_key)
            alert_data = self._fetch_alert_data_safely(provider, location_key, api_key)
            result = self._build_weather_result(weather_data, alert_data)
            self.current_weather_data = result
            return result
        except Exception as e:
            logger.error(f'获取天气数据失败: {e}')
            return self._get_fallback_data(error_code='NETWORK_ERROR')

    def _validate_weather_params(self) -> Optional[Dict[str, Any]]:
        """验证天气参数"""
        location_key = self._get_location_key()
        api_key = config_center.read_conf('Weather', 'api_key')
        current_api = config_center.read_conf('Weather', 'api')
        if not location_key:
            logger.error('位置信息未配置或无效')
            return self._get_fallback_data(error_code='LOCATION')
        if self._is_api_key_required(current_api) and not api_key:
            logger.error(f'{current_api} api密钥缺失')
            return self._get_fallback_data(error_code='API_KEY')

        return None

    def _fetch_alert_data_safely(self, provider: WeatherapiProvider, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """安全获取预警数据"""
        if not provider.supports_alerts():
            return None
        try:
            return provider.fetch_weather_alerts(location_key, api_key)
        except Exception as e:
            logger.warning(f'获取天气预警失败: {e}')
            return None

    def _build_weather_result(self, weather_data: Dict[str, Any], alert_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """构建结果"""
        return {
            'now': weather_data,
            'alert': alert_data or {}
        }

    def _get_location_key(self) -> str:
        """获取位置值"""
        location_key = config_center.read_conf('Weather', 'city')
        if location_key == '0' or not location_key:
            location_key = self._get_auto_location()
        return location_key

    def _get_auto_location(self) -> str:
        """自动获取位置"""
        try:
            from network_thread import getCity
            city_thread = getCity()
            loop = QEventLoop()
            city_thread.finished.connect(loop.quit)
            city_thread.start()
            loop.exec_()  # 阻塞到完成
            location_key = config_center.read_conf('Weather', 'city')
            if location_key == '0' or not location_key:
                return '101010100'  # 默认北京
            return location_key
        except Exception as e:
            logger.error(f'自动获取位置失败: {e}')
            return '101010100'

    def _is_api_key_required(self, api_name: str) -> bool:
        """最神经病的一集"""
        return api_name in ['qweather', 'amap_weather', 'qq_weather']

    def _get_fallback_data(self, error_code: str = 'UNKNOWN_ERROR') -> Dict[str, Any]:
        """回退数据"""
        error_messages = {
            'LOCATION': {'value': '错误', 'unit': '位置信息缺失'},
            'API_KEY': {'value': '错误', 'unit': 'API密钥缺失'},
            'NETWORK_ERROR': {'value': '错误', 'unit': '网络错误'},
            'UNKNOWN_ERROR': {'value': '错误', 'unit': '未知错误'}
        }
        error_info = error_messages.get(error_code, error_messages['UNKNOWN_ERROR'])
        return {
            'error': {
                'info': error_info,
                'code': error_code
            },
            'now': {},
            'alert': {}
        }

    def get_unified_weather_data(self, data_type: str) -> Optional[str]:
        """获取数据(统一)"""
        if not self.current_weather_data:
            return None

        provider = self.get_current_provider()
        if not provider:
            return None
        try:
            if data_type == 'temperature':
                return provider.parse_temperature(self.current_weather_data)
            elif data_type == 'icon':
                return provider.parse_weather_icon(self.current_weather_data)
            elif data_type == 'description':
                return provider.parse_weather_description(self.current_weather_data)
            else:
                logger.warning(f'未知的数据类型: {data_type}')
                return None
        except Exception as e:
            logger.error(f'解析天气数据失败 ({data_type}): {e}')
            return None


class GenericWeatherProvider(WeatherapiProvider):
    """通用天气api获得"""

    @retry_on_failure(max_retries=2, delay=0.5)
    def fetch_current_weather(self, location_key: str, api_key: str) -> Dict[str, Any]:
        """获取当前天气数据"""
        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            from network_thread import proxies
            url = self.base_url.format(location_key=location_key, days=1, key=api_key)
            #logger.debug(f'{self.api_name} 请求URL: {url}')
            response = requests.get(url, proxies=proxies, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f'{self.api_name} 获取天气数据失败: {e}')
            raise

    def fetch_weather_alerts(self, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """获取天气预警数据"""
        if not self.supports_alerts():
            return None

        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            from network_thread import proxies
            alert_url = self.config['alerts'].get('url', '')
            if not alert_url:
                return None

            url = alert_url.format(location_key=location_key, key=api_key)
            # logger.debug(f'{self.api_name} 预警请求URL: {url.replace(api_key, "***" if api_key else "(空)")}')
            response = requests.get(url, proxies=proxies, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f'{self.api_name} 获取预警数据失败: {e}')
            return None

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据"""
        temp_path = self.parameters.get('temp', '')
        if not temp_path:
            logger.error(f"温度路径为空: {self.api_name}")
            return None
        # logger.debug(f"解析温度 - api: {self.api_name}, 路径: {temp_path}")
        value = self._extract_value_by_path(data, temp_path)
        # logger.debug(f"提取的温度值: {value}")
        return f"{value}°" if value is not None else None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码"""
        icon_path = self.parameters.get('icon', '')
        if not icon_path:
            logger.error(f"图标路径为空: {self.api_name}")
            return None
        value = self._extract_value_by_path(data, icon_path)
        # logger.debug(f"提取的图标值: {value}")
        # 神经天气服务商
        if self.config.get('return_desc', False) and value:
            pass

        return str(value) if value is not None else None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析描述"""
        desc_path = self.parameters.get('description', '')
        if desc_path:
            result = self._extract_value_by_path(data, desc_path)
            return str(result) if result is not None else None

        icon_code = self.parse_weather_icon(data)
        if icon_code:
            # 通过WeatherDataProcessor获得
            return None

        return None

    def _extract_value_by_path(self, data: Dict[str, Any], path: str) -> Optional[Union[str, int, float, Dict[str, Any], List[Any]]]:
        """提取数据值"""
        if not self._is_valid_extraction_input(data, path):
            return None

        try:
            value: Any = data
            for key in path.split('.'):
                value = self._extract_single_key(value, key)
                if value is None:
                    return None
            return value
        except Exception as e:
            logger.error(f'解析数据路径 {path} 失败: {e}')
            return None

    def _is_valid_extraction_input(self, data: Any, path: str) -> bool:
        """验证输入有效性"""
        return bool(path and data)

    def _extract_single_key(self, value: Any, key: str) -> Optional[Union[str, int, float, Dict[str, Any], List[Any]]]:
        """提取单键值"""
        if key == '0' and isinstance(value, list):
            return value[0] if len(value) > 0 else None
        elif isinstance(value, dict):
            return value.get(key)
        else:
            return None


class XiaomiWeatherProvider(GenericWeatherProvider):
    """小米天气api获得"""

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气温度"""
        try:
            # 结构: current.temperature.value
            current = data.get("current", {})
            temperature = current.get('temperature', {})
            temp_unit = temperature.get('unit')
            temp_value = temperature.get('value')

            if temp_value is not None:
                return f"{temp_value}{temp_unit}"
            else:
                logger.error(f"小米天气api温度数据为空")
                return None
        except Exception as e:
            logger.error(f"解析小米天气温度失败: {e}")
            return None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析图标代码"""
        try:
            current = data.get("current", {})
            code = current.get('weather')
            if code is None:
                logger.error("天气码为空")
                return None
            return str(code)
        except Exception as e:
            logger.error(f"解析天气图标失败: {e}")
            return None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析小米天气api描述"""
        try:
            weather_code = self.parse_weather_icon(data)
            if weather_code:
                return weather_code  # WeatherDataProcessor处理
            return None
        except Exception as e:
            logger.error(f"解析小米天气描述失败: {e}")
            return None

    def fetch_weather_alerts(self, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """获取小米天气预警"""
        try:
            weather_data = self.fetch_current_weather(location_key, api_key)
            if weather_data:
                alerts = self.parse_weather_alerts(weather_data)
                if alerts:
                    result = {'warning': alerts}
                    return result
            return None
        except Exception as e:
            return None

    def parse_weather_alerts(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析小米天气预警"""
        try:
            alerts_data = data.get('alerts', [])
            if not alerts_data:
                return []

            return self._process_xiaomi_alerts(alerts_data)
        except Exception as e:
            return []

    def _process_xiaomi_alerts(self, alerts_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """处理小米天气预警"""
        alerts = []
        for alert_item in alerts_data:
            if isinstance(alert_item, dict):
                alert = self._build_xiaomi_alert(alert_item)
                alerts.append(alert)
        return alerts

    def _build_xiaomi_alert(self, alert_item: Dict[str, Any]) -> Dict[str, Any]:
        """构建小米天气预警"""
        return {
            'id': alert_item.get('alertId', ''),
            'title': alert_item.get('title', ''),
            'level': alert_item.get('level', ''),
            'detail': alert_item.get('detail', ''),
            'start_time': alert_item.get('pubTime', ''),
            'end_time': alert_item.get('end_time', ''),
            'type': alert_item.get('type', ''),
            'description': alert_item.get('detail', '')
        }



class QWeatherProvider(GenericWeatherProvider):
    """和风天气api提供者"""

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据(和风天气)"""
        try:
            # 和风天气api结构: now.temp
            now = data.get('now', {})
            temp = now.get('temp')

            if temp is not None:
                return f"{temp}°"
            return None
        except Exception as e:
            logger.error(f"解析和风天气温度失败: {e}")
            return None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码(和风天气)"""
        try:
            # 和风天气api结构: now.icon
            now = data.get('now', {})
            icon_code = now.get('icon')

            if icon_code is not None:
                return str(icon_code)
            return None
        except Exception as e:
            logger.error(f"解析和风天气图标失败: {e}")
            return None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气描述(和风天气)"""
        try:
            # 和风天气api结构: now.text
            now = data.get('now', {})
            text = now.get('text')

            if text:
                return text
            icon_code = self.parse_weather_icon(data)
            return icon_code if icon_code else None
        except Exception as e:
            logger.error(f"解析和风天气描述失败: {e}")
            return None

    def fetch_weather_alerts(self, location_key: str, api_key: str) -> Optional[Dict[str, Any]]:
        """获取和风天气预警数据"""
        if not location_key:
            raise ValueError(f'{self.api_name}: location_key 参数不能为空')

        try:
            from network_thread import proxies
            # 和风天气预警API
            alert_url = f"https://devapi.qweather.com/v7/warning/now?location={location_key}&key={api_key}"
            # logger.debug(f'和风天气预警请求URL: {alert_url.replace(api_key, "***" if api_key else "(空)")}')

            response = requests.get(alert_url, proxies=proxies, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f'和风天气获取预警数据失败: {e}')
            return None

    def parse_weather_alerts(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析和风天气预警"""
        try:
            if not self._validate_qweather_response(data):
                return []

            warning_list = data.get('warning', [])
            if not warning_list:
                return []

            return self._process_qweather_warnings(warning_list)
        except Exception as e:
            logger.error(f"解析和风天气预警数据失败: {e}")
            return []

    def _validate_qweather_response(self, data: Dict[str, Any]) -> bool:
        """验证和风天气响应"""
        if data.get('code') != '200':
            logger.warning(f"和风天气预警API返回错误: {data.get('code')}")
            return False
        return True

    def _process_qweather_warnings(self, warning_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """处理和风天气预警"""
        alerts = []
        for warning in warning_list:
            try:
                alert = self._build_qweather_alert(warning)
                alerts.append(alert)
                logger.debug(f"解析预警: {alert['title']} - {alert['level']}")
            except Exception as e:
                logger.error(f"解析单个预警失败: {e}")
                continue

        logger.info(f"和风天气成功解析 {len(alerts)} 条预警信息")
        return alerts

    def _build_qweather_alert(self, warning: Dict[str, Any]) -> Dict[str, Any]:
        """构建和风天气预警"""
        return {
            'id': warning.get('id', ''),
            'title': warning.get('title', ''),
            'sender': warning.get('sender', ''),
            'pub_time': warning.get('pubTime', ''),
            'start_time': warning.get('startTime', ''),
            'end_time': warning.get('endTime', ''),
            'status': warning.get('status', ''),
            'level': warning.get('level', ''),
            'severity': warning.get('severity', ''),
            'severity_color': warning.get('severityColor', ''),
            'type': warning.get('type', ''),
            'type_name': warning.get('typeName', ''),
            'text': warning.get('text', ''),
            'urgency': warning.get('urgency', ''),
            'certainty': warning.get('certainty', ''),
            'related': warning.get('related', '')
        }

    def supports_alerts(self) -> bool:
        """和风天气支持预警功能"""
        return True


class AmapWeatherProvider(GenericWeatherProvider):
    """高德天气api提供者"""

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据(高德天气)"""
        try:
            # 高德天气api结构: lives[0].temperature
            lives = data.get('lives', [])
            if lives and len(lives) > 0:
                temp = lives[0].get('temperature')
                if temp is not None:
                    return f"{temp}°"
            return None
        except Exception as e:
            logger.error(f"解析高德天气温度失败: {e}")
            return None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码(高德天气)"""
        try:
            # 高德天气api结构: lives[0].weather
            lives = data.get('lives', [])
            if lives and len(lives) > 0:
                weather = lives[0].get('weather')
                if weather is not None:
                    return str(weather)
            return None
        except Exception as e:
            logger.error(f"解析高德天气图标失败: {e}")
            return None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气描述(高德天气)"""
        try:
            # 高德天气api结构: lives[0].weather
            lives = data.get('lives', [])
            if lives and len(lives) > 0:
                weather = lives[0].get('weather')
                if weather:
                    return weather

            return None
        except Exception as e:
            logger.error(f"解析高德天气描述失败: {e}")
            return None


class QQWeatherProvider(GenericWeatherProvider):
    """腾讯天气api提供者"""

    def parse_temperature(self, data: Dict[str, Any]) -> Optional[str]:
        """解析温度数据(腾讯天气)"""
        try:
            # 腾讯天气api结构: result.realtime[0].infos.temp
            realtime = data.get('result', {}).get('realtime', [])
            if realtime and len(realtime) > 0:
                temp = realtime[0].get('infos', {}).get('temp')
                if temp is not None:
                    return f"{temp}°"
            return None
        except Exception as e:
            logger.error(f"解析腾讯天气温度失败: {e}")
            return None

    def parse_weather_icon(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气图标代码(腾讯天气)"""
        try:
            # 腾讯天气api结构: result.realtime[0].infos.weather_code
            realtime = data.get('result', {}).get('realtime', [])
            if realtime and len(realtime) > 0:
                weather_code = realtime[0].get('infos', {}).get('weather_code')
                if weather_code is not None:
                    return str(weather_code)
            return None
        except Exception as e:
            logger.error(f"解析腾讯天气图标失败: {e}")
            return None

    def parse_weather_description(self, data: Dict[str, Any]) -> Optional[str]:
        """解析天气描述(腾讯天气)"""
        try:
            # 腾讯天气api结构: result.realtime[0].infos.weather
            realtime = data.get('result', {}).get('realtime', [])
            if realtime and len(realtime) > 0:
                weather = realtime[0].get('infos', {}).get('weather')
                if weather:
                    return weather

            return None
        except Exception as e:
            logger.error(f"解析腾讯天气描述失败: {e}")
            return None


class WeatherDatabase:
    """天气数据库管理类"""

    def __init__(self, weather_manager: WeatherManager):
        self.weather_manager = weather_manager
        self._update_db_path()

    def _update_db_path(self) -> str:
        """更新数据库路径"""
        current_api = self.weather_manager.get_current_api()
        api_params = self.weather_manager.api_config.get('weather_api_parameters', {})
        db_name = api_params.get(current_api, {}).get('database', 'xiaomi_weather.db')
        self.db_path = os.path.join(base_directory, 'config', 'data', db_name)
        return self.db_path

    def search_city_by_name(self, search_term: str) -> List[str]:
        """根据城市名称搜索城市"""
        self._update_db_path()
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM citys WHERE name LIKE ?', ('%' + search_term + '%',))
            cities_results = cursor.fetchall()
            conn.close()

            return [city[2] for city in cities_results]
        except Exception as e:
            logger.error(f'搜索城市失败: {e}')
            return []

    def search_code_by_name(self, city_name: str, district_name: str = '') -> str:
        """根据城市名称获取城市代码"""
        normalized_city, normalized_district = self._normalize_city_params(city_name, district_name)
        if not normalized_city:
            return '101010100'

        self._update_db_path()
        try:
            return self._search_city_in_database(normalized_city, normalized_district)
        except Exception as e:
            logger.error(f'搜索城市代码失败: {e}')
            return '101010100'

    def _normalize_city_params(self, city_name: str, district_name: str = '') -> Tuple[str, str]:
        """标准化参数"""
        if isinstance(city_name, (tuple, list)):
            city_name = str(city_name[0]) if city_name else ''
        if isinstance(district_name, (tuple, list)):
            district_name = str(district_name[0]) if district_name else ''
        if not city_name:
            return '', ''
        clean_city = city_name.replace('市', '')
        clean_district = district_name.replace('区', '') if district_name else ''

        return clean_city, clean_district

    def _search_city_in_database(self, clean_city: str, clean_district: str) -> str:
        """在数据库中搜索城市"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 先精确匹配
            exact_result = self._try_exact_match(cursor, clean_city, clean_district)
            if exact_result:
                return exact_result
            # 再模糊匹配
            fuzzy_result = self._try_fuzzy_match(cursor, clean_city)
            if fuzzy_result:
                return fuzzy_result
            logger.warning(f'未找到城市: {clean_city}，使用默认城市代码')
            return '101010100'
        finally:
            conn.close()

    def _try_exact_match(self, cursor, clean_city: str, clean_district: str) -> Optional[str]:
        """尝试精确匹配"""
        search_name = f"{clean_city}.{clean_district}" if clean_district else clean_city
        cursor.execute('SELECT * FROM citys WHERE name = ?', (search_name,))
        exact_results = cursor.fetchall()

        if exact_results:
            logger.debug(f'找到城市: {exact_results[0][2]}，代码: {exact_results[0][3]}')
            return str(exact_results[0][3])
        return None

    def _try_fuzzy_match(self, cursor, clean_city: str) -> Optional[str]:
        """尝试模糊匹配"""
        cursor.execute('SELECT * FROM citys WHERE name LIKE ?', ('%' + clean_city + '%',))
        fuzzy_results = cursor.fetchall()

        if fuzzy_results:
            logger.debug(f'模糊找到城市: {fuzzy_results[0][2]}，代码: {fuzzy_results[0][3]}')
            return str(fuzzy_results[0][3])
        return None

    def search_city_by_code(self, city_code: str) -> str:
        """根据城市代码获取城市名称"""
        self._update_db_path()
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM citys WHERE city_num LIKE ?', ('%' + city_code + '%',))
            cities_results = cursor.fetchall()
            conn.close()

            if cities_results:
                return cities_results[0][2]
            return '北京'  # 默认城市

        except Exception as e:
            logger.error(f'根据代码搜索城市失败: {e}')
            return '北京'


class WeatherDataProcessor:
    """统一天气数据处理"""

    def __init__(self, weather_manager: WeatherManager):
        self.weather_manager = weather_manager
        self._status_cache = {}

    def clear_cache(self):
        """清理所有缓存"""
        self._status_cache.clear()

    def clear_api_cache(self, api_name: str):
        """清理指定api的缓存"""
        if api_name in self._status_cache:
            del self._status_cache[api_name]

    def _load_weather_status(self, api_name: Optional[str] = None) -> Dict[str, Any]:
        """加载天气状态配置"""
        if not api_name:
            api_name = self.weather_manager.get_current_api()
        if api_name in self._status_cache:
            return self._status_cache[api_name]

        try:
            with open(os.path.join(base_directory, 'config', 'data', f'{api_name}_status.json'), 'r', encoding='utf-8') as f:
                status_data = json.load(f)
                self._status_cache[api_name] = status_data
                return status_data
        except Exception as e:
            logger.error(f'加载天气状态配置失败: {e}')
            return {'weatherinfo': []}

    def get_weather_by_code(self, code: str, api_name: Optional[str] = None) -> str:
        """根据天气代码获取天气描述"""
        weather_status = self._load_weather_status(api_name)
        for weather in weather_status.get('weatherinfo', []):
            if str(weather.get('code')) == str(code):
                # logger.debug(f'天气代码 {code} 对应的天气描述为: {weather.get("wea", "未知")}')
                return weather.get('wea', '未知')
        return '未知'

    def get_weather_icon_by_code(self, code: str, api_name: Optional[str] = None) -> str:
        """根据天气代码获取图标路径"""
        weather_status = self._load_weather_status(api_name)
        weather_code = self._find_weather_code(weather_status, code, api_name)

        if not weather_code:
            return self._get_default_weather_icon()

        return self._build_weather_icon_path(weather_code)

    def _find_weather_code(self, weather_status: Dict[str, Any], code: str, api_name: Optional[str]) -> Optional[str]:
        """查找代码"""
        for weather in weather_status.get('weatherinfo', []):
            if str(weather.get('code')) == str(code):
                original_code = weather.get('original_code')
                if original_code is not None:
                    return str(original_code)
                else:
                    return str(weather.get('code'))

        logger.error(f'未找到天气代码({api_name}) {code}')
        return None

    def _get_default_weather_icon(self) -> str:
        """获取默认图标"""
        return os.path.join(base_directory, 'img', 'weather', '99.svg')

    def _build_weather_icon_path(self, weather_code: str) -> str:
        """构建图标路径"""
        if self._is_night_weather_type(weather_code) and self._is_night_time():
            return os.path.join(base_directory, 'img', 'weather', f'{weather_code}d.svg')

        icon_path = os.path.join(base_directory, 'img', 'weather', f'{weather_code}.svg')
        if not os.path.exists(icon_path):
            logger.warning(f'天气图标文件不存在: {icon_path}')
            return self._get_default_weather_icon()

        return icon_path

    def _is_night_weather_type(self, weather_code: str) -> bool:
        """夜间天气类型判断"""
        return weather_code in ('0', '1', '3', '13')  # 晴、多云、阵雨、阵雪

    def _is_night_time(self) -> bool:
        """夜间时间判断"""
        current_time = datetime.datetime.now()
        return current_time.hour < 6 or current_time.hour >= 18

    def get_weather_stylesheet(self, code: str, api_name: Optional[str] = None) -> str:
        """获取天气背景样式"""
        current_time = datetime.datetime.now()
        weather_status = self._load_weather_status(api_name)
        weather_code = '99'

        for weather in weather_status.get('weatherinfo', []):
            if str(weather.get('code')) == str(code):
                original_code = weather.get('original_code')
                weather_code = str(original_code) if original_code is not None else str(weather.get('code'))
                break

        if weather_code in ('0', '1', '3', '99', '900'):  # 晴、多云、阵雨、未知
            if 6 <= current_time.hour < 18:  # 日间
                return os.path.join('img', 'weather', 'bkg', 'day.png')
            else:  # 夜间
                return os.path.join('img', 'weather', 'bkg', 'night.png')

        return os.path.join('img', 'weather', 'bkg', 'rain.png')

    def get_weather_code_by_description(self, description: str, api_name: Optional[str] = None) -> str:
        """根据天气描述获取天气代码"""
        weather_status = self._load_weather_status(api_name)
        for weather in weather_status.get('weatherinfo', []):
            if str(weather.get('wea')) == description:
                return str(weather.get('code'))
        return '99'

    def get_alert_image_path(self, alert_type: str) -> str:
        """获取天气预警图标路径"""
        provider = self.weather_manager.get_current_provider()
        if not provider or not provider.supports_alerts():
            return os.path.join(base_directory, 'img', 'weather', 'alerts', 'blue.png')

        alerts_config = provider.config.get('alerts', {})
        alerts_types = alerts_config.get('types', {})

        color_mapping = {
            'blue': '蓝色',
            'yellow': '黄色',
            'orange': '橙色',
            'red': '红色'
        }
        icon_name = alerts_types.get(alert_type)
        if not icon_name and alert_type in color_mapping:
            icon_name = alerts_types.get(color_mapping[alert_type])
        if not icon_name:
            icon_name = 'blue.png'
        return os.path.join(base_directory, 'img', 'weather', 'alerts', icon_name)

    def is_alert_supported(self) -> bool:
        """检查当前api是否支持天气预警"""
        provider = self.weather_manager.get_current_provider()
        return provider.supports_alerts() if provider else False

    def extract_weather_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """从天气数据中提取指定字段的值（兼容旧接口）"""
        if not weather_data:
            logger.error('weather_data is None!')
            return None

        provider = self.weather_manager.get_current_provider()
        if not provider:
            return self._legacy_extract_weather_data(key, weather_data)

        try:
            if key == 'temp':
                return provider.parse_temperature(weather_data)
            elif key == 'icon':
                icon_code = provider.parse_weather_icon(weather_data)
                if provider.config.get('return_desc', False) and icon_code:
                    return self.get_weather_code_by_description(icon_code, self.weather_manager.get_current_api())
                return icon_code
            elif key in ('alert', 'alert_title', 'alert_desc'):
                return self._extract_alert_data(key, weather_data)
            else:
                # 回退到旧方法
                return self._legacy_extract_weather_data(key, weather_data)
        except Exception as e:
            logger.error(f'提取天气数据失败 ({key}): {e}')
            return self._legacy_extract_weather_data(key, weather_data)

    def _extract_alert_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """提取预警数据"""
        provider = self.weather_manager.get_current_provider()
        if not provider or not provider.supports_alerts():
            return None

        if isinstance(provider, QWeatherProvider):
            return self._extract_qweather_alert_data(key, weather_data)
        elif isinstance(provider, XiaomiWeatherProvider):
            return self._extract_xiaomi_alert_data(key, weather_data)

        alerts_config = provider.config.get('alerts', {})
        if key == 'alert':
            path = alerts_config.get('type', '')
        elif key == 'alert_title':
            path = alerts_config.get('title', '')
        elif key == 'alert_desc':
            path = alerts_config.get('description', '')
        else:
            return None
        if not path:
            return None
        if hasattr(provider, '_extract_value_by_path'):
            return provider._extract_value_by_path(weather_data, path)

        return None

    def _extract_qweather_alert_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """提取和风天气预警数据"""
        try:
            alert_data = weather_data.get('alert', {})
            if not alert_data or alert_data.get('code') != '200':
                return None
            warning_list = alert_data.get('warning', [])
            if not warning_list:
                return None
            first_warning = warning_list[0]
            if key == 'alert':
                return first_warning.get('severityColor', '')
            elif key == 'alert_title':
                return first_warning.get('title', '')
            elif key == 'alert_desc':
                return first_warning.get('text', '')
            else:
                return None

        except Exception as e:
            logger.error(f"提取和风天气预警数据失败: {e}")
            return None

    def _extract_xiaomi_alert_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """提取小米天气预警数据"""
        try:
            # 预警数据alert.warning
            alert_data = weather_data.get('alert', {})
            if not alert_data or 'warning' not in alert_data:
                return None
            alerts_data = alert_data.get('warning', [])
            if not alerts_data or not isinstance(alerts_data, list):
                return None
            first_alert = alerts_data[0]
            if not isinstance(first_alert, dict):
                return None
            result = None
            if key == 'alert':
                result = first_alert.get('level', '')
            elif key == 'alert_title':
                result = first_alert.get('title', '')
            elif key == 'alert_desc':
                result = first_alert.get('detail', '')
            else:
                return None
            return result

        except Exception as e:
            return None

    def get_weather_alerts(self, weather_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取所有预警信息"""
        provider = self.weather_manager.get_current_provider()
        if not provider or not provider.supports_alerts():
            return []

        alert_data = weather_data.get('alert', {})
        if isinstance(provider, QWeatherProvider):
            return self._get_qweather_alerts(provider, alert_data)
        elif isinstance(provider, XiaomiWeatherProvider):
            return self._get_xiaomi_alerts(alert_data)
        else:
            return self._get_generic_alerts(alert_data)

    def _get_qweather_alerts(self, provider, alert_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取和风天气预警"""
        if hasattr(provider, 'parse_weather_alerts'):
            return provider.parse_weather_alerts(alert_data)
        return []

    def _get_xiaomi_alerts(self, alert_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取小米天气预警"""
        if alert_data and 'warning' in alert_data and isinstance(alert_data.get('warning'), list):
            return alert_data.get('warning', [])
        return []

    def _get_generic_alerts(self, alert_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取通用天气预警"""
        if not alert_data:
            return []

        if 'warning' in alert_data and isinstance(alert_data.get('warning'), list):
            warnings = alert_data.get('warning', [])
            return [warning for warning in warnings if isinstance(warning, dict)]

        if 'alerts' in alert_data:
            return alert_data.get('alerts', [])

        return []

    def get_unified_alert_data(self, weather_data: Dict[str, Any]) -> Dict[str, Any]:
        """获取统一格式的预警数据

        Args:
            weather_data (Dict[str, Any]): 原始天气数据

        Returns:
        {
            'has_alert': bool,  # 是否有预警
            'alert_count': int,  # 预警数量
            'primary_alert': {  # 主要预警(最高级别)
                'type': str,  # 预警类型(如'暴雨')
                'level': str,  # 预警级别(蓝/黄/橙/红)
                'color': str,  # 预警颜色代码
                'title': str,  # 预警标题
                'description': str,  # 预警描述
                'severity': int,  # 严重程度(1-4, 4最严重)
                'display_text': str  # 用于显示的简短文本
            },
            'all_alerts': List[Dict]  # 所有预警详情
        }
        """
        provider = self.weather_manager.get_current_provider()
        if not self._validate_alert_support(provider):
            return self._create_empty_alert_data()
        all_alerts = self.get_weather_alerts(weather_data)
        if not all_alerts:
            return self._create_empty_alert_data()
        unified_alerts = self._process_all_alerts(all_alerts, provider)
        if not unified_alerts:
            return self._create_empty_alert_data()
        return self._build_unified_alert_result(unified_alerts)

    def _validate_alert_support(self, provider) -> bool:
        """预警支持验证"""
        return provider and provider.supports_alerts()

    def _create_empty_alert_data(self) -> Dict[str, Any]:
        """创建空模板"""
        return {
            'has_alert': False,
            'alert_count': 0,
            'primary_alert': None,
            'all_alerts': []
        }

    def _process_all_alerts(self, all_alerts: List[Dict[str, Any]], provider) -> List[Dict[str, Any]]:
        """处理预警数据"""
        unified_alerts = []
        for alert in all_alerts:
            unified_alert = self._normalize_alert_data(alert, provider)
            if unified_alert:
                unified_alerts.append(unified_alert)
        return unified_alerts

    def _build_unified_alert_result(self, unified_alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构建预警模板"""
        unified_alerts.sort(key=lambda x: x.get('severity', 0), reverse=True)
        primary_alert = unified_alerts[0]
        return {
            'has_alert': True,
            'alert_count': len(unified_alerts),
            'primary_alert': primary_alert,
            'all_alerts': unified_alerts
        }

    def _normalize_alert_data(self, alert: Dict[str, Any], provider) -> Optional[Dict[str, Any]]:
        """预警数据标准化"""
        try:
            if 'severityColor' in alert or 'startTime' in alert:
                return self._normalize_qweather_alert(alert)
            elif isinstance(provider, QWeatherProvider):
                return self._normalize_qweather_alert(alert)
            elif isinstance(provider, XiaomiWeatherProvider):
                return self._normalize_xiaomi_alert(alert)
            else:
                return self._normalize_generic_alert(alert)
        except Exception as e:
            logger.error(f"标准化预警数据失败: {e}")
            return None

    def _normalize_qweather_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """标准化和风天气预警"""
        title = alert.get('title', '')
        severity_color = alert.get('severityColor', '')
        alert_type, alert_level = self._extract_alert_info_from_title(title)
        severity_map = {
            'Blue': 1, 'Yellow': 2, 'Orange': 3, 'Red': 4,
            'blue': 1, 'yellow': 2, 'orange': 3, 'red': 4,
            '蓝': 1, '黄': 2, '橙': 3, '红': 4
        }
        severity = severity_map.get(severity_color, 1)
        if alert_type and alert_level:
            display_text = f"{alert_type}{alert_level}色预警"
        elif alert_type:
            display_text = f"{alert_type}预警"
        else:
            display_text = "天气预警"
        return {
            'type': alert_type or '未知',
            'level': alert_level or severity_color,
            'color': severity_color,
            'title': title,
            'description': alert.get('text', ''),
            'severity': severity,
            'display_text': display_text,
            'start_time': alert.get('startTime', ''),
            'end_time': alert.get('endTime', ''),
            'source': 'qweather'
        }

    def _normalize_xiaomi_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """标准化小米天气预警"""
        title = alert.get('title', '')
        alert_type, alert_level = self._extract_xiaomi_alert_info(alert, title)
        severity = self._calculate_xiaomi_severity(alert_level)
        display_text = self._build_xiaomi_display_text(alert_type, alert_level)

        return {
            'type': alert_type,
            'level': alert_level,
            'color': alert_level,  # 小米天气用level作为颜色
            'title': title,
            'description': alert.get('detail', ''),
            'severity': severity,
            'display_text': display_text,
            'start_time': alert.get('start_time', ''),
            'end_time': alert.get('end_time', ''),
            'source': 'xiaomi'
        }

    def _extract_xiaomi_alert_info(self, alert: Dict[str, Any], title: str) -> Tuple[str, str]:
        """提取小米天气预警类型,级别"""
        alert_type = alert.get('type', '')
        alert_level = alert.get('level', '')

        if not alert_type or not alert_level:
            extracted_type, extracted_level = self._extract_alert_info_from_title(title)
            alert_type = alert_type or extracted_type or '未知'
            alert_level = alert_level or extracted_level or '未知'

        return alert_type, alert_level

    def _calculate_xiaomi_severity(self, alert_level: str) -> int:
        """映射严重度"""
        level_map = {
            '蓝色': 1, '黄色': 2, '橙色': 3, '红色': 4,
            '蓝': 1, '黄': 2, '橙': 3, '红': 4
        }
        return level_map.get(alert_level, 1)

    def _build_xiaomi_display_text(self, alert_type: str, alert_level: str) -> str:
        """构建小米天气预警文本"""
        if alert_type and alert_level:
            return f"{alert_type}{alert_level}预警"
        elif alert_type:
            return f"{alert_type}预警"
        else:
            return "天气预警"

    def _normalize_generic_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """标准化通用预警数据(其他天气API)"""
        title = alert.get('title', alert.get('name', ''))
        alert_type, alert_level = self._extract_alert_info_from_title(title)
        severity = 1
        if 'level' in alert:
            level_map = {'1': 1, '2': 2, '3': 3, '4': 4}
            severity = level_map.get(str(alert['level']), 1)
        elif alert_level:
            level_map = {'蓝': 1, '黄': 2, '橙': 3, '红': 4}
            severity = level_map.get(alert_level, 1)
        display_text = f"{alert_type}预警" if alert_type else "天气预警"
        return {
            'type': alert_type or '未知',
            'level': alert_level or '未知',
            'color': alert.get('color', ''),
            'title': title,
            'description': alert.get('description', alert.get('desc', '')),
            'severity': severity,
            'display_text': display_text,
            'start_time': alert.get('start_time', ''),
            'end_time': alert.get('end_time', ''),
            'source': 'generic'
        }

    def _extract_alert_info_from_title(self, title: str) -> Tuple[Optional[str], Optional[str]]:
        """从预警标题中提取预警类型和级别"""
        pattern = r'发布(\w+)(蓝|黄|橙|红)色预警'
        match = re.search(pattern, title)

        if match:
            alert_type = match.group(1)  # 预警类型
            alert_level = match.group(2)  # 预警级别
            return alert_type, alert_level
        # fallback
        type_patterns = [
            r'(暴雨|大雨|雷电|大风|高温|寒潮|冰雹|雾|霾|道路结冰|森林火险|干旱|台风|龙卷风)预警',
            r'(\w+)(蓝|黄|橙|红)色预警',
            r'(\w+)预警'
        ]

        for pattern in type_patterns:
            match = re.search(pattern, title)
            if match:
                if len(match.groups()) >= 2:
                    return match.group(1), match.group(2)
                else:
                    return match.group(1), None

        return None, None

    def _legacy_extract_weather_data(self, key: str, weather_data: Dict[str, Any]) -> Optional[str]:
        """数据提取(向后兼容)"""
        current_api = self.weather_manager.get_current_api()
        api_params = self.weather_manager.api_config.get('weather_api_parameters', {})
        current_params = api_params.get(current_api, {})

        parameter_path = self._get_parameter_path(key, current_params)
        if not parameter_path:
            logger.error(f'未找到参数路径: {key}')
            return None

        value = self._extract_value_by_api(current_api, current_params, key, parameter_path, weather_data)
        return self._format_extracted_value(key, value, current_params)

    def _get_parameter_path(self, key: str, current_params: Dict[str, Any]) -> str:
        """获取参数路径"""
        if key == 'alert':
            alerts_config = current_params.get('alerts', {})
            return alerts_config.get('type', '')
        elif key == 'alert_title':
            alerts_config = current_params.get('alerts', {})
            return alerts_config.get('title', '')
        else:
            return current_params.get(key, '')

    def _extract_value_by_api(self, current_api: str, current_params: Dict[str, Any],
                             key: str, parameter_path: str, weather_data: Dict[str, Any]) -> Any:
        """根据API类型提取值"""
        context = WeatherExtractionContext(
            current_params=current_params,
            key=key,
            weather_data=weather_data,
            current_api=current_api,
            parameter_path=parameter_path
        )

        if current_api == 'amap_weather':
            return self._extract_amap_value(context)
        elif current_api == 'qq_weather':
            return self._extract_qq_value(context)
        else:
            return self._extract_generic_value(context)

    def _extract_amap_value(self, context: WeatherExtractionContext) -> str:
        """提取高德天气值"""
        return context.weather_data.get('lives', [{}])[0].get(
            context.current_params.get(context.key, ''), ''
        )

    def _extract_qq_value(self, context: WeatherExtractionContext) -> str:
        """提取QQ天气值"""
        realtime_data = context.weather_data.get('result', {}).get('realtime', [{}])
        if realtime_data:
            return str(realtime_data[0].get('infos', {}).get(
                context.current_params.get(context.key, ''), ''
            ))
        return ''

    def _extract_generic_value(self, context: WeatherExtractionContext) -> Any:
        """提取通用天气值"""
        value = context.weather_data
        parameters = context.parameter_path.split('.')

        for param in parameters:
            value = self._process_single_parameter(value, param, context.current_api, context.key)
            if value is None or value == '错误':
                return value
        return value

    def _process_single_parameter(self, value: Any, param: str, current_api: str, key: str) -> Any:
        """处理单个参数"""
        if not value:
            logger.warning(f'天气信息值{key}为空')
            return None

        if param == '0':
            if isinstance(value, list) and len(value) > 0:
                return value[0]
            else:
                logger.error(f'无法获取数组第一个元素: {param}')
                return None
        elif isinstance(value, dict) and param in value:
            return value[param]
        else:
            logger.error(f'获取天气参数失败，{param}不存在于{current_api}中')
            return '错误'

    def _format_extracted_value(self, key: str, value: Any, current_params: Dict[str, Any]) -> Optional[str]:
        """格式化提取值"""
        if value is None:
            return None

        if key == 'temp' and value:
            return str(value) + '°'
        elif key == 'icon' and current_params.get('return_desc', False):
            return self.get_weather_code_by_description(str(value))

        return str(value)


class WeatherReportThread(QThread):
    """天气数据获取"""
    weather_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.weather_manager = WeatherManager()

    def run(self):
        """线程运行方法"""
        try:
            weather_data = self.weather_manager.fetch_weather_data()
            if weather_data:
                self.weather_signal.emit(weather_data)
            else:
                logger.error('获取天气数据返回None')
                self.weather_signal.emit({'error': {'info': {'value': '错误', 'unit': ''}}})
        except Exception as e:
            logger.error(f'触发天气信息失败: {e}')
            self.weather_signal.emit({'error': {'info': {'value': '错误', 'unit': ''}}})


weather_manager = WeatherManager()
weather_database = WeatherDatabase(weather_manager)
weather_processor = WeatherDataProcessor(weather_manager)


def on_weather_api_changed(new_api: str):
    global weather_manager, weather_processor
    weather_manager.on_api_changed(new_api)
    weather_processor.clear_cache()

# 兼容性用
def search_by_name(search_term: str) -> List[str]:
    """根据名称搜索城市"""
    return weather_database.search_city_by_name(search_term)


def search_code_by_name(city_name: str, district_name: str = '') -> str:
    """根据名称搜索城市代码"""
    return weather_database.search_code_by_name(city_name, district_name)


def search_by_num(city_code: str) -> str:
    """根据代码搜索城市"""
    return weather_database.search_city_by_code(city_code)


def get_weather_by_code(code: str) -> str:
    """根据代码获取天气描述"""
    return weather_processor.get_weather_by_code(code)


def get_weather_icon_by_code(code: str) -> str:
    """根据代码获取天气图标"""
    return weather_processor.get_weather_icon_by_code(code)

def get_weather_stylesheet(code: str) -> str:
    """获取天气样式表"""
    return weather_processor.get_weather_stylesheet(code)


def get_weather_data(key: str = 'temp', weather_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """获取天气数据"""
    return weather_processor.extract_weather_data(key, weather_data)


def get_unified_weather_alerts(weather_data: Dict[str, Any]) -> Dict[str, Any]:
    """获取统一格式的天气预警数据

    Args:
        weather_data: 天气数据字典

    Returns:
        统一格式的预警数据字典，包含:
        - has_alert: 是否有预警
        - alert_count: 预警数量
        - primary_alert: 主要预警信息
        - all_alerts: 所有预警列表
    """
    return weather_processor.get_unified_alert_data(weather_data)


def get_alert_image(alert_type: str) -> str:
    """获取预警图标"""
    return weather_processor.get_alert_image_path(alert_type)


def is_supported_alert() -> bool:
    """检查是否支持预警"""
    return weather_processor.is_alert_supported()


def get_weather_url() -> str:
    """获取天气URL"""
    provider = weather_manager.get_current_provider()
    return provider.base_url if provider else ''


def get_weather_alert_url() -> Optional[str]:
    """获取天气预警URL"""
    provider = weather_manager.get_current_provider()
    if not provider or not provider.supports_alerts():
        return 'NotSupported'
    alerts_config = provider.config.get('alerts', {})
    return alerts_config.get('url')


if __name__ == '__main__':
    try:
        print("=== 测试 ===")
        cities = search_by_name('北京')
        print(f"搜索'北京'的结果: {cities[:5]}")
        code = search_code_by_name('北京', '')
        print(f"北京的城市代码: {code}")
        city_name = search_by_num(code)
        print(f"代码{code}对应的城市: {city_name}")
        weather_data = weather_manager.fetch_weather_data()
        if weather_data:
            print(f"获取到的天气数据结构: {type(weather_data)}")
            print(f"天气数据键: {list(weather_data.keys()) if isinstance(weather_data, dict) else 'Not a dict'}")

            if 'now' in weather_data:
                now_data = weather_data['now']
                print(f"当前天气数据: {now_data}")
                temp = weather_processor.extract_weather_data('temp', now_data)
                icon = weather_processor.extract_weather_data('icon', now_data)
                print(f"解析的温度: {temp}")
                print(f"解析的天气图标: {icon}")
            else:
                print("天气数据中没有'now'字段")
        else:
            print("未获取到天气数据")
        weather_desc = get_weather_by_code('0')
        print(f"\n天气代码0对应的描述: {weather_desc}")
        icon_path = get_weather_icon_by_code('0')
        print(f"天气代码0对应的图标: {icon_path}")


    except Exception as e:
        print(f"测试出错: {e}")
        import traceback
        traceback.print_exc()