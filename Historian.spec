# Сборка Historian.exe: pyinstaller Historian.spec
# GitHub собирает exe сам при каждом изменении main и выкладывает в Releases (.github/workflows/exe.yml).
a = Analysis(
    ["scripts/historian_exe.py"],
    pathex=["."],
    datas=[("historian/page.html", "historian"), ("scripts/install_task.ps1", "scripts")],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="Historian",
    console=False,  # консоль для окна бота exe открывает сам, а по расписанию работает без окна
    upx=False,
)
