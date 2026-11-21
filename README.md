# 시스템 정적 보안 분석 키트

Codex, Claude Code, Mistral Vibe, OpenCode에서 사용하는 정적 보안 분석 스킬입니다. **각 클라이언트의 대화창에서 설치하고, 분석을 실행하고, 모델 배정을 설정할 수 있습니다.** 사용자가 Python 헬퍼나 설정 파일을 직접 다룰 필요는 없습니다.

현재 배포물은 스킬과 역할별 에이전트입니다. 아래의 클라이언트 안 설치는 **에이전트가 저장소 전체를 받아 키트 설치기를 실행하는 방식**입니다. 플러그인 스토어 등록이나 마켓플레이스 설치 명령을 제공하는 배포물은 아닙니다.

클라이언트는 먼저 설치하고 로그인해야 합니다. 대화형 설치에는 에이전트의 파일 쓰기·명령 실행·인터넷 접근이 필요하며 호스트 권한·조직 정책을 따릅니다. 설치기는 실행 환경을 확인하고 없으면 자동으로 준비합니다. Linux·macOS·WSL용이며 관리자 권한은 필요하지 않습니다.

> 로컬 작업본을 설치하려면 키트를 열어 둔 클라이언트에서 `현재 열린 키트 저장소의 INSTALL.md를 읽고 현재 클라이언트에 이 작업본을 설치해줘.`라고 요청하십시오. 키트를 다른 위치에 내려받았다면 그 경로를 함께 전달합니다.

## Codex

### 설치

평소처럼 터미널에서 `codex`를 실행한 뒤 **Codex 대화창**에 입력합니다.

```text
https://github.com/caterpie-dad/static-analysis-kit 저장소의 INSTALL.md를 읽고 현재 Codex에 static-analysis-kit을 사용자 전역으로 설치해줘.
```

에이전트가 스킬·역할 등록을 마치면 새 대화를 시작합니다. `/skills`에서 `static-analysis-kit`을 확인할 수 있습니다.

터미널에서 직접 설치할 때는 다음 한 줄도 사용할 수 있습니다.

```sh
curl -fsSL https://raw.githubusercontent.com/caterpie-dad/static-analysis-kit/main/install.sh | sh -s -- codex
```

### 실행

Codex 대화창에 대상 소스 경로를 지정합니다.

```text
$static-analysis-kit /path/to/project를 정적분석하라.
```

### 설정

```text
$static-analysis-kit 설정
```

이후 같은 대화에서 “현재 모델 설정 보여줘”, “검토 역할만 Astra로 바꿔줘”, “모든 역할을 현재 모델 하나로 통일해줘”처럼 요청합니다. **`$`는 키트 스킬 호출, `/model`은 Codex 자체의 주 모델 선택**입니다. 기존 `$system-static-analysis` 호출도 유지합니다.

## Claude Code

### 설치

터미널에서 `claude`를 실행한 뒤 **Claude Code 대화창**에 입력합니다.

```text
https://github.com/caterpie-dad/static-analysis-kit 저장소의 INSTALL.md를 읽고 현재 Claude Code에 static-analysis-kit을 사용자 전역으로 설치해줘.
```

에이전트의 설치 완료 안내 후 새 세션을 시작합니다.

터미널에서 직접 설치하는 대안입니다.

```sh
curl -fsSL https://raw.githubusercontent.com/caterpie-dad/static-analysis-kit/main/install.sh | sh -s -- claude-code
```

### 실행

```text
/static-analysis-kit /path/to/project를 정적분석하라.
```

### 설정

```text
/static-analysis-kit 설정
```

같은 대화에서 수집·분석·검토 모델을 지정하거나 기본값으로 복원하도록 요청합니다. 현재 대화의 주 모델 변경이 필요하면 Claude Code의 모델 선택 기능을 안내받습니다.

## Mistral Vibe

### 설치

터미널에서 `vibe`를 실행한 뒤 **Vibe 대화창**에 입력합니다.

```text
https://github.com/caterpie-dad/static-analysis-kit 저장소의 INSTALL.md를 읽고 현재 Mistral Vibe에 static-analysis-kit을 사용자 전역으로 설치해줘.
```

설치 완료 후 새 세션을 시작합니다. 기존 세션에서 스킬 목록만 갱신할 때는 `/reload`를 사용할 수 있습니다. 역할 정의의 재로딩이 필요하면 에이전트의 안내를 따릅니다.

터미널에서 직접 설치하는 대안입니다.

```sh
curl -fsSL https://raw.githubusercontent.com/caterpie-dad/static-analysis-kit/main/install.sh | sh -s -- mistral-vibe
```

### 실행

```text
/static-analysis-kit /path/to/project를 정적분석하라.
```

### 설정

```text
/static-analysis-kit 설정
```

