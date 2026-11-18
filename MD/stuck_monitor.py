"""
stuck_monitor.py -- "teletransporte" controlado pelo Python, no lugar do
teletransporte automático do SUMO.

Motivação (verificação de nov/2026): com o teletransporte padrão do SUMO
(--time-to-teleport = 300 s), ~80% dos veículos elétricos eram
teletransportados enquanto esperavam na fila e PULAVAM a parada de recarga
("Vehicle ... skips stop on lane ..." no log). O SUMO não permite proteger
só alguns veículos do teletransporte: a opção é global.

Solução: desligar o teletransporte do SUMO (time-to-teleport = -1, ver
io_utils.write_cfg_file) e reproduzir a mesma regra aqui, com UMA exceção:

    - A cada `intervalo_s` segundos simulados, procura veículos parados
      (velocidade < 0,1 m/s) há pelo menos `limite_s` segundos que sejam o
      PRIMEIRO da fila (sem veículo logo à frente) -- mesma regra do SUMO,
      que só teletransporta o primeiro da fila. Um veículo cujo único
      obstáculo à frente é um elétrico esperando vaga também conta como
      primeiro da fila (pode "ultrapassar" a fila da estação).
    - Esse veículo é movido para o início do PRÓXIMO trecho da sua rota
      (um trecho só, para nunca pular a estação), na faixa menos ocupada.
      Se já estiver no último trecho da rota, é removido (chegou ao fim).
    - EXCEÇÃO: um elétrico que ainda NÃO recarregou e que está no trecho da
      sua estação, ou no trecho imediatamente anterior, NÃO é movido. Ele
      está na fila da estação e deve esperar a vaga.

Como o movimento é sempre para o trecho seguinte da rota, um elétrico que
ainda não chegou à estação continua com a estação à frente e não perde a
parada.

Custo: 1 chamada TraCI por passo (quem terminou a recarga) + uma varredura
dos veículos a cada `intervalo_s` segundos simulados. Estimado em segundos
por simulação.

ATENÇÃO -- testar no SUMO 1.2 antes de rodar o grid: este módulo usa
traci.simulation.getParkingEndingVehiclesIDList, traci.vehicle.getWaitingTime,
getLeader, getRouteIndex, getRoute, isStopped, moveTo, remove,
getLanePosition, getLength, getMinGap, traci.lane.getLastStepVehicleIDs,
traci.lane.getAllowed e traci.lane.getLength. A função
verificar_api() confere se elas existem e falha com mensagem clara se não.
Todas conferidas no código-fonte do SUMO 1.2.0 (tag v1_2_0).

Espaço livre: no SUMO 1.2, moveTo insere o veículo à força, sem checar
colisão. Por isso o monitor só move o veículo se houver, no início da faixa
de destino, espaço para o comprimento dele + a distância mínima (minGap) até
a traseira do primeiro veículo da faixa. Sem espaço, tenta de novo na
próxima varredura (contagem "adiado_sem_espaco"), como o teletransporte
nativo, que também espera a faixa liberar.
"""
from __future__ import annotations

from collections import Counter

FUNCOES_NECESSARIAS = {
    "simulation": ["getParkingEndingVehiclesIDList"],
    "vehicle": ["getIDList", "getWaitingTime", "getLeader", "getRouteIndex",
                "getRoute", "getRoadID", "isStopped", "moveTo", "remove",
                "getLanePosition", "getLength", "getMinGap"],
    "lane": ["getLastStepVehicleIDs", "getAllowed", "getLength"],
}


def verificar_api(traci) -> None:
    faltando = [
        f"traci.{dominio}.{nome}"
        for dominio, nomes in FUNCOES_NECESSARIAS.items()
        for nome in nomes
        if not hasattr(getattr(traci, dominio), nome)
    ]
    if faltando:
        raise RuntimeError(
            "stuck_monitor: esta versão do TraCI não tem as funções "
            f"{faltando}. O monitoramento não pode ser usado."
        )


