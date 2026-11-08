#!/usr/bin/env python3
"""Запуск штатных средств 1С с настройками проекта и проверкой результата."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def read_text(path):
    return Path(path).read_text(encoding="utf-8")

def settings():
    return json.loads(read_text(ROOT / "stand.json"))

def windows():
    return os.name == "nt"

def platform_root(cfg):
    return Path(cfg["platform"])

def platform_bin(cfg):
    return platform_root(cfg) / "bin"

def runner_artifact():
    """Закреплённый архив v8-runner для текущей ОС."""
    pin = json.loads(read_text(ROOT / "scripts/v8-runner.json"))
    if "artifacts" in pin:
        artifact = pin["artifacts"]["windows" if windows() else "linux"]
    else:
        artifact = pin
    name = artifact.get("name") or ("v8-runner.exe" if windows() else "v8-runner")
    return pin, artifact, ROOT / "1c/v8runner/bin" / pin["version"] / name

def connection_of(cfg):
    return f"Srvr={cfg['server']};Ref={cfg['infobase']}"

def host_path(cfg, path):
    """Путь, который видит платформа. На Linux это префикс контейнера, на Windows — сам путь."""
    return (cfg.get("container_path_prefix") or "") + str(path)

def onec_cmd(cfg, mode, args):
    """Команда платформы. mode: thin, designer, create.

    На Linux остаётся обёртка launcher (`onec --thin`). На Windows вызывается
    1cv8.exe / 1cv8c.exe установленной платформы."""
    if not windows() and cfg.get("launcher"):
        cmd = [cfg["launcher"]]
        if mode == "thin":
            cmd += ["--thin", "ENTERPRISE"]
        elif mode == "designer":
            cmd += ["DESIGNER"]
        elif mode == "create":
            cmd += ["CREATEINFOBASE"]
        else:
            raise ValueError(mode)
        return cmd + list(args)
    exe = platform_bin(cfg) / ("1cv8c.exe" if mode == "thin" else "1cv8.exe")
    if mode == "thin":
        return [str(exe), "ENTERPRISE", *args]
    if mode == "designer":
        return [str(exe), "DESIGNER", *args]
    if mode == "create":
        return [str(exe), "CREATEINFOBASE", *args]
    raise ValueError(mode)

def detached():
    if windows():
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}

CONF_RULE = "DisableUnsafeActionProtection=.*va-manager.*"

def read_conf(path):
    """Текст conf.cfg. Общий файл платформы на Windows — UTF-16, файл версии часто UTF-8."""
    if not path.is_file():
        return ""
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")

def write_conf(path, text):
    raw = path.read_bytes() if path.is_file() else b""
    utf16 = raw.startswith((b"\xff\xfe", b"\xfe\xff")) or (not raw and windows())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-16" if utf16 else "utf-8-sig"))

def conf_paths(cfg):
    """Файлы conf.cfg, которые реально читает платформа.

    Строка ConfLocation в conf версии перенаправляет настройки в общий каталог.
    Правило дописывается туда, а не во второй файл, иначе UTF-8 дописывается в UTF-16."""
    if not windows():
        return []
    root = platform_root(cfg)
    seeds = [root.parent / "conf" / "conf.cfg", platform_bin(cfg) / "conf" / "conf.cfg"]
    resolved = []
    for path in seeds:
        text = read_conf(path)
        location = re.search(r"^ConfLocation=(.+)$", text, re.M)
        target = Path(location.group(1).strip()) / "conf.cfg" if location else path
        if target not in resolved:
            resolved.append(target)
    return resolved

def conf_text(cfg):
    if not windows():
        try:
            return subprocess.run(
                ["distrobox", "enter", "-T", cfg["container"], "--", "cat", "/opt/1cv8/conf/conf.cfg"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    return "\n".join(read_conf(path) for path in conf_paths(cfg))

def ensure_conf_rule(cfg):
    """Разрешает служебную обработку в выбранной базе менеджера из stand.json."""
    if cfg.get("vanessa_manager") == "server":
        # В серверном режиме доверие задается флагами client_mcp в выбранной ИБ.
        # Общесистемный conf.cfg не расширяем на рабочие серверные базы.
        return
    if not windows():
        subprocess.run([cfg["launcher"], "--prepare-headless"], stdout=sys.stderr, check=True)
        return
    denied = []
    patterns = [".*va-manager.*"]
    if cfg.get("vanessa_manager") == "server":
        patterns.append('.*Ref="*' + re.escape(cfg["infobase"]) + '"*.*')
    for path in conf_paths(cfg):
        text = read_conf(path)
        match = re.search(r"^DisableUnsafeActionProtection=(.*)$", text, re.M)
        existing = match.group(1).strip().split(";") if match else []
        missing = [pattern for pattern in patterns if pattern not in existing]
        if not missing:
            continue
        rule = "DisableUnsafeActionProtection=" + ";".join([*existing, *missing])
        if match:
            updated = text[:match.start()] + rule + text[match.end():]
        else:
            updated = text + ("\n" if text and not text.endswith("\n") else "") + rule + "\n"
        try:
            write_conf(path, updated)
        except OSError:
            denied.append(path)
    if denied:
        raise RuntimeError(
            "нет права записать conf.cfg (" + ", ".join(str(p) for p in denied) + "). "
            f"От администратора добавьте строку: DisableUnsafeActionProtection={';'.join(patterns)}")

def ensure_ras(cfg):
    """Поднимает ras, если порт администрации кластера ещё не слушается."""
    address = cfg.get("ras", "localhost:1545")
    host, _, port_text = address.partition(":")
    port = int(port_text or "1545")
    host = host or "127.0.0.1"
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex((host, port)) == 0:
            return
    agent = cfg.get("agent", "localhost:1540")
    subprocess.Popen(
        [str(platform_bin(cfg) / "ras.exe"), "cluster", f"--port={port}", agent],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detached())
    for _ in range(40):
        time.sleep(0.25)
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex((host, port)) == 0:
                return
    raise RuntimeError(f"ras не открыл {address}")

def v8_runner(cfg, args, dry_run=False):
    """Запускает v8-runner с подключением из stand.json."""
    pin, artifact, binary = runner_artifact()
    overlay = ROOT / "v8project.local.yaml"
    connection = connection_of(cfg)
    if windows():
        cmd = [str(binary), *args]
    else:
        cmd = ["distrobox", "enter", "-T", cfg["container"], "--", "bash", "-c",
               # Дисплей :99 поднимает обёртка onec --prepare-headless.
               'cd "$0" && DISPLAY=:99 exec "$1" "${@:2}"',
               cfg["container_path_prefix"] + str(ROOT), cfg["container_path_prefix"] + str(binary), *args]
    if dry_run:
        if windows() and args[:2] == ["test", "yaxunit"]:
            print(shlex.join([str(binary), "build"]))
            shown = yaxunit_enterprise_cmd(cfg, "<config.json>", "<enterprise.out.log>")
            print(shlex.join(shown))
        else:
            print(shlex.join(cmd))
        return
    if not binary.exists():
        data = urllib.request.urlopen(artifact["url"]).read()
        if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise RuntimeError("хеш архива v8-runner не совпадает с scripts/v8-runner.json")
        binary.parent.mkdir(parents=True, exist_ok=True)
        suffix = artifact.get("suffix") or ("v8-runner.exe" if windows() else "/v8-runner")
        if artifact["url"].endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                member = next(name for name in archive.namelist() if name.endswith(suffix))
                binary.write_bytes(archive.read(member))
        else:
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                member = next(item for item in tar.getmembers() if item.name.endswith(suffix))
                binary.write_bytes(tar.extractfile(member).read())
        if not windows():
            binary.chmod(0o755)
    # Overlay дополняют команды v8-runner (tools download), поэтому он создаётся один раз,
    # а при каждом запуске сверяется со stand.json.
    if not overlay.exists():
        platform = ""
        if windows():
            platform = f'tools:\n  platform:\n    path: "{platform_bin(cfg).as_posix()}"\n'
        overlay.write_text(
            f'infobase:\n  connection: "{connection}"\n  user: {cfg["user"]}\n{platform}',
            encoding="utf-8")
    # v8-runner переписывает overlay и может снять кавычки, поэтому сверяется значение.
    elif not re.search(r'^\s+connection:\s*"?' + re.escape(connection) + r'"?\s*$', read_text(overlay), re.M):
        raise RuntimeError(f"{overlay.name} не совпадает со stand.json: ожидается {connection}")
    # Вывод подготовки уходит в stderr: stdout может быть транспортом MCP.
    # Правило conf.cfg нужно только базе-менеджеру Vanessa, не серверу MCP v8-runner.
    if windows():
        # os.execv на Windows порождает новый процесс и сразу завершает текущий,
        # поэтому оболочка видит успех, пока Конфигуратор ещё работает.
        os.chdir(ROOT)
        if args[:2] == ["test", "yaxunit"]:
            sys.exit(run_yaxunit_windows(cfg, binary, args[2:]))
        sys.exit(subprocess.run(cmd).returncode)
    ensure_conf_rule(cfg)
    os.execvp(cmd[0], cmd)

def yaxunit_enterprise_cmd(cfg, config_path, log_path):
    """Команда тонкого клиента. /C и RunUnitTests — разные аргументы.

    v8-runner 0.5.1 склеивает их в /C\\"RunUnitTests=...\\", Windows экранирует кавычки,
    и YAxUnit не перехватывает запуск: открывается обычный сеанс УТ."""
    return [
        str(platform_bin(cfg) / "1cv8c.exe"), "ENTERPRISE",
        "/IBConnectionString", connection_of(cfg),
        "/N", cfg["user"], "/Lru",
        "/DisableStartupDialogs", "/DisableStartupMessages",
        "/C", "RunUnitTests=" + str(config_path),
        "/Out", str(log_path),
    ]

def partial_load_logs():
    log_dir = ROOT / "1c/v8runner/build/logs/platform"
    if not log_dir.is_dir():
        return []
    return [log for log in log_dir.glob("*-load.log")
            if "файла-списка" in log.read_text(encoding="utf-8-sig", errors="replace")]

def partial_load_failed():
    """Конфигуратор 8.3.27 не читает список частичной загрузки, который пишет v8-runner 0.5.1."""
    return bool(partial_load_logs())

def partial_load_source_sets():
    """Имена расширений из лога `build-NN-<имя>-load.log` с ошибкой списка загрузки."""
    names = []
    for log in partial_load_logs():
        match = re.fullmatch(r"build-\d+-(.+)-load", log.stem)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names

def forget_extension_load_cache(names=()):
    """Сбрасывает кэш названных расширений, чтобы сборка выбрала полную загрузку.

    Пустой список — запасной путь: сбросить все расширения. Кэш типовой
    `designer-main.redb` не трогается: его пересборка — это загрузка всей УТ.
    Полная загрузка снова включает безопасный режим только у сброшенного расширения."""
    storage = ROOT / "1c/v8runner/build/hash-storages"
    if not storage.is_dir():
        return
    if not names:
        names = [db.stem.removeprefix("designer-") for db in storage.glob("designer-*.redb")]
    for name in names:
        if name == "main":
            continue
        db = storage / f"designer-{name}.redb"
        if db.is_file():
            db.unlink()

def run_yaxunit_windows(cfg, binary, scope):
    """Сборку делает v8-runner, прогон — платформа с исправленным параметром запуска."""
    requested_run_dir = os.environ.get("ONEC_YAXUNIT_RUN_DIR")
    run_dir = (ROOT / requested_run_dir).resolve() if requested_run_dir else ROOT / "1c/v8runner/build/temp/yaxunit/manual"
    if requested_run_dir and not run_dir.is_relative_to((ROOT / "1c/tmp").resolve()):
        raise ValueError("ONEC_YAXUNIT_RUN_DIR должен находиться в 1c/tmp проекта")
    print("Каталог результатов YAxUnit:", run_dir, flush=True)
    build = subprocess.run([str(binary), "build"])
    if build.returncode != 0 and partial_load_failed():
        forget_extension_load_cache(partial_load_source_sets())
        build = subprocess.run([str(binary), "build"])
    if build.returncode != 0:
        return build.returncode
    run_dir.mkdir(parents=True, exist_ok=True)
    report = run_dir / "report.xml"
    out_log = run_dir / "enterprise.out.log"
    runner_log = run_dir / "runner.log"
    report.unlink(missing_ok=True)
    config_path = run_dir / "config.json"
    config = {
        "reportFormat": "jUnit",
        "reportPath": str(report),
        "closeAfterTests": True,
        "showReport": False,
        "logging": {"file": str(runner_log), "console": False, "level": "info"},
    }
    names = [item for item in scope if item != "all"]
    if names:
        config["filter"] = {"extensions": names}
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    completed = subprocess.run(yaxunit_enterprise_cmd(cfg, config_path, out_log))
    if not report.is_file() or report.stat().st_size == 0:
        details = out_log.read_text(encoding="utf-8-sig", errors="replace") if out_log.is_file() else ""
        raise RuntimeError(
            "YAxUnit не записал отчёт"
            + (f"; код клиента {completed.returncode}" if completed.returncode else "")
            + (f"\n{details.strip()}" if details.strip() else ""))
    root = ET.parse(report).getroot()
    cases = list(root.iter("testcase"))
    if not cases:
        raise RuntimeError(f"YAxUnit записал отчёт без выполненных тестов: {report}")
    failed = 0
    for case in cases:
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            problem = case.find("skipped")
        name = case.get("classname", "") + "." + case.get("name", "")
        if problem is None:
            print("✓ " + name)
            continue
        failed += 1
        message = (problem.get("message") or problem.text or "").strip()
        if problem.tag == "skipped":
            message = "тест пропущен" + (": " + message if message else "")
        print("✗ " + name + (": " + message if message else ""))
    # Ошибки обработчиков YAxUnit находятся прямо в testsuite, вне testcase.
    # Зеленые тесты при неуспешной очистке не являются успешным прогоном.
    for suite in root.iter():
        if suite.tag not in {"testsuite", "testsuites"}:
            continue
        for problem in suite:
            if problem.tag in {"failure", "error", "skipped"}:
                failed += 1
                message = (problem.get("message") or problem.text or "").strip()
                print("✗ обработчик " + suite.get("name", "") + (": " + message if message else ""))
    if failed:
        print(f"не прошло: {failed}")
        return 1
    if completed.returncode:
        return completed.returncode
    print(f"тесты прошли; выполнено: {len(cases)}")
    return 0

MANAGER = ROOT / "1c/v8runner/va-manager"

def va_manager_args(cfg, container):
    """Подключение менеджера из stand.json; серверный менеджер использует стенд УТ."""
    if cfg.get("vanessa_manager") == "server":
        return ["/S" + cfg["server"] + "\\" + cfg["infobase"], "/N" + cfg["user"]]
    return ["/F", container(MANAGER)]

def vanessa_file(name, download=True):
    """Закреплённый файл Vanessa из scripts/vanessa.json, скачивается и сверяется по хешу.

    Свой закреп, а не `v8 tools download vanessa`: 05.10.2026 раннер скачал сборку
    1.2.043.1 без MCP, хотя последним релизом была 1.2.043.42."""
    pin = json.loads(read_text(ROOT / "scripts/vanessa.json"))[name]
    target = ROOT / "1c/v8runner/vanessa" / name / pin["version"] / Path(pin.get("member") or pin["url"]).name
    if download and target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() != pin["sha256"]:
        raise RuntimeError(f"хеш кэша {name} не совпадает с scripts/vanessa.json: {target}")
    if download and not target.is_file():
        data = urllib.request.urlopen(pin["url"], timeout=60).read()
        if "member" in pin:
            data = zipfile.ZipFile(io.BytesIO(data)).read(pin["member"])
        if hashlib.sha256(data).hexdigest() != pin["sha256"]:
            raise RuntimeError(f"хеш {name} не совпадает с scripts/vanessa.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return target, pin["sha256"]

def kill_clients(marker):
    """Завершает процессы 1cv8c, в аргументах которых есть marker.

    Свои процессы помечаются путём /Out: родительский процесс их не ждёт."""
    marker_text = str(marker)
    if windows():
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='1cv8c.exe'\" | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        raw = completed.stdout.strip()
        if not raw:
            return
        rows = json.loads(raw)
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if marker_text in (row.get("CommandLine") or ""):
                os.kill(int(row["ProcessId"]), 15)
        return
    marker_bytes = os.fsencode(marker_text)
    for entry in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            args = entry.read_bytes().split(b"\0")
            if args and Path(os.fsdecode(args[0])).name == "1cv8c" and any(marker_bytes in arg for arg in args):
                os.kill(int(entry.parent.name), 15)
        except (OSError, ValueError):
            pass

def va_manager(cfg, container, env):
    """Создаёт пустую файловую базу менеджера Vanessa, если её нет.

    Правило conf.cfg снимает защиту от опасных действий только с баз, в пути которых
    есть va-manager, поэтому каталог менять нельзя."""
    if cfg.get("vanessa_manager") == "server":
        return
    if not (MANAGER / "1Cv8.1CD").is_file():
        subprocess.run(onec_cmd(cfg, "create", ["File=" + container(MANAGER)]),
                       env=env, stdin=subprocess.DEVNULL, check=True, timeout=300)

# Непересекающиеся порты тестовых клиентов va-mcp и пакетного va, чтобы регрессия
# не подключалась к клиенту интерактивного MCP и не рвала его.
VA_MCP_PORTS = range(48000, 48050)
VA_PORTS = range(48050, 48100)

def va_client(cfg, ports, extra=""):
    """Профиль тестового клиента рабочей базы и диапазон портов для VAParams."""
    # Сценарии и MCP подключаются к клиенту по этому имени, а не по имени базы.
    # Новый клиент Vanessa запускает на свободном порту диапазона, порт профиля
    # она при этом не учитывает: без диапазона оба менеджера берут 48000.
    return {"ДиапазонПортовTestclient": f"{ports.start}-{ports.stop - 1}",
            "ДанныеКлиентовТестирования": [{
                "Имя": "УТ", "Синоним": "УТ", "ТипКлиента": "Тонкий",
                "ПутьКИнфобазе": f'Srvr="{cfg["server"]}";Ref="{cfg["infobase"]}";',
                "ПортЗапускаТестКлиента": ports.start, "ИмяКомпьютера": "localhost",
                "ДопПараметры": f'/N{cfg["user"]} /Lru /VLru' + extra}]}

def va_mcp_url():
    """Адрес MCP Vanessa из сгенерированного agent-kit .mcp.json."""
    servers = json.loads(read_text(ROOT / ".mcp.json"))["mcpServers"]
    if "vanessa" not in servers:
        raise RuntimeError("в agent-kit.json нет сервера vanessa; добавить и выполнить scripts/emit-mcp.sh")
    return urllib.parse.urlsplit(servers["vanessa"]["url"])

def va_mcp_call(url, tool, arguments, timeout=120):
    """Вызов инструмента MCP Vanessa по HTTP (streamable, ответ JSON или SSE)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    def call(method, params, ident=1):
        body = {"jsonrpc": "2.0", "method": method, "params": params} | ({"id": ident} if ident else {})
        request = urllib.request.Request(url.geturl(), json.dumps(body).encode(), headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.headers.get("Mcp-Session-Id"):
                headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
            return response.read()
    call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "onec.py", "version": "1"}})
    call("notifications/initialized", {}, None)
    return call("tools/call", {"name": tool, "arguments": arguments})

