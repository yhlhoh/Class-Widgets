@echo off
echo �������⻷��
uv venv
call .venv\Scripts\activate
echo ��װ����
uv pip install -r requirements.txt
uv pip install nuitka imageio
echo ���
python -m nuitka main.py ^
--enable-plugin=pyqt5 ^
--disable-console ^
--mode=app ^
-o"ClassWidgets" ^
--windows-icon-from-ico=img/favicon.icns ^
--product-name="Class Widgets" ^
--product-version="1.1.7.1" ^
--file-description="ȫ������α�" ^
--include-data-dir=img=img ^
--include-data-dir=ui=ui ^
--include-data-dir=view=view ^
--include-data-dir=config=config ^
--include-data-dir=plugins=plugins ^
--include-data-dir=font=font ^
--include-data-dir=audio=audio ^
--include-data-files=LICENSE=LICENSE ^
--include-package=pyttsx3.drivers
