# ForPublish — 연구 주제 발굴 에이전트

Windows에서 실행하는 **로컬 연구 문헌 탐색 및 DFT 연구 주제 발굴 대시보드**입니다. GitHub Actions에서 Windows EXE를 빌드하므로 Python을 별도로 설치하지 않아도 됩니다.

## 첫 설치 (Windows)

1. [Windows build Actions](https://github.com/Skylark51/ForPublish/actions/workflows/windows-build.yml)에서 **main** 브랜치의 최신 성공 실행을 엽니다.
2. Artifacts의 **ForPublish-Windows**를 내려받아 ZIP을 풉니다.
3. `ForPublish.exe`를 실행합니다. 기본 브라우저가 `http://127.0.0.1:8765/`을 엽니다. Windows SmartScreen이 확인을 요청할 수 있습니다. 소스와 Actions 빌드를 확인한 뒤 실행하세요.
4. 데이터는 `%LOCALAPPDATA%\ForPublish\research.sqlite3`에 자동 저장됩니다. 프로그램을 종료하려면 EXE 프로세스를 종료합니다.

## GitHub에서 업데이트

GitHub CLI와 Git이 없다면 PowerShell에서 다음을 **한 번** 실행합니다.

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
gh auth login
```

그다음 원하는 폴더로 이동하여 처음 한 번 복제합니다.

```powershell
cd "$HOME\Documents"
git clone https://github.com/Skylark51/ForPublish.git
cd ForPublish
.\scripts\update-local.ps1
.\ForPublish.exe
```

다음 업데이트부터는 실행 중인 EXE를 닫고 이 프로젝트 폴더에서 다음을 실행합니다.

```powershell
git pull --ff-only origin main
.\scripts\update-local.ps1
.\ForPublish.exe
```

스크립트는 **main** 브랜치에서 성공한 최근 GitHub Actions 빌드 파일을 다운로드합니다. 이전 EXE가 있으면 `backups/`에 백업합니다. GitHub Actions artifact 보존 기간은 30일입니다.

## 동작

- Crossref에서 실제 DOI가 있는 문헌 최대 50편을 검색합니다. 키워드, 발행 연도, 논문 수를 지정할 수 있습니다.
- 문헌의 제목·저널·DOI를 확인하고, DFT로 검증할 만한 예비 가설 4개를 제시합니다.
- 선택 사항으로 OpenAI Responses API에 DOI·제목·초록 발췌를 전송해 상세 가설을 작성합니다. **API 키가 필요하며 별도 사용료**가 청구될 수 있습니다. ChatGPT 구독료에 포함되지 않습니다. 모델별 비용은 [공식 API 가격](https://openai.com/api/pricing/)을 확인하세요.
- 연구 기록을 로컬 SQLite에 저장하고, 논문 목록을 CSV 및 전체 기록을 JSON으로 내보낼 수 있습니다.
- 제공된 논문 결과는 완전한 선행연구 조사에 해당하지 않습니다. **신규성·선행연구 부재·메커니즘은 추가 문헌조사와 계산으로 검증**해야 합니다.

## 데이터·보안

대시보드 서버는 `127.0.0.1`에만 바인딩합니다. 검색어는 Crossref에 전송됩니다. AI 분석을 활성화한 경우에만 일부 논문 메타데이터가 OpenAI API에 전송됩니다. API 키는 DB에 저장하지 않습니다. 검색 기록 및 분석 텍스트는 사용자 PC에 저장됩니다. 온라인 검색이 필요하므로 완전 오프라인에서는 신규 문헌 검색이 되지 않습니다.

## 개발 및 검증

Python 3.12 환경에서 다음을 실행할 수 있습니다. 실행 환경에 별도 Python 패키지는 필요하지 않습니다.

```powershell
python -m unittest discover -s tests -v
python app.py
```

Windows EXE는 `.github/workflows/windows-build.yml`의 PyInstaller 빌드에서 생성합니다.

> 상태: 초기 버전 0.1.0. 실제 연구용 자동 서버 계산(Gaussian/ORCA) 제출은 포함되어 있지 않습니다. 기능 변경은 문헌 검증과 데이터 모델 확장 후 단계적으로 진행할 수 있습니다.
