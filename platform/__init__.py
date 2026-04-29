"""AI 기반 인프라 모니터링 플랫폼 PoC 패키지.

이 폴더의 코드는 `infra_monitoring_ai_platform_architecture.md` 설계서를
바탕으로 만든 최소 기능 제품(MVP) 예제입니다.

실제 운영 환경에서는 Kafka, Prometheus, OpenSearch, PostgreSQL 같은 외부
시스템이 필요하지만, 처음 학습하고 실행해 보기 쉽도록 이 PoC는 모든 데이터를
메모리에 저장합니다. 서버를 재시작하면 데이터가 초기화되는 대신 설치와 실행이
단순해집니다.

주의: 이 패키지 이름은 사용자 요청에 맞춰 `platform`으로 만들었습니다.
Python 표준 라이브러리에도 같은 이름의 `platform` 모듈이 있으므로, 일부
라이브러리가 `platform.system()` 같은 표준 함수를 찾을 때 문제가 생길 수
있습니다. 아래 호환 코드는 표준 라이브러리 `platform.py`를 별도 이름으로
읽어 와서, 이 패키지에서도 같은 함수들을 사용할 수 있게 넘겨줍니다.
"""

from __future__ import annotations

import importlib.util
import sysconfig
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_stdlib_platform() -> ModuleType:
    """표준 라이브러리의 platform.py를 직접 찾아 별도 모듈로 로드합니다."""
    stdlib_path = Path(sysconfig.get_path("stdlib")) / "platform.py"
    spec = importlib.util.spec_from_file_location("_stdlib_platform", stdlib_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"표준 platform 모듈을 찾을 수 없습니다: {stdlib_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_stdlib_platform = _load_stdlib_platform()


def __getattr__(name: str) -> Any:
    """이 패키지에 없는 속성은 표준 platform 모듈에서 찾아 반환합니다."""
    return getattr(_stdlib_platform, name)


# 자주 쓰이는 표준 platform 함수는 명시적으로 노출합니다.
system = _stdlib_platform.system
machine = _stdlib_platform.machine
processor = _stdlib_platform.processor
python_version = _stdlib_platform.python_version
python_implementation = _stdlib_platform.python_implementation
platform = _stdlib_platform.platform
release = _stdlib_platform.release
version = _stdlib_platform.version
