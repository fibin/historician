"""Точка входа Historian.exe (сборка: pyinstaller Historian.spec).

Exe собран без консоли, чтобы задача по расписанию раз в час не мигала окном. Окну бота консоль нужна:
в ней видно, что бот работает, а если её закрыть, бот останавливается. Поэтому без аргументов exe сам
открывает консоль и запускает окно бота, а с аргументами (--due от планировщика) работает молча
и пишет всё в logs/<дата>.log.
"""
import os
import sys
import traceback
from datetime import date

if getattr(sys, "frozen", False):
    # accounts/, logs/, music/ и .env лежат рядом с exe. Переходим туда до импорта historian: он сразу читает .env
    os.chdir(os.path.dirname(os.path.abspath(sys.executable)))


def _console() -> None:
    import ctypes
    kernel = ctypes.windll.kernel32
    if not kernel.GetConsoleWindow():
        kernel.AllocConsole()
    kernel.SetConsoleTitleW("Historian")
    sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    sys.stdin = open("CONIN$", encoding="utf-8")


def _log() -> None:
    os.makedirs("logs", exist_ok=True)
    sys.stdout = sys.stderr = open(os.path.join("logs", f"{date.today().isoformat()}.log"), "a", encoding="utf-8")


def main() -> None:
    args = sys.argv[1:]
    if args:
        if sys.stdout is None:  # без консоли выводу некуда идти
            _log()
        try:
            from historian import main as cli
            cli.main(args)
        except Exception:
            traceback.print_exc()
            sys.exit(1)
        return
    if os.name == "nt":
        try:
            _console()
        except OSError:  # без консоли окно бота всё равно работает
            pass
    try:
        from historian import web
        web.run()
    except Exception:
        traceback.print_exc()
        input("\nНажмите Enter, чтобы закрыть окно.")


if __name__ == "__main__":
    main()
