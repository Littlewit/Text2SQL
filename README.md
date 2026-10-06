<div align="center">

# Text2SQL 鏅鸿兘鏁版嵁鍒嗘瀽骞冲彴

**鐢ㄨ嚜鐒惰瑷€鏌ヨ鏁版嵁搴擄紝鍗冲埢鐢熸垚鍥捐〃涓庣粨璁?*

[![CI](https://github.com/Littlewit/Text2SQL/actions/workflows/ci.yml/badge.svg)](https://github.com/Littlewit/Text2SQL/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3.x%20%2B%20Element%20Plus-4FC08D?logo=vuedotjs&logoColor=white)
![Docker](https://img.shields.io/badge/Docker%20Compose-ready-2496ED?logo=docker&logoColor=white)
![Eval](https://img.shields.io/badge/%E8%AF%84%E6%B5%8B%E5%9F%BA%E7%BA%BF-231%E6%9D%A1%20%C2%B7%2097.4%25-brightgreen)

</div>

---

## 椤圭洰绠€浠?

闈㈠悜闈炴妧鏈汉鍛樼殑鏅鸿兘鏁版嵁鍒嗘瀽骞冲彴锛氫笟鍔′汉鍛樼敤涓枃鎻愰棶锛堝銆屼笂涓湀鍝釜搴楅摵 GMV 鏈€楂橈紵銆嶏級锛?
骞冲彴鑷姩瀹屾垚 **鎰忓浘鐞嗚В 鈫?Schema 娣峰悎妫€绱?鈫?SQL 鐢熸垚 鈫?AST 瀹夊叏鏍￠獙 鈫?鏉冮檺鏀瑰啓 鈫?鍙鎵ц 鈫?鑴辨晱 鈫?鍥捐〃娓叉煋**
鐨勫畬鏁撮摼璺紝骞朵互銆岀粨璁?+ 鍥捐〃 + SQL 瑙ｉ噴 + 鍙ｅ緞澹版槑銆嶅洓瑕佺礌鍛堢幇缁撴灉銆?

### 鏍稿績鐗规€?

- **瀵硅瘽寮忔煡璇?* 鈥?澶氳疆涓婁笅鏂囩户鎵裤€佸缓璁拷闂€佹祦寮忛樁娈靛弽棣堬紙SSE锛?
- **Text2SQL 寮曟搸** 鈥?DeepSeek Flash + Few-shot 鍔ㄦ€佸彫鍥?+ 鎸囨爣鍙ｅ緞褰掍竴鍖?+ Schema 娣峰悎妫€绱紙pgvector锛岃〃閰嶉淇濆簳 + 鑱氬悎鍔犲垎锛?
- **绾垫繁闃插尽** 鈥?AST 绾?SQL 鏍￠獙鐧藉悕鍗曘€佽绾ф潈闄愭敞鍏ワ紙union/intersect 鍙厤锛夈€佸垪绾ц鑹查殣钘忋€佹晱鎰熷瓧娈佃劚鏁忋€佸彧璇昏处鍙枫€丵PS/骞跺彂闄愭祦銆佹瘡鏃ラ厤棰濄€佺啍鏂?
- **杩愯惀闂幆** 鈥?杩愯惀鐪嬫澘锛堟垚鍔熺巼/鑰楁椂鍒嗗竷/閲嶈瘯鐜?Token 鐢ㄩ噺锛夈€佹煡璇㈠巻鍙?鏀惰棌/鍒嗕韩銆丗ew-shot 鏍蜂緥搴撲笌鍙嶉閲囩撼銆佸璁℃棩蹇楋紙涓嶅彲绡℃敼 + 淇濈暀鏈熸竻鐞嗭級
- **璐ㄩ噺闂ㄧ** 鈥?231 鏉¤瘎娴嬪熀绾匡紙瀹夊叏/鍙洖 100%锛夈€佸洖褰掑姣旀姤鍛娿€佽鐩栫巼 鈮?0%
- **鍚屾瀯閮ㄧ讲** 鈥?鍏ㄧ幆澧冪粺涓€ PostgreSQL + pgvector锛堝惈鍚戦噺妫€绱級锛孌ocker Compose 涓€閿惎鍔?

### 璇勬祴鍩虹嚎锛圡3-T1锛?

| 缁村害 | 閫氳繃鐜?|
|---|---|
| 瀹夊叏鎷︽埅锛堝啓搴?鍗遍櫓鍑芥暟/娉ㄥ叆/绯荤粺琛級 | 100% |
| 琛ㄥ彫鍥烇紙top-10 鍏ㄥ懡涓級 | 100% |
| 瓒婄晫鎷掔瓟 / 鏃堕棿瑙ｆ瀽 | 100% |
| **鎵ц缁撴灉涓€鑷达紙EX锛?* | **95%+** |
| 鎰忓浘璇嗗埆 | 88% |
| **鏁翠綋** | **97.4%**锛?31 鏉★紝鐪熷疄 LLM锛?|

## 鏋舵瀯

```mermaid
flowchart LR
    FE[Vue3 + ECharts] --> API[FastAPI 缃戝叧]
    API --> RL[闄愭祦 / 姣忔棩閰嶉]
    API --> NLU[鎰忓浘涓庡疄浣撶悊瑙
    API --> SR[Schema 娣峰悎妫€绱
    SR --> PGV[(pgvector)]
    NLU --> GEN[SQL 鐢熸垚]
    GEN --> LLM[DeepSeek Flash]
    GEN --> GUARD[SQL 鏍￠獙 / 鏉冮檺鏀瑰啓 / 鑴辨晱]
    GUARD --> EXE[鍙鎵ц鍣╙
    EXE --> BIZ[(涓氬姟搴?PostgreSQL)]
    API --> META[(鍏冩暟鎹簱 PostgreSQL)]
    API --> RC[Redis 闄愭祦/閰嶉]
    API --> DASH[杩愯惀鐪嬫澘 / 璇勬祴绠＄悊]
```

## 蹇€熷紑濮?

> 鍓嶇疆鏉′欢锛歔Docker](https://docs.docker.com/desktop/)锛堟暟鎹簱蹇呴』璧板鍣級銆丳ython 3.10+銆丯ode 18+

```bash
# 1. 鍏嬮殕
git clone https://github.com/Littlewit/Text2SQL.git
cd Text2SQL

# 2. 鍚姩鍩虹璁炬柦锛圥ostgreSQL pgvector + Redis锛汸G 鏄犲皠瀹夸富鏈?5433锛?
docker compose -f docker-compose.dev.yml up -d

# 3. 鍚庣渚濊禆涓庤縼绉?
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
alembic upgrade head

# 4. 绀轰緥涓氬姟搴撲笌璇箟灞傜瀛愶紙璇勬祴/婕旂ず鏁版嵁锛?
psql -h localhost -p 5433 -U t2s -d postgres -c "CREATE DATABASE demo_business"
psql -h localhost -p 5433 -U t2s -d demo_business -f scripts/demo_business.sql
# 鍦ㄧ鐞嗗悗鍙版帴鍏ユ暟鎹簮 demo_business 骞跺畬鎴愭壂鎻忓悗锛?
python scripts/seed_eval_meta.py
python scripts/seed_few_shots.py

# 5. 鍚姩鍚庣锛堢粺涓€鍏ュ彛锛屽鐞?Windows 浜嬩欢寰幆鍏煎锛?
python run.py

# 6. 鍓嶇锛堝彟寮€缁堢锛?
cd ../frontend
npm install
npm run dev
```

鍚庣 API 浣嶄簬 `http://localhost:8000/api/v1`锛屼氦浜掑紡鏂囨。瑙?`/docs`銆?
鍐呯疆璐﹀彿锛歚admin / admin123`锛堥鍚己鍒朵慨鏀癸級銆傚唴缃鑹诧細`R-BIZ` 涓氬姟鐢ㄦ埛銆乣R-DA` 鏁版嵁鍒嗘瀽銆乣R-AD` 绠＄悊鍛樸€乣R-AU` 瀹¤鍛樸€?

## 椤圭洰缁撴瀯

```text
鈹溾攢鈹€ backend/                  # FastAPI 鍚庣
鈹?  鈹溾攢鈹€ app/api/v1/           #   璺敱灞傦紙璁よ瘉/鏌ヨ SSE/绠＄悊鍚庡彴/杩愯惀锛?
鈹?  鈹溾攢鈹€ app/core/             #   閰嶇疆/瀹夊叏/闄愭祦/閰嶉/缁撴灉缂撳瓨
鈹?  鈹溾攢鈹€ app/services/         #   NLU銆佹绱€佺敓鎴愩€乻ql_guard銆佹潈闄愩€佽劚鏁忋€佹墽琛屻€佸浘琛ㄣ€佽瘎娴?
鈹?  鈹溾攢鈹€ app/infra/            #   ORM 妯″瀷涓庢暟鎹簱寮曟搸
鈹?  鈹溾攢鈹€ app/llm/              #   LLM / Embedding 閫傞厤灞傦紙鍙浛鎹級
鈹?  鈹溾攢鈹€ alembic/              #   杩佺Щ锛?001~0010锛屼粎 PostgreSQL 鏂硅█锛?
鈹?  鈹溾攢鈹€ eval/                 #   璇勬祴妗嗘灦锛?31 鏉＄敤渚嬨€乺unner銆佸熀绾匡級
鈹?  鈹溾攢鈹€ scripts/              #   绀轰緥搴?璇箟灞?Few-shot 绉嶅瓙鑴氭湰
鈹?  鈹斺攢鈹€ tests/                #   鍗曞厓 + 闆嗘垚娴嬭瘯锛堢湡瀹?PG锛?
鈹溾攢鈹€ frontend/                 # Vue3 + TS 鍓嶇锛堝璇?鍘嗗彶/鏀惰棌/绠＄悊鍚庡彴/杩愯惀鐪嬫澘锛?
鈹溾攢鈹€ docker-compose.dev.yml    # 寮€鍙戠幆澧冪紪鎺?
鈹溾攢鈹€ docker-compose.yml        # 鐢熶骇缂栨帓
鈹斺攢鈹€ .github/workflows/        # CI 娴佹按绾匡紙lint/娴嬭瘯/瑕嗙洊鐜囬棬绂侊級
```

## 寮€鍙?

```bash
# 鍚庣娴嬭瘯涓庢鏌?
cd backend
pytest -m "not integration"                    # 鍗曞厓娴嬭瘯锛堟棤澶栭儴渚濊禆锛?
pytest -m integration                          # 闆嗘垚娴嬭瘯锛堥渶 Docker锛岀湡瀹?PG + pgvector锛?
pytest -m "not integration" --cov=app --cov-append
pytest -m integration --cov=app --cov-append --cov-fail-under=70   # 瑕嗙洊鐜囬棬绂?
ruff check .

# 璇勬祴锛堢湡瀹?LLM锛岄渶 DEEPSEEK_API_KEY锛?
python -m eval.run --offline                   # 绂荤嚎瀹夊叏绫诲埆锛圕I 闂ㄧ锛?00% 绾㈢嚎锛?
python -m eval.run                             # 鍏ㄩ噺锛堜笌 baseline.json 瀵规瘮锛?
python -m eval.run --kinds sql_exec,recall     # 鎸囧畾绫诲埆

# 鍓嶇
cd frontend
npm run dev
npm run build
```

## 鏂囨。

瀹屾暣浜у搧涓庢妧鏈枃妗ｅ瓨鏀句簬鏈湴 `.codebuddy/docs/`銆佷换鍔¤鍒掍簬 `.codebuddy/plans/`锛堜笉鍏ュ簱锛夛細

| 鏂囨。 | 璇存槑 |
|---|---|
| 璇︾粏闇€姹傛枃妗?v1.1 | 8 澶фā鍧椼€?30 鏉″姛鑳介渶姹傘€侀潪鍔熻兘鎸囨爣涓庨獙鏀舵爣鍑?|
| 绯荤粺璁捐 v1.0 | 鏋舵瀯銆佹牳蹇冮摼璺€佹暟鎹簱 DDL銆丄PI 濂戠害銆侀儴缃茶璁?|
| M1/M2 浠诲姟璁″垝 | T0~T6銆丮2-T1~T6 浠诲姟鍖呮媶瑙ｄ笌瀹屾垚璁板綍 |
| M3 浠诲姟璁″垝 | 璐ㄩ噺鍐插埡 / 瀵硅瘽娣卞寲 / 鐢熶骇灏辩华锛堣繘琛屼腑锛?|

## Roadmap

- [x] **M1** 鈥?鑴氭墜鏋?/ 璁よ瘉搴曞骇 / Schema 绠＄悊閾捐矾 / 鏌ヨ涓婚摼璺?/ 鍙鍖?/ 绀轰緥搴撲笌瀹夊叏璇勬祴
- [x] **M2** 鈥?鏁版嵁闂幆 / SQL 澧炲己 / 鏉冮檺绮剧粏鍖?/ 鍙鍖栧鍑?/ 杩愯惀鐪嬫澘 / 璇勬祴鍩虹嚎锛?9.2%锛?
- [x] **M3-T1** 鈥?鐢熸垚璐ㄩ噺鍐插埡锛堣瘎娴嬪熀绾?97.4%锛孍X 95%+锛?
- [ ] M3-T2 鈥?Embedding 鐪熸ā鍨嬫帴鍏ワ紙bge-large-zh锛?
- [ ] M3-T3 鈥?瀵硅瘽寮忓垎鏋愭繁鍖栵紙澶氳疆鏀瑰啓 / 瀵规瘮闂锛?
- [ ] M3-T4 鈥?Celery 寮傛浠诲姟涓庢€ц兘
- [ ] M3-T5 鈥?鐢熶骇鍖栭儴缃诧紙涓€閿垵濮嬪寲 / 澶囦唤 / 鐩戞帶锛?
- [ ] M3-T6 鈥?UAT 涓庝氦浠橀獙鏀?

## 瀹夊叏璇存槑

骞冲彴瀵逛笟鍔℃暟鎹簱**涓ユ牸鍙**锛汱LM 杈撳嚭闆朵俊浠伙紝鎵€鏈?SQL 蹇呴』閫氳繃 AST 鐧藉悕鍗曟牎楠屻€?
鏉冮檺鏀瑰啓涓庤鏁伴檺鍒跺悗鏂瑰彲鎵ц锛涙晱鎰熷€煎湪鏈嶅姟绔嚭鍙ｇ粺涓€鑴辨晱鍚庢墠杩涘叆鍓嶇涓庡鍑猴紱
瀵嗛挜浠呯粡鐜鍙橀噺娉ㄥ叆锛坄DEEPSEEK_API_KEY`锛夛紝鏁版嵁婧愬嚟鎹?AES-GCM 鍔犲瘑瀛樺偍銆傝瑙侀渶姹傛枃妗?搂9 瀹夊叏涓庡悎瑙勩€?

---

<div align="center">

Built with FastAPI 路 SQLAlchemy 2.0 路 pgvector 路 Vue3 路 ECharts

</div>