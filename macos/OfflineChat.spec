# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['offlinechat_app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PyObjCTools',
        'Foundation',
        'CoreBluetooth',
        'objc',
        'libdispatch',
        'queue',
        'threading',
        'tkinter',
        'tkinter.scrolledtext',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OfflineChat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OfflineChat',
)

app = BUNDLE(
    coll,
    name='OfflineChat.app',
    icon=None,
    bundle_identifier='com.offlinechat.app',
    info_plist={
        'NSBluetoothAlwaysUsageDescription': 'OfflineChat использует Bluetooth для обмена сообщениями между устройствами.',
        'NSBluetoothPeripheralUsageDescription': 'OfflineChat использует Bluetooth для обмена сообщениями между устройствами.',
        'CFBundleName': 'OfflineChat',
        'CFBundleDisplayName': 'OfflineChat',
        'CFBundleIdentifier': 'com.offlinechat.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSMinimumSystemVersion': '10.15',
    },
)