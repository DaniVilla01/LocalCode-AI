# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller para Local Code Agent.
# En Windows produce dist/local-code-agent.exe.

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = []

a = Analysis(
    ['local_code_agent.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('README.md', '.'),
        ('config.example.json', '.'),
    ],
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='local-code-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