def wait_va_mcp_ready(url, log, timeout=45):
    """Порт открывается раньше регистрации команд; проверить реальный read-only вызов."""
    deadline = time.monotonic() + timeout
    last_error = "команды ещё не зарегистрированы"
    while time.monotonic() < deadline:
        try:
            raw = va_mcp_call(url, "manage_test_client_profiles", {"action": "get_list"}, timeout=5)
            payload = raw.decode("utf-8-sig").strip()
            if payload.startswith("{"):
                responses = [json.loads(payload)]
            else:
                responses = [json.loads(line[5:].strip()) for line in payload.splitlines()
                             if line.startswith("data:") and line[5:].strip()]
            if any(isinstance(item, dict) and not item.get("error")
                   and isinstance(item.get("result"), dict) and not item["result"].get("isError")
                   for item in responses):
                return
            last_error = payload[:300]
        except (OSError, ValueError) as error:
            last_error = str(error)
        time.sleep(1)
    raise RuntimeError(f"MCP Vanessa не готов: {last_error}; лог менеджера: {log}")

def run_va_mcp(cfg, container, visible, dry_run, mode):
    """Менеджер Vanessa с MCP для интерактивной работы агента с формами.

    MCP-сервер живёт в сеансе менеджера (расширение client_mcp), поэтому харнес его не
    запускает: менеджер стартует до сессии агента и работает до остановки. manage_test_client
    только подключается к профилю «УТ», поэтому тестовый клиент рабочей базы запускается здесь."""
    url = va_mcp_url()
    params = ROOT / "1c/v8runner/va-mcp.json"
    logs = ROOT / "1c/logs/va-mcp"
    env = dict(os.environ, ONEC_HEADLESS="0" if visible else "1", GDK_BACKEND="x11")
    client = va_client(cfg, VA_MCP_PORTS)
    def start_client():
        subprocess.Popen(onec_cmd(cfg, "thin", [
            "/S" + cfg["server"] + "\\" + cfg["infobase"],
            "/N" + cfg["user"], "/TESTCLIENT", "-TPort", str(VA_MCP_PORTS.start), "/Lru", "/VLru",
            "/DisableStartupDialogs", "/DisableStartupMessages", "/Out", container(logs / "client.log")]),
                         env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **detached())
    if mode in {"stop", "restart-client"}:
        # Убитый клиент оставляет сеанс в кластере, поэтому сначала штатное закрытие.
        try:
            va_mcp_call(url, "close_test_client", {"profileName": "УТ"}, timeout=5)
            time.sleep(5)
        except OSError:
            pass
        kill_clients(container(logs / "client.log"))
        if mode == "restart-client":
            # Открытый клиент не видит загруженное расширение; менеджер и MCP остаются.
            start_client()
            print("Тестовый клиент перезапущен; подключиться заново: manage_test_client connect «УТ»")
            return
        kill_clients(container(logs))
        print("Менеджер и тестовый клиент остановлены")
        return
    # Отметка ставится после загрузки и снятия флагов.
    marker = (ROOT / "1c/v8runner/client_mcp-server.ready" if cfg.get("vanessa_manager") == "server"
              else MANAGER / "client_mcp.ready")
    bootstrap = cfg.get("vanessa_manager") == "server"
    cmd = onec_cmd(cfg, "thin", [
        *va_manager_args(cfg, container), "/TESTMANAGER",
        "/Lru", "/VLru", "/DisableStartupDialogs", "/DisableStartupMessages", "/Out", container(logs / "manager.log"),
        *([] if bootstrap else ["/Execute", container(vanessa_file("epf", download=False)[0])]),
        "/C", ("VANESSA_SERVER_BOOTSTRAP;" if bootstrap else "") + f"QuietInstallVanessaExt;DisableFirstRunHelper;runMcp;mcpPort={url.port};VAParams={container(params)}"])
    if dry_run:
        print(f"ONEC_HEADLESS={env['ONEC_HEADLESS']}", shlex.join(cmd))
        return
    if mode == "start":
        ensure_conf_rule(cfg)
    with socket.socket() as probe:
        if probe.connect_ex((url.hostname, url.port)) == 0:
            raise RuntimeError(f"порт {url.port} занят: менеджер Vanessa уже запущен (этот или другой стенд)")
    vanessa_file("epf")
    va_manager(cfg, container, env)
    logs.mkdir(parents=True, exist_ok=True)
    cfe, sha = vanessa_file("client_mcp")
    if not marker.is_file() or marker.read_text().strip() != sha:
        log = logs / "extension.log"
        log.write_text("")
        subprocess.run(onec_cmd(cfg, "designer", [
            *va_manager_args(cfg, container), "/DisableStartupDialogs",
            "/LoadCfg", container(cfe), "-Extension", "client_mcp", "/UpdateDBCfg", "/Out", container(log)]),
                       env=dict(env, ONEC_HEADLESS="1"), stdin=subprocess.DEVNULL, check=True, timeout=300)
        if re.search(r"\b(error|ошибка)\b", log.read_text(encoding="utf-8-sig", errors="replace"), re.I):
            raise RuntimeError(f"client_mcp не загружен в базу менеджера: {log}")
        # Конфигуратор загружает расширение в безопасном режиме, и client_mcp не может создать
        # Файл: падают открытие .feature, шаги и скриншоты. Снимает флаги только ibcmd.
        run_ibcmd(cfg, ["update", "--name=client_mcp", "--safe-mode=no", "--unsafe-action-protection=no"],
                  None if cfg.get("vanessa_manager") == "server" else MANAGER)
        marker.write_text(sha + "\n")
    params.write_text(json.dumps({
        "ИспользоватьКомпонентуVanessaExt": True, "ИскатьЭлементыФормыПоИмени": True,
        "ИспользоватьРедакторVanessaEditor": False,
        "ТаймаутЗапуска1С": 120,
        "ДелатьОтчетВФорматеjUnit": True,
        "КаталогВыгрузкиJUnit": container(logs / "junit"),
        "ДелатьЛогВыполненияСценариевВТекстовыйФайл": True,
        "ИмяФайлаЛогВыполненияСценариев": container(logs / "steps.log"),
        "ДелатьСкриншотПриВозникновенииОшибки": True,
        "ИспользоватьВнешнююКомпонентуДляСкриншотов": True,
        "СпособСнятияСкриншотовВнешнейКомпонентой": 1,
        "КаталогВыгрузкиСкриншотов": container(logs / "screenshots"),
        # Явно задаём интерактивный режим, чтобы он не зависел от сохранённых
        # настроек предыдущего пакетного запуска в той же базе менеджера.
        "ВыполнитьСценарии": False, "ЗавершитьРаботуСистемы": False,
        "ЗакрытьTestClientПослеЗапускаСценариев": False} | client,
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    start_client()
    if windows():
        # execvpe на Windows не экранирует аргументы с пробелами в пути проекта.
        subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, **detached())
        wait_va_mcp_ready(url, logs / "manager.log", timeout=180)
        print(f"MCP Vanessa готов: {url.geturl()}; профиль тестового клиента «УТ». Остановка — va-mcp --stop.", flush=True)
    else:
        print(f"Запуск MCP Vanessa: {url.geturl()}; профиль «УТ». Остановка — va-mcp --stop.", flush=True)
        os.execvpe(cmd[0], cmd, env)

def run_va(cfg, feature, container):
    """Сценарии Vanessa: менеджер в пустой файловой базе, тестовый клиент — в рабочей.

    v8-runner запускает менеджер в самой базе, где стартовые окна УТ не дают открыться
    обработке; отдельный менеджер этого не знает."""
    if not feature.exists():
        raise RuntimeError(f"нет сценариев: {feature}")
    ensure_conf_rule(cfg)
    epf = vanessa_file("epf")[0]
    env = dict(os.environ, ONEC_HEADLESS="1", GDK_BACKEND="x11")
    va_manager(cfg, container, env)
    reports = ROOT / "1c/logs/vanessa"
    reports.mkdir(parents=True, exist_ok=True)
    report = Path(tempfile.mkdtemp(prefix="run-", dir=reports))
    params = {
        "КаталогФич": container(feature), "ВыполнитьСценарии": True, "ЗавершитьРаботуСистемы": True,
        "ИспользоватьКомпонентуVanessaExt": True, "ТаймаутЗапуска1С": 120,
        "ДелатьСкриншотПриВозникновенииОшибки": True, "ИспользоватьВнешнююКомпонентуДляСкриншотов": True,
        # 1 = снимок окон процесса клиента тестирования: работает при заблокированном экране стенда.
        "СпособСнятияСкриншотовВнешнейКомпонентой": 1,
        "ДелатьОтчетВФорматеjUnit": True, "КаталогВыгрузкиJUnit": container(report),
        "ВыгружатьСтатусВыполненияСценариевВФайл": True,
        "ПутьКФайлуДляВыгрузкиСтатусаВыполненияСценариев": container(report / "status.txt"),
        "ДелатьЛогВыполненияСценариевВТекстовыйФайл": True,
        "ИмяФайлаЛогВыполненияСценариев": container(report / "steps.log"),
        "КаталогВыгрузкиСкриншотов": container(report / "screenshots"),
        "ЗакрытьTestClientПослеЗапускаСценариев": True,
    } | va_client(cfg, VA_PORTS, f' /Out "{container(report / "client.log")}"')
    (report / "VAParams.json").write_text(json.dumps(params, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bootstrap = cfg.get("vanessa_manager") == "server"
    cmd = onec_cmd(cfg, "thin", [
        *va_manager_args(cfg, container), "/TESTMANAGER",
        "/Lru", "/VLru", "/DisableStartupDialogs", "/DisableStartupMessages",
        "/Out", container(report / "manager.log"), *([] if bootstrap else ["/Execute", container(epf)]),
        "/C", ("VANESSA_SERVER_BOOTSTRAP;" if bootstrap else "") + "StartFeaturePlayer;QuietInstallVanessaExt;DisableFirstRunHelper;VAParams=" + container(report / "VAParams.json")])
    print("Отчёт:", report, flush=True)
    try:
        subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, stdout=sys.stderr, check=True, timeout=900)
    finally:
        kill_clients(container(report))
    status = (report / "status.txt").read_text(encoding="utf-8-sig").strip() if (report / "status.txt").exists() else ""
    cases = [case for xml in report.glob("*.xml") for case in ET.parse(xml).iter("testcase")]
    failed = [case.get("name") for case in cases if any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))]
    for case in cases:
        print(("✗ " if case.get("name") in failed else "✓ ") + str(case.get("name")))
    if status != "0" or not cases or failed:
        raise RuntimeError(f"сценарии не прошли (статус {status or 'нет'}, сценариев {len(cases)}): {report}")
    print(f"Готово; сценариев: {len(cases)}")

