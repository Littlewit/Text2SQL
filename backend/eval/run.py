"""评测入口 CLI（EV-02/04/05）。

用法：
  python -m eval.generate_cases            # 生成/更新用例集
  python -m eval.run --offline --gate      # 离线门禁（CI 强制，确定性）
  python -m eval.run --report report.json  # 全量评测（需 LLM_API_KEY）

门禁规则（EV-04）：
  - 离线类别通过率必须 100%（安全红线，不可妥协）；
  - LLM 类别如存在 baseline.json，整体通过率下降超过阈值（默认 5%，P-56）即失败。
"""

import argparse
import json
import sys
from pathlib import Path

from eval.runner import OFFLINE_KINDS, load_cases, run_eval

BASELINE_FILE = Path(__file__).parent / "baseline.json"
REPORT_FILE = Path(__file__).parent / "report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Text2SQL 评测")
    parser.add_argument("--offline", action="store_true", help="仅跑离线类别（CI 门禁）")
    parser.add_argument("--limit", type=int, default=None, help="限制用例数（冒烟）")
    parser.add_argument("--gate", action="store_true", help="启用门禁判定（非 0 退出码）")
    parser.add_argument("--threshold", type=float, default=0.05, help="相对基线下降阈值（P-56，默认 5%%）")
    args = parser.parse_args()

    cases = load_cases()
    report = run_eval(cases, offline_only=args.offline, limit=args.limit)

    REPORT_FILE.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    d = report.to_dict()
    print(f"评测完成: total={d['total']} passed={d['passed']} failed={d['failed']} "
          f"skipped={d['skipped']} pass_rate={d['pass_rate']} ({d['duration_ms']}ms)")
    for tag, stat in sorted(d["by_tag"].items()):
        rate = round(stat["passed"] / max(stat["total"], 1), 3)
        print(f"  [{tag}] {stat['passed']}/{stat['total']} ({rate})")
    for f in d["failures"][:10]:
        print(f"  FAIL {f['id']} [{f['kind']}] {f['detail']}")

    if not args.gate:
        return 0

    # 门禁 1：离线类别（确定性安全用例）必须 100%
    offline = {k: v for k, v in d["by_tag"].items()
               if any(c["tag"] == k and c["kind"] in OFFLINE_KINDS for c in cases)}
    for tag, stat in offline.items():
        if stat["passed"] < stat["total"]:
            print(f"GATE FAIL: 离线类别 {tag} 通过率 {stat['passed']}/{stat['total']} < 100%")
            return 1

    # 门禁 2：整体通过率相对基线下降超阈值（EV-04）
    if BASELINE_FILE.exists():
        baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
        base_rate = baseline.get("pass_rate", 0)
        if d["pass_rate"] < base_rate - args.threshold:
            print(f"GATE FAIL: 通过率 {d['pass_rate']} 相对基线 {base_rate} 下降超 {args.threshold}")
            return 1
    else:
        BASELINE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"基线不存在，已写入当前结果作为基线: {BASELINE_FILE}")

    print("GATE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
