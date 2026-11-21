# 공식 자료와 유지보수

2026-11-21 설치 경로 구분: [Codex 플러그인 패키지](https://developers.openai.com/plugins/build/plugins), [Claude Code 플러그인](https://code.claude.com/docs/en/plugins), [Vibe 플러그인](https://docs.mistral.ai/vibe/code/cli/plugins), [OpenCode 플러그인](https://opencode.ai/docs/plugins)의 네이티브 패키지·관리 방식은 현재 키트의 전역 스킬·역할 설치기와 별개다. README는 각 클라이언트 안에서 에이전트에게 전체 설치를 요청하는 방식을 먼저 안내하며 미제공 마켓플레이스 명령을 안내하지 않는다.

2026-11-21 대화형 진입 확인: [Codex 개발 명령](https://learn.chatgpt.com/docs/developer-commands?surface=cli)의 `/skills`와 [모델 선택](https://learn.chatgpt.com/docs/models?surface=cli)의 `/model`을 구분한다. `$static-analysis-kit`은 설치한 스킬 호출이며 키트가 새 내장 slash 명령이나 현재 대화의 모델 전환 API를 제공한다고 가정하지 않는다.

2026-11-21 설치 배포 확인: [Codex skills](https://developers.openai.com/codex/skills), [Codex subagents](https://developers.openai.com/codex/subagents), [Claude skills](https://code.claude.com/docs/en/skills), [Claude subagents](https://code.claude.com/docs/en/sub-agents), [Vibe skills](https://docs.mistral.ai/vibe/code/cli/skills), [Vibe agents](https://docs.mistral.ai/vibe/code/cli/agents), [OpenCode skills](https://opencode.ai/docs/skills/), [OpenCode agents](https://opencode.ai/docs/agents/)의 사용자 전역 발견 경로를 사용한다. 런타임 자동 준비는 [uv 공식 설치](https://docs.astral.sh/uv/getting-started/installation/)와 [환경변수](https://docs.astral.sh/uv/reference/environment/)의 독립 설치·Python 저장 위치를 따른다. 실제 계정별 기능 적용은 별도 확인한다.

문서 확인 기준일: 2026-11-20, Asia/Seoul. 어댑터는 확인한 설정 형식을 사용하며 모든 과거·미래 클라이언트에 같은 구문을 보장하지 않는다. 실행할 때 설치된 CLI 버전·도움말·설정 로딩 결과를 확인한다. 초기 작성 환경에서 확인한 Codex CLI 버전은 `0.164.0-alpha.11.1`이었다. 이는 Codex에 한정된 환경 기록이며 다른 클라이언트의 버전이나 현재 실행 검증을 뜻하지 않는다.

| 자료 | 이 키트에서 확인한 사항 |
| --- | --- |
| [Agent Skills 명세](https://agentskills.io/specification) | 공통 SKILL.md 형식, 환경 요구사항 메타데이터와 상대 참조 |
| [Claude Code 지침](https://code.claude.com/docs/en/memory#agents-md) | AGENTS.md 직접 로딩 조건과 CLAUDE.md import |
| [Claude Code Skills](https://code.claude.com/docs/en/skills) | .claude/skills 발견과 표준·확장 필드 구분 |
| [Claude Code 하위 에이전트](https://code.claude.com/docs/en/sub-agents) | Markdown 정의, 모델 선택과 컨텍스트·권한 |
| [Vibe 설정](https://docs.mistral.ai/vibe/code/cli/configuration) | 프로젝트·사용자 설정, trust와 추가 디렉터리의 의미 |
| [Vibe 에이전트](https://docs.mistral.ai/vibe/code/cli/agents) | TOML 역할 정의와 모델·도구 범위 |
| [Vibe Skills](https://docs.mistral.ai/vibe/code/cli/skills) | .agents/skills 발견과 allowed-tools의 비강제성 |
| [Vibe 설정 명세](https://docs.mistral.ai/vibe/code/cli/configuration-reference) | 공급자·모델 별칭과 네이티브 옵션 |
| [OpenCode V1 에이전트 원본](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/web/src/content/docs/agents.mdx) | V1 호환 agent Markdown과 모델 참조 |
| [OpenCode V1 Skills 원본](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/web/src/content/docs/skills.mdx) | .agents/skills 및 .opencode/skills 탐색 |
| [OpenCode V1→V2 안내](https://opencode.ai/docs/migrate-v1/) | 지원 V1 설정의 호환성, V2 전용 구문·플러그인 차이 |
| [Codex 사용자화](https://learn.chatgpt.com/docs/customization/overview) | AGENTS, skills, MCP의 역할 구분 |
| [Skills 작성](https://learn.chatgpt.com/docs/build-skills) | `.agents/skills` 발견과 수동·자동 호출 |
| [하위 에이전트](https://learn.chatgpt.com/docs/agent-configuration/subagents) | standalone `.codex/agents/*.toml`의 필수 필드와 모델 설정, 호스트 권한 상속 |
| [Codex Security 설치](https://learn.chatgpt.com/docs/security/plugin) | 로컬 플러그인과 새 세션 적용, 결과 해석 |
| [Codex Security 스캔](https://learn.chatgpt.com/docs/security/plugin/scans) | Codebase 범위, 보안 컨텍스트, 소스 기반 근거 |
| [반복 스캔](https://learn.chatgpt.com/docs/security/plugin/deep-scans) | 반복 조사와 남을 수 있는 검토 공백 |
| [CodeQL 데이터 흐름](https://codeql.github.com/docs/writing-codeql-queries/about-data-flow-analysis/) | 함수 내·함수 간 데이터 흐름과 모델링 한계 |
| [Semgrep taint](https://docs.semgrep.dev/writing-rules/data-flow/taint-mode/overview) | source·propagator·sink와 지원 범위 |
| [OWASP 코드 리뷰](https://cheatsheetseries.owasp.org/cheatsheets/Secure_Code_Review_Cheat_Sheet.html) | 맥락·업무 속성·배포 검토의 중요성 |

각 조사의 근거는 해당 대상의 소스·설정·버전에서 확인한다. 과거 조사 결과나 세션 기록을 참고하더라도 새 대상에 대한 사실과 판정은 별도로 검증한다.

공식 문서의 설정 지원과 이 키트에서 실제 실행해 검증한 조합은 구별한다. 클라이언트·설정 형식의 버전 기준은 어댑터에, 수행한 시험과 미검증 조건은 [VALIDATION.md](../VALIDATION.md)에 기록한다.

업데이트 시 특정 장애를 막기 위한 룰을 계속 덧붙이기보다 실제 실패 원인, 적용 범위, 반례를 검토해 필요한 최소 지침을 수정한다. 도구와 모델 관련 사실은 공식 자료로 다시 확인하고 변경한 근거를 이 파일과 해당 조사에 남긴다.

## 전체 유형과 준비 자료

추가 확인일: 2026-11-21, Asia/Seoul.

| 자료 | 적용 범위 |
| --- | --- |
| [MITRE CWE 다운로드](https://cwe.mitre.org/data/downloads.html), [전체 XML](https://cwe.mitre.org/data/xml/cwec_latest.xml.zip) | 전체 weakness 분류를 내려받아 버전·원본 SHA-256를 고정하고 스택별 적용 여부를 전수 대조. Top-N·언어별 view는 전체 분류의 대체물이 아님 |
| [OWASP ASVS 다운로드](https://asvs.owasp.org/downloads/) | 웹 애플리케이션·서비스의 보안 요구사항 자료. 웹 이외의 스택·업무·호스트·권한 경계는 관련 공식 자료와 시스템 불변조건으로 추가 검토 |

`latest`는 조사 준비 시 다운로드 위치이며 버전 고정을 뜻하지 않는다. `workspace.py cwe`가 실제 XML 버전·해시·다운로드 시점을 조사별로 기록한다. 전체 분류 대조와 모든 미지의 취약점 발견 보장은 구별한다.
