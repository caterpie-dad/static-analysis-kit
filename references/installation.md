# 사용자 전역 설치와 고급 설정

일반 사용자는 [README](../README.md)의 설치 명령과 짧은 분석 요청만 사용한다. 이 문서는 경로 변경·개인 모델 연결·문제 해결이 필요할 때 읽는다. 배포 형식은 각 클라이언트가 발견하는 **스킬과 하위 에이전트**이며 플러그인 마켓플레이스나 MCP 서버는 필요하지 않다.

README의 클라이언트별 대화형 설치 요청을 받으면 에이전트는 [INSTALL.md](../INSTALL.md)에 따라 전체 저장소를 확보하고 설치·검증을 수행한다. 사용자가 직접 `curl`을 실행하는 것은 대안이다. 현재 배포에는 플러그인 manifest나 마켓플레이스 항목이 없으므로 각 제품의 플러그인 스토어 설치와 이 경로를 구분한다.

## 설치 경로

| 클라이언트 | 스킬 | 역할별 에이전트 |
| --- | --- | --- |
| Codex | `~/.codex/skills/static-analysis-kit/` | `~/.codex/agents/static_*.toml` |
| Claude Code | `~/.claude/skills/static-analysis-kit/` | `~/.claude/agents/static_*.md` |
| Mistral Vibe | `~/.vibe/skills/static-analysis-kit/` | `~/.vibe/agents/static_*.toml` |
| OpenCode | `~/.config/opencode/skills/static-analysis-kit/` | `~/.config/opencode/agents/static_*.md` |

