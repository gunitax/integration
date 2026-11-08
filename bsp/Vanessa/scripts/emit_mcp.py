"""Генерация MCP-конфигов Windows из agent-kit.json и текущего пути проекта."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def executable(name, previous, candidates=()):
    options = [previous, shutil.which(name), *map(str, candidates)]
    for option in options:
        if option and Path(option).is_file():
            return str(Path(option).resolve())
    raise ValueError(f"Не найден {name}; установите его или добавьте в PATH")


def specifications(root):
    enabled = read_json(root / "agent-kit.json")
    previous = read_json(root / ".mcp.json").get("mcpServers", {})
    unknown = set(enabled) - {"bsl-platform", "context7", "v8-runner", "vanessa"}
    if unknown:
        raise ValueError(f"Неизвестные MCP: {sorted(unknown)}")
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    specs = {}
    for name in enabled:
        old = previous.get(name, {})
        options = enabled[name] if isinstance(enabled, dict) else {}
        if name == "context7" and options.get("url"):
            specs[name] = {"url": options["url"]}
            continue
        if name == "bsl-platform":
            java = executable("java", old.get("command"),
                              (local / "Programs").glob("temurin*/**/bin/java.exe"))
            jar = root / "build/tools/mcp-bsl-context-0.3.2.jar"
            platform = Path(read_json(root / "stand.json")["platform"]) / "bin"
            old_args = old.get("args", [])
            if "--platform-path" in old_args:
                i = old_args.index("--platform-path") + 1
                if i < len(old_args) and Path(old_args[i]).exists():
                    # Сохраняем рабочий короткий Windows-путь к справке.
                    platform = Path(old_args[i])
            if not jar.is_file() or not (platform / "shcntx_ru.hbk").is_file():
                raise ValueError("Не найдены JAR bsl-platform или справка платформы")
            specs[name] = {"command": java, "args": ["-Dfile.encoding=UTF-8", "-jar",
                           str(jar), "--platform-path", str(platform)]}
        elif name == "context7":
            node = executable("node", old.get("command"),
                              (local / "Microsoft/WinGet/Packages").glob("OpenJS.NodeJS*/**/node.exe"))
            entry = root / "build/tools/context7/node_modules/@upstash/context7-mcp/dist/index.js"
            if not entry.is_file():
                raise ValueError("Не установлен локальный context7")
            specs[name] = {"command": node, "args": [str(entry)]}
        elif name == "v8-runner":
            specs[name] = {"command": sys.executable,
                           "args": ["-X", "utf8", str(root / "scripts/onec.py"), "v8", "mcp", "serve", "stdio"]}
        else:
            specs[name] = {"url": old.get("url", "http://127.0.0.1:9874/mcp")}
    return specs


def toml_value(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(k, ensure_ascii=False) + " = " + toml_value(v)
                                 for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def outputs(root, specs):
    def without_transport(entry, spec):
        obsolete = {"command", "args", "env", "env_vars"} if "url" in spec else {"url"}
        return {k: v for k, v in entry.items() if k not in obsolete}
    result = {}
    for relative in (".mcp.json", ".cursor/mcp.json"):
        document = read_json(root / relative)
        old = document.get("mcpServers", {})
        document["mcpServers"] = {name: {**without_transport(old.get(name, {}), spec), **spec} for name, spec in specs.items()}
        result[relative] = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    for relative, zcode in ((".zcode/config.json", True), ("opencode.json", False)):
        document = read_json(root / relative)
        if not zcode:
            document.setdefault("$schema", "https://opencode.ai/config.json")
        container = document.setdefault("mcp", {})
        old = container.get("servers", {}) if zcode else container
        servers = {}
        for name, spec in specs.items():
            entry = without_transport(old.get(name, {}), spec)
            entry.setdefault("enabled", True)
            entry.setdefault("timeoutMs" if zcode else "timeout", 120000 if name in ("bsl-platform", "v8-runner") else 30000)
            if "url" in spec:
                entry.update(type="http" if zcode else "remote", **spec)
            elif zcode:
                entry.update(type="stdio", **spec)
            else:
                entry.update(type="local", command=[spec["command"], *spec["args"]])
            servers[name] = entry
        if zcode:
            container["servers"] = servers
        else:
            document["mcp"] = servers
        result[relative] = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    path = root / ".codex/config.toml"
    original = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    previous = tomllib.loads(original).get("mcp_servers", {})
    # Не затрагиваем остальные настройки Codex; серверные секции генерируются целиком.
    remainder = re.sub(r"(?ms)^\[mcp_servers\.[^\n]+\]\s*\n.*?(?=^\[|\Z)", "", original).strip()
    sections = [remainder] if remainder else []
    for name, spec in specs.items():
        entry = without_transport(previous.get(name, {}), spec)
        entry.update(spec)
        entry.setdefault("enabled", True)
        entry.setdefault("startup_timeout_sec", 120 if name in ("bsl-platform", "v8-runner") else 30)
        entry.setdefault("tool_timeout_sec", {"v8-runner": 3600, "vanessa": 180}.get(name, 60))
        if name == "context7" and "url" not in spec:
            entry.setdefault("env_vars", ["CONTEXT7_API_KEY"])
        lines = [f"[mcp_servers.{name}]"]
        for key, value in entry.items():
            encoded = toml_value(value)
            lines.append(f"{key} = {encoded}")
        sections.append("\n".join(lines))
    result[".codex/config.toml"] = "\n\n".join(sections) + "\n"
    tomllib.loads(result[".codex/config.toml"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Проверить без записи")
    args = parser.parse_args()
    generated = outputs(ROOT, specifications(ROOT))
    changed = []
    for relative, text in generated.items():
        path = ROOT / relative
        if not path.exists() or path.read_text(encoding="utf-8-sig") != text:
            changed.append(relative)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    print("MCP: " + (", ".join(changed) if changed else "конфиги актуальны"))
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    sys.exit(main())
