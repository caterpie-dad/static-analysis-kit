# 에이전트에서 설치·업데이트·제거

이 문서는 사용자의 요청으로 키트를 설치하는 코딩 에이전트가 읽는다. 사용자는 클라이언트의 대화창에서 설치를 요청하면 된다. 일반 사용자에게 shell 명령·Python 파일 실행·TOML 작성을 되돌려 요구하지 않는다. 작업에는 호스트가 허용하는 네트워크·파일 쓰기·명령 실행을 사용한다.

설치 작업은 대상 시스템의 보안 분석과 별개다. 분석할 소스 경로를 요청하거나 감사 워크스페이스를 만들지 않는다. 현재 클라이언트에 등록된 계정·모델·권한을 사용하며 자격증명이나 새 모델 계정은 만들지 않는다.

## 클라이언트와 설치 원본 확인

현재 호스트와 사용자 요청을 기준으로 다음 중 하나를 선택한다. 다른 CLI가 설치돼 있다는 이유로 그 클라이언트도 설치하지 않는다. 사용자가 명시적으로 모두 설치해 달라고 한 경우에만 `all`을 사용한다.

| 현재 호스트 | 설치기 선택 | 설치 후 분석 호출 | 설정 호출 |
| --- | --- | --- | --- |
| Codex | `codex` | `$static-analysis-kit /path/to/project를 정적분석하라.` | `$static-analysis-kit 설정` |
| Claude Code | `claude-code` | `/static-analysis-kit /path/to/project를 정적분석하라.` | `/static-analysis-kit 설정` |
| Mistral Vibe | `mistral-vibe` | `/static-analysis-kit /path/to/project를 정적분석하라.` | `/static-analysis-kit 설정` |
| OpenCode | `opencode` | `static-analysis-kit 스킬로 /path/to/project를 정적분석하라.` | `static-analysis-kit 스킬로 모델 설정 보여줘.` |

공식 저장소는 `https://github.com/caterpie-dad/static-analysis-kit`이다. 사용자가 로컬 작업본·특정 버전·fork를 지정했다면 그 지정을 따른다. 현재 작업본의 변경이 원격에 게시되기 전에는 해당 로컬 경로를 사용한다. 원격 자료가 없으면 성공한 척하거나 다른 저장소로 대체하지 않는다.

원격 설치·업데이트는 허용된 다운로드 도구로 저장소 전체를 임시 경로에 확보한다. Git을 사용할 수 있으면 새 임시 디렉터리에 clone하고 실제 commit을 기록한다. Git이 없으면 공식 GitHub HTTPS 아카이브를 다운로드해 전체 구조를 유지한다. 최신 업데이트 요청에는 새 원본을 확보하며 기존 설치 패키지를 최신 소스라고 추정하지 않는다.

기존 사용자 checkout을 reset·clean하거나 dirty 변경을 버리지 않는다. [README](README.md), 이 문서와 `install.sh`가 같은 원본에 있는지 확인한다. 클라이언트의 스킬 설치 기능이 폴더 하나만 복사한다면 `.agents/skills/static-analysis-kit/`만 설치해 종료하지 않는다. 이 키트는 공통 참조·역할·스키마·헬퍼 전체가 필요하다.

## 설치 또는 업데이트

선택한 전체 키트 루트를 `KIT_SOURCE`, 현재 클라이언트 선택을 `CLIENT`라 할 때 에이전트가 내부적으로 다음을 실행한다. 경로는 argv로 전달하거나 shell에 맞게 안전하게 인용한다.

```text
sh KIT_SOURCE/install.sh CLIENT
```