def db_password(cfg):
    db = cfg.get("dbms") or {}
    env_name = db.get("password_env")
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    local = ROOT / "stand.local.json"
    if local.is_file():
        stored = json.loads(read_text(local)).get("dbms", {}).get("password")
        if stored:
            return stored
    return None

def mask_password(cmd, cfg):
    password = db_password(cfg)
    if not password:
        return cmd
    hidden = "--db-pwd=" + password
    return ["--db-pwd=***" if part == hidden else part for part in cmd]

def ibcmd(cfg, args, file_base=None):
    """ibcmd для управления расширениями базы.

    С file_base — файловая база без пользователей вместо рабочей.
    Пользователя ИБ принимает только форма `config extension`; `extension` его не знает.
    На Windows без dbms.user используется проверка подлинности Windows."""
    if windows():
        binary = platform_bin(cfg) / "ibcmd.exe"
        if not binary.is_file():
            raise RuntimeError(f"нет ibcmd: {binary}")
    else:
        rac_path = shutil.which("onec-rac")
        if not rac_path:
            raise RuntimeError("нет onec-rac: серверная платформа не установлена (.agents/skills/onec-development/references/setup.md)")
        binary = Path(os.path.realpath(rac_path)).parent / "ibcmd"
    db = cfg["dbms"]
    if file_base:
        target = ["--db-path=" + str(file_base)]
    else:
        target = ["--dbms=" + db["kind"], "--db-server=" + db["server"], "--db-name=" + db["name"]]
        if db.get("user"):
            target.append("--db-user=" + db["user"])
        password = db_password(cfg)
        if password:
            target.append("--db-pwd=" + password)
        target.append("--user=" + cfg["user"])
    return [str(binary), "config", "extension", *args[:1], *target, *args[1:]]

