#!/usr/bin/env python3
"""Build the minimal tree-sitter vendor directory for rtok.

Runs rtok's `scripts/grammars.py fetch` in an rtok checkout, then copies only what rtok's
libs/treesitter-native build compiles (found with `cc -MM`), one license per upstream repo,
the pre-generated rtok_ts_table.c and a grammars.txt with module-relative paths. The result in
dist/vendor drops straight into rtok's libs/treesitter-native/build/vendor; build rtok with
`-x :treesitter-native:fetchGrammars`.

Usage: build.py --rtok DIR [--out dist] [--history history.json] [--log history.log] [--force]
Writes KEY=VALUE lines (name, sha256, outcome, ...) to $GITHUB_OUTPUT when set, and a compact
report to $GITHUB_STEP_SUMMARY.
"""
import argparse, datetime, glob, hashlib, json, os, shutil, subprocess, sys, urllib.request

NOW = datetime.datetime.now(datetime.timezone.utc)
LINES = []

def log(msg):
    line = f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line, flush=True)
    LINES.append(line)

def deps(src_files, includes):
    """Every file the compiler reads for src_files (system headers excluded)."""
    out = subprocess.run(["cc", "-MM", "-w", *[f"-I{i}" for i in includes], *src_files],
                         capture_output=True, text=True, check=True).stdout
    found = set()
    for tok in out.replace("\\\n", " ").split():
        if not tok.endswith(":"):
            found.add(os.path.realpath(tok))
    return found

LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING", "COPYING.txt", "LICENSE-MIT")

def license_for(repo, commit):
    for name in LICENSE_NAMES:
        try:
            data = urllib.request.urlopen(f"https://raw.githubusercontent.com/{repo}/{commit}/{name}", timeout=60).read()
            return name, data
        except Exception:
            continue
    return None, None

