# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['il2_tracker_launcher.py'],
    pathex=[],
    binaries=[
        (r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe', '.'),
    ],
    datas=[
        ('campaign_progress_config.yaml', '.'),
        ('stock_campaigns.yaml', '.'),
        ('object_categories.yaml', '.'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        '_tkinter',
		'pdfkit',
        'country_validator_gui',
        'step1_extract_mission_dates',
        'step3_generate_events',
        'step4_process_mission_logs',
        'decode_campaing_usersave1',
        'monitor_campaigns',
        'il2_mission_debrief',
		'cleanup_failed_missions',
		'PIL',
		'PIL.Image',
		'PIL.DdsImagePlugin',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='IL2_CampaignTracker',
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
