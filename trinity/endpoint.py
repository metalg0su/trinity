from typing import (
    Tuple,
)
from lahja import (
    BroadcastConfig,
    ConnectionConfig,
    Endpoint,
)

from trinity.constants import (
    MAIN_EVENTBUS_ENDPOINT,
)
from trinity.events import (
    AvailableEndpointsUpdated,
    EventBusConnected,
    ShutdownRequest,
)


class TrinityEventBusEndpoint(Endpoint):
    """
    Lahja Endpoint with some Trinity specific logic.
    """
    def request_shutdown(self, reason: str) -> None:
        """
        Perfom a graceful shutdown of Trinity. Can be called from any process.
        """
        self.broadcast(
            ShutdownRequest(reason),
            BroadcastConfig(filter_endpoint=MAIN_EVENTBUS_ENDPOINT)
        )

    def connect_to_other_endpoints(self,
                                   ev: AvailableEndpointsUpdated) -> None:

        for connection_config in ev.available_endpoints:
            if connection_config.name == self.name:
                continue
            elif self.is_connected_to(connection_config.name):
                continue
            else:
                self.logger.info(
                    "EventBus Endpoint %s connecting to other Endpoint %s",
                    self.name,
                    connection_config.name
                )
                self.connect_to_endpoints_nowait(connection_config)

    def auto_connect_new_announced_endpoints(self) -> None:
        """
        Connect this endpoint to all new endpoints that are announced
        """
        print("아마도 Networking 엔드포인트가 얘를 호출할 것임. 확인하기. >", self.name)
        self.subscribe(AvailableEndpointsUpdated, self.connect_to_other_endpoints)

    def announce_endpoint(self) -> None:
        """
        Announce this endpoint to the :class:`~trinity.endpoint.TrinityMainEventBusEndpoint` so
        that it will be further propagated to all other endpoints, allowing them to connect to us.
        """
        # 다른 애들한테 알려서, 다른 애들이 알린 애들이 메인 엔드포인트를 바라볼 수 있게 하는듯
        print(f"자신(엔드포인트 {self.name})를 다른 이들에게 announce(broadcast)")

        self.broadcast(
            EventBusConnected(ConnectionConfig(name=self.name, path=self.ipc_path)),
            BroadcastConfig(filter_endpoint=MAIN_EVENTBUS_ENDPOINT)
        )


class TrinityMainEventBusEndpoint(TrinityEventBusEndpoint):
    """
    Endpoint that operates like a bootnode in the sense that every other endpoint is aware of this
    endpoint, connects to it by default and uses it to advertise itself to other endpoints.
    """

    available_endpoints: Tuple[ConnectionConfig, ...]

    def track_and_propagate_available_endpoints(self) -> None:
        """
        Track new announced endpoints and propagate them across all other existing endpoints.
        """
        self.available_endpoints = tuple()

        def handle_new_endpoints(ev: EventBusConnected) -> None:
            # In a perfect world, we should only reach this code once for every endpoint.
            # However, we check `is_connected_to` here as a safe guard because theoretically
            # it could happen that a (buggy, malicious) plugin raises the `EventBusConnected`
            # event multiple times which would then raise an exception if we are already connected

            # to that endpoint.
            if not self.is_connected_to(ev.connection_config.name):
                # 제일 처음에는 메인에 붙는군
                self.logger.info(
                    "EventBus of main process connecting to EventBus %s", ev.connection_config.name
                )
                self.connect_to_endpoints_blocking(ev.connection_config)

            self.available_endpoints = self.available_endpoints + (ev.connection_config,)
            print(f"현재 가능한 endpoints?: {self.available_endpoints}")
            self.logger.debug("New EventBus Endpoint connected %s", ev.connection_config.name)
            # Broadcast available endpoints to all connected endpoints, giving them
            # a chance to cross connect
            self.broadcast(AvailableEndpointsUpdated(self.available_endpoints))
            self.logger.debug("Connected EventBus Endpoints %s", self.available_endpoints)

        print(f"섮스! - TrinityMainEventBusEndpoint")
        print(f"이벤트 종류: {EventBusConnected}")
        print(f"핸들링할 엔드포인트: {handle_new_endpoints}")
        self.subscribe(EventBusConnected, handle_new_endpoints)