기존 `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `VIBE_HOME`, `OPENCODE_CONFIG_DIR`를 설정했다면 해당 경로를 사용한다. OpenCode의 기본 경로에는 `XDG_CONFIG_HOME`도 적용한다. 사용자 전역 설정 파일·로그인·공급자·권한 설정을 편집하지 않는다. 역할 파일만으로 위임 기능을 켜거나 조직 정책을 바꾸지는 않는다.

공통 키트는 `${XDG_DATA_HOME:-~/.local/share}/static-analysis-kit/packages/`에 내용 해시로 구분해 보관한다. 설치 원본 저장소와 독립된 완전한 복사본이며, 원본을 이동·삭제해도 참조는 유지된다. `runs/`와 `tools/`는 패키지 밖의 같은 데이터 루트에 둔다. `registrations/`에는 설치 소유권·해시·모델 요청 정보를 기록한다. 이 기록은 비밀 저장소가 아니다.

스킬 디렉터리에는 기존 `system-static-analysis` 호환 진입점도 함께 둔다.

전체 데이터 위치를 바꾸려면 설치·업데이트·제거 때 동일한 환경변수를 사용한다.

```sh
STATIC_ANALYSIS_KIT_HOME="$HOME/security-kit" sh install.sh all
```

설치 경로의 symlink는 거부한다. macOS 등에서 사용자 지정 경로에 symlink가 있다면 실제 경로를 지정한다. 설치 실패 시 기존 등록 파일을 복구한다. 동시 설치는 잠금으로 거부하며, 설치기가 강제 종료되어 잠금이 남았을 때만 실행 중인 설치가 없는지 확인하고 해당 `.install.lock`을 제거한다.

## 실행 환경과 다운로드

Linux·macOS·WSL의 POSIX shell, `curl`, `tar`를 사용한다. 키트는 사용 가능한 Python 3.10 이상과 TOML 파서를 확인한다. 없으면 Astral 공식 uv 설치기를 임시 위치에 받아 키트 전용 Python 3.11을 준비한다. 전역 패키지나 shell 초기화 파일·PATH를 바꾸지 않는다. 설치된 실행기 경로는 패키지의 `.installation.json`과 스킬에 기록한다. 호스트 실행기를 제거했다면 설치 명령을 다시 실행한다.

기본 원격 설치는 GitHub `main`의 HTTPS 아카이브를 받는다. 재현 가능한 배포에는 검토한 commit SHA를 지정한다. 부트스트랩 자체도 같은 commit에서 받는다.

```sh
curl -fsSL https://raw.githubusercontent.com/caterpie-dad/static-analysis-kit/COMMIT_SHA/install.sh | STATIC_ANALYSIS_KIT_REF=COMMIT_SHA sh -s -- codex
```

위 `COMMIT_SHA`는 실제 공개된 commit으로 바꾼다. 개인 fork·오프라인 배포는 저장소 전체를 받은 뒤 그 디렉터리에서 `sh install.sh CLIENT`를 실행한다. `STATIC_ANALYSIS_KIT_SOURCE`로 이미 확보한 전체 소스 경로를 지정할 수도 있다. 런타임까지 없으면 오프라인에서 자동 준비할 수 없다. 인증·라이선스가 필요한 분석 도구는 키트 설치와 별도로 기존 계정 권한을 따른다.

## 개인 모델 프로파일

일반 사용자는 설치 후 에이전트에서 `static-analysis-kit 설정`을 요청하고 자연어로 모델을 고른다. 내부 설정을 저장·변경하는 작업은 에이전트가 수행하며 수동 파일 작성이나 재설치가 필요 없다. 아래 TOML 옵션은 관리자·개발자의 일괄 배포를 위한 고급 경로다.

모델을 지정하지 않는 설치가 기본이다. 사용자가 이미 클라이언트에 등록한 모델을 역할별로 지정하려면 [프로파일 안내](configuration.md)에 따라 로컬 TOML을 작성하고 설치 시 전달한다. 사용자가 Python 헬퍼를 실행할 필요는 없다.

```sh
sh install.sh claude-code --override /path/to/models.local.toml
sh install.sh all --profile /path/to/profile.toml
```

업데이트 시 옵션을 생략하면 설치 기록의 역할·모델·옵션을 재사용한다. 변경하려면 새 프로파일 옵션을 전달한다. 기본 상속으로 되돌리려면 `--profile profiles/default.toml`을 명시한다. `all`에 명시적 모델을 지정한다면 선택한 프로파일이 네 클라이언트 각각의 모델 참조를 제공해야 한다. 모델 접근과 실제 적용은 클라이언트에서 확인하며 설치기는 모델을 호출하지 않는다. 비밀값을 프로파일에 넣지 않는다.

## 설치 확인과 문제 해결

1. 설치 명령의 종료 코드와 `CLIENT: installed` 메시지를 확인하고 새 세션을 시작한다.
2. Codex는 `$static-analysis-kit` 또는 `/skills`, Claude Code·Vibe는 `/static-analysis-kit`를 입력해 스킬 목록을 확인한다. 기존 `system-static-analysis` 이름도 유지한다. Vibe의 기존 세션에서는 `/reload`도 사용할 수 있다. OpenCode에는 스킬 이름을 명시해 사용을 요청한다.
3. 표시되지 않으면 위 표의 `SKILL.md`가 현재 클라이언트가 사용하는 사용자 홈에 있는지 확인한다. 클라이언트 버전·조직 정책·프로젝트 설정이 전역 스킬 또는 역할을 가릴 수 있다. 설치가 성공했더라도 모델 실행까지 확인한 것은 아니다.
4. `existing user file` 또는 `modified kit registration`이면 표시된 파일을 보존하고 다른 곳으로 옮기거나 내용을 검토한다. 설치기는 동명 개인 파일과 직접 수정한 등록 파일을 강제로 덮어쓰지 않는다. 기존 전역 모델 설정을 지울 필요는 없다.
5. 하위 에이전트가 지원되지 않거나 비활성화된 환경에서는 주 세션에서 가능한 조사를 계속하며 독립 검토 미수행을 기록한다. 지원 문법·실행 검증 범위는 [검증 기록](../VALIDATION.md)을 확인한다.

제거는 `sh install.sh CLIENT --uninstall`이다. 등록 소유권과 해시가 확인되는 파일만 제거하며 조사 기록·도구·패키지를 지우지 않는다. 클라이언트 홈을 옮겼다면 기존 데이터 루트의 등록 기록으로 이전 경로의 파일을 식별한다.
