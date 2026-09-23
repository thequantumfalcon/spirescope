"""Exercise a distributed executable against disposable data and state only."""
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def qualify(executable: Path, dataset: Path, work: Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    live, candidate, state = (work / name for name in ("live", "candidate", "state"))
    shutil.copytree(dataset, live)
    shutil.copytree(dataset, candidate)
    state.mkdir()
    sentinel = state / "settings.json"
    sentinel.write_text('{"qualification_sentinel":true}', encoding="utf-8")
    env = {**os.environ, "STS2_DATA_DIR": str(live), "STS2_STATE_DIR": str(state),
           "STS2_SAVE_DIR": str(work / "no-saves"), "STS2_GAME_DIR": str(work / "no-game"),
           "STS2_MODS_DIR": str(work / "no-mods"), "STS2_LOG_FILE": str(work / "no-log"),
           "STS2_HOST": "127.0.0.1", "STS2_LANG": "en", "STS2_SYNC_URL": "",
           "SPIRESCOPE_OPEN_BROWSER": "0", "SPIRESCOPE_CHECK_UPDATES": "0"}
    results = {}

    def run(*args, expected=0):
        result = subprocess.run([str(executable), *map(str, args)], env=env,
                                cwd=work, capture_output=True, text=True, timeout=120)
        if result.returncode != expected:
            raise RuntimeError(f"{args[0]} returned {result.returncode}: {result.stdout[-1000:]} {result.stderr[-1000:]}")
        return result

    def bundle():
        archive = work / "fixture.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(candidate, arcname="data")
        checksum = work / "fixture.sha256"
        checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "  fixture.tar.gz\n")
        return archive, checksum

    results["version"] = run("--version").stdout.strip()
    run("validate-data", live)
    results["validate_good"] = True
    cards = json.loads((candidate / "cards.json").read_text(encoding="utf-8"))
    cards[0]["description"] = "Artifact qualification fixture."
    (candidate / "cards.json").write_text(json.dumps(cards), encoding="utf-8")
    archive, checksum = bundle()
    run("install-data", archive, "--sha256", checksum)
    installed = (live / "cards.json").read_bytes()
    assert json.loads(installed)[0]["description"] == "Artifact qualification fixture."
    results["install_good"] = True
    checksum.write_text("0" * 64)
    run("install-data", archive, "--sha256", checksum, expected=1)
    assert (live / "cards.json").read_bytes() == installed
    results["reject_checksum"] = True
    (candidate / "potions.json").write_text("[]")
    archive, checksum = bundle()
    run("validate-data", candidate, expected=1)
    run("install-data", archive, "--sha256", checksum, expected=1)
    assert (live / "cards.json").read_bytes() == installed
    results["reject_invalid_dataset"] = True
    # Reproduce the actual interrupted-swap boundary, then start the app.
    backup = live.with_name(live.name + ".backup")
    assert backup.resolve().is_relative_to(work.resolve())
    if backup.exists():
        shutil.rmtree(backup)
    live.rename(backup)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env["STS2_PORT"] = str(port)
    started = time.monotonic()
    with (work / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(executable), "serve", "--no-browser"], cwd=work,
            env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            base = f"http://127.0.0.1:{port}"
            while True:
                try:
                    with urllib.request.urlopen(base + "/ready", timeout=1) as response:
                        assert response.status == 200
                        break
                except (urllib.error.URLError, OSError):
                    if process.poll() is not None or time.monotonic() - started > 20:
                        raise RuntimeError("Artifact did not become ready; inspect server.log") from None
                    time.sleep(0.1)
            results["ready_seconds"] = round(time.monotonic() - started, 3)
            for path in ("/cards", "/settings", "/docs", "/deck", "/static/swagger/init.js"):
                with urllib.request.urlopen(base + path, timeout=10) as response:
                    assert response.status == 200
            assert (live / "cards.json").read_bytes() == installed
            results["restart_recovers_interrupted_swap"] = True
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    assert sentinel.read_text() == '{"qualification_sentinel":true}'
    results["user_state_preserved"] = True
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="spirescope-artifact-") as scratch:
        results = qualify(options.executable.resolve(), options.dataset.resolve(), Path(scratch))
    options.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