def run_ibcmd(cfg, args, file_base=None):
    with tempfile.TemporaryDirectory() as data:
        # Без stdin ibcmd бесконечно переспрашивает недостающие учётные данные.
        return subprocess.run(ibcmd(cfg, args, file_base) + ["--data=" + data], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8", check=True, timeout=300).stdout

def clear_extension_safety(cfg, extension):
    """Снимает безопасный режим и защиту от опасных действий.

    Конфигуратор включает обе галки при каждой полной загрузке расширения.
    """
    run_ibcmd(cfg, ["update", "--name=" + extension, "--safe-mode=no", "--unsafe-action-protection=no"])

def cluster_sessions(cfg):
    """Сеансы целевой базы: (кластер, описание базы, текст списка сеансов)."""
    if windows():
        ensure_ras(cfg)
        rac = [str(platform_bin(cfg) / "rac.exe"), cfg.get("ras", "localhost:1545")]
        decode = {"encoding": "cp866", "errors": "replace"}  # rac.exe пишет в OEM-кодировке консоли
    else:
        rac = ["onec-rac"]
        decode = {"encoding": "utf-8", "errors": "replace"}
    clusters = subprocess.check_output(rac + ["cluster", "list"], timeout=60, **decode)
    ids = re.findall(r"^cluster\s*:\s*(\S+)", clusters, re.M)
    if len(ids) != 1:
        raise RuntimeError("нужен однозначный локальный кластер")
    bases = subprocess.check_output(rac + ["infobase", "summary", "list", "--cluster=" + ids[0]], timeout=60, **decode)
    match = [b for b in bases.split("\n\n") if re.search(r"^name\s*:\s*" + re.escape(cfg["infobase"]) + r"\s*$", b, re.M)]
    if len(match) != 1:
        raise RuntimeError("целевая база не найдена однозначно")
    ib = re.search(r"^infobase\s*:\s*(\S+)", match[0], re.M).group(1)
    sessions = subprocess.check_output(
        rac + ["session", "list", "--cluster=" + ids[0], "--infobase=" + ib], timeout=60, **decode)
    return ids[0], match[0], sessions

def doctor(cfg, container):
    """Проверяет готовность стенда без изменений и называет команду для каждой проблемы.

    Причины граблей и порядок развёртывания — .agents/skills/onec-development/references/setup.md."""
    problems = 0
    def report(ok, what, fix=""):
        nonlocal problems
        problems += not ok
        print(("✓ " if ok else "✗ ") + what + ("" if ok else f" → {fix}"), flush=True)
    onec = "python scripts/onec.py"
    report((ROOT / "1c/config/Configuration.xml").is_file(), "выгрузка типовой для поиска", f"{onec} dump-config")
    report((ROOT / "1c/v8runner/main/Configuration.xml").is_file(), "замороженная копия типовой для v8-runner",
           "cp -a 1c/config 1c/v8runner/main, затем первая сборка (.agents/skills/onec-development/references/setup.md)")
    report((ROOT / "1c/v8runner/build/hash-storages/designer-main.redb").is_file(), "кэш сборки типовой",
           f"{onec} v8 build --source-set main (полная загрузка типовой, долго)")
    pin, _, binary = runner_artifact()
    report(binary.is_file(), "v8-runner закреплённой версии",
           f"скачается при первом {onec} v8 ...")
    overlay = ROOT / "v8project.local.yaml"
    connection = connection_of(cfg)
    report(not overlay.exists() or re.search(r'^\s+connection:\s*"?' + re.escape(connection) + r'"?\s*$',
           read_text(overlay), re.M) is not None, "v8project.local.yaml совпадает со stand.json",
           f"исправить connection на {connection}")
    running = False
    try:
        url = va_mcp_url()
        with socket.socket() as probe:
            probe.settimeout(2)
            running = probe.connect_ex((url.hostname, url.port)) == 0
        # Не ошибка: менеджер нужен только для интерактивной работы с формами.
        print(("· " if not running else "✓ ") + f"MCP Vanessa {url.geturl()}"
              + ("" if running else f" не запущен; для работы с формами: {onec} va-mcp"), flush=True)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        report(False, "MCP Vanessa в agent-kit", str(exc))
    if (MANAGER / "client_mcp.ready").is_file() and not running:
        # База-менеджер занята, пока менеджер запущен; флаги читаются только на остановленном.
        try:
            block = run_ibcmd(cfg, ["list"], MANAGER)
            report(re.search(r"^safe-mode\s*:\s*no", block, re.M) is not None
                   and re.search(r"^unsafe-action-protection\s*:\s*no", block, re.M) is not None,
                   "client_mcp в базе-менеджере: безопасный режим и защита сняты",
                   ".agents/skills/onec-development/references/setup.md, «Ошибка при вызове конструктора (Файл)»")
        except (OSError, subprocess.SubprocessError) as exc:
            report(False, "расширения базы-менеджера через ibcmd", str(exc))
    conf = conf_text(cfg)
    report(re.search(r"^DisableUnsafeActionProtection=.*va-manager", conf, re.M) is not None,
           "conf.cfg снимает защиту с базы-менеджера Vanessa",
           ".agents/skills/onec-development/references/setup.md: строка DisableUnsafeActionProtection для va-manager")
    if windows():
        help_ok = (platform_bin(cfg) / "shcntx_ru.hbk").is_file()
    else:
        mcp = ROOT / ".mcp.json"
        help_dirs = re.findall(r"platform-help/([\d.]+)", read_text(mcp) if mcp.exists() else "")
        help_ok = bool(help_dirs) and (Path.home() / ".local/share/erp-stand/platform-help" / help_dirs[0] / "shcntx_ru.hbk").is_file()
    report(help_ok, "справка платформы для bsl-platform",
           "shcntx_ru.hbk лежит в bin установленной платформы (.agents/skills/onec-development/references/setup.md)")
    try:
        cluster, _, sessions = cluster_sessions(cfg)
        ids = re.findall(r"^session\s*:\s*(\S+)", sessions, re.M)
        # Тестовый клиент va-mcp держит один сеанс, пока MCP Vanessa запущен.
        allowed = (2 if cfg.get("vanessa_manager") == "server" else 1) if running else 0
        report(len(ids) <= allowed, f"нет посторонних сеансов базы ({len(ids)}, допустимо для клиента va-mcp — {allowed})",
               f"закрыть клиенты; только свой или согласованный сеанс без процесса: {onec} close-session --session=<UUID> --apply")
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        report(False, "кластер и база доступны", f"{exc}; проверить службу агента сервера и stand.json")
    try:
        listing = run_ibcmd(cfg, ["list"])
        extensions = {re.search(r'^name\s*:\s*"(.*)"', block, re.M).group(1): block
                      for block in listing.split("\n\n") if re.search(r"^name\s*:", block, re.M)}
    except (OSError, subprocess.SubprocessError, AttributeError, RuntimeError) as exc:
        extensions = None
        report(False, "список расширений через ibcmd", f"{exc}; проверить stand.json dbms и доступ роли к БД")
    if extensions is not None:
        report("YAXUNIT" in extensions, "YAxUnit загружен",
               f"{onec} v8 tools download yaxunit; {onec} load-extension --extension YAXUNIT --path build/tools/<YAxUnit>.cfe --apply")
        va_extension_path, _ = vanessa_file("extension", download=False)
        report("VAExtension" in extensions, "VAExtension для чтения данных через MCP загружен",
               f"{onec} download-va-extension; {onec} load-extension --extension VAExtension --path {va_extension_path.relative_to(ROOT).as_posix()} --apply")
        wanted = re.findall(r"- name: (\S+)\s+type: EXTENSION", read_text(ROOT / "v8project.yaml"))
        for name in wanted:
            report(name in extensions, f"расширение {name} из v8project.yaml загружено", f"{onec} v8 build")
        for name, block in extensions.items():
            unsafe = re.search(r"^safe-mode\s*:\s*no", block, re.M) and re.search(r"^unsafe-action-protection\s*:\s*no", block, re.M)
            report(bool(unsafe), f"{name}: безопасный режим и защита сняты",
                   f"{onec} unsafe-extension --extension {name} --apply")
    if problems:
        raise RuntimeError(f"проблем: {problems}")
    print("Стенд готов")

def cli():
    if windows():
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["preflight", "close-session", "open", "designer", "check", "dump-config", "load-extension", "dump-extension", "export-extension", "dump-ib", "restore-ib", "unsafe-extension", "va", "va-mcp", "download-va-extension", "doctor", "v8", "build-external", "dump-external"])
    p.add_argument("--output", type=Path, help="Выходной EPF для build-external или XML для dump-external")
    p.add_argument("--session", help="UUID согласованного сеанса для close-session")
    p.add_argument("--extension", help="Имя расширения")
    p.add_argument("--path", type=Path, help="Каталог XML или файл артефакта")
    p.add_argument("--objects", nargs="+", help="dump-config: полные имена выбранных объектов метаданных")
    p.add_argument("--apply", action="store_true", help="Выполнить изменение базы")
    p.add_argument("--dry-run", action="store_true", help="Показать команду без запуска")
    p.add_argument("--visible", action="store_true", help="va-mcp: видимое окно вместо виртуального дисплея")
    p.add_argument("--stop", action="store_true", help="va-mcp: остановить менеджер и тестовый клиент")
    p.add_argument("--restart-client", action="store_true", help="va-mcp: перезапустить только тестовый клиент")
    p.epilog = "v8 [--dry-run] <аргументы v8-runner> — запуск v8-runner, например: v8 test yaxunit <ИмяРасширения>"
    argv = sys.argv[1:]
    if argv[:1] == ["v8"]:
        dry_run = argv[1:2] == ["--dry-run"]
        args = argv[2:] if dry_run else argv[1:]
        if not args:
            p.error("нужны аргументы v8-runner")
        v8_runner(settings(), args, dry_run)
        return
    a = p.parse_args()
    cfg = settings()
    if a.action == "dump-external":
        if not a.path or not a.output:
            p.error("dump-external требует --path <EPF> --output <новый XML>")
        source, output = a.path.resolve(), a.output.resolve()
        if not source.is_file() or source.suffix.lower() != ".epf" or output.suffix.lower() != ".xml":
            p.error("нужны существующий EPF и выходной XML")
        if not source.is_relative_to(ROOT) or not output.is_relative_to(ROOT):
            p.error("файлы обработки должны находиться в проекте")
        if output.exists() or output.with_suffix("").exists():
            p.error("выходной XML или каталог уже существует")
        log = ROOT / "1c/logs/dump-external.log"
        cmd = onec_cmd(cfg, "designer", ["/S" + cfg["server"] + "\\" + cfg["infobase"],
            "/N" + cfg["user"], "/Lru", "/DisableStartupDialogs", "/DisableStartupMessages",
            "/DumpExternalDataProcessorOrReportToFiles", str(output), str(source), "/Out", str(log)])
        if a.dry_run:
            print(shlex.join(cmd))
            return
        output.parent.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        subprocess.run(cmd, check=True, timeout=180)
        details = log.read_text(encoding="utf-8-sig", errors="replace")
        if re.search(r"\b(error|ошибка)\b", details, re.I):
            raise RuntimeError(f"Ошибка выгрузки EPF; журнал: {log}")
        if not output.is_file() or not output.stat().st_size:
            raise RuntimeError(f"XML не создан; журнал: {log}")
        print(f"Выгружено: {output}; журнал: {log}")
        return
    if a.action == "build-external":
        if not a.path or not a.output:
            p.error("build-external требует --path <XML> и --output <EPF>")
        source, output = a.path.resolve(), a.output.resolve()
        if not source.is_file() or output.suffix.lower() != ".epf":
            p.error("нужны существующий XML обработки и выходной .epf")
        if not source.is_relative_to(ROOT) or not output.is_relative_to(ROOT):
            p.error("файлы обработки должны находиться в проекте")
        if ET.parse(source).getroot().find("{*}ExternalDataProcessor") is None:
            p.error("XML не является внешней обработкой")
        log = ROOT / "1c/logs/build-external.log"
        cmd = onec_cmd(cfg, "designer", ["/S" + cfg["server"] + "\\" + cfg["infobase"],
            "/N" + cfg["user"], "/Lru", "/DisableStartupDialogs", "/DisableStartupMessages",
            "/LoadExternalDataProcessorOrReportFromFiles", str(source), str(output), "/Out", str(log)])
        if a.dry_run:
            print(shlex.join(cmd))
            return
        output.parent.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="external-", dir=output.parent) as temp_dir:
            candidate = Path(temp_dir) / output.name
            cmd[cmd.index(str(output))] = str(candidate)
            subprocess.run(cmd, check=True, timeout=180)
            details = log.read_text(encoding="utf-8-sig", errors="replace")
            if re.search(r"\b(error|ошибка)\b", details, re.I):
                raise RuntimeError(f"Ошибка сборки EPF; журнал: {log}")
            if not candidate.is_file() or not candidate.stat().st_size:
                raise RuntimeError(f"EPF не создан; журнал: {log}")
            candidate.replace(output)
        print(f"Собрано: {output}; журнал: {log}")
        return
    if a.action == "download-va-extension":
        artifact, digest = vanessa_file("extension", download=not a.dry_run)
        print("VAExtension:", artifact)
        print("SHA-256:", digest)
        return
    if a.action == "close-session":
        if not a.session or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", a.session):
            p.error("нужно --session с UUID сеанса")
        if not (a.apply or a.dry_run):
            p.error("закрытие согласованного сеанса требует --apply")
        cluster, _, sessions = cluster_sessions(cfg)
        if a.session not in re.findall(r"^session\s*:\s*(\S+)", sessions, re.M):
            p.error("сеанс не найден в целевой базе stand.json")
        rac = [str(platform_bin(cfg) / "rac.exe"), cfg.get("ras", "localhost:1545")] if windows() else ["onec-rac"]
        cmd = rac + ["session", "terminate", "--cluster=" + cluster, "--session=" + a.session]
        if a.dry_run:
            print(shlex.join(cmd))
        else:
            subprocess.run(cmd, check=True, timeout=60)
            print("Сеанс закрыт:", a.session)
        return
    if a.extension and not re.fullmatch(r"[\w]+", a.extension):
        p.error("недопустимое имя расширения")
    extension_actions = {"load-extension", "dump-extension", "export-extension"}
    if a.action in extension_actions | {"unsafe-extension"} and not a.extension:
        p.error("нужно --extension")
    if a.action in extension_actions | {"dump-ib", "restore-ib"} and a.path is None:
        p.error("нужно --path")
    if a.action in {"load-extension", "restore-ib", "unsafe-extension"} and not (a.apply or a.dry_run):
        p.error("изменение базы требует --apply")
    target = a.path.resolve() if a.path else ROOT / "1c/config"
    def container(path):
        return host_path(cfg, path)
    if a.action == "preflight":
        if a.dry_run:
            print("Цель:", cfg["server"], cfg["infobase"])
            return
        _, base, sessions = cluster_sessions(cfg)
        print(base, sessions, sep="\n")
        return
    if a.action == "va":
        run_va(cfg, a.path.resolve() if a.path else ROOT / "1c/vanessa/features", container)
        return
    if a.action == "va-mcp":
        run_va_mcp(cfg, container, a.visible, a.dry_run,
                   "stop" if a.stop else "restart-client" if a.restart_client else "start")
        return
    if a.action == "doctor":
        doctor(cfg, container)
        return
    if a.action == "unsafe-extension":
        # Конфигуратор и v8-runner загружают расширения в безопасном режиме, а YAxUnit и
        # регламент поставки требуют его отключить; это умеет только ibcmd.
        args = ["update", "--name=" + a.extension, "--safe-mode=no", "--unsafe-action-protection=no"]
        if a.dry_run:
            shown = ibcmd(cfg, args)
            print(shlex.join(mask_password(shown, cfg)))
            return
        clear_extension_safety(cfg, a.extension)
        print("Готово")
        return
    cmd = onec_cmd(cfg, "thin" if a.action == "open" else "designer", [])
    cmd += ["/S" + cfg["server"] + "\\" + cfg["infobase"], "/N" + cfg["user"], "/Lru", "/DisableStartupDialogs", "/DisableStartupMessages"]
    if a.action == "check":
        cmd += ["/CheckCanApplyConfigurationExtensions"]
    elif a.action in {"dump-config", "dump-extension"}:
        cmd += ["/DumpConfigToFiles", container(target), "-Format", "Hierarchical"]
        if a.action == "dump-extension":
            cmd += ["-Extension", a.extension]
        if a.objects:
            if a.action != "dump-config" or not a.path or target in {ROOT / "1c/config", ROOT / "1c/v8runner/main"}:
                p.error("--objects требует dump-config и отдельный --path")
            object_list = ROOT / "1c/tmp" / ("dump-objects-" + str(time.time_ns()) + ".txt")
            object_list.parent.mkdir(parents=True, exist_ok=True)
            object_list.write_text("\n".join(a.objects) + "\n", encoding="utf-8")
            cmd += ["-listFile", container(object_list)]
    elif a.action == "load-extension" and target.suffix == ".cfe":
        # Готовая поставка стороннего расширения; совместимость задал её автор.
        if not target.is_file():
            p.error("файл расширения не найден")
        cmd += ["/LoadCfg", container(target), "-Extension", a.extension, "/UpdateDBCfg"]
    elif a.action == "load-extension":
        if not target.is_dir():
            p.error("загрузка принимает каталог XML или файл .cfe; совместимость XML проверяется до запуска")
        root = ET.parse(target / "Configuration.xml").getroot()
        props = root.find("{*}Configuration/{*}Properties")
        if props is None or props.findtext("{*}Name") != a.extension:
            p.error("имя в XML не совпадает с --extension")
        if props.findtext("{*}ConfigurationExtensionCompatibilityMode") != cfg["compatibility"]:
            p.error("совместимость расширения не совпадает со stand.json")
        cmd += ["/LoadConfigFromFiles", container(target), "-Format", "Hierarchical", "-Extension", a.extension, "/UpdateDBCfg"]
    elif a.action == "export-extension":
        cmd += ["/DumpCfg", container(target), "-Extension", a.extension]
    elif a.action in {"dump-ib", "restore-ib"}:
        if a.action == "restore-ib" and not target.is_file():
            p.error("снимок не найден")
        cmd += ["/DumpIB" if a.action == "dump-ib" else "/RestoreIB", container(target)]
    log = ROOT / "1c/logs" / (a.action + ".log")
    if a.action not in {"open", "designer"}:
        cmd += ["/Out", container(log)]
    if a.dry_run:
        print(shlex.join(cmd))
        return
    env = os.environ.copy()
    env["ONEC_HEADLESS"] = "0" if a.action in {"open", "designer"} else "1"
    if a.action in {"dump-config", "dump-extension"}:
        target.mkdir(parents=True, exist_ok=True)
    elif a.action in {"export-extension", "dump-ib"}:
        if target.exists():
            p.error("выходной файл уже существует; выберите новое имя")
        target.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    if a.action not in {"open", "designer"}:
        log.write_text("")
    subprocess.run(cmd, env=env, check=True)
    if a.action in {"open", "designer"}:
        return
    text = log.read_text(encoding="utf-8-sig", errors="replace")
    if re.search(r"\b(error|ошибка)\b", text, re.I):
        raise RuntimeError(f"Ошибка Designer: {log}")
    if a.action in {"dump-config", "dump-extension"}:
        if a.objects and not (target / "ConfigDumpInfo.xml").exists():
            # Выгрузка корневых объектов по listFile не всегда создаёт ConfigDumpInfo.
            folders = {"DefinedType": "DefinedTypes", "ChartOfCharacteristicTypes": "ChartsOfCharacteristicTypes",
                       "ChartOfAccounts": "ChartsOfAccounts", "ChartOfCalculationTypes": "ChartsOfCalculationTypes"}
            for object_name in a.objects:
                kind, name, *children = object_name.split(".")
                path = target / folders.get(kind, kind + "s") / (name + ".xml")
                if len(children) == 2 and children[0] in {"Form", "Template", "Command"}:
                    path = path.with_suffix("") / (children[0] + "s") / (children[1] + ".xml")
                ET.parse(path)
        else:
            ET.parse(target / ("ConfigDumpInfo.xml" if a.objects else "Configuration.xml"))
    if a.action in {"dump-ib", "export-extension"} and (not target.exists() or target.stat().st_size == 0):
        raise RuntimeError("не создан выходной файл")
    if a.action == "load-extension":
        clear_extension_safety(cfg, a.extension)
        print("Безопасный режим и защита от опасных действий сняты")
    print(f"Готово; лог: {log}")

if __name__ == "__main__":
    try:
        cli()
    except (OSError, ValueError, ET.ParseError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
