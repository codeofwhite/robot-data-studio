#!/usr/bin/env python3
"""Read-only indexer over data/: classify runs into success/failure and emit a catalog.

Reads existing state only (cloth_runs/*/state.json, output/validation.json,
data/studio.db, expert_demos failure/trajectory markers, experiment report JSONs).
Writes only NEW files:

  data/RUN_INDEX.md      human catalog (successes first)
  data/RUN_INDEX.json    machine-readable
  data/views/<bucket>/   relative symlinks to classified entries

Never modifies source data, never touches studio.db, never rewrites manifests.

Evidence levels are kept distinct on purpose (see BUCKETS):
  physics_passed  -- cloth validation outcome=passed (NOT closed-loop success)
  qa_accepted     -- episode qa_status=accepted (QA level only, not task success)
Name-derived buckets are marked as inference and are NOT linked into views/.

Usage:
  python3 scripts/index_data_runs.py            # write index + views
  python3 scripts/index_data_runs.py --dry-run  # counts only, write nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
DB = DATA / "studio.db"
CLOTH_RUNS = DATA / "cloth_runs"
EXPERT_ROOTS = [
    DATA / "expert_demos" / "curobo-cloth-v1" / "runs",
    DATA / "expert_demos" / "curobo-cloth-friction-v1" / "probes",
]
VISUAL = DATA / "visual_fidelity" / "robodojo_style_preview"
REPORT_GLOBS = [
    "cloth_multisolver_v2/report.json",
    "cloth_multisolver_v2/batch-report.json",
    "cloth_contact_repair_v1/report.json",
    "cloth_contact_repair_v1/verification.json",
    "clothforge_coverage_v1/coverage.json",
    "clothforge_coverage_v1/browser-acceptance.json",
    "verification/*/final_report.json",
    "training/*/reports/*.json",
    "training/*/*/report.json",
    "training/*/*/train_report.json",
    "evaluations/*/*.json",
]

# bucket -> (meaning, evidence_level, is_success_view)
BUCKETS = {
    "physics_passed": ("cloth run validation outcome=passed", "state.json+validation.json", True),
    "physics_failed": ("cloth run failed/unavailable or validation failed", "state.json+validation.json", False),
    "physics_other": ("cloth run with no/partial output or unknown outcome", "state.json+output listing", False),
    "qa_accepted": ("episode qa_status=accepted", "studio.db episodes.qa_status", True),
    "qa_rejected": ("episode qa_status=rejected", "studio.db episodes.qa_status", False),
    "qa_pending": ("episode qa_status=pending", "studio.db episodes.qa_status", False),
    "expert_passed": ("expert run with trajectory.npz and no failure.txt", "filesystem markers", True),
    "expert_failed": ("expert run with failure.txt", "filesystem markers", False),
    "expert_incomplete": ("expert run with neither trajectory nor failure.txt", "filesystem markers", False),
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------- cloth_runs
def collect_cloth_runs():
    rows = []
    if not CLOTH_RUNS.is_dir():
        return rows
    for name in sorted(os.listdir(CLOTH_RUNS)):
        if not name.startswith("run-"):
            continue
        base = CLOTH_RUNS / name
        if not base.is_dir():
            continue
        st = load_json(base / "state.json") or {}
        out = base / "output"
        files = sorted(os.listdir(out)) if out.is_dir() else []
        val = load_json(out / "validation.json") if "validation.json" in files else {}
        val = val or {}
        status = st.get("status")
        outcome = st.get("outcome") or val.get("outcome")
        if outcome == "passed" and status == "completed":
            bucket = "physics_passed"
        elif outcome in ("failed", "unavailable") or status == "failed" or (
            val.get("outcome") == "failed"
        ):
            bucket = "physics_failed"
        else:
            bucket = "physics_other"
        rows.append(
            {
                "kind": "cloth_run",
                "id": name,
                "bucket": bucket,
                "path": str(base.relative_to(DATA)),
                "engine": st.get("engine_id"),
                "garment": (st.get("selected_asset_id") or "").replace("MDL-clothforge-", ""),
                "scenario": st.get("scenario"),
                "material": st.get("material_id"),
                "status": status,
                "outcome": outcome,
                "validation_outcome": val.get("outcome"),
                "failed_gates": val.get("failed_gates") or [],
                "error": st.get("error"),
                "returncode": st.get("returncode"),
                "gpu": st.get("gpu"),
                "seconds": st.get("worker_wall_seconds"),
                "created_at": st.get("created_at"),
                "outputs": files,
            }
        )
    return rows


# ---------------------------------------------------------------- episodes
def collect_episodes():
    rows = []
    if not DB.is_file():
        return rows
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "select episode_uuid, path, task, qa_status, operator_success, auto_success,"
            " failure_reason, num_frames, session_id from episodes"
        )
        for uuid, path, task, qa, op_ok, auto_ok, reason, frames, session in cur.fetchall():
            bucket = {
                "accepted": "qa_accepted",
                "rejected": "qa_rejected",
                "pending": "qa_pending",
            }.get(qa, "qa_pending")
            rows.append(
                {
                    "kind": "episode",
                    "id": uuid,
                    "bucket": bucket,
                    "path": path,
                    "relpath": os.path.relpath(path, DATA) if path.startswith(str(DATA)) else path,
                    "task": task,
                    "qa_status": qa,
                    "operator_success": op_ok,
                    "auto_success": auto_ok,
                    "failure_reason": reason,
                    "num_frames": frames,
                    "session_id": session,
                }
            )
    finally:
        con.close()
    return rows


def collect_db_side():
    """exports + consumer_smokes, informational only (not bucketed into views)."""
    out = {"exports": [], "consumer_smokes": [], "sessions": []}
    if not DB.is_file():
        return out
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        for r in con.execute("select id, format, status, output_path, error from exports"):
            out["exports"].append(
                {"id": r[0], "format": r[1], "status": r[2], "output_path": r[3], "error": r[4]}
            )
        for r in con.execute("select id, consumer, status, report_path, error from consumer_smokes"):
            out["consumer_smokes"].append(
                {"id": r[0], "consumer": r[1], "status": r[2], "report_path": r[3], "error": r[4]}
            )
        for r in con.execute("select id, adapter_id, scene_id, status, target_episodes from sessions"):
            out["sessions"].append(
                {"id": r[0], "adapter": r[1], "scene": r[2], "status": r[3], "target": r[4]}
            )
    finally:
        con.close()
    return out


# ---------------------------------------------------------------- expert runs
def collect_expert():
    rows = []
    for root in EXPERT_ROOTS:
        if not root.is_dir():
            continue
        for name in sorted(os.listdir(root)):
            base = root / name
            if not base.is_dir():
                continue
            has_fail = (base / "failure.txt").is_file()
            has_traj = (base / "trajectory.npz").is_file()
            if has_fail:
                bucket = "expert_failed"
                reason = "failure.txt present"
            elif has_traj:
                bucket = "expert_passed"
                reason = None
            else:
                bucket = "expert_incomplete"
                reason = "no trajectory.npz and no failure.txt"
            fail_head = None
            if has_fail:
                try:
                    txt = (base / "failure.txt").read_text(encoding="utf-8", errors="replace")
                    lines = [ln for ln in txt.strip().splitlines() if ln.strip()]
                    fail_head = lines[-1][:160] if lines else "failure.txt (empty)"
                except Exception:
                    fail_head = "failure.txt (unreadable)"
            rows.append(
                {
                    "kind": "expert_run",
                    "id": f"{root.parent.name}/{name}",
                    "bucket": bucket,
                    "path": str(base.relative_to(DATA)),
                    "group": root.parent.name,
                    "has_trajectory": has_traj,
                    "has_failure": has_fail,
                    "failure_tail": fail_head,
                    "reason": reason,
                }
            )
    return rows


# ---------------------------------------------------------------- name-derived
NAME_FINAL = re.compile(r"(^|[_-])(final|rejected|smoke|attempt\d+)([_-]|$)", re.I)


def collect_visual_name_derived():
    """Inference only: visual_fidelity provenance.json has no pass/fail field."""
    rows = []
    if not VISUAL.is_dir():
        return rows
    for name in sorted(os.listdir(VISUAL)):
        base = VISUAL / name
        if not base.is_dir():
            continue
        low = name.lower()
        if "rejected" in low:
            guess = "rejected_by_name"
        elif low.endswith("_final") or "_final" in low:
            guess = "final_by_name"
        elif "smoke" in low:
            guess = "smoke_by_name"
        elif re.search(r"attempt\d+", low):
            guess = "attempt_by_name"
        else:
            guess = "other_by_name"
        prov = load_json(base / "provenance.json") or {}
        rows.append(
            {
                "kind": "visual_preview",
                "id": name,
                "bucket": None,  # not linked into views/ -- inference only
                "path": str(base.relative_to(DATA)),
                "name_guess": guess,
                "created_at": prov.get("created_at"),
                "visual_style": prov.get("visual_style"),
                "renderer_profile": (prov.get("renderer_profile") or {}).get("id"),
                "purpose": prov.get("purpose"),
            }
        )
    return rows


# ---------------------------------------------------------------- reports
def collect_reports():
    rows = []
    seen = set()
    for pattern in REPORT_GLOBS:
        for path in sorted(DATA.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            doc = load_json(path)
            if doc is None:
                continue
            items = doc if isinstance(doc, list) else [doc]
            outcomes = {}
            cases = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                o = it.get("outcome") or it.get("status") or it.get("result")
                if o is None:
                    continue
                outcomes[str(o)] = outcomes.get(str(o), 0) + 1
                if it.get("run_id") or it.get("failed_gates") is not None:
                    cases.append(
                        {
                            "run_id": it.get("run_id"),
                            "engine": it.get("engine"),
                            "garment": it.get("garment"),
                            "scenario": it.get("scenario"),
                            "outcome": o,
                            "failed_gates": it.get("failed_gates") or [],
                        }
                    )
            if not outcomes:
                continue
            rows.append(
                {
                    "kind": "report",
                    "path": str(path.relative_to(DATA)),
                    "outcomes": outcomes,
                    "review_status": (doc.get("review_status") if isinstance(doc, dict) else None),
                    "cases": cases,
                }
            )
    return rows


# ---------------------------------------------------------------- views
def write_views(buckets, dry_run: bool):
    views = DATA / "views"
    if dry_run:
        return
    views.mkdir(exist_ok=True)
    # remove only our own previous symlink trees (never real dirs/files)
    for child in list(views.iterdir()):
        if child.is_symlink():
            child.unlink()
        elif child.is_dir() and not child.is_symlink():
            for sub in list(child.iterdir()):
                if sub.is_symlink():
                    sub.unlink()
            try:
                sub.rmdir()
            except OSError:
                pass
            try:
                child.rmdir()
            except OSError:
                pass
    for bucket, entries in buckets.items():
        bdir = views / bucket
        bdir.mkdir(parents=True, exist_ok=True)
        for e in entries:
            target = Path(e["path"])
            link = bdir / e["id"].replace("/", "__")
            rel = os.path.relpath(DATA / target, bdir)
            if link.exists() or link.is_symlink():
                if link.is_symlink():
                    link.unlink()
                else:
                    continue
            link.symlink_to(rel)


# ---------------------------------------------------------------- markdown
def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def build_md(payload) -> str:
    generated = payload["generated_at"]
    cr, ep, ex = payload["cloth_runs"], payload["episodes"], payload["expert_runs"]
    side, reports, visual = payload["db_side"], payload["reports"], payload["visual_name_derived"]

    def pick(rows, b):
        return [r for r in rows if r["bucket"] == b]

    L = []
    A = L.append
    A(f"# data/ 运行索引（成功/失败归类）")
    A("")
    A(f"生成时间：`{generated}`　·　生成脚本：`scripts/index_data_runs.py`（只读源数据）")
    A("")
    A("> **证据分级**：`physics_passed` = 布料校验 `outcome=passed`，**不等于**闭环任务成功；")
    A("> `qa_accepted` = episode `qa_status=accepted`，只是 QA 层，**不等于**任务成功。")
    A("> 二者都不证明闭环提升。`visual_fidelity` 仅由目录名推断，不进 `views/`。")
    A("")
    A("## 0. 一眼看成功")
    A("")
    A("```bash")
    A("ls data/views/physics_passed   # 布料仿真校验通过")
    A("ls data/views/qa_accepted      # QA 接受的 episode")
    A("ls data/views/expert_passed    # expert 演示有 trajectory 且无 failure.txt")
    A("```")
    A("")
    A("## 1. 总览")
    A("")
    A(
        md_table(
            ["类别", "成功", "失败", "其他/待定", "合计", "证据来源"],
            [
                [
                    "cloth_runs",
                    len(pick(cr, "physics_passed")),
                    len(pick(cr, "physics_failed")),
                    len(pick(cr, "physics_other")),
                    len(cr),
                    "state.json + validation.json",
                ],
                [
                    "episodes",
                    f'{len(pick(ep, "qa_accepted"))} (accepted)',
                    f'{len(pick(ep, "qa_rejected"))} (rejected)',
                    f'{len(pick(ep, "qa_pending"))} (pending)',
                    len(ep),
                    "studio.db episodes.qa_status",
                ],
                [
                    "expert_demos",
                    len(pick(ex, "expert_passed")),
                    len(pick(ex, "expert_failed")),
                    len(pick(ex, "expert_incomplete")),
                    len(ex),
                    "failure.txt / trajectory.npz",
                ],
            ],
        )
    )
    A("")
    A(
        f"下游：exports {sum(1 for e in side['exports'] if e['status']=='completed')} completed / "
        f"{sum(1 for e in side['exports'] if e['status']!='completed')} 其他；"
        f"consumer_smokes {sum(1 for e in side['consumer_smokes'] if e['status']=='passed')} passed / "
        f"{len(side['consumer_smokes'])} 合计。"
    )
    A("")

    # ---- successes first
    A("## 2. 成功案例（cloth_runs 校验通过）")
    A("")
    mat = {}
    for r in pick(cr, "physics_passed"):
        mat.setdefault((r["engine"], r["garment"], r["scenario"], r["material"]), []).append(r["id"])
    A(
        md_table(
            ["engine", "garment", "scenario", "material", "次数", "run_id（可点开）"],
            [
                [k[0], k[1], k[2], k[3], len(v), "<br>".join(f"`{x}`" for x in v)]
                for k, v in sorted(mat.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            ],
        )
    )
    A("")
    A("## 3. 成功案例（episodes QA accepted）")
    A("")
    tasks = {}
    for r in pick(ep, "qa_accepted"):
        tasks.setdefault(r["task"], []).append(r)
    A(
        md_table(
            ["task", "条数", "op_ok", "auto_ok", "示例路径"],
            [
                [k, len(v), sum(1 for x in v if x["operator_success"] == 1), sum(1 for x in v if x["auto_success"] == 1), f"`{v[0]['relpath']}`"]
                for k, v in sorted(tasks.items(), key=lambda kv: -len(kv[1]))
            ],
        )
    )
    A("")
    A("完整 92 条见 `RUN_INDEX.json` 的 `episodes`（`bucket=qa_accepted`），或 `ls data/views/qa_accepted`。")
    A("")
    A("## 4. 成功案例（expert_demos）")
    A("")
    exp_ok = pick(ex, "expert_passed")
    A(f"共 {len(exp_ok)} 个 run 含 `trajectory.npz` 且无 `failure.txt`：")
    A("")
    A(", ".join(f"`{r['id']}`" for r in exp_ok) if exp_ok else "（无）")
    A("")

    # ---- failures
    A("## 5. 失败清单与原因")
    A("")
    A("### 5.1 cloth_runs")
    A("")
    reasons = {}
    for r in pick(cr, "physics_failed"):
        key = r.get("error") or f"outcome={r.get('outcome')}/status={r.get('status')}"
        reasons.setdefault(str(key), []).append(r)
    A(md_table(["原因", "次数", "run_id"], [[k[:80], len(v), "<br>".join(f"`{x['id']}`" for x in v)] for k, v in sorted(reasons.items(), key=lambda kv: -len(kv[1]))]))
    A("")
    A("### 5.2 episodes（rejected）")
    A("")
    fr = {}
    for r in pick(ep, "qa_rejected"):
        fr.setdefault(r.get("failure_reason") or "(none)", []).append(r)
    A(md_table(["failure_reason", "次数"], [[k[:80], len(v)] for k, v in sorted(fr.items(), key=lambda kv: -len(kv[1]))]))
    A("")
    A("### 5.3 expert_demos（failure.txt）")
    A("")
    ef = pick(ex, "expert_failed")
    A(md_table(["run", "报错尾行"], [[f"`{r['id']}`", (r.get("failure_tail") or "")[:100]] for r in ef]))
    A("")

    # ---- other
    A("## 6. 其他 / 未归类")
    A("")
    A(f"- cloth_runs 其他 {len(pick(cr,'physics_other'))} 个（无 output 或 outcome 缺失）：")
    for r in pick(cr, "physics_other"):
        A(f"  - `{r['id']}` status={r['status']} outcome={r['outcome']} outputs={r['outputs'][:4]}")
    A(f"- episodes pending {len(pick(ep,'qa_pending'))} 条")
    A(f"- expert_demos 无 trajectory 也无 failure.txt {len(pick(ex,'expert_incomplete'))} 个")
    A("")

    # ---- db side
    A("## 7. 下游导出与 consumer smoke")
    A("")
    A("### exports")
    A("")
    A(md_table(["format", "status", "output_path", "error"], [[e["format"], e["status"], f"`{e['output_path']}`", (e.get("error") or "")[:60]] for e in side["exports"]]))
    A("")
    A("### consumer_smokes")
    A("")
    A(md_table(["consumer", "status", "report_path"], [[e["consumer"], e["status"], f"`{e['report_path']}`"] for e in side["consumer_smokes"]]))
    A("")

    # ---- reports
    A("## 8. 实验报告 outcome 汇总")
    A("")
    A(md_table(["报告", "outcomes", "review_status"], [[f"`{r['path']}`", r["outcomes"], r.get("review_status")] for r in reports]))
    A("")

    # ---- visual name-derived
    A("## 9. visual_fidelity（仅目录名推断，非证据）")
    A("")
    A("`provenance.json` 没有成败字段，下表按命名猜测，**不进 `views/`**，仅便于找候选成品。")
    A("")
    g = {}
    for r in visual:
        g.setdefault(r["name_guess"], []).append(r)
    A(md_table(["命名猜测", "个数", "目录"], [[k, len(v), "<br>".join(f"`{x['id']}`" for x in v)] for k, v in sorted(g.items())]))
    A("")

    # ---- views map
    A("## 10. views/ 目录说明")
    A("")
    A(md_table(["目录", "含义", "证据来源", "是否算成功"], [[f"`views/{k}/`", v[0], v[1], "是" if v[2] else "否"] for k, v in BUCKETS.items()]))
    A("")
    A("views/ 内是相对符号链接，指向原始 run/episode 目录；删 views 不影响源数据。")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print counts only, write nothing")
    args = ap.parse_args()

    db_hash_before = sha256_file(DB) if DB.is_file() else None

    cr = collect_cloth_runs()
    ep = collect_episodes()
    ex = collect_expert()
    side = collect_db_side()
    reports = collect_reports()
    visual = collect_visual_name_derived()

    buckets = {k: [] for k in BUCKETS}
    for e in cr + ep + ex:
        buckets.setdefault(e["bucket"], []).append(e)

    print(f"cloth_runs   : {len(cr)}  " + " ".join(f"{k}={len(v)}" for k, v in buckets.items() if k.startswith("physics_")))
    print(f"episodes     : {len(ep)}  " + " ".join(f"{k}={len(v)}" for k, v in buckets.items() if k.startswith("qa_")))
    print(f"expert_runs  : {len(ex)}  " + " ".join(f"{k}={len(v)}" for k, v in buckets.items() if k.startswith("expert_")))
    print(f"reports      : {len(reports)}   visual_name_derived: {len(visual)}")
    print(f"exports      : {len(side['exports'])}   consumer_smokes: {len(side['consumer_smokes'])}   sessions: {len(side['sessions'])}")

    if args.dry_run:
        print("--dry-run: nothing written")
        return 0

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "data_root": str(DATA),
        "db_sha256": db_hash_before,
        "buckets": {k: {"meaning": v[0], "evidence": v[1], "is_success": v[2]} for k, v in BUCKETS.items()},
        "counts": {k: len(v) for k, v in buckets.items()},
        "cloth_runs": cr,
        "episodes": ep,
        "expert_runs": ex,
        "db_side": side,
        "reports": reports,
        "visual_name_derived": visual,
    }
    (DATA / "RUN_INDEX.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "RUN_INDEX.md").write_text(build_md(payload), encoding="utf-8")
    write_views(buckets, dry_run=False)

    db_hash_after = sha256_file(DB) if DB.is_file() else None
    if db_hash_before != db_hash_after:
        print("ERROR: studio.db changed during indexing", file=sys.stderr)
        return 2
    print(f"wrote {DATA/'RUN_INDEX.md'}")
    print(f"wrote {DATA/'RUN_INDEX.json'}")
    print(f"wrote {DATA/'views'}/{{{','.join(k for k,v in buckets.items() if v)}}}")
    print(f"studio.db sha256 unchanged: {db_hash_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
