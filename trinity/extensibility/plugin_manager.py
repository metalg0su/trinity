from abc import (
    ABC,
    abstractmethod,
)
from argparse import (
    ArgumentParser,
    Namespace,
    _SubParsersAction,
)
import asyncio
import logging
from typing import (
    Any,
    Awaitable,
    Dict,
    Iterable,
    List,
    Optional,
    Union,
)

from trinity.config import (
    TrinityConfig
)
from trinity.endpoint import (
    TrinityEventBusEndpoint,
    TrinityMainEventBusEndpoint,
)
from trinity.extensibility.exceptions import (
    UnsuitableShutdownError,
)
from trinity.extensibility.plugin import (
    BaseAsyncStopPlugin,
    BaseIsolatedPlugin,
    BaseMainProcessPlugin,
    BasePlugin,
    PluginContext,
    TrinityBootInfo,
)
from trinity._utils.ipc import (
    kill_processes_gracefully,
)


class BaseManagerProcessScope(ABC):
    """
    Define the operational model under which a
    :class:`~trinity.extensibility.plugin_manager.PluginManager` works. Subclasses
    define whether a :class:`~trinity.extensibility.plugin_manager.PluginManager` is
    responsible to manage a specific plugin and how its
    :class:`~trinity.extensibility.plugin.PluginContext` is created.
    """

    endpoint: TrinityEventBusEndpoint

    @abstractmethod
    def is_responsible_for_plugin(self, plugin: BasePlugin) -> bool:
        """
        Define whether a :class:`~trinity.extensibility.plugin_manager.PluginManager` operating
        under this scope is responsible to manage the given ``plugin``.
        """
        pass

    @abstractmethod
    def create_plugin_context(self,
                              plugin: BasePlugin,
                              boot_info: TrinityBootInfo) -> None:
        """
        Create the :class:`~trinity.extensibility.plugin.PluginContext` for the given ``plugin``.
        """
        pass


class MainAndIsolatedProcessScope(BaseManagerProcessScope):
    """ 얘는 메인 스코프로 관리되기 위해 정의된 것 같고..."""

    def __init__(self, main_proc_endpoint: TrinityMainEventBusEndpoint) -> None:
        self.endpoint = main_proc_endpoint

    def is_responsible_for_plugin(self, plugin: BasePlugin) -> bool:
        """
        Return ``True`` if if the plugin instance is a subclass of
        :class:`~trinity.extensibility.plugin.BaseIsolatedPlugin` or
        :class:`~trinity.extensibility.plugin.BaseMainProcessPlugin`
        """
        return isinstance(plugin, BaseIsolatedPlugin) or isinstance(plugin, BaseMainProcessPlugin)

    def create_plugin_context(self,
                              plugin: BasePlugin,
                              boot_info: TrinityBootInfo) -> None:
        """
        Create a :class:`~trinity.extensibility.plugin.PluginContext` that creates a new
        :class:`~lahja.endpoint.Endpoint` dedicated to the isolated plugin that runs in its own
        process. The :class:`~lahja.endpoint.Endpoint` enable application wide event-driven
        communication even across process boundaries.
        """

        if isinstance(plugin, BaseIsolatedPlugin):
            # Isolated plugins use their own Endpoint that lives in the new process. It is only
            # created here for API symmetry. Endpoints are pickleable *before* they are connected,
            # which means, this Endpoint will be pickled and transferred into the new process
            # together with the rest of the `PluginContext`.
            plugin.set_context(PluginContext(TrinityEventBusEndpoint(), boot_info,))


class SharedProcessScope(BaseManagerProcessScope):
    #todo: 얘의 목적은 무엇인가

    def __init__(self, shared_proc_endpoint: TrinityEventBusEndpoint) -> None:
        self.endpoint = shared_proc_endpoint

    def is_responsible_for_plugin(self, plugin: BasePlugin) -> bool:
        """
        Return ``True`` if if the plugin instance is a subclass of
        :class:`~trinity.extensibility.plugin.BaseAsyncStopPlugin`.
        """
        return isinstance(plugin, BaseAsyncStopPlugin)

    def create_plugin_context(self,
                              plugin: BasePlugin,
                              boot_info: TrinityBootInfo) -> None:
        """
        Create a :class:`~trinity.extensibility.plugin.PluginContext` that uses the
        :class:`~lahja.endpoint.Endpoint` of the
        :class:`~trinity.extensibility.plugin_manager.PluginManager` as the event bus that
        enables application wide, event-driven communication even across process boundaries.
        """
        # Plugins that run in a shared process all share the endpoint of the plugin manager
        plugin.set_context(PluginContext(self.endpoint, boot_info))