예를 들어 “Mistral Large 4 하나로 모든 역할을 수행하도록 설정해줘”라고 요청합니다. 에이전트가 현재 Vibe에 연결된 모델·프리셋을 확인합니다. 주 모델과 요약·제목 등 보조 모델까지 한 종류로 제한하려면 그 적용 여부도 함께 확인합니다.

## OpenCode

### 설치

터미널에서 `opencode`를 실행한 뒤 **OpenCode 대화창**에 입력합니다.

```text
https://github.com/caterpie-dad/static-analysis-kit 저장소의 INSTALL.md를 읽고 현재 OpenCode에 static-analysis-kit을 사용자 전역으로 설치해줘.
```

설치 완료 후 새 세션을 시작합니다. OpenCode의 모델·공급자 연결은 기존 설정을 사용합니다.

터미널에서 직접 설치하는 대안입니다.

```sh
curl -fsSL https://raw.githubusercontent.com/caterpie-dad/static-analysis-kit/main/install.sh | sh -s -- opencode
```

### 실행

```text
static-analysis-kit 스킬을 사용해서 /path/to/project를 정적분석하라.
```

### 설정

```text
static-analysis-kit 스킬로 모델 설정을 보여주고, 역할별 모델을 변경해줘.
```

이후 같은 대화에서 원하는 모델 배정을 말합니다. 에이전트가 현재 공급자에 등록된 모델을 확인하고, 주 모델은 OpenCode의 모델 선택 기능과 대조합니다.

## 공통 사용 안내

모델 설정은 대화로 저장·변경하며 다음 분석과 업데이트에도 유지합니다. 기본 설치는 클라이언트의 상속·기본값을 따릅니다. 수집(`inventory`)·분석(`analyst`)·독립 검토(`reviewer`)를 같은 모델이나 서로 다른 모델로 배정할 수 있습니다. 선택이 모호할 때만 질문하며, 지원되지 않는 모델로 조용히 대체하지 않습니다.

설정 저장·역할 파일 갱신과 **현재 세션에서 실제 적용된 모델**을 구분합니다. 주 모델의 직접 전환 기능이 호스트에 없으면 같은 클라이언트의 모델 선택 화면을 안내합니다. 설정 파일을 사용자가 작성하거나 설치기를 다시 실행할 필요는 없습니다.

배포·인프라 소스가 있으면 분석 요청에 그 경로도 함께 전달합니다. 재개는 “static-analysis-kit 스킬로 /path/to/project 분석을 이어가라”라고 요청합니다. 같은 대상의 조사가 여러 개면 조사 경로를 지정합니다.

기본 결과 위치는 `~/.local/share/static-analysis-kit/runs/`입니다. 사용자 지정 데이터 위치나 `XDG_DATA_HOME`을 쓰면 그 위치를 따릅니다. 보고서에는 코드 위치·해시·발췌, 취약 경로, 반증·보호 계층, 영향 조건과 미확인을 남깁니다.

전체 소스 파일·줄과 보안 경로, 기술 스택별 적용 취약점 유형과 작업을 모두 검토해야 완료로 기록합니다. 남은 검토는 `partial` 또는 `blocked`로 남깁니다. 검토 커버리지 100%가 모든 취약점 발견을 보증하지는 않습니다. 대상 소스 수정·서비스 기동·공격·PoC 실행은 포함하지 않습니다. [완료 규칙](references/completion.md)

## 업데이트·제거

현재 클라이언트의 대화창에서 요청할 수 있습니다.

```text
키트 저장소의 최신 INSTALL.md를 읽고 현재 클라이언트의 static-analysis-kit을 업데이트해줘.
```

```text
키트의 INSTALL.md에 따라 현재 클라이언트의 static-analysis-kit 등록을 제거하고 조사 기록은 보존해줘.
```

업데이트는 기존 모델 배정·개인 인증·조사 기록을 보존합니다. 수동 수정한 등록 파일은 덮어쓰지 않고 충돌을 알립니다. 제거는 키트 소유권이 확인되는 등록 파일만 삭제하며 조사 기록·다운로드 도구·과거 패키지는 보존합니다.

직접 설치에서는 같은 설치 명령을 다시 실행하면 업데이트하고, 끝에 `--uninstall`을 붙이면 제거합니다. 이미 내려받은 키트 폴더에서는 `sh install.sh codex` 또는 `sh install.sh codex --uninstall`처럼 실행할 수 있습니다. 네 클라이언트를 모두 선택하려면 클라이언트 이름을 `all`로 바꿉니다.

스킬이 보이지 않거나 설치가 실패하면 [문제 해결](references/installation.md#설치-확인과-문제-해결)을 확인하십시오. 실제 검증한 환경·클라이언트 로딩 범위는 [VALIDATION.md](VALIDATION.md)에 기록합니다.

[에이전트용 설치 절차](INSTALL.md) · [고급 설치·경로](references/installation.md) · [관리자 모델 프로파일](references/configuration.md) · [개발·검증](references/maintenance.md)
