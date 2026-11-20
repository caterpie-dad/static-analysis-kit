# 공식 자료와 유지보수

구성 작성 기준일: 2026-11-20, Asia/Seoul. 호스트에서 확인한 CLI는 `0.164.0-alpha.11.1`이다. 이 키트가 모든 과거·미래 클라이언트에 같은 설정 구문을 보장하지 않는다. 실행할 때 현재 CLI 도움말과 공식 문서를 확인한다.

| 자료 | 이 키트에서 확인한 사항 |
| --- | --- |
| [Codex 사용자화](https://learn.chatgpt.com/docs/customization/overview) | AGENTS, skills, MCP의 역할 구분 |
| [Skills 작성](https://learn.chatgpt.com/docs/build-skills) | `.agents/skills` 발견과 수동·자동 호출 |
| [하위 에이전트](https://learn.chatgpt.com/docs/agent-configuration/subagents) | standalone `.codex/agents/*.toml`의 필수 필드와 모델 설정, 호스트 권한 상속 |
| [Codex Security 설치](https://learn.chatgpt.com/docs/security/plugin) | 로컬 플러그인과 새 세션 적용, 결과 해석 |
| [Codex Security 스캔](https://learn.chatgpt.com/docs/security/plugin/scans) | Codebase 범위, 보안 컨텍스트, 소스 기반 근거 |
| [반복 스캔](https://learn.chatgpt.com/docs/security/plugin/deep-scans) | 반복 조사와 남을 수 있는 검토 공백 |
| [CodeQL 데이터 흐름](https://codeql.github.com/docs/writing-codeql-queries/about-data-flow-analysis/) | 함수 내·함수 간 데이터 흐름과 모델링 한계 |
| [Semgrep taint](https://docs.semgrep.dev/writing-rules/data-flow/taint-mode/overview) | source·propagator·sink와 지원 범위 |
| [OWASP 코드 리뷰](https://cheatsheetseries.owasp.org/cheatsheets/Secure_Code_Review_Cheat_Sheet.html) | 맥락·업무 속성·배포 검토의 중요성 |

이 키트는 Dynamo의 특정 취약점이나 모델 세션 기록을 새 대상의 증거로 재사용하지 않는다. 기존 연구에서 얻은 원칙인 신뢰 가정의 코드 대조, 전제조건 명시, 반증, 전체 경로 근거, 미분석 영역 보존을 일반적인 조사 계약으로 반영했다.

업데이트 시 특정 장애를 막기 위한 룰을 계속 덧붙이기보다 실제 실패 원인, 적용 범위, 반례를 검토해 필요한 최소 지침을 수정한다. 도구와 모델 관련 사실은 공식 자료로 다시 확인하고 변경한 근거를 이 파일과 해당 조사에 남긴다.
