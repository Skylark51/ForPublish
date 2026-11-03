"""ForPublish: local-only research topic discovery dashboard (Python stdlib)."""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import sqlite3
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "ForPublish"
VERSION = "0.1.0"
DEFAULT_QUERY = "bioinorganic chemistry iron nitrosyl reaction mechanism"
CROSSREF_URL = "https://api.crossref.org/works"
RESPONSES_URL = "https://api.openai.com/v1/responses"
USER_AGENT = "ForPublish/0.1.0 (research literature discovery; local desktop application)"


def data_dir() -> Path:
    override = os.environ.get("FORPUBLISH_DATA_DIR")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else None
    return Path(base or Path.home() / ".local" / "share") / APP_NAME


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL, query TEXT NOT NULL,
            data TEXT NOT NULL
        )""")


def store_run(path: Path, result: dict) -> int:
    with closing(sqlite3.connect(path)) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO runs(created_at, query, data) VALUES (?, ?, ?)",
            (result["created_at"], result["query"], json.dumps(result, ensure_ascii=False)),
        )
        return int(cursor.lastrowid)


def list_runs(path: Path) -> list[dict]:
    with closing(sqlite3.connect(path)) as conn, conn:
        rows = conn.execute(
            "SELECT id, created_at, query, data FROM runs ORDER BY id DESC LIMIT 100"
        ).fetchall()
    summaries = []
    for run_id, created_at, query, raw in rows:
        run = json.loads(raw)
        summaries.append({"id": run_id, "created_at": created_at, "query": query,
                          "paper_count": len(run.get("papers", [])), "mode": run.get("mode")})
    return summaries


def read_run(path: Path, run_id: int) -> dict | None:
    with closing(sqlite3.connect(path)) as conn, conn:
        row = conn.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    result = json.loads(row[0])
    result["id"] = run_id
    return result


def _year(record: dict) -> int | None:
    for key in ("published", "published-online", "published-print", "issued", "created"):
        parts = record.get(key, {}).get("date-parts", [])
        if parts and parts[0] and isinstance(parts[0][0], int):
            return parts[0][0]
    return None


def normalize_paper(record: dict) -> dict | None:
    doi = str(record.get("DOI", "")).strip()
    title = record.get("title") or []
    title = title[0] if isinstance(title, list) and title else (title if isinstance(title, str) else "")
    if not title or not doi:
        return None
    authors = record.get("author", [])[:5]
    people = ", ".join(" ".join(filter(None, [a.get("given", ""), a.get("family", "")])).strip()
                       for a in authors)
    journal = record.get("container-title") or []
    journal = journal[0] if isinstance(journal, list) and journal else ""
    abstract = re.sub(r"<[^>]+>", " ", record.get("abstract") or "")
    abstract = " ".join(html.unescape(abstract).split())[:1500]
    return {"doi": doi, "title": html.unescape(title), "year": _year(record),
            "authors": people, "journal": html.unescape(journal),
            "abstract": abstract, "url": "https://doi.org/" + urllib.parse.quote(doi, safe="/._-()")}


def fetch_crossref(query: str, limit: int, year_from: int | None, year_to: int | None) -> list[dict]:
    params = {"query.bibliographic": query, "rows": str(limit), "select":
              "DOI,title,author,container-title,published,published-online,published-print,issued,abstract"}
    filters = []
    if year_from is not None:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if year_to is not None:
        filters.append(f"until-pub-date:{year_to}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    url = CROSSREF_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                    "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.load(response)
    seen = set()
    papers = []
    for raw in payload.get("message", {}).get("items", []):
        paper = normalize_paper(raw)
        if paper is None or paper["doi"].lower() in seen:
            continue
        seen.add(paper["doi"].lower())
        papers.append(paper)
    return papers


def generate_ideas(query: str, papers: list[dict]) -> list[dict]:
    """Deterministic research hypotheses; these are suggestions, not literature conclusions."""
    metal = next((m for m in ("Fe", "Co", "Mn", "Ni", "Cu")
                  if re.search(r"\b" + m + r"\b", query, re.I)), "금속")
    topic = query.strip()[:110]
    refs = [p["doi"] for p in papers[:3]]
    ideas = [
        ("스핀 상태와 반응 경로 경쟁", "반응 전후에 가능한 스핀 다중도와 전이상태 상대에너지를 비교하면 경로 선호도가 달라질 수 있다.",
         "가능한 S 값별 opt/freq → 동일 기준의 single-point energy → TS 및 IRC로 경로를 검증합니다."),
        ("리간드 전자 효과와 반응 장벽", f"{metal} 중심의 리간드 전자 공여성을 변화시키면 {topic} 관련 장벽이 달라질 수 있다.",
         "배위 환경을 유지한 치환체 쌍을 설계하고 ΔG‡, 결합 길이, 스핀 밀도를 비교합니다."),
        ("경쟁적인 결합 활성화 선택성", "유사한 조건에서 가능한 두 결합 활성화 경로의 상대 에너지가 선택성을 좌우할 수 있다.",
         "두 반응 좌표의 TS/IRC를 탐색하고 생성물 및 속도론적 우세 여부를 함께 평가합니다."),
        ("용매 및 양성자화 상태 민감도", "용매 극성이나 양성자화 위치에 따라 중간체 안정성과 반응 순서가 변할 수 있다.",
         "CPCM 조건과 가능한 protonation site를 교차 비교하되 기준 상태와 화학양론을 명확히 맞춥니다."),
    ]
    return [{"title": title, "hypothesis": hypothesis, "validation": validation,
             "related_dois": refs[:2], "status": "검증 전 가설"}
            for title, hypothesis, validation in ideas]


def openai_analysis(api_key: str, model: str, query: str, papers: list[dict]) -> tuple[str, dict]:
    context = [{"title": p["title"], "doi": p["doi"], "year": p["year"],
                "abstract_excerpt": p["abstract"][:420]} for p in papers[:12]]
    prompt = ("다음은 Crossref의 검색 결과입니다. 제공된 정보만 근거로 연구 주제 3개를 한국어로 제안하세요. "
              "각 주제마다 (1) 가설 (2) 차별성 검증에 필요한 문헌검토 (3) DFT 계산 계획 "
              "(4) 관련 DOI (5) 불확실성을 명시하세요. 제목과 초록에 없는 사실을 단정하지 마세요. "
              "참고 DOI를 생성하거나 만들어내면 안 됩니다.\n\n"
              + json.dumps({"query": query, "papers": context}, ensure_ascii=False))
    data = json.dumps({"model": model, "instructions": "You are a careful computational bioinorganic chemistry research assistant.",
                       "input": prompt, "max_output_tokens": 1500}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(RESPONSES_URL, data=data, method="POST", headers={
        "Authorization": "Bearer " + api_key, "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as response:
        payload = json.load(response)
    pieces = []
    for item in payload.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "output_text":
                pieces.append(part.get("text", ""))
    answer = "\n".join(pieces) or str(payload.get("output_text", ""))
    if not answer:
        raise ValueError("AI 응답에서 텍스트를 찾지 못했습니다.")
    return answer, payload.get("usage", {})


def parse_options(params: dict) -> tuple[str, int, int | None, int | None, str, str]:
    query = str(params.get("query", "")).strip()
    if not (3 <= len(query) <= 400):
        raise ValueError("검색어는 3~400자로 입력하세요.")
    limit = int(params.get("limit", 15))
    if not 1 <= limit <= 50:
        raise ValueError("논문 수는 1~50편으로 지정하세요.")
    year_from = int(params["year_from"]) if params.get("year_from") else None
    year_to = int(params["year_to"]) if params.get("year_to") else None
    if (year_from and not 1900 <= year_from <= 2100) or (year_to and not 1900 <= year_to <= 2100):
        raise ValueError("연도는 1900~2100 사이여야 합니다.")
    if year_from and year_to and year_from > year_to:
        raise ValueError("시작 연도가 종료 연도보다 큽니다.")
    model = str(params.get("model", "gpt-5-mini")).strip()
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,80}", model):
        raise ValueError("AI 모델 이름 형식이 올바르지 않습니다.")
    api_key = str(params.get("api_key", "")).strip()
    return query, limit, year_from, year_to, model, api_key


def run_research(params: dict, path: Path) -> dict:
    query, limit, start, end, model, key = parse_options(params)
    papers = fetch_crossref(query, limit, start, end)
    result = {"query": query, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "filters": {"limit": limit, "year_from": start, "year_to": end},
              "source": "Crossref (https://www.crossref.org/)",
              "mode": "AI+heuristic" if key else "heuristic", "papers": papers,
              "ideas": generate_ideas(query, papers), "ai_analysis": "", "ai_usage": {}}
    if key and papers:
        result["ai_analysis"], result["ai_usage"] = openai_analysis(key, model, query, papers)
        result["ai_model"] = model
    result["id"] = store_run(path, result)
    return result


def export_csv(result: dict) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Title", "Year", "Journal", "Authors", "DOI", "URL", "Abstract"])
    for p in result["papers"]:
        writer.writerow([p["title"], p["year"], p["journal"], p["authors"],
                         p["doi"], p["url"], p["abstract"]])
    return output.getvalue().encode("utf-8-sig")


PAGE = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ForPublish · Research Topic Lab</title>
<style>
:root{font-family:Inter,"Malgun Gothic",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1f2a37;background:#f4f6fa}*{box-sizing:border-box}body{margin:0}header{background:#101d32;color:#f5f8fb;padding:24px 5.5%}header .small{letter-spacing:.13em;font-size:11px;color:#88aeff;font-weight:700}header h1{margin:5px 0 5px;font-size:26px}header p{margin:0;color:#bdc9dd;font-size:13px}main{max-width:1280px;padding:24px 22px 50px;margin:auto;display:grid;grid-template-columns:minmax(0,1fr) 288px;gap:22px}.card{background:white;border:1px solid #e1e7f0;border-radius:14px;box-shadow:0 4px 18px #101d3209;padding:22px;margin-bottom:18px}h2{font-size:17px;margin:0 0 18px}h3{font-size:15px;margin:0 0 8px}.muted,.foot{color:#6a788c;font-size:12px}.row{display:flex;gap:12px;flex-wrap:wrap}.form-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}.field{margin-bottom:12px;min-width:0}.field label{font-size:12px;font-weight:700;display:block;margin-bottom:7px;color:#46536a}input{font-family:inherit;font-size:14px;padding:10px 12px;width:100%;border:1px solid #d4ddea;border-radius:8px;color:#223248;background:#fff}input:focus{outline:2px solid #adc8fa;border-color:#528ef6}.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.chip{background:#eff4ff;border:1px solid #dbe6fc;color:#2e5ba3;font-size:12px;border-radius:20px;padding:6px 10px;cursor:pointer}.button{border:0;padding:11px 18px;border-radius:9px;background:#2468d9;color:white;cursor:pointer;font-weight:700}.button:disabled{opacity:.5;cursor:wait}.button.secondary{background:#e9eff9;color:#274067}.button:hover:not(:disabled){filter:brightness(.95)}.toggle{display:flex;align-items:center;gap:9px;margin:10px 0 16px;font-size:13px}.toggle input{width:auto}.danger{color:#ad2737}#status{font-size:13px;margin-top:12px;min-height:20px}.split-head{display:flex;justify-content:space-between;gap:16px;align-items:center}.metric{background:#f4f7fc;padding:14px;border-radius:10px;flex:1;min-width:120px}.metric b{font-size:20px;display:block}.idea{border-left:3px solid #2d73de;padding:12px 16px;margin:14px 0;background:#f7faff;border-radius:0 9px 9px 0}.idea p,.paper p{font-size:13px;line-height:1.75;margin:5px 0}.paper{padding:15px 0;border-bottom:1px solid #edf0f6}.paper:last-child{border:0}.paper .meta{font-size:12px;color:#6a788c;margin:4px 0}.paper a{color:#1e61b6;overflow-wrap:anywhere;text-decoration:none;font-weight:650}.history-btn{background:none;border:0;border-bottom:1px solid #e6eaf2;text-align:left;padding:12px 0;width:100%;cursor:pointer;color:#263e62}.history-btn b{display:block;font-size:12px;margin-bottom:4px}.history-btn span{display:block;font-size:11px;color:#78879e}pre{white-space:pre-wrap;word-break:break-word;font:13px/1.7 inherit}.empty{border:1px dashed #ccd6e5;border-radius:12px;padding:36px;color:#7f8ba0;text-align:center}.badge{display:inline-block;background:#edf6f1;color:#167a48;font-size:11px;padding:4px 7px;border-radius:7px}.ai-card{white-space:pre-wrap;line-height:1.7;font-size:13px;background:#f5f8ff;border-radius:9px;padding:16px}footer{max-width:1280px;margin:auto;padding:0 24px 40px;font-size:12px;color:#7b8798}@media(max-width:850px){main{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr 1fr}}@media(max-width:480px){main{padding:12px}.form-grid{grid-template-columns:1fr}.card{padding:15px}header{padding:20px}}
</style></head><body>
<header><div class="small">COMPUTATIONAL BIOINORGANIC CHEMISTRY</div><h1>ForPublish <span style="font-weight:400;color:#94b8ff">/ Research Topic Lab</span></h1><p>실제 문헌의 DOI를 확인하고, 계산화학 연구 가설과 검증 계획을 축적합니다.</p></header>
<main><section><div class="card"><h2>문헌 탐색 설정</h2><form id="searchForm">
<div class="field"><label for="query">연구 주제 / 검색어</label><input id="query" value="bioinorganic chemistry iron nitrosyl reaction mechanism" required minlength="3"></div>
<div class="chips"><button type="button" class="chip" data-query="Fe nitrosyl nitrite proton coupled electron transfer">Fe–NO / PCET</button><button type="button" class="chip" data-query="Mn(III) peroxo ligand ring size ketone">Mn–peroxo / Ring size</button><button type="button" class="chip" data-query="cobalt peroxyhemiacetal oxidative deformylation mechanism">Co–peroxyhemiacetal</button><button type="button" class="chip" data-query="nonheme iron oxo hydrogen atom abstraction">Fe(IV)=O / HAA</button></div>
<div class="form-grid" style="margin-top:16px"><div class="field"><label for="limit">검색 논문 수 (1–50)</label><input id="limit" type="number" value="15" min="1" max="50"></div><div class="field"><label for="from">발행 연도 시작</label><input id="from" type="number" min="1900" max="2100" placeholder="예: 2018"></div><div class="field"><label for="to">발행 연도 종료</label><input id="to" type="number" min="1900" max="2100" placeholder="예: 2026"></div></div>
<label class="toggle"><input type="checkbox" id="ai"> OpenAI API로 연구 가설 상세 분석 (선택 사항 · 유료)</label>
<div id="aiFields" hidden><div class="row"><div class="field" style="flex:2;min-width:200px"><label for="key">API 키 (저장되지 않음)</label><input id="key" type="password" autocomplete="off" placeholder="sk-..."></div><div class="field" style="flex:1;min-width:150px"><label for="model">모델</label><input id="model" value="gpt-5-mini"></div></div><p class="muted">선택 시 논문 제목·초록 일부·DOI가 OpenAI API로 전송됩니다. 사용량에 따른 API 요금이 발생합니다.</p></div>
<button class="button" id="run" type="submit">논문 검색 및 가설 생성</button><span style="margin-left:10px" class="muted">출처: Crossref · 로컬 SQLite 저장</span><div id="status" aria-live="polite"></div></form></div>
<div class="card"><div class="split-head"><h2>연구 주제 제안</h2><span class="badge">검증 전 가설</span></div><div id="ideas"><div class="empty">검색을 실행하면 실험·계산 계획이 이곳에 표시됩니다.</div></div><div id="aiResult"></div></div>
<div class="card"><div class="split-head"><h2>근거 문헌</h2><div class="row"><button type="button" id="jsonExport" class="button secondary" disabled>JSON</button><button type="button" id="csvExport" class="button secondary" disabled>CSV</button></div></div><div id="paperCount" class="muted"></div><div id="papers"><div class="empty">검색한 논문 제목·저널·연도·DOI를 확인할 수 있습니다.</div></div></div></section>
<aside><div class="card"><h2>연구 기록</h2><p class="muted">최대 최근 100개의 검색 기록이 이 PC에 저장됩니다.</p><div id="history">불러오는 중…</div></div><div class="card"><h2>데이터 및 개인정보</h2><p class="muted">대시보드는 127.0.0.1에서만 실행됩니다. 문헌 검색어는 Crossref로, AI 분석을 켠 경우 선택한 논문 정보는 OpenAI로 전송됩니다.</p><p class="muted">가설은 아이디어 단계이며, 선행 연구의 부재나 신규성을 보증하지 않습니다. 실제 논문을 검토하고 계산으로 검증하세요.</p><p class="muted">API 키는 요청 중에만 사용하며 기록 DB에 저장되지 않습니다.</p></div></aside></main><footer>ForPublish v0.1.0 · 1차 연구 주제 발굴 도구 · 로컬 저장 경로는 실행 환경의 사용자 데이터 디렉터리</footer>
<script>
const $=id=>document.getElementById(id);let current=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const post=(url,obj)=>fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(obj)}).then(async r=>{let d=await r.json();if(!r.ok)throw Error(d.error||'요청 실패');return d});
const status=(message,error=false)=>{$('status').textContent=message;$('status').className=error?'danger':''};
async function loadHistory(){try{const runs=await (await fetch('/api/runs')).json();$('history').innerHTML=runs.length?runs.map(r=>`<button class="history-btn" data-id="${r.id}"><b>${esc(r.query)}</b><span>${esc(r.created_at.slice(0,16).replace('T',' '))} UTC · ${r.paper_count}편</span></button>`).join(''):'<p class="muted">기록이 없습니다.</p>';document.querySelectorAll('[data-id]').forEach(x=>x.onclick=()=>loadRun(x.dataset.id));}catch(e){$('history').textContent=e.message}}
function render(r){current=r;$('paperCount').textContent=`${r.papers.length}편 · ${r.source} · ${r.mode}`;
$('ideas').innerHTML=r.ideas.map(i=>`<div class="idea"><h3>${esc(i.title)}</h3><p><b>가설</b> · ${esc(i.hypothesis)}</p><p><b>검증 계산</b> · ${esc(i.validation)}</p><p class="muted">관련 DOI: ${i.related_dois.map(esc).join(' / ')||'없음'} · ${esc(i.status)}</p></div>`).join('');
$('aiResult').innerHTML=r.ai_analysis?`<h3 style="margin:20px 0 10px">AI 문헌 기반 제안 · ${esc(r.ai_model)}</h3><div class="ai-card">${esc(r.ai_analysis)}</div>`:'';
$('papers').innerHTML=r.papers.length?r.papers.map((p,i)=>`<article class="paper"><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${i+1}. ${esc(p.title)}</a><div class="meta">${esc(p.authors)} · ${esc(p.journal)} · ${esc(p.year||'연도 미상')}</div><div class="meta">DOI: ${esc(p.doi)}</div>${p.abstract?`<p>${esc(p.abstract)}</p>`:''}</article>`).join(''):'<div class="empty">검색 결과가 없습니다. 검색어 또는 연도 범위를 조정하세요.</div>';
$('jsonExport').disabled=false;$('csvExport').disabled=false;}
async function loadRun(id){try{let r=await fetch('/api/runs/'+id);if(!r.ok)throw Error('기록을 불러오지 못했습니다.');render(await r.json());status('저장된 검색 기록을 불러왔습니다.')}catch(e){status(e.message,true)}}
$('searchForm').onsubmit=async e=>{e.preventDefault();let b=$('run');b.disabled=true;status('Crossref 문헌을 검색하고 가설을 작성하는 중…');const options={query:$('query').value,limit:Number($('limit').value),year_from:$('from').value,year_to:$('to').value,model:$('model').value,api_key:$('ai').checked?$('key').value:''};try{if($('ai').checked&&!options.api_key)throw Error('AI 분석을 위해 API 키를 입력하세요.');const r=await post('/api/research',options);render(r);status(`검색 및 저장 완료 · ${r.papers.length}편`);await loadHistory()}catch(err){status(err.message,true)}finally{b.disabled=false}};
$('ai').onchange=()=>{$('aiFields').hidden=!$('ai').checked};document.querySelectorAll('[data-query]').forEach(c=>c.onclick=()=>{$('query').value=c.dataset.query});
function download(format){if(!current)return;window.location.href='/api/runs/'+current.id+'/export.'+format;}
$('jsonExport').onclick=()=>download('json');$('csvExport').onclick=()=>download('csv');loadHistory();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    database: Path

    def log_message(self, fmt: str, *args: object) -> None:
        # Never log request bodies or credentials.
        if sys.stdout is not None:  # PyInstaller --noconsole sets stdout to None on Windows.
            print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_bytes(self, payload: bytes, status: int = 200, mime: str = "application/json; charset=utf-8",
                   filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, value: object, status: int = 200) -> None:
        self.send_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"), status)

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            self.send_bytes(PAGE.encode("utf-8"), mime="text/html; charset=utf-8")
            return
        if path == "/api/health":
            self.send_json({"ok": True, "version": VERSION})
            return
        if path == "/api/runs":
            self.send_json(list_runs(self.database))
            return
        match = re.fullmatch(r"/api/runs/(\d+)(?:/export\.(json|csv))?", path)
        if match:
            result = read_run(self.database, int(match.group(1)))
            if result is None:
                self.send_json({"error": "기록을 찾을 수 없습니다."}, 404)
            elif match.group(2) == "csv":
                self.send_bytes(export_csv(result), mime="text/csv; charset=utf-8", filename="ForPublish-papers.csv")
            elif match.group(2) == "json":
                self.send_bytes(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
                                filename="ForPublish-research.json")
            else:
                self.send_json(result)
            return
        self.send_json({"error": "페이지를 찾을 수 없습니다."}, 404)

    def do_POST(self) -> None:
        if self.path != "/api/research":
            self.send_json({"error": "페이지를 찾을 수 없습니다."}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 20000:
                raise ValueError("요청 크기가 올바르지 않습니다.")
            options = json.loads(self.rfile.read(length))
            if not isinstance(options, dict):
                raise ValueError("JSON 객체를 보내야 합니다.")
            self.send_json(run_research(options, self.database))
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            self.send_json({"error": str(e)}, 400)
        except urllib.error.HTTPError as e:
            self.send_json({"error": f"외부 API 오류 (HTTP {e.code}). 키, 쿼리 또는 사용량을 확인하세요."}, 502)
        except (urllib.error.URLError, TimeoutError) as e:
            self.send_json({"error": f"외부 API에 연결할 수 없습니다: {type(e).__name__}"}, 502)
        except Exception:
            self.send_json({"error": "서버 오류가 발생했습니다. 실행 로그를 확인하세요."}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="ForPublish local research dashboard")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    db_path = data_dir() / "research.sqlite3"
    initialize_database(db_path)
    server_type = type("LocalHandler", (Handler,), {"database": db_path})
    server = ThreadingHTTPServer(("127.0.0.1", args.port), server_type)
    address = f"http://127.0.0.1:{server.server_address[1]}/"
    if sys.stdout is not None:
        print(f"{APP_NAME} {VERSION} → {address}\nData: {db_path}", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()