class PluginManager:
    """
    The plugin manager is responsible to register, keep and manage the life cycle of any available
    plugins.

    A :class:`~trinity.extensibility.plugin_manager.PluginManager` is tight to a specific
    :class:`~trinity.extensibility.plugin_manager.BaseManagerProcessScope` which defines which
    plugins are controlled by this specific manager instance.

    This is due to the fact that Trinity currently allows plugins to either run in a shared
    process, also known as the "networking" process, as well as in their own isolated
    processes.

    Trinity uses two different :class:`~trinity.extensibility.plugin_manager.PluginManager`
    instances to govern these different categories of plugins.

      .. note::

        This API is very much in flux and is expected to change heavily.
    """

    def __init__(self, scope: BaseManagerProcessScope) -> None:
        self._scope = scope
        self._plugin_store: List[BasePlugin] = []
        self._logger = logging.getLogger("trinity.extensibility.plugin_manager.PluginManager")

    @property
    def event_bus_endpoint(self) -> TrinityEventBusEndpoint:
        """
        Return the :class:`~lahja.endpoint.Endpoint` that the
        :class:`~trinity.extensibility.plugin_manager.PluginManager` instance uses to connect to
        the event bus.
        """
        return self._scope.endpoint

    def register(self, plugins: Union[BasePlugin, Iterable[BasePlugin]]) -> None:
        """
        Register one or multiple instances of :class:`~trinity.extensibility.plugin.BasePlugin`
        with the plugin manager.
        """
        logging.warning("플러그인 register")

        new_plugins = [plugins] if isinstance(plugins, BasePlugin) else plugins
        self._plugin_store.extend(new_plugins)

    def amend_argparser_config(self,
                               arg_parser: ArgumentParser,
                               subparser: _SubParsersAction) -> None:
        """
        Call :meth:`~trinity.extensibility.plugin.BasePlugin.configure_parser` for every registered
        plugin, giving them the option to amend the global parser setup.
        """
        for plugin in self._plugin_store:
            plugin.configure_parser(arg_parser, subparser)

    def prepare(self,
                args: Namespace,
                trinity_config: TrinityConfig,
                boot_kwargs: Dict[str, Any] = None) -> None:
        """
        Create and set the :class:`~trinity.extensibility.plugin.PluginContext` and call
        :meth:`~trinity.extensibility.plugin.BasePlugin.ready` on every plugin that this
        plugin manager instance is responsible for.
        """

        # todo: 이 플러그인 매니저가 연결된 버스에, _plugin_store에 입력된 플러그인들이 접속(ready 상태)되도록 하는 메소드인 것 같음..

        logging.warning("플러그인 준비. 준비되었다고 알리는건가")
        logging.warning(f"현재 플러그인 목록: {[pg.name for pg in self._plugin_store]}")
        logging.warning(f"현재 플러그인 갯수: {len(self._plugin_store)}")
        logging.warning(f"목표 이벤트 버스 엔드포인트: {self.event_bus_endpoint}")

        for plugin in self._plugin_store:
            # 자기의 스코프 안에 있지 않은 플러그인으 ㄴ걸러내고
            if not self._scope.is_responsible_for_plugin(plugin):
                continue

            # 관련있는 녀석들만 context 생성
            self._scope.create_plugin_context(
                plugin,
                TrinityBootInfo(args, trinity_config, boot_kwargs)
            )
            logging.warning(f"{plugin.name} 플러그인 상태: {plugin.status}")
            plugin.ready(self.event_bus_endpoint)
            logging.warning(f"{plugin.name} 플러그인을 준비 상태로 변경: {plugin.status}\n\n")

    def shutdown_blocking(self) -> None:
        """
        Synchronously shut down all running plugins. Raises an
        :class:`~trinity.extensibility.exceptions.UnsuitableShutdownError` if called on a
        :class:`~trinity.extensibility.plugin_manager.PluginManager` that operates in the
        :class:`~trinity.extensibility.plugin_manager.SharedProcessScope`.
        """

        if isinstance(self._scope, SharedProcessScope):
            raise UnsuitableShutdownError("Use `shutdown` for instances of this scope")

        self._logger.info("Shutting down PluginManager with scope %s", type(self._scope))

        plugins = [
            plugin for plugin in self._plugin_store
            if isinstance(plugin, BaseIsolatedPlugin) and plugin.running
        ]
        processes = [plugin.process for plugin in plugins]

        for plugin in plugins:
            self._logger.info("Stopping plugin: %s", plugin.name)

        kill_processes_gracefully(processes, self._logger)

        for plugin in plugins:
            self._logger.info("Successfully stopped plugin: %s", plugin.name)

    async def shutdown(self) -> None:
        """
        Asynchronously shut down all running plugins. Raises an
        :class:`~trinity.extensibility.exceptions.UnsuitableShutdownError` if called on a
        :class:`~trinity.extensibility.plugin_manager.PluginManager` that operates in the
        :class:`~trinity.extensibility.plugin_manager.MainAndIsolatedProcessScope`.
        """
        if isinstance(self._scope, MainAndIsolatedProcessScope):
            raise UnsuitableShutdownError("Use `shutdown_blocking` for instances of this scope")

        self._logger.info("Shutting down PluginManager with scope %s", type(self._scope))

        async_plugins = [
            plugin for plugin in self._plugin_store
            if isinstance(plugin, BaseAsyncStopPlugin) and plugin.running
        ]

        stop_results = await asyncio.gather(
            *self._stop_plugins(async_plugins), return_exceptions=True
        )

        for plugin, result in zip(async_plugins, stop_results):
            if isinstance(result, Exception):
                self._logger.error(
                    'Exception thrown while stopping plugin %s: %s', plugin.name, result
                )
            else:
                self._logger.info("Successfully stopped plugin: %s", plugin.name)

    def _stop_plugins(self,
                      plugins: Iterable[BaseAsyncStopPlugin]
                      ) -> Iterable[Awaitable[Optional[Exception]]]:
        for plugin in plugins:
            self._logger.info("Stopping plugin: %s", plugin.name)
            yield plugin.stop()
