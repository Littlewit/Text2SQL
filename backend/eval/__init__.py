"""Text2SQL 评测框架（EV-01~05、§11.3）。

用例分类与执行方式：
- time_parse   离线可跑：时间解析器期望值比对（确定性）
- guard_reject 离线可跑：恶意 SQL 必须被 sql_guard 拦截（安全红线）
- guard_pass   离线可跑：合法 SQL 必须通过
- sql_exec     需 LLM：生成 SQL 与标准 SQL 在 demo 库执行，比对结果集（EX，NFR-A-01）
- refused      需 LLM：越界问题必须拒答且不生成 SQL（FR-NLU-03）
- clarify      需 LLM：模糊问题必须澄清（FR-NLU-02）
- intent       需 LLM：意图分类正确（NFR-A-03）

离线用例（前两类）作为 CI 强制门禁（确定性、无外部依赖）；
LLM 用例产出分维度报告，供回归对比（EV-04）。
"""
