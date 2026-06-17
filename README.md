# 박부장 — 아저씨 말투 챗봇

40대 후반~60대 초반 남성의 인터넷 커뮤니티 말투를 **캐릭터화**한 챗봇이다.
실존 인물을 흉내 내지 않는다. "정 많은 동네 부장님 / 멘토 아저씨"라는 **가상 캐릭터**다.

말투 특징:
- 마침표(`.`)를 어색하거나 과하게
- 띄어쓰기가 불규칙
- 훈계 반 조언 반, 회상/경험형 표현 ("내가 해보니", "왕년에", "요즘 젊은 친구들은")
- 가끔 한자어 병기 (건강(健康), 책임(責任))
- **아재개그(말장난)** — 문맥이 맞을 때만 자연스럽게 끼워 넣는다

## 바로 써보기

```powershell
python app.py
```

→ 브라우저에서 http://127.0.0.1:8000

- 입력창에 질문 입력 (예: `운동 시작하려는데 뭐부터 하지`)
- 말투 강도 조절 없이 항상 박춘배 톤으로 답한다.

LLM 설정이 없거나 실패하면 자동 대체 답변 없이 오류만 반환한다.

## LLM 설정

자세한 건 [`llm.env.example`](llm.env.example).

```powershell
# 예) Google Gemini 무료 키: https://aistudio.google.com/apikey
$env:LLM_PROVIDER="gemini"
$env:LLM_API_KEY="발급받은_키"
python app.py
```

`LLM_PROVIDER` 는 `gemini` / `groq` / `openrouter` / `ollama` 를 지원한다.
프로바이더만 정하면 엔드포인트·기본 모델이 자동으로 채워진다.

## 답 생성 방식 (요구사항 그대로)

```
사용자 입력
  → Safety Filter        위협/집단비하 요청 거절, 개인정보 마스킹  (safety_filter.py)
  → Base Answer Generator LLM 전용                              (chatbot.py / llm_client.py)
  → Character Styling     마침표/띄어쓰기/한자/문맥형 아재개그       (style_engine.py)
  → Safety Filter         출력 한 번 더 정제
  → 응답
```

- **원문 데이터를 LLM 에 그대로 넣지 않는다.** [`prompt_builder.py`](prompt_builder.py) 가
  페르소나([`persona/profile.json`](persona/profile.json)) + 학습된 **문체 지표**(`analysis/style_model.json`)
  만 요약해 시스템 프롬프트를 자동 생성한다.
- 아재개그는 답변 문맥의 키워드가 맞을 때만 삽입한다.

## 데이터 수집 (선택)

공개 커뮤니티 글/댓글을 모아 문체 지표를 학습할 수 있다. **법/약관 준수가 전제다.**

- `collector.py` 는 **매 요청마다 robots.txt 를 확인**하고, 막히면 수집하지 않는다.
- 개인정보(이메일·전화·계좌·주소·차량번호·닉네임)는 **수집 시점에 즉시 마스킹**된다([`clean_text.py`](clean_text.py)).
- `sites.yaml` 의 대상은 기본값이 모두 `terms_ok: false` 다. **약관/robots 확인 후 직접 `true` 로** 바꿔야 돈다.

```powershell
# 1) sites.yaml 에서 수집 허용 확인된 사이트만 terms_ok: true 로 변경
python collector.py --config sites.yaml --db data/style_corpus.sqlite --target-records 1000000
# 2) (raw -> 정제 JSONL 이 필요하면) python clean_text.py
# 3) DB 기반 문체 재학습
python train_style_model.py --db data/style_corpus.sqlite
python app.py
```

저장 필드: `source_site`, `post_url`, `content_type`(post/comment), `text`, `text_length` 등.
실패는 `logs/collector_failures.jsonl` 에 남는다. JS 렌더링이 필요한 사이트는 대상에
`render_js: true` (Playwright 설치 필요).

> 100만 건 같은 대량 수집은 **수집을 허용하는 사이트에서, 약관을 지키며** 충분한 시간을 두고
> 돌려야 한다. 본 저장소는 그게 없어도 파이프라인이 즉시 돌아가도록 합성 시드
> ([`setup_corpus.py`](setup_corpus.py))를 제공한다. 시드는 실제 글을 베낀 게 아니라
> 문체 지표를 보여주려고 직접 작성한 예시이며 개인정보가 없다.

## 문체 분석

```powershell
python style_features.py   # data/processed/clean_text.jsonl -> analysis/style_report.md, style_features.json
```

리포트는 마침표/물음표 빈도, 불규칙 띄어쓰기, 한자 병기, 회상/경험형 표현, 종결어미 등
**지표만** 담는다. 원문 문장을 길게 인용하지 않는다.

## 안전·윤리

- 특정 집단/소수자 혐오·비하, 선동, 위협, 실존 인물 흉내, 개인정보 노출, 과도한 욕설을 금지한다.
- 입력과 출력 양쪽에서 Safety Filter 가 동작한다.
- 수집/학습에는 **안전 정제 버전만** 사용한다.

## 파일 구조

| 파일 | 역할 |
| --- | --- |
| `app.py` | 로컬 웹 서버 (UI + API) |
| `web/` | 채팅 UI |
| `chatbot.py` | 파이프라인 (Safety → 생성 → 스타일링 → Safety) |
| `prompt_builder.py` | 페르소나+문체지표 기반 시스템 프롬프트 자동 생성 |
| `llm_client.py` | OpenAI 호환 LLM 클라이언트 (무료 프로바이더 프리셋) |
| `style_engine.py` | 캐릭터 스타일링 (마침표/띄어쓰기/한자/아재개그) |
| `safety_filter.py` | 안전 필터 (위협/비하/개인정보) |
| `collector.py` `config.py` `html_text.py` | robots.txt 준수 수집기 |
| `clean_text.py` | PII 마스킹 + 안전 정제 |
| `database.py` | SQLite 코퍼스 저장 |
| `style_features.py` `train_style_model.py` | 문체 지표 추출·학습 |
| `setup_corpus.py` | 시드 → DB → 학습 원클릭 |
| `tests/` | 단위 테스트 |

## 테스트

```powershell
python -m unittest discover -s tests -p "test_*.py"
```
