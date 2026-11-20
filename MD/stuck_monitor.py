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
    "simulation": ["getParkingEndingVehiclesIDList", "getParkingStartingVehiclesIDList"],
    "vehicle": ["getIDList", "getIDCount", "isStoppedParking", "getSignals", "getWaitingTime", "getLeader", "getRouteIndex",
                "getRoute", "getRoadID", "isStopped", "moveTo", "remove",
                "getLanePosition", "getLength", "getMinGap", "setStop", "resume",
                "getLaneID", "getSpeed", "getDrivingDistance", "getDecel", "getNextStops", "setParkingAreaStop"],
    "edge": ["getLastStepVehicleIDs"],
    "lane": ["getLastStepVehicleIDs", "getAllowed", "getLength", "getLinks"],
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
                 mapa_faixas=None, log_intervalo_s: int = 600, log_fn=print,
                 capacidade: int | None = None, aproximacao: dict | None = None,
                 faixa_estacao: dict | None = None, fila_intervalo_s: int = 1,
                 folga_saida_m: float = 12.0, saida_estacoes: dict | None = None,
                 meia_zona_m: float = 6.0) -> None:
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
        self.log_intervalo_s = log_intervalo_s
        self.log_fn = log_fn
        # Fila na rua da estação, parando ANTES das vagas (ver _controlar_fila).
        # Desligada se capacidade/aproximacao/faixa_estacao não forem informadas.
        self.capacidade = capacidade
        self.aproximacao = aproximacao or {}
        self.faixa_estacao = faixa_estacao or {}   # trecho da estação -> faixa da parkingArea
        self.fila_intervalo_s = fila_intervalo_s
        self.folga_saida_m = folga_saida_m
        self.estacionados: Counter = Counter()     # estação -> elétricos estacionados nela
        self.autorizados: set[str] = set()         # elétricos com vaga garantida, a caminho
        self.em_espera: dict[str, int] = {}        # elétrico -> passo em que recebeu a parada de espera
        self.saindo_da_espera: set[str] = set()    # liberados da espera, ainda voltando para a via
        self._ponto_espera: dict[str, float | None] = {}
        self._faixa_para_cache: dict[tuple[str, str], int | None] = {}
        self._saida: dict[str, set] = {s_: set(e) for s_, e in (saida_estacoes or {}).items()}
        # trechos de saída de TODAS as estações: nenhuma fila espera neles
        self._saida_todas: set = set().union(*self._saida.values()) if self._saida else set()
        self._local_espera: dict[str, tuple] = {}   # elétrico -> (trecho, pos, faixa) da parada de espera
        self._vaga_ociosa_desde: dict[str, int] = {}  # estação -> passo desde que há vaga e ninguém parado
        self._diag_restantes = 3
        self._diag_fila_restantes = 3
        self.meia_zona_m = meia_zona_m
        self._bloqueio_desde: dict[str, int] = {}   # estação -> passo desde que a saída está bloqueada
        self._fila_parada_desde: dict[str, int] = {}   # quantas vezes imprimir o diagnóstico de bloqueio

    # ------------------------------------------------------------------
    def apos_passo(self) -> None:
        """Chamar uma vez depois de cada traci.simulationStep()."""
        t = self.traci
        for v in t.simulation.getParkingStartingVehiclesIDList():
            if v in self.em_espera:
                continue  # entrou na área de espera (fora da via), não na vaga
            if v in self.ev_station_edge:
                self.estacionados[self.ev_station_edge[v]] += 1
                self.autorizados.discard(v)
        for v in t.simulation.getParkingEndingVehiclesIDList():
            if v in self.saindo_da_espera or v in self.em_espera:
                self.saindo_da_espera.discard(v)
                continue  # saiu da área de espera, não terminou recarga
            self.recarregados.add(v)
            if v in self.ev_station_edge:
                self.estacionados[self.ev_station_edge[v]] -= 1
        self.passo += 1
        controle = self.capacidade and self.aproximacao and self.faixa_estacao
        if controle and self.passo % 30 == 0:
            self._recontar_estacionados()
        if controle and self.passo % 60 == 0:
            self._destravar_saidas()
            self._ajudar_troca_de_faixa()
        if controle and self.passo % 10 == 0:
            self._apagar_esperas_esquecidas()
        if controle and self.passo % self.fila_intervalo_s == 0:
            self._controlar_fila()
        if self.log_intervalo_s and self.passo % self.log_intervalo_s == 0:
            self._log_progresso()
        if self.passo % self.intervalo_s != 0:
            return
        for v in t.vehicle.getIDList():
            if t.vehicle.getWaitingTime(v) < self.limite_s:
                continue
            if t.vehicle.isStopped(v):
                continue  # estacionado na estação (parada programada)
            trecho = t.vehicle.getRoadID(v)
            if not trecho:
                continue
            if trecho.startswith(":"):
                # Dentro de um cruzamento. Espera o dobro do limite (pode ser
                # só um semáforo/preferência demorada) e então move para a
                # rua seguinte da rota. Antes isso nunca acontecia, e um
                # veículo travado no cruzamento prendia para sempre todos os
                # que precisavam passar por ele (visto no piloto de 18/11:
                # elétricos já recarregados parados no fim da rua da estação
                # por mais de 1 hora, com a rua seguinte vazia).
                if t.vehicle.getWaitingTime(v) >= 2 * self.limite_s:
                    self._mover_para_proximo_trecho(v, origem="cruzamento")
                continue
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
        if (trecho_lider.startswith(":")
                and self.traci.vehicle.getWaitingTime(id_lider) >= self.limite_s):
            return True  # líder travado dentro do cruzamento: pode ser ultrapassado
        return self._esperando_vaga(id_lider, trecho_lider)

    def _esperando_vaga(self, v: str, trecho: str) -> bool:
        estacao = self.ev_station_edge.get(v)
        if estacao is None or v in self.recarregados:
            return False  # veículo comum, ou elétrico que já recarregou
        if v in self.em_espera or v in self.autorizados:
            # Na fila (em qualquer rua) ou a caminho de uma vaga garantida.
            # Não pode ser empurrado para frente: passaria do ponto de espera
            # e nunca chegaria a "parar na parada", então a vaga dele nunca
            # seria liberada (visto no piloto de 18/11: vagas ociosas com
            # fila esperando e movidos_eletrico subindo).
            return True
        if trecho == estacao:
            return True
        rota = self.traci.vehicle.getRoute(v)
        idx = self.traci.vehicle.getRouteIndex(v)
        return idx + 1 < len(rota) and rota[idx + 1] == estacao

    def _mover_para_proximo_trecho(self, v: str, origem: str = "") -> None:
        t = self.traci
        rota = t.vehicle.getRoute(v)
        idx = t.vehicle.getRouteIndex(v)
        if idx < 0 or idx >= len(rota) - 1:
            t.vehicle.remove(v)
            self.contagem["removido_no_fim_da_rota"] += 1
            return
        # Até onde pode ir: normalmente só a rua seguinte. Se o veículo já
        # está parado há 2x o limite e a rua seguinte continua cheia, é um
        # engarrafamento em bloco (sem o teletransporte do SUMO, ninguém nele
        # consegue andar -- visto no piloto: 8 carros parados 40 min na rua de
        # saída de uma estação). Então faz como o teletransporte do SUMO:
        # pula para a primeira rua da rota, até 10 à frente, que tenha espaço.
        # Elétrico que ainda não recarregou nunca pula a própria estação.
        limite_idx = len(rota) - 1
        estacao = self.ev_station_edge.get(v)
        if estacao is not None and v not in self.recarregados:
            try:
                limite_idx = rota.index(estacao, idx + 1) - 1
            except ValueError:
                pass
        alcance = 1
        if t.vehicle.getWaitingTime(v) >= 2 * self.limite_s:
            alcance = 10
        necessario = t.vehicle.getLength(v) + t.vehicle.getMinGap(v)
        faixa = None
        for k in range(idx + 1, min(idx + 1 + alcance, limite_idx + 1)):
            faixas = self._faixas_permitidas(rota[k])
            if not faixas:
                continue
            candidata, livre = max(((f, self._espaco_livre(f)) for f in faixas),
                                   key=lambda par: par[1])
            if livre >= necessario:
                faixa = candidata
                if k > idx + 1:
                    self.contagem["pulou_engarrafamento"] += 1
                break
        if faixa is None:
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
        if origem:
            self.contagem[f"movido_do_{origem}"] += 1

    def _mover_na_rua(self, v: str, faixa: str, pos: float) -> None:
        """moveTo que NÃO perde as paradas da rua de onde o carro sai.

        No SUMO 1.2, moveTo tira o veículo da faixa como num teletransporte
        (leaveLane com NOTIFICATION_TELEPORT), e isso descarta toda parada
        que ele tinha na rua em que estava ("Vehicle ... skips stop on
        lane"), mesmo se o destino for na MESMA rua. A ajuda na troca de
        faixa e o recuo para destravar movem elétricos dentro da rua da
        própria estação, então eles perdiam a parada de recarga e seguiam
        viagem sem recarregar. Na grade de 19/11, 70% dos elétricos sem
        recarga (10.488 de 14.900) chegaram ao destino sem parar, e por
        abordagem isso acompanha o número de ajudas na troca de faixa.

        Guarda as paradas que o carro tem na rua de destino, faz o moveTo e
        recoloca as que sumiram e ainda estão à frente da nova posição: a de
        recarga (setParkingAreaStop, com a duração original) e a de espera
        do monitor (setStop na pista).
        """
        t = self.traci
        trecho = faixa.rsplit("_", 1)[0]
        try:
            antes = [p for p in t.vehicle.getNextStops(v) if p[0].rsplit("_", 1)[0] == trecho]
        except t.exceptions.TraCIException:
            antes = []
        t.vehicle.moveTo(v, faixa, pos)
        if not antes:
            return
        try:
            depois = {(p[0], round(p[1], 2), p[2]) for p in t.vehicle.getNextStops(v)}
        except t.exceptions.TraCIException:
            depois = set()
        # recoloca na ordem em que estavam (a de espera vem antes da de recarga)
        for f, fim, lugar, _flags, duracao, _ate in antes:
            if (f, round(fim, 2), lugar) in depois or fim < pos:
                continue
            try:
                if lugar:
                    t.vehicle.setParkingAreaStop(v, lugar, duration=duracao)
                else:
                    t.vehicle.setStop(v, trecho, pos=fim, laneIndex=int(f.rsplit("_", 1)[1]),
                                      duration=duracao)
                self.contagem["parada_recolocada_apos_mover"] += 1
            except t.exceptions.TraCIException:
                self.contagem["falha_ao_recolocar_parada"] += 1

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
    def _ponto_de_espera(self, estacao: str) -> float | None:
        """Posição na faixa da estação onde o primeiro da fila para:
        alguns metros antes das vagas, que ficam no meio da faixa
        (graph_utils.parking_space_positions). None se a faixa for curta
        demais para caber a espera antes das vagas."""
        if estacao not in self._ponto_espera:
            meio = self.traci.lane.getLength(self.faixa_estacao[estacao]) / 2.0
            ponto = meio - self.folga_saida_m
            # Precisa sobrar pelo menos ~20 m de faixa antes do ponto de espera
            # para os carros que chegam pelas outras faixas conseguirem passar
            # para a faixa das vagas antes de parar. Com menos que isso, a
            # fila espera no fim da rua anterior (como nas faixas curtas).
            # Visto no piloto (18/11, pior do greedy, estação 5667170: 49 m,
            # 3 faixas, ponto a 8,7 m do início): 62 elétricos "passaram do
            # ponto", encheram a faixa das vagas e travaram a saída.
            self._ponto_espera[estacao] = ponto if ponto >= 20.0 else None
        return self._ponto_espera[estacao]

    def _recontar_estacionados(self) -> None:
        """Recontagem real (isStoppedParking) dos elétricos estacionados em
        cada estação. A contagem por eventos de início/fim de estacionamento
        se desencontrava em alguns casos: o monitor achava a estação cheia
        com ela vazia, e a fila não andava (piloto, 18/11: 0 estacionados,
        84 na fila, liberação nunca disparada)."""
        t = self.traci
        real = Counter()
        for v in t.vehicle.getIDList():
            estacao = self.ev_station_edge.get(v)
            if (estacao is not None and v not in self.em_espera
                    and v not in self.saindo_da_espera and t.vehicle.isStoppedParking(v)):
                real[estacao] += 1
        if real != +self.estacionados:
            self.contagem["recontagem_corrigiu"] += 1
        self.estacionados = real

    def _apagar_esperas_esquecidas(self) -> None:
        """
        Elétrico já autorizado (liberado da fila) não pode continuar com a
        parada de espera do monitor. Na grade de 19/11 (genetic, 36 est.,
        estação 319929496, 7 impasses), o primeiro da fila estava autorizado
        mas ainda parado na parada de espera (getNextStops: parada sem
        estação, alcançada, ~19 h restantes), em frente às vagas vazias, com
        ~40 autorizados atrás dele. A liberação de emergência apaga a parada
        com setStop(duração 0), que só funciona se ela ainda não foi
        alcançada; se o carro chega a ela no mesmo instante, ela fica.
        A cada 10 s, toda parada sem estação (só o monitor cria paradas
        assim) de um autorizado é encerrada: resume() se ele está parado
        nela, setStop(duração 0) se ainda não chegou.
        """
        t = self.traci
        presentes = set(t.vehicle.getIDList())
        for v in list(self.autorizados):
            if v not in presentes or v in self.recarregados:
                continue
            try:
                paradas = t.vehicle.getNextStops(v)
                if not paradas or paradas[0][2]:
                    continue  # nenhuma parada, ou a próxima é a da estação
                faixa, pos = paradas[0][0], paradas[0][1]
                if t.vehicle.isStopped(v) and not t.vehicle.isStoppedParking(v):
                    t.vehicle.resume(v)
                else:
                    trecho, idx = faixa.rsplit("_", 1)
                    t.vehicle.setStop(v, trecho, pos=pos, laneIndex=int(idx), duration=0.0)
                self.contagem["espera_esquecida_apagada"] += 1
            except t.exceptions.TraCIException:
                self.contagem["falha_ao_apagar_espera"] += 1

    def _destravar_saidas(self) -> None:
        """
        Última garantia contra o travamento na saída. Se uma estação tem
        estacionado querendo sair (pisca ligado) há mais de 5 min simulados,
        os elétricos ainda não recarregados que estão parados na faixa da
        estação, da zona das vagas em diante (são eles que tampam a saída),
        são levados de volta para trás do ponto de espera, na mesma faixa,
        se houver espaço livre ali; senão, são retirados da simulação
        (contados em "removido_para_destravar": não recarregam).
        """
        t = self.traci
        bloqueadas = set()
        estacionados_em = {}
        for v in t.vehicle.getIDList():
            estacao = self.ev_station_edge.get(v)
            if (estacao is not None and v not in self.em_espera
                    and v not in self.saindo_da_espera and t.vehicle.isStoppedParking(v)):
                estacionados_em.setdefault(estacao, []).append(v)
                if t.vehicle.getSignals(v) & 0b11:
                    bloqueadas.add(estacao)
        for estacao in list(self._bloqueio_desde):
            if estacao not in bloqueadas:
                del self._bloqueio_desde[estacao]
        for estacao in bloqueadas:
            desde = self._bloqueio_desde.setdefault(estacao, self.passo)
            if self.passo - desde < 300:
                continue
            faixa = self.faixa_estacao.get(estacao)
            if faixa is None:
                continue
            comp = t.lane.getLength(faixa)
            ponto = self._ponto_de_espera(estacao)
            inicio_zona = comp / 2.0 - self.meia_zona_m if ponto is not None else 0.0
            na_faixa = [(t.vehicle.getLanePosition(v), v) for v in t.lane.getLastStepVehicleIDs(faixa)]
            # todas as faixas da rua da estação (em rua de várias faixas, quem
            # tampa pode estar na faixa do lado, esperando para entrar)
            na_rua = [(t.vehicle.getLanePosition(v), v) for f in self._faixas(estacao)
                      for v in t.lane.getLastStepVehicleIDs(f)]
            for pos, v in sorted(na_rua, reverse=True):
                if (self.ev_station_edge.get(v) != estacao or v in self.recarregados
                        or t.vehicle.isStoppedParking(v) or pos < inicio_zona - 1.0):
                    continue
                destino = self._vaga_atras(faixa, ponto, na_faixa, v) if ponto is not None else None
                try:
                    if destino is not None:
                        self._mover_na_rua(v, faixa, destino)
                        self.autorizados.discard(v)
                        self.contagem["recuado_para_destravar"] += 1
                    else:
                        t.vehicle.remove(v)
                        self.autorizados.discard(v)
                        self.em_espera.pop(v, None)
                        self.contagem["removido_para_destravar"] += 1
                except t.exceptions.TraCIException:
                    self.contagem["falha_ao_destravar"] += 1
            self._destravar_fila_na_saida(estacao, inicio_zona, estacionados_em.get(estacao, []))
            self._bloqueio_desde[estacao] = self.passo

    def _destravar_fila_na_saida(self, estacao: str, inicio_zona: float,
                                 estacionados: list) -> None:
        """
        Fila que dá a volta no quarteirão e tampa a própria saída (grade de
        19/11: random 49 est. rep. 5, estação 131959462, e pseudorandom 16
        est. rep. 3, estação 320389127#0). A saída da estação leva, pelo
        quarteirão, de volta à rua onde a fila espera; a fila cresce para
        trás até ocupar essa saída. Quem recarregou (ou passa por ali indo
        para outra estação) fica parado na rua da estação, atrás da fila, e
        os estacionados não conseguem voltar à faixa. Ninguém anda.

        Com a saída bloqueada há mais de 5 min, além do que _destravar_saidas
        já faz:
        (a) outros veículos parados na rua da estação, da zona das vagas em
            diante (comuns, já recarregados, elétricos de outras estações),
            vão para a frente na própria rota, como no teletransporte do
            SUMO (_mover_para_proximo_trecho, até 10 ruas se preciso);
        (b) elétricos desta estação ainda não recarregados (na fila ou
            autorizados) parados no caminho de saída -- as ruas da rota de
            quem está estacionado depois da estação, até 8, parando antes da
            primeira rua onde a fila espera -- são retirados da simulação
            (contados em "removido_fila_na_saida": não recarregam).
        """
        t = self.traci
        for f in self._faixas(estacao):
            for v in t.lane.getLastStepVehicleIDs(f):
                if (self.ev_station_edge.get(v) == estacao and v not in self.recarregados):
                    continue  # tratado em _destravar_saidas
                if (t.vehicle.isStoppedParking(v) or t.vehicle.getSpeed(v) > 0.1
                        or t.vehicle.getLanePosition(v) < inicio_zona - 1.0):
                    continue
                try:
                    self._mover_para_proximo_trecho(v, "saida_bloqueada")
                except t.exceptions.TraCIException:
                    self.contagem["falha_ao_destravar"] += 1
        espera = {loc[0] for w, loc in self._local_espera.items()
                  if w in self.em_espera and self.ev_station_edge.get(w) == estacao}
        caminho = set()
        for v in estacionados:
            try:
                rota = t.vehicle.getRoute(v)
                i = rota.index(estacao, max(t.vehicle.getRouteIndex(v), 0))
            except (ValueError, t.exceptions.TraCIException):
                continue
            for e in rota[i + 1:i + 9]:
                if e in espera or e == estacao:
                    break
                caminho.add(e)
        for e in caminho:
            for f in self._faixas(e):
                for v in t.lane.getLastStepVehicleIDs(f):
                    if (self.ev_station_edge.get(v) != estacao or v in self.recarregados
                            or v not in self.em_espera and v not in self.autorizados
                            or t.vehicle.getSpeed(v) > 0.1):
                        continue
                    try:
                        t.vehicle.remove(v)
                        self.em_espera.pop(v, None)
                        self.autorizados.discard(v)
                        self.contagem["removido_fila_na_saida"] += 1
                    except t.exceptions.TraCIException:
                        self.contagem["falha_ao_destravar"] += 1

    def _ajudar_troca_de_faixa(self) -> None:
        """
        Em rua de várias faixas, o elétrico que ainda não recarregou e está na
        rua da sua estação numa faixa que NÃO é a das vagas, parado há mais de
        limite_s, provavelmente não consegue trocar de faixa (a faixa das
        vagas está tomada pela fila). Faz o que o teletransporte do SUMO faria,
        sem pular a estação: coloca-o na faixa das vagas, no fim da fila, se
        houver espaço ali (antes do ponto de espera). Visto no piloto (18/11,
        pior do greedy, estação 5667170 com 3 faixas): fila e autorizados
        parados nas faixas 1 e 2, ninguém chegava à faixa 0.
        """
        t = self.traci
        for estacao, faixa in self.faixa_estacao.items():
            faixas = self._faixas(estacao)
            if len(faixas) < 2:
                continue
            ponto = self._ponto_de_espera(estacao)
            na_faixa = [(t.vehicle.getLanePosition(o), o) for o in t.lane.getLastStepVehicleIDs(faixa)]
            for f in faixas:
                if f == faixa:
                    continue
                for v in t.lane.getLastStepVehicleIDs(f):
                    if (self.ev_station_edge.get(v) != estacao or v in self.recarregados
                            or t.vehicle.getWaitingTime(v) < self.limite_s):
                        continue
                    teto = ponto if (ponto is not None and v not in self.autorizados) \
                        else t.vehicle.getLanePosition(v)
                    destino = self._vaga_atras(faixa, teto + 2.0, na_faixa, v)
                    if destino is None:
                        continue
                    try:
                        self._mover_na_rua(v, faixa, destino)
                        na_faixa.append((destino, v))
                        self.contagem["ajuda_troca_de_faixa"] += 1
                    except t.exceptions.TraCIException:
                        self.contagem["falha_ao_mover"] += 1

    def _vaga_atras(self, faixa: str, ponto: float, na_faixa: list, v: str) -> float | None:
        """Posição livre na faixa, atrás do ponto de espera, para recuar v."""
        t = self.traci
        precisa = t.vehicle.getLength(v) + t.vehicle.getMinGap(v)
        ocupados = [(p - t.vehicle.getLength(o) - t.vehicle.getMinGap(o), p)
                    for p, o in na_faixa if o != v]
        pos = ponto - 2.0  # um pouco antes do ponto, para receber a parada de espera
        while pos - precisa >= 0:
            if all(fim < pos - precisa or ini > pos for ini, fim in ocupados):
                return pos
            pos -= 1.0
        return None

    def _faixa_para(self, trecho: str, estacao: str) -> int | None:
        """Índice da faixa de `trecho` que tem conexão para o trecho
        `estacao` (o trecho seguinte na rota)."""
        chave = (trecho, estacao)
        if chave not in self._faixa_para_cache:
            idx = None
            for i, faixa in enumerate(self._faixas(trecho)):
                if any(link[0].rsplit("_", 1)[0] == estacao
                       for link in self.traci.lane.getLinks(faixa)):
                    idx = int(faixa.rsplit("_", 1)[1])
                    break
            self._faixa_para_cache[chave] = idx
        return self._faixa_para_cache[chave]

    def _saida_outras(self, estacao: str) -> set:
        """Trechos de saída das OUTRAS estações."""
        return set().union(*(e for s_, e in self._saida.items() if s_ != estacao)) \
            if len(self._saida) > 1 else set()

    def _local_de_espera(self, v: str, estacao: str):
        """(trecho, posição, índice da faixa, índice do trecho na rota de v)
        onde `v` deve esperar a vaga. None se não houver onde esperar.

        Regra geral: o mais perto possível da estação, mas NUNCA num trecho
        por onde os elétricos saem da estação depois de recarregar (os 2
        trechos seguintes à estação nas rotas dos elétricos dela). Senão a
        fila de quem entra tampa o caminho de quem sai. Isso acontece em rua
        sem saída: entra-se e sai-se pela mesma rua, com retorno no fim (visto
        no piloto de 18/11, estação -40900869#2: a fila para entrar ocupava a
        rua de saída, e os já recarregados não conseguiam sair).

        - Se a rua anterior à estação não é caminho de saída:
          * faixa da estação comprida o bastante: espera na própria rua da
            estação, folga_saida_m antes das vagas;
          * faixa curta demais: espera no fim da rua anterior.
        - Se a rua anterior é caminho de saída: volta pela rota até a
          primeira rua que não é, e espera no fim dela.
        """
        t = self.traci
        rota = t.vehicle.getRoute(v)
        idx_rota = max(t.vehicle.getRouteIndex(v), 0)
        try:
            i = rota.index(estacao, idx_rota)
        except ValueError:
            return None
        novos = set(rota[i + 1:i + 3])
        self._saida.setdefault(estacao, set()).update(novos)
        self._saida_todas |= novos
        # proibido esperar no caminho de saída de qualquer estação (a fila
        # de uma estação já travou a saída de outra vizinha no piloto:
        # pseudorandom, estação 26658280#0, 18/11)
        proibido = self._saida_todas
        if (i > 0 and rota[i - 1] not in proibido and estacao not in
                (self._saida_todas - self._saida.get(estacao, set()))):
            ponto = self._ponto_de_espera(estacao)
            if ponto is not None and estacao not in self._saida_outras(estacao):
                return estacao, ponto, int(self.faixa_estacao[estacao].rsplit("_", 1)[1]), i
        # Volta pela rota até achar uma rua que não seja caminho de saída e
        # que tenha comprimento para um carro parar (>= 5 m antes do fim).
        # Ruas curtas demais (trechinhos de cruzamento) são puladas: a fila
        # espera na rua anterior a elas. Visto no piloto (18/11, pior do
        # greedy, estação 5667170): a rua anterior tinha 3,7 m, não havia
        # onde esperar, 133 elétricos seguiram direto para a estação cheia
        # e 79 tiveram de ser removidos. Limite: até 4 ruas para trás.
        #
        # Folga até as vagas (grade de 19/11): entre o primeiro da fila e o
        # início da zona das vagas ficam sempre folga_saida_m - meia_zona_m
        # (10 m), também quando a fila espera numa rua anterior. Antes, ela
        # parava a 1 m do fim da rua anterior; com a estação numa faixa
        # curta (sem zona, vagas na faixa inteira), quem recarregou não
        # conseguia voltar à faixa -- o SUMO 1.2 exige distância segura até
        # o carro de trás -- e a estação travava para sempre (greedyvoronoi
        # 16 est. rep. 3, estação 23787966#0 com 4,4 m: 16 impasses; random
        # 49 est. rep. 5, estação 131959462 com 16 m: 6 impasses).
        folga = self.folga_saida_m - self.meia_zona_m
        comp_est = t.lane.getLength(self.faixa_estacao[estacao])
        meio = comp_est / 2.0
        inicio_zona = meio - self.meia_zona_m if meio - self.folga_saida_m >= 5.0 else 0.0
        distancia = inicio_zona          # do fim da rua j até o início das vagas
        j = i - 1
        while j >= 0 and i - j <= 4:
            if rota[j] not in proibido:
                trecho, seguinte = rota[j], rota[j + 1]
                faixa_idx = self._faixa_para(trecho, seguinte)
                if faixa_idx is not None:
                    comp = t.lane.getLength(f"{trecho}_{faixa_idx}")
                    pos = comp - max(1.0, folga - distancia)
                    if pos >= 5.0:
                        return trecho, pos, faixa_idx, j
            distancia += t.lane.getLength(f"{rota[j]}_0")
            j -= 1
        return None

    def _controlar_fila(self) -> None:
        """
        Fila na rua da estação, mas parando ANTES das vagas.

        Problema (confirmado no piloto, 18/11, SUMO 1.2): sem controle, quem
        chega com a estação cheia para em frente às vagas; quem termina a
        recarga precisa de espaço livre na faixa, na altura da vaga, para
        voltar à via e não consegue -- e a fila espera alguém sair.
        Resultado: 4 estações com 7 elétricos já recarregados presos e a
        fila parada por horas.

        Solução: quando o elétrico entra na rua da estação (ou na rua
        anterior, a caminho dela) e não há vaga para ele, recebe uma parada
        comum (na via) em _ponto_de_espera -- folga_saida_m metros antes das
        vagas. Os seguintes da fila param atrás dele, na mesma rua (e, se
        a fila crescer, na rua anterior), como numa fila real. O trecho em
        frente às vagas fica livre, e quem recarregou consegue sair. Quando
        abre uma vaga, o primeiro da fila é liberado (resume) e segue para
        estacionar.

        Vagas livres = capacidade - estacionados - elétricos já autorizados
        a caminho. Se a faixa da estação for curta demais, a estação fica
        sem controle (comportamento padrão do SUMO).
        """
        t = self.traci
        presentes_set = set(t.vehicle.getIDList())
        for estacao, trechos in self.aproximacao.items():
            perto = [v for e in (estacao, *trechos) for v in t.edge.getLastStepVehicleIDs(e)
                     if self.ev_station_edge.get(v) == estacao
                     and v not in self.recarregados]
            # elétricos já autorizados ainda a caminho das vagas ocupam uma vaga
            # Autorizado parado há mais de 2 min não conta como vaga ocupada:
            # quem tem vaga garantida anda até ela. Parado assim, ele está
            # preso atrás da própria fila (foi autorizado por ter passado do
            # ponto de espera) e, contando como vaga ocupada, impedia o
            # primeiro da fila de ser liberado -- fila parada com a estação
            # vazia (piloto, 18/11: 82 na fila, 0 estacionados, diagnóstico
            # de fila nunca disparava porque o monitor não via vaga livre).
            autorizados_andando = [v for v in perto if v in self.autorizados
                                   and t.vehicle.getWaitingTime(v) < 120]
            livres = (self.capacidade - self.estacionados[estacao]
                      - len(autorizados_andando))
            # 1) Se já existe fila, a vaga só vai para quem está PARADO no
            #    ponto de espera -- fisicamente o primeiro da fila (os de trás
            #    estão bloqueados por ele, então não estão "parados na
            #    parada"). Reservar a vaga pela ordem em que receberam a
            #    parada travava: o primeiro pela ordem podia estar numa rua de
            #    aproximação diferente, preso atrás do primeiro físico, que
            #    por sua vez esperava a vaga reservada para o outro.
            fila = sorted((v for v in self.em_espera
                           if self.ev_station_edge.get(v) == estacao),
                          key=self.em_espera.get)
            for v in fila:
                if livres <= 0:
                    break
                if v in presentes_set and t.vehicle.isStopped(v):
                    t.vehicle.resume(v)
                    pass  # espera na pista: não gera evento de estacionamento (ver saindo_da_espera)
                    del self.em_espera[v]
                    self.autorizados.add(v)
                    self.contagem["liberado_da_fila"] += 1
                    livres -= 1
            # 1b) Há vaga, há fila, mas ninguém está parado no ponto de
            #     espera há 60 s: o primeiro da fila não consegue chegar à
            #     parada (ex.: rua de 2 faixas, parada na faixa da direita
            #     ocupada pela fila e ele na da esquerda, sem conseguir
            #     mudar de faixa -- visto no piloto: 4 na fila, estação vazia,
            #     nada andava). Cancela a parada de espera do mais antigo
            #     (setStop com duração 0 apaga uma parada ainda não alcançada)
            #     e o autoriza a seguir para a vaga.
            restantes = [v for v in fila if v in self.em_espera and v in presentes_set]
            if livres > 0 and restantes:
                desde = self._vaga_ociosa_desde.setdefault(estacao, self.passo)
                if self.passo - desde >= 60:
                    v = restantes[0]
                    try:
                        if t.vehicle.isStopped(v):
                            t.vehicle.resume(v)
                            pass  # espera na pista: não gera evento de estacionamento (ver saindo_da_espera)
                        else:
                            trecho_e, pos_e, faixa_e = self._local_espera[v]
                            t.vehicle.setStop(v, trecho_e, pos=pos_e, laneIndex=faixa_e,
                                              duration=0.0)
                        del self.em_espera[v]
                        self.autorizados.add(v)
                        self.contagem["liberado_sem_chegar_ao_ponto"] += 1
                        livres -= 1
                    except (t.exceptions.TraCIException, KeyError):
                        self.contagem["falha_ao_liberar"] += 1
                    self._vaga_ociosa_desde.pop(estacao, None)
            else:
                self._vaga_ociosa_desde.pop(estacao, None)
            fila_viva = [v for v in fila if v in self.em_espera and v in presentes_set]
            if fila_viva and self.estacionados[estacao] < self.capacidade:
                desde = self._fila_parada_desde.setdefault(estacao, self.passo)
                if self.passo - desde >= 900 and self._diag_fila_restantes > 0:
                    self._diag_fila_restantes -= 1
                    self._fila_parada_desde[estacao] = self.passo
                    for linha in self._diagnostico_fila(estacao, fila_viva, livres):
                        print(linha, flush=True)
            else:
                self._fila_parada_desde.pop(estacao, None)
            existe_fila = any(self.ev_station_edge.get(v) == estacao for v in self.em_espera)
            # 2) Quem acabou de chegar: segue direto se há vaga e não há fila;
            #    senão, entra no fim da fila (recebe a parada de espera).
            novos = [v for v in perto if v not in self.autorizados and v not in self.em_espera]
            for v in novos:
                if livres > 0 and not existe_fila:
                    livres -= 1
                    self.autorizados.add(v)
                elif v not in self.em_espera:
                    local = self._local_de_espera(v, estacao)
                    if local is None:
                        self.contagem["sem_local_de_espera"] += 1
                        self.autorizados.add(v)  # não há como segurar; segue o padrão do SUMO
                        continue
                    trecho, pos, faixa_idx, j = local
                    idx_v = t.vehicle.getRouteIndex(v)
                    if idx_v > j or (idx_v == j and t.vehicle.getRoadID(v) == trecho
                                     and t.vehicle.getLanePosition(v) > pos - 1.0):
                        # Já passou do ponto de espera escolhido (mais atrás).
                        # Segunda opção: esperar na própria rua da estação,
                        # antes das vagas, se couber e se ele ainda não passou
                        # desse ponto. Antes ele era autorizado direto, mesmo
                        # sem vaga, e parava em frente às vagas -- o que trava
                        # (visto no piloto: 5 "autorizados" sem vaga parados na
                        # rua da estação -40900869#2, saída bloqueada).
                        ponto = self._ponto_de_espera(estacao)
                        try:
                            i_est = t.vehicle.getRoute(v).index(estacao, max(idx_v, 0))
                        except ValueError:
                            i_est = None
                        ainda_antes = ponto is not None and i_est is not None and (
                            idx_v < i_est or (t.vehicle.getRoadID(v) == estacao
                                              and t.vehicle.getLanePosition(v) < ponto - 1.0))
                        if not ainda_antes:
                            self.contagem["passou_do_ponto_de_espera"] += 1
                            self.autorizados.add(v)  # não há onde segurar; padrão do SUMO
                            continue
                        trecho, pos, j = estacao, ponto, i_est
                        faixa_idx = int(self.faixa_estacao[estacao].rsplit("_", 1)[1])
                        self.contagem["espera_na_rua_da_estacao"] += 1
                    # Distância até o ponto menor que a de frenagem: o SUMO
                    # pararia o carro onde desse, possivelmente em frente às
                    # vagas (visto no piloto: elétricos "na fila" parados
                    # dentro da zona das vagas). Nesse caso, não segura.
                    dist = t.vehicle.getDrivingDistance(v, trecho, pos, faixa_idx)
                    vel = t.vehicle.getSpeed(v)
                    if dist < 0 or dist < vel * vel / (2.0 * t.vehicle.getDecel(v)) + 3.0:
                        self.contagem["passou_do_ponto_de_espera"] += 1
                        self.autorizados.add(v)
                        continue
                    try:
                        # Parada NA PISTA (flags=0): a fila ocupa a faixa e o
                        # trânsito sente, como no SUMO. (Uma versão com espera
                        # fora da via -- flags=1 -- foi testada e descartada em
                        # 18/11: tirava o efeito da fila sobre o trânsito.)
                        t.vehicle.setStop(v, trecho, pos=pos, laneIndex=faixa_idx,
                                          duration=86400.0)
                    except t.exceptions.TraCIException:
                        self.contagem["falha_parada_espera"] += 1
                        self.autorizados.add(v)
                        continue
                    self.em_espera[v] = self.passo
                    self._local_espera[v] = (trecho, pos, faixa_idx)
                    self.contagem["parado_antes_das_vagas"] += 1
        # limpeza: quem saiu da simulação
        presentes = set(t.vehicle.getIDList())
        for v in [v for v in self.em_espera if v not in presentes]:
            del self.em_espera[v]
        self.autorizados &= presentes
        self.saindo_da_espera &= presentes

    def _log_progresso(self) -> None:
        """Linha de progresso no log (a cada log_intervalo_s segundos
        simulados): quantos elétricos ainda estão na rede, quantos estão
        estacionados recarregando, quantos desses já terminaram a recarga
        mas não conseguem voltar para a via (pisca-alerta ligado: saída
        bloqueada) e quantos estão na via a caminho ou na fila."""
        t = self.traci
        presentes = [v for v in t.vehicle.getIDList() if v in self.ev_station_edge]
        estacionados = [v for v in presentes if v not in self.em_espera
                        and v not in self.saindo_da_espera and t.vehicle.isStoppedParking(v)]
        bloqueados = [v for v in estacionados if t.vehicle.getSignals(v) & 0b11]
        por_estacao = Counter(self.ev_station_edge[v] for v in bloqueados)
        msg = (f"MONITOR-PROGRESSO t={t.simulation.getTime():.0f} "
               f"veiculos_na_rede={t.vehicle.getIDCount()} "
               f"eletricos_na_rede={len(presentes)} "
               f"estacionados={len(estacionados)} "
               f"saida_bloqueada={len(bloqueados)} "
               f"na_via={len(presentes) - len(estacionados)} "
               f"ja_recarregaram={len(self.recarregados)} "
               f"na_fila_antes_das_vagas={len(self.em_espera)} "
               f"passaram_do_ponto={self.contagem['passou_do_ponto_de_espera']} "
               f"sem_local_de_espera={self.contagem['sem_local_de_espera']} "
               f"movidos_comum={self.contagem['movido_comum']} "
               f"movidos_eletrico={self.contagem['movido_eletrico']} "
               f"movidos_do_cruzamento={self.contagem['movido_do_cruzamento']} "
               f"adiados_sem_espaco={self.contagem['adiado_sem_espaco']} "
               f"falhas_ao_mover={self.contagem['falha_ao_mover']} "
               f"liberados_sem_chegar_ao_ponto={self.contagem['liberado_sem_chegar_ao_ponto']} "
               f"pulou_engarrafamento={self.contagem['pulou_engarrafamento']} "
               f"recontagem_corrigiu={self.contagem['recontagem_corrigiu']} "
               f"recuado_para_destravar={self.contagem['recuado_para_destravar']} "
               f"removido_para_destravar={self.contagem['removido_para_destravar']} "
               f"ajuda_troca_de_faixa={self.contagem['ajuda_troca_de_faixa']}")
        if por_estacao:
            msg += f" bloqueios_por_trecho={dict(por_estacao)}"
        if self.log_fn is print:
            print(msg, flush=True)
        else:
            self.log_fn(msg)
        if por_estacao and self._diag_restantes > 0:
            self._diag_restantes -= 1
            for estacao in list(por_estacao)[:2]:
                for linha in self._diagnostico(estacao, bloqueados):
                    print(linha, flush=True)

    def _diagnostico_fila(self, estacao: str, fila: list, livres: int) -> list[str]:
        """Fotografia de uma fila que não anda mesmo com vaga livre."""
        t = self.traci
        aut = [v for v in self.autorizados if self.ev_station_edge.get(v) == estacao]
        linhas = [f"MONITOR-DIAG-FILA estacao={estacao} vagas_livres={livres} "
                  f"estacionados={self.estacionados[estacao]} na_fila={len(fila)} "
                  f"autorizados={len(aut)}"]
        for v in aut[:6]:
            linhas.append(f"MONITOR-DIAG-FILA   autorizado {v} trecho={t.vehicle.getRoadID(v)} "
                          f"pos={t.vehicle.getLanePosition(v):.1f} vel={t.vehicle.getSpeed(v):.1f} "
                          f"espera_s={t.vehicle.getWaitingTime(v):.0f}")
        for v in fila[:8]:
            local = self._local_espera.get(v)
            lider = t.vehicle.getLeader(v, 50.0)
            linhas.append(
                f"MONITOR-DIAG-FILA   {v} trecho={t.vehicle.getRoadID(v)} "
                f"faixa={t.vehicle.getLaneID(v)} pos={t.vehicle.getLanePosition(v):.1f} "
                f"vel={t.vehicle.getSpeed(v):.1f} parado={t.vehicle.isStopped(v)} "
                f"espera_s={t.vehicle.getWaitingTime(v):.0f} local_espera={local} "
                f"lider={lider[0] + ' ' + t.vehicle.getRoadID(lider[0]) if lider and lider[0] else None}")
        return linhas

    def _diagnostico(self, estacao: str, bloqueados: list) -> list[str]:
        """Fotografia de uma estação com saída bloqueada: quem está na faixa
        da estação (posição, velocidade, se está parado), onde estão os
        estacionados que querem sair e o que há no trecho seguinte."""
        t = self.traci
        linhas = []
        faixa = self.faixa_estacao.get(estacao) or self._faixas(estacao)[0]
        comp = t.lane.getLength(faixa)
        linhas.append(f"MONITOR-DIAG estacao={estacao} faixa={faixa} comprimento={comp:.1f} "
                      f"ponto_espera={self._ponto_espera.get(estacao)} "
                      f"faixas_no_trecho={len(self._faixas(estacao))}")
        for v in [v for v in bloqueados if self.ev_station_edge.get(v) == estacao]:
            rota = t.vehicle.getRoute(v)
            i = t.vehicle.getRouteIndex(v)
            prox = rota[i + 1] if 0 <= i < len(rota) - 1 else None
            linhas.append(f"MONITOR-DIAG   saindo {v} pos={t.vehicle.getLanePosition(v):.1f} "
                          f"faixa={t.vehicle.getLaneID(v)} proximo_trecho={prox}")
        for f in self._faixas(estacao):
            for v in t.lane.getLastStepVehicleIDs(f):
                tipo = ("eletrico_desta" if self.ev_station_edge.get(v) == estacao else
                        "eletrico_outra" if v in self.ev_station_edge else "comum")
                linhas.append(f"MONITOR-DIAG   na_via {f} {v} {tipo} "
                              f"pos={t.vehicle.getLanePosition(v):.1f} "
                              f"vel={t.vehicle.getSpeed(v):.1f} parado={t.vehicle.isStopped(v)} "
                              f"em_espera={v in self.em_espera} autorizado={v in self.autorizados} "
                              f"espera_s={t.vehicle.getWaitingTime(v):.0f}")
        ultimos = [(t.vehicle.getLanePosition(v), v) for f in self._faixas(estacao)
                   for v in t.lane.getLastStepVehicleIDs(f)]
        if ultimos:
            _, v = max(ultimos)
            lider = t.vehicle.getLeader(v, 50.0)
            if lider and lider[0]:
                lid = lider[0]
                tipo_l = ("eletrico_desta" if self.ev_station_edge.get(lid) == estacao else
                          f"eletrico_de_{self.ev_station_edge[lid]}" if lid in self.ev_station_edge else "comum")
                linhas.append(f"MONITOR-DIAG   lider_do_ultimo {v} -> {lid} ({tipo_l}, recarregou={lid in self.recarregados}, "
                              f"em_espera={lid in self.em_espera}) dist={lider[1]:.1f} "
                              f"trecho={t.vehicle.getRoadID(lid)} vel={t.vehicle.getSpeed(lid):.1f} "
                              f"espera_s={t.vehicle.getWaitingTime(lid):.0f} "
                              f"proximo={t.vehicle.getRoute(lid)[t.vehicle.getRouteIndex(lid) + 1] if t.vehicle.getRouteIndex(lid) + 1 < len(t.vehicle.getRoute(lid)) else None}")
            else:
                linhas.append(f"MONITOR-DIAG   lider_do_ultimo {v} -> nenhum")
        saindo = [v for v in bloqueados if self.ev_station_edge.get(v) == estacao]
        if saindo:
            rota = t.vehicle.getRoute(saindo[0])
            i = t.vehicle.getRouteIndex(saindo[0])
            if 0 <= i < len(rota) - 1:
                prox = rota[i + 1]
                for f in self._faixas(prox):
                    vs = t.lane.getLastStepVehicleIDs(f)
                    linhas.append(f"MONITOR-DIAG   trecho_seguinte {f} veiculos={len(vs)} "
                                  f"comprimento={t.lane.getLength(f):.1f} parados="
                                  f"{sum(1 for v in vs if t.vehicle.getSpeed(v) < 0.1)}")
        return linhas

    def resumo(self) -> list[str]:
        return [f"MONITOR {chave}: {valor}" for chave, valor in sorted(self.contagem.items())]
