"""性能冒烟压测（NFR-P-05、NFR-R-03；§11.1 性能测试）。

用法：locust -f backend/loadtest/locustfile.py --host http://localhost:8000
场景：登录 → 携带 token 反复提交同步查询（FakeLLM 模式下后端无需真实 LLM）。
注意：这是链路冒烟而非容量结论；容量压测需在预发环境以真实 LLM 配额进行。
"""

import os
import random

from locust import HttpUser, between, task

QUESTIONS = [
    "上个月哪个店铺GMV最高？",
    "这个季度退货率超过10%的商品有哪些？",
    "对比一下华东和华南的销售趋势",
    "本季度订单量是多少",
]


class Text2SQLUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        resp = self.client.post("/api/v1/auth/login", json={
            "username": os.environ.get("LOADTEST_USER", "admin"),
            "password": os.environ.get("LOADTEST_PASS", "admin123"),
        })
        self.token = resp.json()["data"]["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        conv = self.client.post("/api/v1/conversations", headers=self.headers, json={})
        self.conv_id = conv.json()["data"]["id"]
        self.ds_id = int(os.environ.get("LOADTEST_DS_ID", "1"))

    @task(3)
    def query(self):
        q = random.choice(QUESTIONS)
        with self.client.post("/api/v1/query", headers=self.headers, catch_response=True, json={
            "question": q, "conversation_id": self.conv_id, "datasource_id": self.ds_id,
        }) as resp:
            if resp.status_code == 200 and resp.json().get("code") == 0:
                resp.success()
            elif resp.status_code == 429:
                resp.success()  # 限流命中属预期行为（FR-SEC-31），不计为失败
            else:
                resp.failure(f"{resp.status_code}: {resp.text[:100]}")

    @task(1)
    def history(self):
        self.client.get("/api/v1/history", headers=self.headers)