이미 설치돼 있으면 같은 명령이 업데이트한다. 저장된 역할별 모델 배정을 유지하려면 사용자가 요청하지 않은 프로파일 옵션을 추가하지 않는다. `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `VIBE_HOME`, `OPENCODE_CONFIG_DIR`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `STATIC_ANALYSIS_KIT_HOME`이 지정돼 있으면 그대로 유지한다. 환경 전체나 인증 파일은 출력하지 않는다.

설치기가 공통 키트 복사본과 두 스킬 진입점·역할별 에이전트 세 개를 사용자 전역에 등록한다. 필요한 실행기는 설치기가 자동 준비한다. 현재 모델·인증·전체 클라이언트 설정은 변경하지 않는다. 사용자 문서에는 Python 실행기나 내부 프로파일을 노출할 필요가 없다.

종료 코드와 `CLIENT: installed` 메시지를 확인한다. 실패하면 실제 오류와 남은 작업을 설명하고 사용자에게 같은 명령을 수동 실행시키는 것으로 완료를 대신하지 않는다. 기존 파일 충돌은 사용자 변경을 보존하며, 호스트의 실제 권한 제한이나 네트워크 제약을 문서로 우회하지 않는다.

## 설치 확인과 사용 안내

기본 데이터 루트는 `${XDG_DATA_HOME:-~/.local/share}/static-analysis-kit`이고 `STATIC_ANALYSIS_KIT_HOME`이 있으면 그 값을 쓴다. 해당 루트의 `registrations/CLIENT.json`에서 설치 패키지를 확인하고 패키지의 `.installation.json`에서 실행기를 찾는다. 표시된 스킬·역할 경로와 파일 존재를 확인한다.

설정 조회는 에이전트가 설치된 실행기로 수행한다.

```text
PYTHON PACKAGE/scripts/manage.py models show --client CLIENT
```

이 조회에는 분석 대상이나 모델 호출이 필요 없다. 실제 클라이언트가 스킬 목록 조회·재로딩 기능을 제공하면 그것으로 확인한다. Codex는 `/skills`에서 선택할 수 있으며 실제 노출된 도구로 목록을 조회할 수 있을 때만 자동 확인했다고 말한다. Vibe의 스킬 재로딩은 `/reload`다. 역할 정의를 다시 읽어야 하는 호스트에는 새 세션 등 필요한 동작을 안내한다.

설치 완료 응답은 설치한 클라이언트와 표의 분석·설정 호출 예시를 보여준다. **파일 등록 성공과 실제 호스트 로딩·모델 호출은 구분**하며 검증하지 않은 모델 접근을 완료로 표시하지 않는다. 다음 대화나 새 세션을 시작해야 하면 그 이유와 호출 예시를 함께 전달한다.

모델을 변경할 때는 [에이전트 인터페이스](references/agent-interface.md)를 따른다. 사용자가 모델 설정 파일을 만들거나 설치기를 다시 실행할 필요는 없다. 설치만 요청했는데 모델 배정을 임의로 변경하지 않는다.

## 제거

사용자가 현재 클라이언트의 키트 제거를 요청하면 설치 기록을 확인하고 같은 공통 설치기에 `--uninstall`을 전달한다. 설치된 패키지의 `install.sh`도 사용할 수 있으며 계정이나 사용자 설정 전체를 삭제하지 않는다.

```text
sh KIT_SOURCE/install.sh CLIENT --uninstall
```

종료 코드와 `CLIENT: uninstalled`를 확인한다. 조사 기록·다운로드 도구·과거 패키지는 보존하며, 충돌이 있으면 사용자 수정 파일을 강제로 삭제하지 않는다.

## 배포 방식의 구분

이 저장소의 현재 설치 방식은 에이전트가 수행하는 사용자 전역 스킬·역할 등록이다. Codex·Claude Code·Vibe의 플러그인 관리나 OpenCode의 패키지 플러그인 설치에 이 키트가 이미 등록됐다고 가정하지 않는다. 없는 마켓플레이스 이름이나 `/plugin install static-analysis-kit` 같은 명령을 만들어 안내하지 않는다. [고급 설치](references/installation.md), [공식 자료](references/sources.md), [검증 기록](VALIDATION.md)을 참고한다.
