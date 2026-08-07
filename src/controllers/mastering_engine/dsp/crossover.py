import logging
import numpy as np
import scipy.signal as signal
from typing import Tuple

logger = logging.getLogger("mastering_engine.dsp.crossover")


class CrossoverError(Exception):
    """Exceção para falhas no processamento de crossover multibanda [14]."""
    pass


class LinkwitzRileyCrossover:
    """
    Crossover multibanda complementar de 3 bandas utilizando filtros Linkwitz-Riley 
    de 4ª ordem efetivos (via Butterworth de 2ª ordem processados bidirecionalmente).
    Garante fase zero e reconstrução de amplitude matematicamente perfeita (Null Test).
    """
    
    def __init__(self, sample_rate: int, low_hz: float = 200.0, high_hz: float = 3000.0):
        if sample_rate <= 0:
            raise CrossoverError(f"Taxa de amostragem inválida: {sample_rate} Hz")
        if low_hz >= high_hz:
            raise CrossoverError(f"Frequência de corte baixa ({low_hz} Hz) deve ser menor que a alta ({high_hz} Hz)")
        if high_hz >= sample_rate / 2:
            raise CrossoverError(f"Frequência de corte alta ({high_hz} Hz) excede o limite de Nyquist ({sample_rate / 2} Hz)")
            
        self.fs = sample_rate
        self.low_hz = low_hz
        self.high_hz = high_hz
        self._design_filters()

    def _design_filters(self) -> None:
        """
        Projeta filtros Butterworth de 2ª ordem. Sob o efeito bidirecional 
        do `sosfiltfilt`, eles passam a atuar como filtros LR4 (24 dB/oitava) 
        com soma de amplitude perfeitamente plana.
        """
        try:
            nyquist = self.fs / 2.0
            
            # --- Crossover Baixo (f_low) ---
            # Filtro Butterworth de 2ª ordem (que se tornará 4ª ordem efetiva no filtfilt)
            self.sos_low_lp = signal.butter(2, self.low_hz / nyquist, btype='low', output='sos')
            self.sos_low_hp = signal.butter(2, self.low_hz / nyquist, btype='high', output='sos')
            
            # --- Crossover Alto (f_high) ---
            self.sos_high_lp = signal.butter(2, self.high_hz / nyquist, btype='low', output='sos')
            self.sos_high_hp = signal.butter(2, self.high_hz / nyquist, btype='high', output='sos')
            
        except Exception as e:
            raise CrossoverError(f"Falha ao projetar filtros do crossover: {str(e)}")

    def _apply_filter_zero_phase(self, audio: np.ndarray, sos: np.ndarray) -> np.ndarray:
        """
        Aplica o processamento SOS de forma bidirecional (zero-phase) 
        para eliminar qualquer desvio de fase e distorção temporal.
        """
        try:
            return signal.sosfiltfilt(sos, audio, axis=-1)
        except Exception as e:
            raise CrossoverError(f"Falha ao executar filtragem zero-phase: {str(e)}")

    def split(self, audio: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Divide o áudio de entrada em três sub-bandas perfeitamente complementares:
        - Banda Baixa (Low-frequency)
        - Banda Média (Mid-frequency)
        - Banda Alta (High-frequency)
        
        Sinal esperado: (canais, amostras) [13]
        Retorna: (low_band, mid_band, high_band)
        """
        audio_32 = audio.astype(np.float32, copy=False)
        
        try:
            # Etapa 1: Divisão complementar na frequência baixa (f_low)
            low_band = self._apply_filter_zero_phase(audio_32, self.sos_low_lp)
            midhigh_band = self._apply_filter_zero_phase(audio_32, self.sos_low_hp)
            
            # Etapa 2: Divisão complementar da banda média-alta na frequência alta (f_high)
            mid_band = self._apply_filter_zero_phase(midhigh_band, self.sos_high_lp)
            high_band = self._apply_filter_zero_phase(midhigh_band, self.sos_high_hp)
            
            return low_band, mid_band, high_band
            
        except Exception as e:
            logger.error(f"Erro ao fatiar bandas espectrais: {str(e)}", exc_info=True)
            raise CrossoverError(f"Erro no processador de crossover: {str(e)}")

    @staticmethod
    def sum_bands(low: np.ndarray, mid: np.ndarray, high: np.ndarray) -> np.ndarray:
        """
        Reconstrói o sinal original somando linearmente as bandas complementares.
        """
        return low + mid + high