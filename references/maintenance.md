# 개발과 검증

사용자 설치·사용법은 [README](../README.md), 고급 설치는 [installation.md](installation.md)에 둔다. 이 문서의 명령은 키트 개발·유지보수용이다. 키트 루트에서 실행한다.

클라이언트 안에서 받은 설치·업데이트·제거 요청은 [INSTALL.md](../INSTALL.md)의 에이전트용 절차를 따른다. 사용자 문서는 클라이언트별 설치·실행·설정을 한 곳에서 찾을 수 있게 유지하고, 현재 배포에 없는 네이티브 플러그인 명령을 설치 경로로 제시하지 않는다.

일반 사용자 설정 UX는 [에이전트 인터페이스](agent-interface.md)와 `scripts/manage.py`가 담당한다. 관리 헬퍼는 JSON으로 요청을 받고 설치기의 소유권·해시 transaction을 재사용한다. 자연어 해석·호스트 모델 이름 식별·실제 활성화 판단은 에이전트가 수행하며 CPU 헬퍼가 모델을 호출하지 않는다.

```sh
python3 scripts/check_kit.py
python3 scripts/configure.py --help
python3 scripts/capabilities.py
python3 scripts/workspace.py --help
python3 scripts/install_python_tool.py --help
python3 -m unittest discover -s tests -v
```

스크립트 변경은 격리된 임시 복사본에서 문법 검사와 관련 동작을 시험한다. `install.sh`는 `sh -n install.sh`로 검사하고 실제 사용자 홈 대신 임시 `HOME`과 `STATIC_ANALYSIS_KIT_HOME`을 사용해 네 클라이언트를 시험한다. 실제 대상 서비스나 모델을 실행할 필요는 없다. 원격 설치를 시험할 때는 전달된 소스와 부트스트랩의 버전이 일치하는지도 확인한다.

공통 프로파일을 네이티브 프로젝트 설정으로 검사·생성하는 개발 헬퍼는 [configuration.md](configuration.md)의 `configure.py`다. 사용자 전역 설치기는 `install.sh`와 `scripts/install.py`이며, 기존 프로젝트 설정 생성기와 소유권 기록을 공유하지 않는다. 설치기는 전역 설정 파일 전체를 생성하지 않고 개별 스킬·역할만 등록한다.

`runs/`, `.tools/`, 캐시와 로컬 모델 설정은 Git에서 제외한다. 배포에는 공통 지침·역할·어댑터·스키마·참조·헬퍼를 함께 포함한다. 스킬 폴더만 복사하면 참조가 끊어진다. 설치기는 허용한 키트 리소스 디렉터리만 복사하고 조사·다운로드·`.local.*` 프로파일을 제외한다.

기본 테스트는 네트워크를 사용하지 않는다. `ensurepip`가 없으면 기존 wheel 설치 시험 하나를 건너뛴다. `STATIC_KIT_ALLOW_NETWORK_TESTS=1`은 공식 PyPI wheel로 격리 환경을 준비하는 경로까지 검사한다. 실제 클라이언트에서의 스킬 발견·네이티브 역할 로딩·모델 접근 확인과 파일 형식·헬퍼 시험은 구분하고 [VALIDATION.md](../VALIDATION.md)에 기록한다.
