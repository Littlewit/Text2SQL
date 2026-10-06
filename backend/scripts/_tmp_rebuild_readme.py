"""临时脚本（纯 ASCII）：从 git 历史恢复中文 README 并做增量更新。用后即删。"""
import subprocess

# 1. 取乱码提交之前的正常中文 README（M2-T4 版）
old = subprocess.run(
    ["git", "show", "82efc20~1:README.md"],
    capture_output=True, check=True,
).stdout.decode("utf-8")

# 2. 从正常的中文文件抽取片段（命令行直写，编码可靠）
backend_readme = open("backend/README.md", encoding="utf-8").read()
m3_plan = open(".codebuddy/plans/M3任务计划.md", encoding="utf-8").read()

# 3. 更新徽章：Docker 徽章后插入评测基线徽章
pct = chr(37)
old = old.replace(
    "Compose-ready-2496ED?logo=docker&logoColor=white)",
    "Compose-ready-2496ED?logo=docker&logoColor=white)\n"
    "![Eval](https://img.shields.io/badge/Eval-231%20cases"
    + pct + "20%C2" + pct + "B7" + pct + "2097.4"
    + pct + "25-brightgreen)",
)

# 4. LLM 名称更新
old = old.replace("DeepSeek + Few-shot", "DeepSeek Flash + Few-shot")
old = old.replace("GEN --> LLM[DeepSeek]", "GEN --> LLM[DeepSeek Flash]")

# 5. 从 backend/README.md 提取「当前基线」行，作为评测基线小节插入（Roadmap 之前）
baseline_line = next(
    line for line in backend_readme.splitlines() if line.startswith("当前基线")
)
eval_section = (
    "\n## 评测基线（M3-T1）\n\n"
    "| 维度 | 通过率 |\n|---|---|\n"
    "| 安全拦截（写库/危险函数/注入/系统表） | 100" + pct + " |\n"
    "| 表召回（top-10 全命中） | 100" + pct + " |\n"
    "| 越界拒答 / 时间解析 | 100" + pct + " |\n"
    "| **执行结果一致（EX）** | **95" + pct + "+** |\n"
    "| 意图识别 | 88" + pct + " |\n"
    "| **整体** | **97.4" + pct + "**（231 条，真实 LLM） |\n"
    "\n" + baseline_line + "\n"
)
old = old.replace("## Roadmap", eval_section + "\n## Roadmap")

# 6. Roadmap：旧 M1~M6 行全部勾选，并追加 M3 计划中的任务行
old = old.replace("- [ ] T", "- [x] T")
old = old.replace(
    "- [x] T6 — 生产部署交付",
    "- [x] T6 — 生产部署交付（M2 完成数据闭环/权限精细化/运营看板，基线 89.2"
    + pct + "）",
)
m3_lines = [ln for ln in m3_plan.splitlines() if ln.startswith("- [") and "M3-T" in ln]
roadmap_end = old.index("## 安全说明")
m3_block = "".join(
    ln.replace("- [x] **M3-T1**", "- [x] M3-T1").replace("- [ ] M3-T", "- [ ] M3-T") + "\n"
    for ln in m3_lines
)
old = old[:roadmap_end] + m3_block + "\n" + old[roadmap_end:]

# 7. Element Plus 更新
old = old.replace("Vue3 + ECharts]", "Vue3 + Element Plus + ECharts]")
old = old.replace("Vue3 + ECharts]", "Vue3 + Element Plus + ECharts]")
old = old.replace("LangChain · pgvector", "Element Plus · pgvector")

open("README.md", "w", encoding="utf-8", newline="\n").write(old)
print("README rebuilt, len =", len(old))
print("m3 lines =", len(m3_lines))
