# 시스템 정적 보안 분석 키트

로컬 파일 읽기와 명령 실행을 지원하는 코딩 에이전트에서 사용하는 정적 보안 분석 지침과 Python 헬퍼입니다. 공통 조사 방법, 역할, 모델 프로파일, 클라이언트별 설정을 분리합니다. 특정 모델이나 공급자는 필수 의존성이 아닙니다.

저장소 전체를 준비하고 새 세션에 아래 문장을 전달하면 시작할 수 있습니다.

```text
static-analysis-kit/START_HERE.md를 읽고 그 지침에 따라 정적분석을 시작하라.
대상 소스 경로: /분석할/프로젝트
배포·인프라 저장소가 있으면 함께 분석하라.
```

가능하면 키트 폴더에서 세션을 시작하십시오. 지침·스킬의 자동 발견은 클라이언트와 버전에 따라 다르므로, 대표 프롬프트는 필요한 공통 파일을 직접 읽도록 안내합니다. 스킬 폴더만 다른 위치에 복사하면 키트 루트의 참조·스크립트 경로가 유지되지 않습니다.

## 에이전트와 모델 설정

Codex, Claude Code, Mistral Vibe, OpenCode용 어댑터를 제공합니다. 기본 [프로파일](profiles/default.toml)은 모델을 덮어쓰지 않고 클라이언트의 상속·기본값을 따릅니다. 역할마다 다른 모델을 쓰려면 [모델 설정 예시](profiles/models.example.toml)를 참고해 사용 가능한 모델 참조와 옵션을 지정하십시오. 별칭과 모델 ID는 사용자 설정이며 공통 조사 지침의 일부가 아닙니다. 로컬 override를 사용할 때는 먼저 해당 TOML 파일을 작성하십시오.

```bash
python3 scripts/configure.py --client claude-code
python3 scripts/configure.py --client claude-code --profile profiles/default.toml --override models.local.toml
```

기본 동작은 생성할 네이티브 설정을 JSON 계획으로 출력하며 파일을 쓰지 않습니다. `--write`를 추가하면 기본적으로 키트 루트에 생성합니다. `--output DIR`로 별도 위치를 선택할 수 있습니다. 기존 사용자 설정과 충돌하면 덮어쓰지 않습니다. 갱신은 생성 기록으로 소유권과 기존 해시가 확인되는 파일에만 `--force`를 사용할 수 있습니다.

모델 ID·공급자 연결·인증은 해당 에이전트에 먼저 등록되어 있어야 합니다. 생성기는 로그인하거나 모델을 호출하지 않으며, 현재 세션의 모델·도구·권한을 바꾸지 않습니다. 사용 중인 클라이언트에서 설정 발견과 적용을 확인하십시오. 어댑터별 파일·옵션·버전 범위와 로컬 설정 관리는 [설정 안내](references/configuration.md)를 따릅니다.

## 무엇이 들어 있는가

| 파일·디렉터리 | 용도 |
| --- | --- |
| [START_HERE.md](START_HERE.md), [AGENTS.md](AGENTS.md), [SECURITY.md](SECURITY.md) | 시작·재개, 운영 지침, 정적 분석 범위 |
| [조사 스킬](.agents/skills/system-static-analysis/SKILL.md) | 공통 지침과 필요한 참조로 연결 |
| [investigation.md](references/investigation.md), [evidence.md](references/evidence.md) | 조사 방법, 반증, 커버리지와 소스 근거 |
| [model-routing.md](references/model-routing.md), [roles/](roles/) | 모델명과 분리된 역할·위임 계약 |
| [profiles/](profiles/), [adapters/](adapters/), [kit.toml](kit.toml) | 역할별 모델 연결, 네이티브 설정 정보, 공통 요구사항 |
| [configuration.md](references/configuration.md), [tooling.md](references/tooling.md), [sources.md](references/sources.md) | 설정·의존성 관리, 도구 선택, 확인한 공식 자료 |
| [configure.py](scripts/configure.py), [capabilities.py](scripts/capabilities.py) | 설정 계획·생성, 로컬 실행 파일과 모델 메타데이터 조사 |
| [workspace.py](scripts/workspace.py), [check_kit.py](scripts/check_kit.py) | 조사 폴더·목록·소스 참조 생성과 기록 검사 |
| [install_python_tool.py](scripts/install_python_tool.py) | 선택한 Python 도구를 독립 환경에 설치 |
| [VALIDATION.md](VALIDATION.md) | 수행한 검증과 미검증 범위 |

Python 3.11 이상을 권장합니다. Python 3.10에서는 기존 `tomli` 또는 pip에 포함된 TOML 파서를 사용할 수 있습니다. 공통 헬퍼는 특정 에이전트 SDK를 요구하지 않습니다. 에이전트 CLI와 선택적 분석기는 각 공식 배포 방식으로 준비합니다.

## 조사와 검증

에이전트는 대상을 확인하고 `workspace.py init`으로 조사 기록을 만듭니다. 실제 질문에 맞는 도구만 선택하며, 특정 플러그인이나 모든 스캐너 설치를 요구하지 않습니다. 로그인·라이선스·조직 정책·네트워크 제약은 기록하고 가능한 정적 근거를 조사합니다.

애플리케이션, 라이브러리, 에이전트, 배치, 서비스, 호스트·컨테이너·클러스터·클라우드 설정을 대상으로 사용할 수 있습니다. 실제 관련 경계와 조건을 확인하며, 미제공 배포 상태를 단정하지 않습니다. 대상 프로그램 실행·배포·공격은 포함하지 않습니다.

```bash
python3 scripts/check_kit.py
python3 scripts/check_kit.py --client claude-code --profile profiles/default.toml
python3 scripts/capabilities.py
python3 -m unittest discover -s tests -v
python3 scripts/workspace.py init --target /path/to/source
```

명령은 키트 루트 기준입니다. 다른 위치에서는 스크립트의 절대 경로를 사용하십시오. `runs/`, `.tools/`, 캐시와 로컬 설정은 Git에서 제외하며 조사 결과의 보관·공유는 별도로 결정합니다.

기본 헬퍼 테스트는 네트워크를 사용하지 않습니다. 시스템에 `ensurepip`가 없으면 wheel 설치 시험 하나를 건너뜁니다. `STATIC_KIT_ALLOW_NETWORK_TESTS=1`로 실행하면 공식 PyPI의 고정된 pip wheel로 독립 환경을 준비하는 대체 경로까지 검사합니다. 에이전트에서의 실제 모델 접근·설정 적용 검증과 헬퍼 테스트는 구분합니다.