class StuckMonitor:
    def __init__(self, traci, ev_station_edge: dict[str, str],
                 intervalo_s: int = 60, limite_s: float = 300.0,
                 mapa_faixas=None) -> None:
        """
        ev_station_edge: {id do elétrico: id do trecho (edge) da sua estação}
        intervalo_s:     de quantos em quantos passos (s) a varredura roda
        limite_s:        tempo parado a partir do qual o veículo é movido
        mapa_faixas:     função sem argumentos que devolve {trecho: (faixas,)}
                         -- usada só se o TraCI não tiver edge.getLaneNumber
                         (ex.: graph_utils.edge_to_lanes)
        """
        verificar_api(traci)
        self.traci = traci
        self.ev_station_edge = ev_station_edge
        self.intervalo_s = intervalo_s
        self.limite_s = limite_s
        self._mapa_faixas_fn = mapa_faixas
        self._mapa_faixas = None
        self._cache_faixas: dict[str, tuple[str, ...]] = {}
        self.recarregados: set[str] = set()
        self.passo = 0
        self.contagem = Counter()

    # ------------------------------------------------------------------
    def apos_passo(self) -> None:
        """Chamar uma vez depois de cada traci.simulationStep()."""
        t = self.traci
        self.recarregados.update(t.simulation.getParkingEndingVehiclesIDList())
        self.passo += 1
        if self.passo % self.intervalo_s != 0:
            return
        for v in t.vehicle.getIDList():
            if t.vehicle.getWaitingTime(v) < self.limite_s:
                continue
            if t.vehicle.isStopped(v):
                continue  # estacionado na estação (parada programada)
            trecho = t.vehicle.getRoadID(v)
            if not trecho or trecho.startswith(":"):
                continue  # dentro de um cruzamento: tenta na próxima varredura
            if self._esperando_vaga(v, trecho):
                self.contagem["eletrico_aguardando_vaga"] += 1
                continue
            if not self._primeiro_da_fila(v):
                continue
            self._mover_para_proximo_trecho(v)

    # ------------------------------------------------------------------
    def _primeiro_da_fila(self, v: str) -> bool:
        """Verdadeiro se não há veículo logo à frente, ou se quem está à
        frente é um elétrico esperando vaga na estação. No segundo caso, o
        veículo de trás pode ser movido (equivale a ultrapassar a fila da
        estação); sem isso, numa via de faixa única, todo o trânsito atrás
        da fila ficaria parado até a fila andar."""
        lider = self.traci.vehicle.getLeader(v, 5.0)
        if lider is None or lider[0] == "":
            return True
        id_lider = lider[0]
        if self.traci.vehicle.isStopped(id_lider):
            return True  # como no SUMO: líder em parada programada não conta
        trecho_lider = self.traci.vehicle.getRoadID(id_lider)
        return self._esperando_vaga(id_lider, trecho_lider)

    def _esperando_vaga(self, v: str, trecho: str) -> bool:
        estacao = self.ev_station_edge.get(v)
        if estacao is None or v in self.recarregados:
            return False  # veículo comum, ou elétrico que já recarregou
        if trecho == estacao:
            return True
        rota = self.traci.vehicle.getRoute(v)
        idx = self.traci.vehicle.getRouteIndex(v)
        return idx + 1 < len(rota) and rota[idx + 1] == estacao

    def _mover_para_proximo_trecho(self, v: str) -> None:
        t = self.traci
        rota = t.vehicle.getRoute(v)
        idx = t.vehicle.getRouteIndex(v)
        if idx < 0 or idx >= len(rota) - 1:
            t.vehicle.remove(v)
            self.contagem["removido_no_fim_da_rota"] += 1
            return
        proximo = rota[idx + 1]
        faixas = self._faixas_permitidas(proximo)
        if not faixas:
            self.contagem["sem_faixa_permitida"] += 1
            return
        necessario = t.vehicle.getLength(v) + t.vehicle.getMinGap(v)
        faixa, livre = max(((f, self._espaco_livre(f)) for f in faixas),
                           key=lambda par: par[1])
        if livre < necessario:
            self.contagem["adiado_sem_espaco"] += 1
            return
        posicao = min(t.vehicle.getLength(v), t.lane.getLength(faixa))
        try:
            t.vehicle.moveTo(v, faixa, posicao)
        except t.exceptions.TraCIException:
            self.contagem["falha_ao_mover"] += 1
            return
        tipo = "eletrico" if v in self.ev_station_edge else "comum"
        self.contagem[f"movido_{tipo}"] += 1

    def _faixas(self, trecho: str) -> tuple[str, ...]:
        if trecho in self._cache_faixas:
            return self._cache_faixas[trecho]
        t = self.traci
        if hasattr(t.edge, "getLaneNumber"):
            faixas = tuple(f"{trecho}_{i}" for i in range(t.edge.getLaneNumber(trecho)))
        else:
            if self._mapa_faixas is None:
                if self._mapa_faixas_fn is None:
                    raise RuntimeError("stuck_monitor: TraCI sem edge.getLaneNumber "
                                       "e nenhum mapa_faixas informado")
                self._mapa_faixas = self._mapa_faixas_fn()
            faixas = tuple(self._mapa_faixas.get(trecho, ()))
        self._cache_faixas[trecho] = faixas
        return faixas

    def _faixas_permitidas(self, trecho: str) -> list[str]:
        faixas = []
        for faixa in self._faixas(trecho):
            permitidos = self.traci.lane.getAllowed(faixa)
            if permitidos and "passenger" not in permitidos:
                continue
            faixas.append(faixa)
        return faixas

    def _espaco_livre(self, faixa: str) -> float:
        """Distância do início da faixa até a traseira do veículo mais
        atrás nela. Faixa vazia conta como espaço ilimitado, para que
        trechos mais curtos que um carro não bloqueiem o veículo para sempre."""
        t = self.traci
        livre = float("inf")
        for outro in t.lane.getLastStepVehicleIDs(faixa):
            traseira = t.vehicle.getLanePosition(outro) - t.vehicle.getLength(outro)
            livre = min(livre, traseira)
        return livre

    # ------------------------------------------------------------------
    def resumo(self) -> list[str]:
        return [f"MONITOR {chave}: {valor}" for chave, valor in sorted(self.contagem.items())]