def tree_sha256(root):
    """Content hash of a directory: sorted relative paths and file bytes."""
    h = hashlib.sha256()
    for path in sorted(p for p in glob.glob(os.path.join(root, "**"), recursive=True) if os.path.isfile(p)):
        rel = os.path.relpath(path, root)
        h.update(rel.encode() + b"\0")
        h.update(hashlib.sha256(open(path, "rb").read()).digest())
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtok", required=True)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--history", default="history.json")
    ap.add_argument("--log", default="history.log")
    ap.add_argument("--force", action="store_true", help="build even if identical to the last history entry")
    a = ap.parse_args()

    rtok = os.path.realpath(a.rtok)
    mod = os.path.join(rtok, "libs", "treesitter-native")
    vendor = os.path.join(mod, "build", "vendor")
    pins_path = os.path.join(mod, "grammars.json")
    pins = json.load(open(pins_path))
    rtok_sha = subprocess.run(["git", "-C", rtok, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or "unknown"
    pins_sha = hashlib.sha256(open(pins_path, "rb").read()).hexdigest()
    history = json.load(open(a.history)) if os.path.exists(a.history) else []
    prev = history[-1] if history else None
    prev_commits = {g["repo"]: g["commit"] for g in (prev or {}).get("fetched", [])}

    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    header = f"=== run {run_id} {NOW.strftime('%Y-%m-%dT%H:%M:%SZ')} rtok {rtok_sha} grammars.json {pins_sha[:12]} ==="
    print(header, flush=True)
    log(f"rtok {rtok_sha}, grammars.json sha256 {pins_sha}, {len(pins['repos'])} repos pinned")

    log("running scripts/grammars.py fetch")
    subprocess.run([sys.executable, os.path.join(rtok, "scripts", "grammars.py"), "fetch"], cwd=rtok, check=True)

    fetched, new, unchanged = [], [], []
    for e in pins["repos"]:
        item = {"repo": e["repo"], "commit": e["commit"]}
        fetched.append(item)
        log(f"fetched {e['repo']} @ {e['commit']}")
        if prev_commits.get(e["repo"]) == e["commit"]:
            unchanged.append(item); log(f"unchanged {e['repo']} @ {e['commit'][:10]}")
        else:
            item = dict(item, previous=prev_commits.get(e["repo"]))
            new.append(item); log(f"new {e['repo']} @ {e['commit'][:10]} (was {(item['previous'] or 'none')[:10]})")

    # Collect exactly what CMake compiles: runtime lib.c and each grammar's parser.c/scanner.c.
    keep = set()
    rt = os.path.join(vendor, "tree-sitter", "lib")
    keep |= deps([os.path.join(rt, "src", "lib.c")], [os.path.join(rt, "include"), os.path.join(rt, "src")])
    keep |= {os.path.realpath(p) for p in glob.glob(os.path.join(rt, "include", "**", "*.h"), recursive=True)}  # cinterop api.h
    rows = []
    for line in open(os.path.join(vendor, "grammars.txt")):
        name, src = line.rstrip("\n").split("\t")
        srcs = [os.path.join(src, f) for f in ("parser.c", "scanner.c") if os.path.exists(os.path.join(src, f))]
        keep |= deps(srcs, [src])
        keep |= {os.path.realpath(p) for p in glob.glob(os.path.join(src, "tree_sitter", "*.h"))}
        rows.append((name, os.path.relpath(src, vendor)))
    vendor_real = os.path.realpath(vendor)
    keep = {p for p in keep if p.startswith(vendor_real + os.sep)}  # drop SDK/toolchain files reported by cc

    out = os.path.join(a.out, "vendor")
    shutil.rmtree(a.out, ignore_errors=True)
    for p in sorted(keep):
        dst = os.path.join(out, os.path.relpath(p, vendor_real))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(p, dst)
    shutil.copyfile(os.path.join(vendor, "rtok_ts_table.c"), os.path.join(out, "rtok_ts_table.c"))
    with open(os.path.join(out, "grammars.txt"), "w") as f:
        f.write("".join(f"{n}\tbuild/vendor/{d}\n" for n, d in rows))  # relative to libs/treesitter-native (CMake source dir)
    log(f"kept {len(keep)} source files for runtime + {len(rows)} grammars")

    missing = []
    for e in pins["repos"]:
        d = e["repo"].split("/")[1]
        name, data = license_for(e["repo"], e["commit"])
        if data is None:
            missing.append(e["repo"]); log(f"WARNING no license file found for {e['repo']}")
            continue
        os.makedirs(os.path.join(out, d), exist_ok=True)
        open(os.path.join(out, d, name), "wb").write(data)
        log(f"license {e['repo']} -> {d}/{name}")

    sha = tree_sha256(out)
    size = sum(os.path.getsize(p) for p in glob.glob(os.path.join(out, "**"), recursive=True) if os.path.isfile(p))
    date = NOW.strftime("%Y-%m-%d")
    name = f"tree-sitter-grammars-{date}"
    log(f"artifact name {name}")
    log(f"content sha256 {sha} ({size} bytes, {len(rows)} grammars)")

    duplicate = prev is not None and prev.get("sha256") == sha and not a.force
    outcome = "skipped as duplicate" if duplicate else "artifact uploaded"
    log(f"outcome: {outcome}")

    if not duplicate:
        history.append({"date": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "run_id": run_id, "name": name, "sha256": sha,
                        "bytes": size, "rtok_commit": rtok_sha, "grammars_json_sha256": pins_sha,
                        "grammar_count": len(rows), "fetched": fetched, "new": new, "unchanged": unchanged})
        json.dump(history, open(a.history, "w"), indent=2); open(a.history, "a").write("\n")
    with open(a.log, "a") as f:
        f.write(header + "\n" + "\n".join(LINES) + "\n")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"name={name}\nsha256={sha}\noutcome={outcome}\nupload={'false' if duplicate else 'true'}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        s = [f"## tree-sitter grammars {date}", "",
             f"rtok `{rtok_sha[:12]}` · {len(rows)} grammars · {len(fetched)} repos: {len(new)} new, {len(unchanged)} unchanged", ""]
        if new:
            s += ["| repo | commit | previous |", "|---|---|---|"]
            s += [f"| {g['repo']} | `{g['commit'][:10]}` | `{(g['previous'] or '-')[:10]}` |" for g in new] + [""]
        s += [f"- Artifact: `{name}`", f"- Content sha256: `{sha}`", f"- Outcome: **{outcome}**"]
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("\n".join(s) + "\n")

if __name__ == "__main__":
    main()
