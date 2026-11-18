# Build with: .venv\Scripts\python.exe -m PyInstaller --noconfirm RiotWatcher.spec
a = Analysis(
    ['ui.py'],
    pathex=[],
    binaries=[],
    datas=[('game_metadata.json', '.'), ('notification.wav', '.'),
           ('assets', 'assets'), ('LICENSE', '.')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='RiotWatcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/logo.ico',
    version='version-info.txt',
)
