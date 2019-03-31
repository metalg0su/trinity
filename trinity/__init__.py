import pkg_resources
import sys

# TODO: update this to use the `trinity` version once extracted from py-evm
print("트리니티의 __init__.py")
__version__: str
try:
    __version__ = pkg_resources.get_distribution("trinity").version
except pkg_resources.DistributionNotFound:
    __version__ = f"eth-{pkg_resources.get_distribution('py-evm').version}"

# This is to ensure we call setup_extended_logging() before anything else.
import eth as _eth_module  # noqa: F401

# todo: 흥미롭네. OS 시스템을 init에서 걸러내는 방식을 사용할 수도 있구나.
# 뭔가 시스템 시작 시 제약을 단단하게 걸어버리면 어떨까
def is_uvloop_supported() -> bool:
    return sys.platform in {'darwin', 'linux'} or sys.platform.startswith('freebsd')


if is_uvloop_supported():
    # Set `uvloop` as the default event loop
    import asyncio  # noqa: E402

    from eth._warnings import catch_and_ignore_import_warning
    with catch_and_ignore_import_warning():
        import uvloop  # noqa: E402

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

from .main import (  # noqa: F401
    main,
)

from .main_beacon import (  # noqa: F401
    main_beacon,
)
