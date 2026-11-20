# Codex 시스템 정적 보안 분석 키트

새 세션에 아래 문장을 전달하면 시작할 수 있습니다. 이 폴더는 다른 프로젝트로 복사해도 됩니다.

```text
static-analysis-kit/START_HERE.md를 읽고 그 지침에 따라 정적분석을 시작하라.
대상 소스 경로: /분석할/프로젝트
배포·인프라 저장소가 있으면 함께 분석하라.
```

가능하면 이 폴더에서 세션을 시작하십시오. 그러면 `AGENTS.md`, `.agents/skills/`, `.codex/agents/`의 기본 발견 경로를 이용합니다. 다른 위치에서 시작해도 대표 프롬프트가 필요한 지침을 명시적으로 읽게 합니다. 세션의 모델이나 네이티브 도구 목록은 문서를 읽는 것만으로 바뀌지 않으며, 클라이언트가 제공하는 기능으로 실제 설정해야 합니다.

## 무엇이 들어 있는가

| 파일 | 용도 |
| --- | --- |
| [START_HERE.md](START_HERE.md) | 새 세션의 대표 프롬프트와 재개 계약 |
| [AGENTS.md](AGENTS.md) | 도구 선택, 위임, 근거, 기록에 관한 운영 지침 |
| [SECURITY.md](SECURITY.md) | 정적분석 범위와 결론의 의미 |
| [.agents/skills/system-static-analysis/SKILL.md](.agents/skills/system-static-analysis/SKILL.md) | 적응형 조사 스킬 |
| [references/investigation.md](references/investigation.md) | 아키텍처·위협모델·서버 권한 경로 조사 |
| [references/evidence.md](references/evidence.md) | 가설·반증·커버리지·코드 증거 작성 |
| [references/tooling.md](references/tooling.md) | 플러그인과 분석 도구의 탐색·다운로드·활용 |
| [references/model-routing.md](references/model-routing.md) | Luna/Sol 역할 배분과 실제 적용 확인 |
| [references/sources.md](references/sources.md) | 검증한 공식 자료와 갱신 지침 |
| [scripts/workspace.py](scripts/workspace.py) | 대상 결합, 조사 폴더 생성, 파일 목록, 코드 참조 |
| [scripts/capabilities.py](scripts/capabilities.py) | 로컬 도구와 모델 캐시 조사 |
| [scripts/install_python_tool.py](scripts/install_python_tool.py) | 선택한 Python 도구를 독립 환경에 설치 |
| [scripts/check_kit.py](scripts/check_kit.py) | 키트·조사 기록의 구조와 코드 참조 검증 |
| [VALIDATION.md](VALIDATION.md) | 작성 시 수행한 검증과 검증 범위 |

실행에는 Python 3.11 이상을 권장합니다. Python 3.10에서도 동작하며, TOML 검증에는 기존 `tomli` 또는 pip에 포함된 TOML 파서를 사용합니다. Python 3.11 이상에서는 표준 라이브러리만 사용합니다. 지원하지 않는 환경이면 Codex가 사용 가능한 인터프리터나 동등한 수단을 확인하고 실행하지 못한 기능을 기록합니다.

## 자동 준비와 적용 범위

대표 프롬프트를 받은 Codex가 대상을 확인하고 `workspace.py init`으로 `runs/` 아래 조사 기록을 만듭니다. 플랫폼과 언어에 맞는 도구를 선택하고 필요한 도구만 다운로드합니다. 모든 스캐너 설치, 고정 룰셋 실행, 전체 도구 순회는 요구하지 않습니다. Codex Security가 이용 가능하면 활용하고, 이용할 수 없어도 소스 감사를 계속합니다.

로그인·라이선스·조직 정책·네트워크 제한을 문서로 해제할 수는 없습니다. 해당 제약과 대체 수단을 기록하며 가능한 분석을 진행합니다. 도구 설치는 분석기 실행 환경을 준비하는 것이며 대상 애플리케이션의 실행·배포·침투를 포함하지 않습니다.

애플리케이션, 라이브러리, 에이전트, 배치, 서비스, 호스트·컨테이너·클러스터·클라우드 설정을 대상으로 사용할 수 있습니다. 데이터 변조·유출, 서비스 및 호스트 권한 확대, 인접 서비스나 관리 평면으로의 권한 전이 가능성을 코드와 제공된 설정으로 추론합니다. 호스트 설정이 제공되지 않으면 해당 경로의 미확인 조건을 남깁니다.

## 분석기만으로 준비 상태 점검

```bash
python3 scripts/check_kit.py
python3 scripts/capabilities.py
python3 -m unittest discover -s tests -v
```

대상 지정과 작업 기록 초기화 예시:

```bash
python3 scripts/workspace.py init --target /path/to/source
```

명령은 이 폴더를 기준으로 적었습니다. 다른 위치에서는 스크립트의 절대 경로를 사용하십시오. `runs/`, `.tools/`, 캐시는 Git에서 제외됩니다. 조사 결과의 보관·공유는 별도로 결정하십시오.

기본 helper 테스트는 네트워크를 사용하지 않습니다. 시스템에 `ensurepip`가 없으면 실제 wheel 설치 테스트 하나를 건너뜁니다. `STATIC_KIT_ALLOW_NETWORK_TESTS=1`로 실행하면 PyPI의 고정된 pip wheel로 독립 환경을 준비하는 대체 경로까지 검사합니다. 대상 시스템에는 접근하지 않습니다.
